# GitHub activity explorer

A local dashboard for trending GitHub repositories, activity over time, observed open PRs, merge durations, and contributors.

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

## Key design decisions

- **DuckDB only:** direct queries met the measured target—read p95 around 21–22 ms during concurrent ingestion. This keeps storage and analytics in one system.
- **Fast range queries:** typed columns, initial repository/time ordering, and 16,384-row groups. Dashboard queries do not parse raw JSON.
- **Idempotent ingestion:** event IDs are unique; identical replays are ignored, conflicting contents are rejected, and writes commit atomically.
- **Snapshot-only PR timing:** no GitHub API enrichment or credentials. Durations use valid observed opening/merge pairs and show sample coverage; missing history gets an explicit explanation.
- **Trending metrics:** *New stars* counts star additions in the selected range. *Momentum* subtracts the previous equal-length window's count; unavailable comparison history falls back to New stars.
- **UTC throughout:** ranges use `[start, end)`. Open PRs reflect the dataset watermark and are independent of the selected activity range.
- **Readable activity:** separate charts per event type, an optional shared scale, and an exact-value table.

For a merge-timing demo, try **openai/codex-security** in the default seven-day view, or **openai/codex** with **All data**. [See all repositories with timing samples](docs/merge-timing-coverage.md).

## Further details

- [Architecture, schema, API and metric definitions](docs/architecture.md)
- [Design decisions and rationale](docs/design-decisions.md)
- [Performance measurements and limits](docs/performance.md)
- [Development, tests and submission notes](docs/development.md)
- [Documentation index](docs/README.md)

Verification: **40 Python tests, six JavaScript tests, and live HTTP integration checks pass**. Test and benchmark commands are in the development guide.
