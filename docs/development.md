# Development, verification and handoff

[Project overview and quickstart](../README.md) · [Documentation index](README.md)

All commands below run from the repository root.

## Development and verification

Node 18+ is needed only for the standalone frontend unit tests. The dashboard has no Node build or runtime dependency.

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m compileall -q app scripts tests
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.e2e
node --test tests/activity-model.test.cjs
```

40 Python tests and six frontend JavaScript unit tests pass. The E2E script starts a real Uvicorn server and verifies ingestion, duplicates, conflicts, analytics, and immediate read-after-write. Browser checks covered keyboard navigation, range controls, stale requests, bot filtering, pagination, invalid-range recovery, responsive layouts, and a submitted event appearing exactly once after Refresh. Browser console errors: none observed.

To replay an import, stop the server first so the CLI can own the embedded database:

```sh
.venv/bin/python -m scripts.import_snapshot --path data/events.jsonl.gz --db data/events.duckdb
```

Identical IDs are ignored; conflicting contents or malformed lines abort the import atomically. To reproduce full-snapshot verification and HTTP measurements, stop all source DB writers and run:

```sh
.venv/bin/python -m scripts.benchmark
```

The benchmark requires a checkpointed source DB with no pending WAL, copies it to a temporary directory, launches a separate server, checks independent references, and writes synthetic events only into the disposable copy. Results are saved to `docs/final-benchmark.json`.

## Receiving one event

```sh
curl -i -X POST http://127.0.0.1:8765/api/events \
  -H 'Content-Type: application/json' --data-binary @docs/demo-event.json
```

Expect 201 for a new ID, 200 for an identical replay, 409 for conflicting contents, and 422 for invalid input. This command adds a demonstration star; use a disposable database for a recording. The interface accepts the supplied GHArchive event shape. A real GitHub webhook would need an adapter and authentication before deployment. API documentation is at http://127.0.0.1:8765/docs.

## Submission files

- Application code, tests, local frontend assets, startup/verification scripts, and the compressed source snapshot.
- Documentation: architecture, metric definitions, assumptions, design decisions, and measurements.
- [Final benchmark](final-benchmark.json), [query plan](query-plan.txt), and [installed versions](installed-packages.txt).
- [Demo walkthrough](https://youtu.be/BF8UxTb9HZQ) and [recording outline](recording-outline.md).
- [Unedited AI session exports](../ai-logs/README.md), including the main conversation and both delegated sessions.

[GitHub repository](https://github.com/ZhePang/servicenow-github-activity). The README links the demo walkthrough and AI session logs.

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
  Implement every metric and endpoint in the architecture guide. Expected results come from small
  independent fixtures and Python counts, not from restating the SQL implementation.
  Tests: exact boundaries; baseline availability; zero baseline; momentum ties;
  zero-filled chart; labeling after closure; reopening; late opening event; timestamp
  ties; opening before selected range; missing duration; bot and actor definitions;
  pagination; unknown repository; consistent metadata/results in a read transaction.
  Extend the HTTP E2E script to verify trends, detail, and immediate read-after-write.

M4. Dashboard (target 20 minutes)
  Implement both views, filters, ranking controls, activity charts, PR pagination, bot toggle,
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
  Finish README with startup instructions, architecture and key decisions; keep metric
  definitions, API examples, measurements, versions and handoff notes in docs/.
  Package every session unedited, including preparation and failed attempts. Prepare
  a recording outline and rehearse the <=5-minute demonstration; video link delivery
  requires the user's recording/upload or an explicitly authorized available tool.

Time estimate is a planning target, not a claim that preparation is excluded.
Record actual effort including the investigation and this design discussion.

## Implementation notes

- M1–M5 implementation and local verification are complete. All 40 Python tests, six JavaScript tests, and live HTTP E2E pass, including timezone-aware fetching, strict PR validation, timestamp overflow handling, atomic rollback, and consistent read transactions.
- Coverage assumption confirmed: imported history is complete and up to date, and the event API continues that stream. Observed date bounds may extend as new events arrive.
- Final contributor queries use the approved action restrictions. The exploratory probe counted all actions for six types; [Performance measurements](performance.md#final-application-measurements) cover the final implementation.

## AI sessions

The [AI session index](../ai-logs/README.md) links raw JSONL copies of the main session,
design audit, and merge-timing investigation. They preserve preparation, discussion,
failed attempts, implementation and review without filtering or rewriting. The
[manifest](../ai-logs/manifest.json) records capture time, original paths, file sizes
and SHA-256 hashes. The main session is captured at that point in the continuing
conversation; later messages require refreshing the export.

## Work time

Work began on 11 October 2026 at 15:10:45 America/Los_Angeles, including preparation, measurement, design discussion, implementation, failed permission attempts, and verification. Packaging timestamps are recorded in [handoff.json](handoff.json). These are session elapsed times, including user discussion and pauses, not a claim of uninterrupted coding time. Implementation began at approximately 15:53:33 local. The user supplied the demo URL at final handoff; recording/upload time is separate and was not tracked.
