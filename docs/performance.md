# Performance measurements

[Project overview and quickstart](../README.md) · [Documentation index](README.md)

## Exploratory DuckDB probe

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

### Decisions supported by the probe

- Choose DuckDB alone: the supplied workload fits direct analytics and committed event ingestion. A second SQLite store would add synchronization and failure-handling work without a demonstrated user-facing gain.
- Normalize typed columns once; avoid parsing source JSON during dashboard requests.
- Sort the initial load by repository/time: median open-PR query latency improved from 2.92 ms in arrival order to about 1.50 ms.
- Use 16,384-row groups: nine groups instead of two. Timestamp-first ordering improved one-hour global ranking from about 0.72 ms to 0.43 ms, while repository-first ordering benefited drill-down. Keep one layout rather than duplicate data for each query.
- Preserve exact range predicates and source arrival sequence. Physical ordering is an optimization, not a lifecycle ordering rule.
- Bulk-load the snapshot. Per-event commits are appropriate for the small receiving interface but expensive for importing the entire file.
- Keep direct queries initially. Add precomputation only if final measurements identify a concrete slow query.

### Limits of the exploratory measurements

The probe did not include HTTP handling, full envelope validation, canonical hashing, raw JSON storage, metadata writes, UI rendering, or crash-recovery testing. Its contributor query counted all actions for six types; the final metric has narrower action rules. The final application benchmark below measures the full implementation. SQLite was not benchmarked, so these results establish DuckDB feasibility rather than a comparative write-speed claim.

[Complete exploratory results](feasibility-results.json)

## Final application measurements

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

The [actual query plan](query-plan.txt) shows repository and exact timestamp filters at the scan, projects only occurred_at/event_type for activity, and excludes raw JSON. No extra ART indexes, rollups, materialized views, or second database were needed to meet the measured target. Initial sorting and small row groups help drill-down; late appends may reduce pruning and should be remeasured before adding periodic compaction or precomputation.

The portable launcher was smoke-tested from a fresh virtual environment and a fresh database using the full snapshot. Import accepted 137,302 events and the launched API reported 500 repositories. The original baseline database remains free of benchmark/demo events.

[Complete final results](final-benchmark.json)
