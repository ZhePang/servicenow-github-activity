# Architecture and analytical contracts

[Project overview and quickstart](../README.md) · [Documentation index](README.md)

## Design

The following design was reviewed in the accompanying AI session. The imported history is assumed complete and up to date; the API represents the continuing real-time event stream, as confirmed in the AI session.

## Purpose

Build a service that accepts GitHub events and a dashboard that explains trending
repositories and their internal activity. Use a single persistent DuckDB database.
The snapshot importer and HTTP endpoint share validation and normalization rules.

## Stack and runtime

- Python 3.11+, FastAPI, Uvicorn, DuckDB 1.5.6.
- Plain HTML, CSS, JavaScript, and a pinned, locally served Chart.js distribution.
- Direct runtime and development dependencies are pinned; see [measured installed versions](installed-packages.txt).
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
Staging files are temporary. The compressed snapshot is committed; generated database files are ignored by Git.

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
- Default rank: star momentum = stars(current range) - stars(previous range).
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
- Fill missing buckets with zeros. Show separate labeled bar charts; stars, PRs,
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
- Rank: number of contribution events in the selected repository/range.
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
- The final benchmark includes raw_json, hashing, validation, metadata updates,
  HTTP, and the final query definitions; see [performance measurements](performance.md).

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
  | [ ] Use same scale                                    [View event counts]|
  | PR events / Issues / Stars: separate count charts                         |
  | Pushes / Reviews / Comments: totals, peaks, UTC dates, shared scale option |
  +-------------------------------------+------------------------------------+
  | Observed open PRs                    | Merge duration                     |
  | As of [dataset watermark]            | Median / mean / p90                |
  | #123   observed opened ...           | Paired N of M merged PRs           |
  | #456   observed reopened ...         | Explicit reason if no valid pairs  |
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
  each event type uses its own bar chart, with matching UTC buckets and explicit count axes.
- System sans-serif text and tabular numerals; use the user's local system font.
- Stable colors, visible keyboard focus, accessible control labels, responsive layout.
- Chart animations disabled. Cancel stale requests when users change filters quickly.
- Loading, empty, invalid-range, and request-failure states are explicit; failed requests
  offer Retry. Empty merge samples explain missing opening history or no merged PRs; no duration is fabricated.
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
      activity-model.js     pure activity and merge presentation models
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
      activity-model.test.cjs  standalone frontend model tests
      conftest.py           small lifecycle/boundary/duplicate fixtures
    docs/                   detailed design, measurements, coverage and handoff
    data/events.jsonl.gz    supplied compressed snapshot
    data/*.duckdb           generated database, ignored
    ai-logs/                unedited session exports and manifest
    requirements.txt, requirements-dev.txt, README.md, .gitignore

```
