---
name: token-analyzer
description: Answer questions about the user's own Claude Code token usage (how much, when, on what, where tokens were wasted, plan-limit use) and customize the Token Analyzer dashboard. Use when the user asks about their tokens, usage, limits, costs, 5-hour windows, or wants to change the dashboard's settings or labels.
---

# Token Analyzer

Data lives in `~/.claude-token-analyzer/` (or `$CTA_HOME`). Scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts`.

| File | Contents |
|---|---|
| `out/agg.json` | everything the dashboard shows: `levels.{day,week,month,year,all}[key]` with `weighted`, `cost`, `requests`, `sessions`, `avg_context`, `avoid_low`, `avoid_high`, `leaks`, `by_task`, `by_project`, `by_tool`, `by_model`, `series`; plus `windows`, `sessions` (timelines), `limits`, `meta` |
| `out/daily.csv` | per usage day: `weighted`, `cost_usd`, `requests`, `sessions`, `avg_context`, `avoid_low`, `waste_est` (= high) |
| `out/usage_hourly.csv` | per session per hour, with `project`, `task_type`, `title` |
| `out/events.csv` | leaks: `day`, `session`, `title`, `kind`, `waste_est`, `detail`, `requests`, `confidence` (likely/possible) |
| `out/report.md` | latest daily report |
| `out/dashboard.html` | the dashboard |
| `limits.jsonl` | plan-limit readings from the optional status line |
| `config.json`, `labels.json` | the user's settings and label overrides |

## Answering usage questions
1. If `out/agg.json` is missing or older than today, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/refresh.py"` (or `python`).
2. Prefer `agg.json` for totals by period; read CSVs only for detail. Use a short script; never print whole files.
3. Report weighted tokens (cost in Sonnet 5 input tokens, from Anthropic's per-model API prices) or `cost` in API-equivalent dollars. Say that "avoidable" is an estimate: `avoid_low` counts likely leaks, `avoid_high` adds possible ones.
4. Only Claude Code sessions on this computer are covered; claude.ai, the phone app and cloud sessions are not, though they share the same plan limits.

## Customizing
Edit `config.json`: `plan` ("subscription"/"api"), `cache_ttl_minutes`, `day_start_hour`, `context_target` ("auto" or a number), `min_reprefill_tokens`, `polling_min_requests`, `polling_max_output_per_request`, `duplicate_window_hours`, `noisy_tool_output_chars`, `reference_model`, `report_history_days`, `privacy_mode`, `auto_refresh_on_session_start`, `open_dashboard_after_refresh`, `nudges`, `statusline_chain`, `extra_log_dirs`, `claude_projects_dir`. Relabel a session in `labels.json`. Then run `refresh.py`. Never edit files inside the plugin folder for personal settings; updates replace them. Prices live in the plugin's `data/pricing.json`.
