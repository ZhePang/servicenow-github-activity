# Design decisions and rationale

[Project overview and quickstart](../README.md) · [Documentation index](README.md)

## Review decisions

1. Default trending metric: absolute star momentum, with 'New stars' also available.
2. Open PRs: current observed snapshot state, independent of the activity range.
3. Contributors: defined contribution-event count, bots excluded by default.
4. UI stack: FastAPI-served HTML/JavaScript with locally bundled Chart.js.

## Snapshot-only merge timing and visualization decisions

### Keep the supplied snapshot as the only analytical source

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

[All 32 repositories with full-month timing samples](merge-timing-coverage.md)
and [exact unrounded statistics](merge-timing-coverage.json).

### Separate activity charts by event type

The original overlaid lines and dense legend were difficult to read. The replacement uses
six aligned bar charts for PR events, issues, stars, pushes, reviews and comments. Each shows
its total, peak, UTC buckets and count axis. Independent scales reveal patterns; a **Use same
scale** control compares absolute volumes. Other observed types expand below, and a keyboard
accessible count table exposes all exact values. Empty types and empty ranges are explicit.
PR activity still counts all PR actions, and exact half-open range filtering is unchanged.

Verification: 40 Python tests, six JavaScript model tests, live HTTP E2E, desktop/mobile
browser checks, tooltips, shared scales, extra types, count tables, pagination, bot filtering,
and rapid rerenders passed. Browser console errors: none observed. The backend queries and
snapshot database were unchanged, so [the final application measurements](performance.md#final-application-measurements) remain the backend baseline.

[Desktop preview](activity-redesign.jpg).

## Sources checked

https://fastapi.tiangolo.com/tutorial/static-files/
https://www.chartjs.org/docs/latest/getting-started/integration.html
https://duckdb.org/docs/current/connect/concurrency
https://duckdb.org/docs/current/guides/performance/indexing
https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads
