# GitHub activity explorer

A local GitHub event analytics dashboard with snapshot import, an idempotent event receiving API, and a single persistent DuckDB store. The design below was reviewed before implementation.

## Run locally

Requirements: Python 3.11+, Bash, curl, and Internet access for the initial dependency installation and snapshot download. No Node build is needed.

```sh
git clone https://github.com/ZhePang/servicenow-github-activity.git
cd servicenow-github-activity
bash scripts/run.sh
```

Open http://127.0.0.1:8765/. Keep the terminal open; Ctrl-C stops the server. First run creates `.venv/`, downloads the supplied snapshot, imports it, and starts one API process. Later runs reuse the database. Use `GHT_PORT=8766 bash scripts/run.sh` for another port. An API already running on that port is reported instead of starting a second process.

The compressed source snapshot is included at [`data/events.jsonl.gz`](data/events.jsonl.gz), from [the supplied dataset release](https://github.com/Chenglin97/gh-trending-dataset/releases/download/v1/github-events-2026-08-top500repos.jsonl.gz). The generated DuckDB database is excluded. Importing the full file took 13.1–13.4 seconds locally after download.

### Development and verification

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m compileall -q app scripts tests
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.e2e
```

39 tests pass. The E2E script starts a real Uvicorn server and verifies ingestion, duplicates, conflicts, analytics, and immediate read-after-write. Browser checks covered keyboard navigation, range controls, stale requests, bot filtering, pagination, invalid-range recovery, responsive layouts, and a submitted event appearing exactly once after Refresh. Browser console errors: none observed.

To replay an import, stop the server first so the CLI can own the embedded database:

```sh
.venv/bin/python -m scripts.import_snapshot --path data/events.jsonl.gz --db data/events.duckdb
```

Identical IDs are ignored; conflicting contents or malformed lines abort the import atomically. To reproduce full-snapshot verification and HTTP measurements, stop all source DB writers and run:

```sh
.venv/bin/python -m scripts.benchmark
```

The benchmark requires a checkpointed source DB with no pending WAL, copies it to a temporary directory, launches a separate server, checks independent references, and writes synthetic events only into the disposable copy. Results are saved to `docs/final-benchmark.json`.

### Receiving one event

```sh
curl -i -X POST http://127.0.0.1:8765/api/events \
  -H 'Content-Type: application/json' --data-binary @docs/demo-event.json
```

Expect 201 for a new ID, 200 for an identical replay, 409 for conflicting contents, and 422 for invalid input. This command adds a demonstration star; use a disposable database for a recording. The interface accepts the supplied GHArchive event shape. A real GitHub webhook would need an adapter and authentication before deployment. API documentation is at http://127.0.0.1:8765/docs.

### Submission files

- Application code, tests, local frontend assets, startup/verification scripts, and the compressed source snapshot.
- This README: reviewed design, metric definitions, assumptions, and measurement appendices.
- [Final benchmark](docs/final-benchmark.json), [query plan](docs/query-plan.txt), and [installed versions](docs/installed-packages.txt).
- [Recording outline](docs/recording-outline.md), target 4:30; recording/upload remains a user handoff.
- Unedited AI session exports will be added at the final handoff, as requested.

[GitHub repository](https://github.com/ZhePang/servicenow-github-activity). The final recording URL and session-log export remain submission handoff steps.

## Design

The following design was reviewed in the accompanying AI session. The imported history is assumed complete and up to date; the API represents the continuing real-time event stream, as confirmed in the AI session.

## Purpose

Build a service that accepts GitHub events and a dashboard that explains trending
repositories and their internal activity. Use a single persistent DuckDB database.
The snapshot importer and HTTP endpoint share validation and normalization rules.

## Stack and runtime

- Python 3.11+, FastAPI, Uvicorn, DuckDB 1.5.6.
- Plain HTML, CSS, JavaScript, and a pinned, locally served Chart.js distribution.
- Direct runtime and development dependencies are pinned; measured installed versions are recorded in docs/installed-packages.txt.
- One Uvicorn process owns the embedded database; two DuckDB execution threads.
- FastAPI serves the dashboard and JSON API from the same origin.
- Project directory: outputs/github-trending/ in the working session; the submission bundle has github-trending/ as its root.
- Tests: pytest for domain/storage/API behavior, an HTTP E2E script that launches
  a real Uvicorn process, and a browser walkthrough with screenshots.

## Architecture

```text

  SNAPSHOT BOOTSTRAP                         HTTP INGESTION
  ------------------                        --------------
  events.jsonl.gz                           POST /api/events
         |                                         |
  stream JSON lines                         parse one JSON object
         |                                         |
         +---------------+-------------------------+
                         |
                         v
              +--------------------------+
              | Shared event validation  |
              | + normalization          |
              | IDs / UTC / PR action    |
              | canonical content hash   |
              +------------+-------------+
                           |
              +------------+-------------+
              |                          |
              v                          v
       typed staging batches      normalized single event
       preserve arrival order     acquire writer lock
       deduplicate in staging
              |                          |
              +------------+-------------+
                           |
                           v
              +--------------------------+
              | Shared persistence rules |
              | BEGIN transaction        |
              | reject conflicting IDs   |
              | insert new events only   |
              | update data metadata     |
              | COMMIT                   |
              +------------+-------------+
                           |
                           v
              +--------------------------+
              | Persistent DuckDB        |
              | events: typed columns    |
              | raw JSON: cold column    |
              | metadata: revision/time  |
              | unique event_id          |
              | initial repo/time order  |
              +------------+-------------+
                           |
                           v
              +--------------------------+
              | Parameterized SQL        |
              | trends / activity        |
              | PR state / durations     |
              | contributors             |
              +------------+-------------+
                           |
              per-request read transaction
              consistent metadata + results
                           |
                           v
              +--------------------------+
              | FastAPI read endpoints   |
              | bounded JSON responses   |
              +------------+-------------+
                           |
                           v
              +--------------------------+
              | Browser dashboard        |
              | range + ranking controls |
              | repository drill-down    |
              +--------------------------+

```

## Domain and storage model


```text
events
  event_id          VARCHAR PRIMARY KEY
  repo_id           BIGINT
  repo_name         VARCHAR
  actor_id          BIGINT
  actor_login       VARCHAR
  is_bot            BOOLEAN
  event_type        VARCHAR
  action            VARCHAR NULL
  occurred_at       TIMESTAMPTZ, normalized to UTC
  received_at       TIMESTAMPTZ
  ingest_seq        BIGINT
  pr_number         INTEGER NULL
  content_hash      VARCHAR
  raw_json          JSON

metadata (one row)
  schema_version, revision, unique_event_count,
  min_event_time, max_event_time, next_ingest_seq

```

Named domain types: EventEnvelope, NormalizedEvent, TimeRange, IngestResult,
TrendRow, RepositoryReport. Domain normalization is independent of DuckDB and HTTP.
Infrastructure code owns SQL, transactions, connections, and downloading.

Event IDs remain strings. Repository and actor IDs are stable numeric identities;
names/logins are display values. The raw payload is preserved but excluded from
analytical SELECT lists. Repository display names use the latest observed name by
event time with ingestion sequence as a tie-breaker.

Allocate ingest_seq before physical sorting, preserving original snapshot arrival
order. Endpoint events receive later sequence values. Neither physical row order
nor API arrival alone determines chronological PR state.

The content hash is SHA-256 over canonicalized source JSON, with object keys sorted;
server-generated received_at and ingest_seq are excluded. A replay with equivalent
JSON key order is a duplicate. An existing event ID with different canonical content
is rejected rather than silently replacing history.

## Validation and ingestion contracts


POST /api/events accepts one GH Archive / GitHub Events API-shaped JSON object:
  id, type, created_at, repo {id,name}, actor {id,login}, payload {...}

Validate nonempty identifiers, positive numeric repo/actor IDs, a timezone-aware
timestamp, and an object payload. PullRequestEvent requires a positive PR number
from payload.number or payload.pull_request.number; if both exist they must agree.
Unknown event types/actions are retained for activity charts but do not gain a
contribution or lifecycle interpretation. Bot detection uses the '[bot]' suffix
and is explicitly described as a heuristic.

201: {event_id, status:'inserted', revision}
200: {event_id, status:'duplicate', revision}; data and revision remain unchanged.
409: existing ID has different canonical content; transaction changes nothing.
422: invalid envelope, timestamp, range, or PR fields; field-level explanation.
Unexpected storage errors roll back and return a generic 500 response; log details
on the server. A successful insertion response is sent only after COMMIT.

The endpoint is a working receiver for this documented envelope format. Registering
GitHub webhooks, signature verification, and adapting webhook-specific payloads are
outside the agreed static-snapshot scope.

## Snapshot bootstrap

1. Download the pinned v1 release asset into data/ if absent.
2. Stream gzip lines, validate with the same normalizer, and stage typed batches.
3. Preserve source line numbers for diagnostics and sequence allocation.
4. Collapse identical repeated IDs; abort on malformed input or conflicting IDs.
5. Insert new events in repository/time order and update metadata in one transaction.
6. Checkpoint and print read/inserted/duplicate counts and elapsed import time.
7. Start Uvicorn after bootstrap succeeds.

The importer can be rerun without increasing event counts. Run the CLI importer
before the server owns the database; incremental input while running uses the API.
Staging files are temporary; download and database files are ignored by Git.

## Analytical definitions for review


Time selection
- All UI labels and API timestamps use UTC.
- Every selected range is half-open: start <= occurred_at < end.
- Initial coverage is the calendar days containing the min/max observed timestamps.
  For this snapshot, the UI covers August 1 through September 1 exclusive.
- Default: last seven calendar days ending at that coverage end.
- Presets: 24 hours, 7 days, all available data; custom UTC start/end controls.
- Ranges must be nonempty and within the displayed observed-day coverage bounds.
- The exact latest event timestamp is always displayed separately as the data watermark.
- After a successful insertion, metadata extends observed bounds when needed. Refresh
  re-queries metadata and the active view; custom selections are preserved if valid.

Trending
- A new star is a WatchEvent with payload.action='started'.
- Proposed default rank: star momentum = stars(current range) - stars(previous range).
- The previous range has exactly the same duration and ends at the current start.
- Include repositories with at least one current-range star.
- Tie-break by current star count descending, then repo_id ascending.
- Also offer 'New stars' sorting; show current count, previous count, and absolute change.
- Momentum is available only when the complete previous window lies within the
  observed-day coverage. Otherwise select 'New stars' and explain that comparison
  history is unavailable; never interpret missing history as zero growth.
- Known zero previous stars can be labeled 'New attention'; no infinite percentage.

Activity chart
- Count deduplicated events by repository, UTC bucket, and event type.
- Preserve exact start/end filtering before bucketing.
- Use hourly buckets for ranges <=48 hours and daily buckets for longer ranges.
- Fill missing buckets with zeros. Include event-type legend toggles; stars, PRs,
  issues, reviews, comments, and other observed types retain explicit labels.
- PR activity means PR events, including labeling etc.; label it accordingly so
  it cannot be mistaken for the number of distinct PRs opened.

Observed open PRs
- 'Now' means the latest event timestamp in the dataset, not today's GitHub state.
- This list uses all available PR history up to that watermark, independent of the
  activity time filter. Show the separate as-of label directly above the list.
- For each (repo_id, pr_number), select the latest state-changing action among
  opened, reopened, closed, merged by (occurred_at DESC, ingest_seq DESC).
- opened/reopened => observed open; closed/merged => not open. A labeling/review
  event alone leaves state unknown and does not create an open PR.
- Missing earlier history limits completeness; describe the list as observed open PRs.
- Rows contain PR number/link, latest transition time, first observed opening time
  when known, and opening actor when known. The snapshot supplies no PR title.
- Paginate 25 rows at a time, newest state transition first, then PR number.

Merge durations
- Select distinct PRs with a merged action inside the chosen activity range.
- Look for their earliest observed opened event across all available earlier history.
- Duration = merge event time - first observed opening time; require a nonnegative
  duration and a valid pair. Reopening does not reset time since first observed open.
- Return median, mean, p90, matched sample count, total merged PR count, and coverage.
- Unknown durations remain unavailable; they do not contribute zero values.
- Display paired/merged counts and the observed-history limitation. Across the entire
  supplied snapshot only 43 PRs have measurable opened-to-merged pairs.

Top contributors
- Proposed rank: number of contribution events in the selected repository/range.
- Include pushes, opened PRs, opened issues, created reviews, created issue/PR comments,
  and created inline review comments. A PushEvent counts as one push, not as commits.
- Exclude stars, forks, labeling, branch creation/deletion, and administrative actions.
- Actors represent who performed events; the payload does not establish all PR authors.
- Exclude '[bot]' actors by default; provide an 'Include bots' checkbox for this table.
- Show top 10 actors, total contributions, and a breakdown by category. Break ties by
  actor_id. Caption the metric as 'Contribution events' to make its definition clear.

## Read API

```text

GET /api/health
  database connectivity + schema version

GET /api/meta
  observed-day coverage, exact watermark, accepted count, repository count, revision

GET /api/trending?start=...&end=...&sort=momentum|stars&limit=20&q=...
  bounded list, metric definition, comparison availability, revision
  limit 1..50; q searches repository names within the 500-repository set

GET /api/repos/{repo_id}?start=...&end=...&include_bots=false&pr_offset=0&pr_limit=25
  repository name, activity series, open-PR page/count/as-of, merge statistics,
  contributor table, range, metric definitions, revision
  PR limit 1..50; offset >=0; nonexistent repository =>404

Every report uses a single read transaction for its SQL statements and metadata.
Thus its watermark, counts, and returned revision describe one consistent snapshot.
SQL parameters are bound; allowed sorting is mapped to fixed SQL expressions.

```

## Query and storage improvements

- Initial ORDER BY repo_id, occurred_at, ingest_seq favors repository drill-down.
- Use 16,384-row groups, the tested small-group layout: nine groups rather than two
  on this snapshot. This setting is cheap, but its benefit is workload-dependent.
- Use typed predicates and column projection; do not parse raw JSON in dashboard SQL.
- event_id uniqueness supplies duplicate lookup; add no extra ART indexes initially.
- Direct queries compute counts, window functions for lifecycle state, and merge pairs.
  There are no precomputed count tables or query caches in the initial implementation.
- Each request gets its own DuckDB cursor/connection; never run concurrent operations
  on the same cursor. Writes are serialized with a process-local lock. Keep one server
  process; read transactions can overlap the writer using separate connections.
- Inspect EXPLAIN ANALYZE for filter placement and projected columns. Late appends
  preserve correct answers but can reduce initial ordering/pruning effectiveness.
- Rerun the performance probe with raw_json, hashing, validation, metadata updates,
  HTTP, and the final query definitions; earlier narrow-column timings are a baseline.

## Dashboard wireframe

```text

  +--------------------------------------------------------------------------+
  | GitHub activity explorer                   Data through [UTC watermark]  |
  | [24h] [7 days] [All]   Start [........] End [........] UTC   [Refresh]     |
  +--------------------------------------------------------------------------+
  | [Momentum | New stars]                    Find repository [...........]  |
  | Rank  Repository                 New stars  Previous   Change           |
  |   1   owner/project-a                 ...       ...      ...   [Open]    |
  |   2   owner/project-b                 ...       ...      ...   [Open]    |
  |   ...                                                                    |
  +--------------------------------------------------------------------------+

  Click a row -> repository view; preserve range and ranking state.

  +--------------------------------------------------------------------------+
  | [Back to trends] owner/project-a                          [View on GitHub]|
  | Selected activity range [start, end) UTC                                 |
  +--------------------------------------------------------------------------+
  | Activity over time                                                      |
  | [Stars] [PR events] [Issues] [Reviews] [Comments] [Other types]            |
  |                       time-series chart                                 |
  +-------------------------------------+------------------------------------+
  | Observed open PRs                    | Merge duration                     |
  | As of [dataset watermark]            | Median / mean / p90                |
  | #123   observed opened ...           | Paired N of M merged PRs           |
  | #456   observed reopened ...         | Unavailable if no valid pairs      |
  | [Previous] [Next]                    | Observed-history explanation       |
  +-------------------------------------+------------------------------------+
  | Top contributors                          [ ] Include bots              |
  | Actor               Contribution events          Breakdown              |
  +--------------------------------------------------------------------------+

```

## Visual and interaction design

- A compact analytical workbench, with left-aligned tables and labeled chart axes.
- Palette: white #FFFFFF, surface #F3F6FA, text #17233B, blue #2563EB,
  purple #7C3AED, amber #B8860B. Blue/purple/amber identify PR/issues/stars;
  additional observed types use labeled, distinguishable chart lines.
- System sans-serif text and tabular numerals; use the user's local system font.
- Stable colors, visible keyboard focus, accessible control labels, responsive layout.
- Chart animations disabled. Cancel stale requests when users change filters quickly.
- Loading, empty, invalid-range, and request-failure states are explicit; failed requests
  offer Retry. Empty merge samples show 'Unavailable', not a fabricated duration.
- Static frontend assets and fonts work without a CDN after dependency setup.
- Review against the brief: prioritize the ranked table and drill-down; keep visual
  decoration minimal so clarity and time spent on correctness remain the priorities.

## Project layout

```text

  github-trending/
    app/
      domain.py             normalized types and shared validation
      store.py              schema, ownership, transactions, ingestion
      queries.py            analytical SQL and response mapping
      main.py               FastAPI routes and static frontend
    web/
      index.html, app.js, styles.css
      vendor/               pinned Chart.js + license
    scripts/
      run.sh                environment, download, bootstrap, start server
      import_snapshot.py    shared importer CLI
      e2e.py                launch server, exercise real HTTP against a test DB
      benchmark.py          independent references and final HTTP measurements
      export_ai_logs.py      refresh byte-for-byte raw session exports
    tests/
      test_domain.py, test_store.py, test_ingestion.py, test_queries.py
      test_frontend.py, test_benchmark.py, test_ai_log_export.py
      conftest.py           small lifecycle/boundary/duplicate fixtures
    data/events.jsonl.gz    supplied compressed snapshot
    data/*.duckdb           generated database, ignored
    ai-logs/                unedited session exports and manifest
    requirements.txt, requirements-dev.txt, README.md, .gitignore

```

## Milestones and verification

At each milestone: types/schema -> expected-behavior tests -> implementation ->
compile/dependency checks -> all existing unit/integration tests. Rerun the complete
existing test suite after each code change; pass the milestone gate before proceeding.

M1. Domain and storage foundation (target 10-15 minutes)
  Types, UTC/range rules, event validation, content hashing, full DuckDB schema,
  metadata, ownership, and connections. Test invalid envelopes, unknown types,
  timestamp normalization, canonical hashes, schema creation, and reopening storage.

M2. Both ingestion paths (target 15 minutes)
  Shared persistence, atomic staging import, duplicate/conflict rules, sequence
  preservation, metadata updates, POST receiver, and import diagnostics.
  Tests: import twice; API duplicate; ID conflict rollback; malformed line abort;
  POST then reopen database; out-of-order events retained; API/import parity.
  Add scripts/e2e.py using a real local Uvicorn process and temporary database.

M3. Analytics and read APIs (target 20 minutes)
  Implement every metric and endpoint above. Expected results come from small
  independent fixtures and Python counts, not from restating the SQL implementation.
  Tests: exact boundaries; baseline availability; zero baseline; momentum ties;
  zero-filled chart; labeling after closure; reopening; late opening event; timestamp
  ties; opening before selected range; missing duration; bot and actor definitions;
  pagination; unknown repository; consistent metadata/results in a read transaction.
  Extend the HTTP E2E script to verify trends, detail, and immediate read-after-write.

M4. Dashboard (target 20 minutes)
  Implement both views, filters, ranking controls, legend, PR pagination, bot toggle,
  data limitations, loading/empty/error states, responsive layout, and local assets.
  Run Python compile/dependency checks and JavaScript syntax checks. Exercise the real
  browser against the server, verify filter changes and navigation, inspect screenshots,
  and confirm a submitted event changes the view exactly once after Refresh.

M5. Final verification and handoff (target 15 minutes + <=5 minute recording)
  Import the full supplied snapshot; assert 137,302 unique accepted events and 500
  repositories. Compare raw counts and matched PR samples with independent analysis.
  Run all unit/integration tests, the browser walkthrough, and final HTTP benchmark.
  Performance writes use a temporary copy so baseline statistics remain reproducible.
  Record first-request and warm latencies, concurrency, hardware available, and scope.
  Local read-API goal: p95 <100 ms for representative ranges under concurrent writes.
  Document measured results; benchmark failures trigger fixes before completion.
  Finish README with startup instructions, metrics, limitations, endpoint examples,
  performance findings, exact dependency versions, actual work time, and AI log links.
  Package every session unedited, including preparation and failed attempts. Prepare
  a recording outline and rehearse the <=5-minute demonstration; video link delivery
  requires the user's recording/upload or an explicitly authorized available tool.

Time estimate is a planning target, not a claim that preparation is excluded.
Record actual effort including the investigation and this design discussion.

## Review decisions

1. Default trending metric: absolute star momentum, with 'New stars' also available.
2. Open PRs: current observed snapshot state, independent of the activity range.
3. Contributors: defined contribution-event count, bots excluded by default.
4. UI stack: FastAPI-served HTML/JavaScript with locally bundled Chart.js.

## Sources checked

https://fastapi.tiangolo.com/tutorial/static-files/
https://www.chartjs.org/docs/latest/getting-started/integration.html
https://duckdb.org/docs/current/connect/concurrency
https://duckdb.org/docs/current/guides/performance/indexing
https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads

## Implementation notes

- M1–M5 implementation and local verification are complete. All 39 tests and live HTTP E2E pass, including timezone-aware fetching, strict PR validation, timestamp overflow handling, atomic rollback, and consistent read transactions.
- Coverage assumption confirmed: imported history is complete and up to date, and the event API continues that stream. Observed date bounds may extend as new events arrive.
- Final contributor queries use the approved action restrictions. The exploratory probe below counted all actions for six types; Appendix B measures the final implementation.

## Appendix A: measurements and database decision

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

The probe did not include HTTP handling, full envelope validation, canonical hashing, raw JSON storage, metadata writes, UI rendering, or crash-recovery testing. Its contributor query counted all actions for six types; the final metric has narrower action rules. The final application benchmark measures the full implementation and is reported in Appendix B. SQLite was not benchmarked, so these results establish DuckDB feasibility rather than a comparative write-speed claim.

[Complete exploratory results](docs/feasibility-results.json)

## Appendix B: final application measurements

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

[Complete final results](docs/final-benchmark.json)

## AI sessions

The user requested that session logs be exported when all work is complete. This initial publication excludes the existing local exports. The final export will preserve every session unedited, including preparation, failed attempts, and delegated review.

## Work time

Work began on 11 October 2026 at 15:10:45 America/Los_Angeles, including preparation, measurement, design discussion, implementation, failed permission attempts, and verification. Final packaging time is recorded in docs/handoff.json. These are session elapsed times, including user discussion and pauses, not a claim of uninterrupted coding time. Implementation began at approximately 15:53:33 local. Recording/upload time is separate and has not yet occurred.
