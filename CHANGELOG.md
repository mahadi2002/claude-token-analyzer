# Changelog

## 0.2.0 (2026-10-21)

Accuracy
- Costs now use Anthropic's price for each model, with 1-hour cache writes (2x input) and 5-minute writes (1.25x) priced separately. Earlier versions counted every write at 1.25x and treated all models alike, which under-counted usage. Prices live in `data/pricing.json`.
- "Weighted tokens" are now cost expressed in Sonnet 5 input tokens; a unit switch also shows API-equivalent dollars or % of your 5-hour limit.
- Resumed sessions are flagged once the prompt cache has expired (1 hour on a subscription, 5 minutes on an API key) instead of after 24 hours.
- New leak rules: model switch mid-session, auto-compaction, noisy tool output, top-tier model on light steps.
- Each request gets at most one leak cause, so nothing is counted twice. "Avoidable" is shown as a range: likely to possible.
- 5-hour windows are built from exact request times.
- The context target is your own 30-day median, kept between 60k and 150k (or set your own).

New
- Plan limits: an optional status line (`/token-analyzer:setup-statusline`) records Claude Code's official 5-hour and weekly limit percentages; the dashboard shows them with reset times and a "runs out at this pace" forecast.
- Live nudges: a one-line warning before a prompt when the context is large or the cache has expired. No tokens used; turn off with `"nudges": false`.
- Session drill-down: tap a session to see its context per request over time, with leaks and compactions marked.
- Copy buttons on tips (handoff prompt, /compact instruction, CLAUDE.md-style rules) and a "Copy summary" for sharing without names.
- Tools & MCP servers and Models breakdowns; calendar heatmap; tap a bar to zoom into a day or month.
- "Hide names" privacy mode.
- Claude Desktop local-agent sessions are read too when present.

Design and accessibility
- Donut charts replaced with sorted bars; text labels on every coloured element; chart summaries for screen readers; keyboard access to drill-downs; "updated" time in the header.

Engineering
- Incremental parsing: only new or changed log files are read on refresh.
- Tests for every leak rule, pricing, windows, limits, nudges and the status line; CI on Windows, macOS and Linux with Python 3.9 to 3.13; `tools/release.py`.

Settings: `resume_idle_hours` and `weights` from 0.1.x are no longer used (see above); existing config files keep working.

## 0.1.0 (2026-10-21)
- First public release.
