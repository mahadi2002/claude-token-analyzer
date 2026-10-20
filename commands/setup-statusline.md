---
description: Show your 5-hour and weekly limit use in the status line and record it for the dashboard
allowed-tools: Read, Edit, Bash
---

Set up the Token Analyzer status line.

1. Read `~/.claude/settings.json` (create `{}` if it does not exist).
2. If it already has a `statusLine` whose command does not contain `token-analyzer` or `statusline.py`, copy that command string into `statusline_chain` in `~/.claude-token-analyzer/config.json` (create the file with just that key if needed), so the old status line keeps showing after ours.
3. Set `statusLine` in `~/.claude/settings.json` to:
   `{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/statusline.py\" 2>/dev/null || python \"${CLAUDE_PLUGIN_ROOT}/scripts/statusline.py\""}`
   Replace `${CLAUDE_PLUGIN_ROOT}` with this plugin's real absolute path (use forward slashes). Change nothing else in the file.
4. Show the user the before/after `statusLine` value and say: the status line now shows "5h x% · 7d y% · ctx z%" on Pro/Max plans, readings are saved to `~/.claude-token-analyzer/limits.jsonl`, and the dashboard's Plan limits card fills in after the next refresh. To undo, restore the previous `statusLine` value shown above.
