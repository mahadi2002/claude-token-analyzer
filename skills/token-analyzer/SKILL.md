---
name: token-analyzer
description: Answer questions about the user's own Claude Code token usage (how much, when, on what, where tokens were wasted) and customize the Claude Token Analyzer dashboard. Use when the user asks about their tokens, usage, limits, costs, 5-hour windows, or wants to change the dashboard's settings or labels.
---

# Claude Token Analyzer

Data lives in `~/.claude-token-analyzer/` (or `$CTA_HOME`):

| File | Contents |
|---|---|
| `out/usage_hourly.csv` | per session per hour: tokens by type, `weighted`, `requests`, `project`, `task_type`, `title` |
| `out/daily.csv` | per usage day: `weighted`, `requests`, `sessions`, `avg_context`, `waste_est`, `waste_share` |
| `out/events.csv` | token leaks: `day`, `session`, `title`, `kind`, `waste_est`, `detail` |
| `out/report.md` | latest daily report |
| `out/dashboard.html` | the dashboard (open in a browser) |
| `config.json` | settings (see below) |
| `labels.json` | manual `{"<session id first 8 chars>": ["Project", "Task type"]}` overrides |

The scripts are in this plugin's `scripts/` folder (`${CLAUDE_PLUGIN_ROOT}/scripts`).

## Answering usage questions
1. If `out/daily.csv` is missing or older than today, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/refresh.py"` (or `python`).
2. Answer from the CSVs with a short script (pandas is not required; use the `csv` module). Read only the columns you need; do not print whole files.
3. Use "weighted tokens" for comparisons: input x1, cache write x1.25, cache read x0.1, output x5 by default. Say that "avoidable" is an estimate from the thresholds in `config.json`.
4. Only Claude Code sessions on this computer are covered; claude.ai chats and cloud sessions are not.

## Customizing
Edit `config.json` (created on first run): `day_start_hour`, `context_target`, `resume_idle_hours`, `resume_min_cache_write`, `polling_min_requests`, `polling_max_output_per_request`, `duplicate_window_hours`, `weights`, `report_history_days`, `auto_refresh_on_session_start`, `open_dashboard_after_refresh`, `claude_projects_dir`. To relabel a session, add it to `labels.json`. Then run `refresh.py`. Never edit files inside the plugin folder for personal settings; plugin updates replace them.
