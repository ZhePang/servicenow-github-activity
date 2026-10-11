# Merge timing availability in the supplied snapshot

Timing is measured from the first observed PR opening to its first observed merge.
The merged PR must be in the selected window; opening history can be anywhere in the
snapshot. Missing openings are excluded, never assigned an estimated duration.

| Window (UTC, end excluded) | Merged PRs | Measurable pairs | Repositories with pairs |
| --- | ---: | ---: | ---: |
| 25 Aug–1 Sep 2026, default seven days | 305 | 2 | 2 |
| 1 Aug–1 Sep 2026, full snapshot | 1,448 | 43 | 32 |

The raw PR payloads contain url/id/number/head/base, and no created_at, merged_at,
or closed_at lifecycle timestamps. Independent raw-gzip counts matched 1,000 live API
repository reports (all 500 repositories in both windows). The current calculation is
consistent with the supplied data; unavailable durations result from sparse history.

## Default seven-day window

| Repository | Measurable / merged | Median | Local dashboard |
| --- | ---: | ---: | --- |
| agentconnect-md/agentconnect | 1 / 3 | 7.1 min | [Open](http://127.0.0.1:8765/#repo/1310543401) |
| openai/codex-security | 1 / 1 | 20.4 h | [Open](http://127.0.0.1:8765/#repo/1299769220) |

## Full-month window

Select **All data** in the dashboard. These 32 repositories have timing samples.
Small samples describe observed PRs and should not be treated as a repository-wide performance estimate.

| Repository | Repo ID | Measurable / merged | Median |
| --- | ---: | ---: | ---: |
| agentconnect-md/agentconnect | 1310543401 | 1 / 13 | 7.1 min |
| anthropics/claude-plugins-official | 1100776768 | 1 / 7 | 8.5 min |
| bastani-inc/atomic | 1081638046 | 1 / 2 | 13.5 min |
| block/buzz | 1174789082 | 1 / 7 | 30.1 min |
| chatwoot/chatwoot | 202291859 | 1 / 3 | 9.7 min |
| Comfy-Org/workflow_templates | 940826973 | 1 / 4 | 8.4 min |
| DeusData/codebase-memory-mcp | 1166102148 | 1 / 2 | 17 s |
| electron/electron | 9384267 | 1 / 4 | 2.5 h |
| esengine/DeepSeek-Reasonix | 1216785679 | 2 / 11 | 17.8 min |
| frappe/erpnext | 1864233 | 1 / 5 | 38.5 min |
| get-bb/bb | 1166119443 | 2 / 9 | 12.6 min |
| home-assistant/core | 12888993 | 1 / 10 | 21.4 min |
| jdx/mise | 586920414 | 2 / 4 | 4.4 h |
| kirodotdev/KiroCrew | 1303258850 | 1 / 14 | 31.3 min |
| kortix-ai/suna | 868173144 | 1 / 3 | 7.4 min |
| MaaEnd/MaaEnd | 471226425 | 2 / 5 | 13.8 min |
| metabase/metabase | 30203935 | 1 / 17 | 54.8 min |
| microsoft/aspire | 696529789 | 1 / 5 | 59.0 min |
| NixOS/nixpkgs | 4542716 | 1 / 68 | 39.6 min |
| numtide/llm-agents.nix | 1022026685 | 2 / 19 | 4.5 min |
| open-city-ai/haidian | 1262423362 | 4 / 58 | 17.5 min |
| openai/codex | 965415649 | 2 / 14 | 2.3 min |
| openai/codex-security | 1299769220 | 2 / 6 | 10.7 h |
| python/cpython | 81598961 | 1 / 4 | 6.4 min |
| qwen-code-dev-bot/oh-my-cli | 1299227072 | 1 / 3 | 5.7 min |
| raullenchai/Rapid-MLX | 1166182351 | 1 / 9 | 14.6 min |
| renovatebot/renovate | 76734068 | 2 / 3 | 11.9 min |
| stablyai/orca | 1183888342 | 1 / 16 | 12.0 min |
| strelov1/freehire | 1261698251 | 1 / 7 | 15.2 min |
| TableProApp/TablePro | 1117891044 | 1 / 5 | 18.9 min |
| tutti-os/tutti | 1267314128 | 1 / 6 | 27 s |
| vercel/ai | 644461337 | 1 / 8 | 15.2 min |

workweave/router has 0/2 measurable merges in the default window and 0/3 across the month.

[Exact counts and unrounded statistics](merge-timing-coverage.json)
