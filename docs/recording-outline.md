# Demonstration outline — target 4 minutes 30 seconds

Record the browser and terminal, then supply the resulting video link with the submission.
The outline and walkthrough are prepared; a video has not been recorded or uploaded.

## Preparation before recording

1. Run `bash scripts/run.sh` and open http://127.0.0.1:8765/.
2. For the ingestion demonstration, use a disposable copy: stop the server with Ctrl-C,
   copy `data/events.duckdb` to `data/demo.duckdb`, then start:

   ```sh
   GHT_DB_PATH=data/demo.duckdb .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --workers 1
   ```

   Stop writers and ensure there is no pending source `.wal` before copying.
3. Prepare a second terminal at the project root for the curl commands below.
4. Keep README Appendix B and `docs/final-benchmark.json` ready to show.

## 0:00–0:45 — Question and trending

Show the default seven-day ranking. Explain that momentum means new star events minus
an equally long previous window, with deterministic ties. Switch to New stars, then All
data to show why comparison becomes unavailable. Return to seven days and search for
`openai/codex`.

## 0:45–1:45 — Repository activity and data honesty

Open the repository. Show the activity chart, change to 24h for hourly counts, and use
All data to show merge samples. Explain that open PR state is reconstructed at the data
watermark and does not change with the activity range. Openings absent from the snapshot
make merge durations unknown, so the UI shows measurable/merged coverage. Contributor
scores count defined contribution events; pushes are not commit counts. Toggle bots.

For pagination, briefly search `openclaw/openclaw`: it has 70 observed open PRs.

## 1:45–2:35 — Receiving interface and idempotence

Return to seven-day trends and search `openai/codex`; note its star count. In the terminal:

```sh
curl -i -X POST http://127.0.0.1:8765/api/events \
  -H 'Content-Type: application/json' --data-binary @docs/demo-event.json
```

Show 201, then Refresh in the browser to show one new star. Repeat the identical command
and show 200/duplicate, then Refresh to show the count stays the same. This is a receiving
interface; the exercise does not include a real GitHub subscription or webhook adapter.

## 2:35–3:30 — Architecture and measured choices

Show the README ASCII diagram: shared normalization, snapshot staging and HTTP receiver,
one transactional DuckDB store, consistent read transactions, same-origin dashboard.
Explain typed predicates, initial repository/time order, 16,384-row groups, event-ID
uniqueness and one writer. Raw JSON is retained but excluded from analytical scans.

## 3:30–4:30 — Evidence and limits

Show Appendix B: 137,302 unique events; 506 repository reports independently verified;
~69.5 individual HTTP commits/s with concurrent reads; read p95 ~21–22 ms. Compare with
the snapshot's busiest event-time second (16 events). Explain that event time is not
network arrival time, and this is a local single-process measurement. Show the 39 passing
tests and live HTTP E2E command/results. Mention that direct queries met the target, so
extra stores and precomputation were not needed for this measured dataset.

End with startup instructions and the unedited AI-log folder. Total target: 4:30.
