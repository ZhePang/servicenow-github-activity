#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PORT="${GHT_PORT:-8765}"
if curl --fail --silent "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "An API is already running at http://127.0.0.1:$PORT/. Use GHT_PORT to choose another port."
  exit 0
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
mkdir -p data
if [[ ! -f data/events.jsonl.gz ]]; then
  curl --fail --location --retry 3 'https://github.com/Chenglin97/gh-trending-dataset/releases/download/v1/github-events-2026-08-top500repos.jsonl.gz' -o data/events.jsonl.gz.download
  mv data/events.jsonl.gz.download data/events.jsonl.gz
fi
if [[ ! -f data/events.duckdb ]]; then
  .venv/bin/python -m scripts.import_snapshot --path data/events.jsonl.gz --db data/events.duckdb
fi
echo "Dashboard: http://127.0.0.1:$PORT/ — keep this terminal open; Ctrl-C stops it."
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --workers 1
