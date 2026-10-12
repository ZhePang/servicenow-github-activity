# GitHub activity explorer

A local dashboard for trending GitHub repositories, activity over time, observed open PRs, merge durations, and contributors.

## Demo walkthrough

[Watch the demo walkthrough on YouTube](https://youtu.be/BF8UxTb9HZQ).

## Run locally

Requires **Python 3.11+, Bash, curl**, and Internet access to install dependencies. No GitHub token or frontend build is required.

```sh
git clone https://github.com/ZhePang/servicenow-github-activity.git
cd servicenow-github-activity
bash scripts/run.sh
```

Open **http://127.0.0.1:8765/**. The script creates a virtual environment, installs dependencies, and imports the bundled August 2026 gzip snapshot: **137,302 unique events across 500 repositories**. Import takes about 13 seconds locally; later starts reuse the database. Keep the terminal open; **Ctrl-C** stops the server.

Use `GHT_PORT=8766 bash scripts/run.sh` to choose another port. The generated database stays local.

## Architecture

**FastAPI + DuckDB** serve a plain HTML/CSS/JavaScript dashboard with locally bundled Chart.js.

```text
Snapshot .jsonl.gz ──┐
                    ├── Shared validation + normalization
POST /api/events ───┘                  │
                                      ▼
                              DuckDB events + metadata
                                      │
                              Analytical SQL queries
                                      │
                              FastAPI JSON endpoints
                                      │
                              Browser dashboard
```

One server process owns the database. Writes are serialized; each report uses its own read transaction. The snapshot importer and event receiver share ingestion rules. The receiver is an interface for new events; the app has no live GitHub subscription.

## Design decisions

### Appendix A: measurements and database decision

Measurements were taken before application implementation on a local macOS arm64 machine, with DuckDB 1.5.6, two execution threads, persistent storage, and WAL enabled.

| Snapshot workload | Observed rate |
| --- | ---: |
| Average across August | 0.052 events/s |
| Busiest hour | 1.12 events/s |
| Busiest rolling minute | 2.1 events/s |
| Busiest second | 16 events/s |

These estimates use event timestamps for 500 selected repositories, not actual network arrival timestamps or all GitHub activity. The input contains 138,676 rows, including 1,374 identical repeated event IDs.

| Probe | Result |
| --- | ---: |
| Individually committed inserts alongside activity queries | 321 events/s |
| Write p95 | 3.87 ms |
| Concurrent activity query p95 | 2.69 ms |
| Seven-day star ranking p95 | 1.17 ms |
| Busiest-repository activity p95 | 1.89 ms |
| Contributor query p95 | 1.19 ms |
| Observed open-PR query p95 | 1.63 ms |
| Matched merge statistics p95 | 2.37 ms |

All six exploratory SQL results matched independent Python results across five layouts. Samples were warm (30 per query/layout), without flushing the operating-system cache. Gzip normalization took 3.06 seconds; bulk load, unique-index build, and checkpoint took 0.33 seconds. The narrow normalized database was about 11 MiB, excluding original JSON payloads.

#### Decisions supported by the probe

- Choose DuckDB alone: the supplied workload fits direct analytics and committed event ingestion. A second SQLite store would add synchronization and failure-handling work without a demonstrated user-facing gain.
- Normalize typed columns once; avoid parsing source JSON during dashboard requests.
- Sort the initial load by repository/time: median open-PR query latency improved from 2.92 ms in arrival order to about 1.50 ms.
- Use 16,384-row groups: nine groups instead of two. Timestamp-first ordering improved one-hour global ranking from about 0.72 ms to 0.43 ms, while repository-first ordering benefited drill-down. Keep one layout rather than duplicate data for each query.
- Preserve exact range predicates and source arrival sequence. Physical ordering is an optimization, not a lifecycle ordering rule.
- Bulk-load the snapshot. Per-event commits are appropriate for the small receiving interface but expensive for importing the entire file.
- Keep direct queries initially. Add precomputation only if final measurements identify a concrete slow query.

#### Limits of the exploratory measurements

The probe did not include HTTP handling, full envelope validation, canonical hashing, raw JSON storage, metadata writes, UI rendering, or crash-recovery testing. Its contributor query counted all actions for six types; the final metric has narrower action rules. The final application benchmark measures the full implementation and is reported in Appendix B. SQLite was not benchmarked, so these results establish DuckDB feasibility rather than a comparative write-speed claim.

[Complete exploratory results](docs/feasibility-results.json) · [Measurement methods and limits](docs/performance.md#exploratory-duckdb-probe)

### Appendix B: final application measurements

The actual application retains raw JSON, validates and hashes envelopes, updates metadata, and serves JSON over loopback HTTP. It uses DuckDB 1.5.6, two execution threads, and one Uvicorn process on macOS arm64 / Python 3.11.2. The full-schema database is **384.8 MiB**, versus ~11 MiB for the earlier narrow probe; raw payload retention accounts for much of the difference. It contains nine initial row groups.

| HTTP workload | First request | Warm p95 (30 samples) |
| --- | ---: | ---: |
| Seven-day trending | 21.7 ms | 19.7 ms |
| One-hour trending | 18.0 ms | 18.1 ms |
| Whole-month trending | 18.0 ms | 18.5 ms |
| Busiest-repository seven-day report | 23.6 ms | 18.7 ms |
| Busiest-repository whole-month report | 19.6 ms | 20.7 ms |

The repository report includes activity, PR state/pagination, merge statistics, and contributors. First requests are per workload in one process; the OS cache was not flushed. These are local feasibility results, not cold-storage or production load guarantees.

One writer sent 1,000 individual HTTP events, each committed before responding, while one reader alternated trending and repository reports:

| Concurrent workload | Result |
| --- | ---: |
| Sustained committed ingestion | 69.5 events/s |
| Write p95 | 17.0 ms |
| Trending read p95 | 21.1 ms |
| Repository-report read p95 | 22.0 ms |
| Read samples | 362 per endpoint |

Duplicate replay did not increase the event count. Read p95 meets the local <100 ms goal. Compared with the busiest snapshot event-time second (16 events), measured individual-request throughput offers roughly 4.3× headroom in this test. Actual burst arrivals, many readers, and long-term appends need separate measurement.

Independent Python analysis read the raw gzip directly and verified all 500 repositories, plus six extra drill-down reports and six trend reports across month/seven-day/hour ranges. Activity counts, PR state order and pagination, merge coverage/statistics, and contribution breakdowns matched. Counts: 138,676 input rows, 137,302 unique events, 1,374 duplicates, 500 repositories, 1,448 merged PRs, and only 43 with a usable observed opening/merge pair.

The [actual query plan](docs/query-plan.txt) shows repository and exact timestamp filters at the scan, projects only occurred_at/event_type for activity, and excludes raw JSON. No extra ART indexes, rollups, materialized views, or second database were needed to meet the measured target. Initial sorting and small row groups help drill-down; late appends may reduce pruning and should be remeasured before adding periodic compaction or precomputation.

The portable launcher was smoke-tested from a fresh virtual environment and a fresh database using the full snapshot. Import accepted 137,302 events and the launched API reported 500 repositories. The original baseline database remains free of benchmark/demo events.

[Complete final results](docs/final-benchmark.json) · [Detailed measurements](docs/performance.md#final-application-measurements) · [Reproduce the benchmark](docs/development.md#development-and-verification)

### Appendix C: snapshot-only merge timing and visualization decisions

#### Keep the supplied snapshot as the only analytical source

During review, most repositories appeared to have unavailable merge times. We checked
all 500 repositories in the default seven-day and full-month windows against an independent
analysis of the raw gzip: 1,000 API reports agreed on merged and measurable counts.
The limitation is missing PR opening history in the source, rather than a merge-query defect.

| Snapshot window (UTC) | Merged PRs | Measurable pairs | Repositories with samples |
| --- | ---: | ---: | ---: |
| 25 Aug–1 Sep 2026, default | 305 | 2 | 2 |
| 1 Aug–1 Sep 2026, full month | 1,448 | 43 | 32 |

The PR payloads contain url/id/number/head/base but no created_at, merged_at, or closed_at
fields. An opening event may precede the month or be absent from the supplied records.
We cannot infer the true opening time for those PRs from this snapshot.

**Decision:** keep the supplied snapshot as the only analytical source. Do not add GitHub
API timestamp enrichment, cached external metadata, or a GitHub authentication requirement.
This keeps interviewer startup simple and results reproducible from the committed gzip.
The event receiver remains available as a separate exercise interface; no live GitHub
subscription or external lookup is required for any dashboard read.

Public GitHub data can be fetched without authentication, but the unauthenticated API limit
is 60 requests/hour. Bulk enrichment would require more setup or a separately prepared cache,
plus another source to document. [GitHub rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

Consequences:

- Measure only valid observed opening-to-merge pairs, and expose measurable/merged coverage.
- Distinguish **no merged PRs in the range** from **merged PRs with missing opening history**.
- Show a reason and a full-snapshot range action instead of three repeated unavailable values.
- Preserve median/mean/p90 for valid samples, including a valid zero duration.
- Treat small samples as observations, not a repository-wide performance estimate.

Default-window examples: **openai/codex-security** has 1/1 measurable merge, median **20.4 h**;
**agentconnect-md/agentconnect** has 1/3, median **7.1 min**. Select **All data** for examples
such as **openai/codex**, 2/14, median **2.3 min**. workweave/router has 0/2 in the default
window and 0/3 in the full month.

[All 32 repositories with full-month timing samples](docs/merge-timing-coverage.md)
and [exact unrounded statistics](docs/merge-timing-coverage.json).

#### Separate activity charts by event type

The original overlaid lines and dense legend were difficult to read. The replacement uses
six aligned bar charts for PR events, issues, stars, pushes, reviews and comments. Each shows
its total, peak, UTC buckets and count axis. Independent scales reveal patterns; a **Use same
scale** control compares absolute volumes. Other observed types expand below, and a keyboard
accessible count table exposes all exact values. Empty types and empty ranges are explicit.
PR activity still counts all PR actions, and exact half-open range filtering is unchanged.

Verification: 40 Python tests, six JavaScript model tests, live HTTP E2E, desktop/mobile
browser checks, tooltips, shared scales, extra types, count tables, pagination, bot filtering,
and rapid rerenders passed. Browser console errors: none observed. The backend queries and
snapshot database were unchanged, so Appendix B remains the backend measurement baseline.

[Desktop preview](docs/activity-redesign.jpg) · [Detailed PR timing and visualization rationale](docs/design-decisions.md#snapshot-only-merge-timing-and-visualization-decisions).

## AI session logs

[Unedited session logs and index](ai-logs/README.md) include this conversation and both delegated sessions. The [export manifest](ai-logs/manifest.json) records capture time, file sizes, and SHA-256 hashes.

## Further details

- [Architecture, schema, API and metric definitions](docs/architecture.md)
- [Design decisions and rationale](docs/design-decisions.md)
- [Performance measurements and limits](docs/performance.md)
- [Development, tests and submission notes](docs/development.md)
- [Documentation index](docs/README.md)

Verification: **40 Python tests, six JavaScript tests, and live HTTP integration checks pass**. Test and benchmark commands are in the development guide.
