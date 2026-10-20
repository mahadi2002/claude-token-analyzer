---
description: Refresh your Claude Code token dashboard, open it, and show today's report
allowed-tools: Bash, Read
---

Refresh and open the Claude Token Analyzer dashboard.

1. Run (use `python` if `python3` is not found):
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/refresh.py" --open`
   If `${CLAUDE_PLUGIN_ROOT}` is empty, find `token-analyzer/scripts/refresh.py` under `~/.claude/plugins/` and run that.
2. Read `~/.claude-token-analyzer/out/report.md`.
3. Reply with the report's summary line and its "What to do today" tips, in at most 6 short lines. Say the dashboard opened in the browser and give its path. Do not re-analyse the logs yourself.

$ARGUMENTS
