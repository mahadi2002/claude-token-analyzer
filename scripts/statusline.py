"""Optional Claude Code status line.

Shows "5h 42% · 7d 18% · ctx 31%" and records the official plan-limit percentages to
~/.claude-token-analyzer/limits.jsonl so the dashboard can show real limit use and forecasts.
No network, no tokens. To keep your current status line too, set "statusline_chain" in
config.json to its command; its output is shown after ours.

Install: /token-analyzer:setup-statusline (or add to ~/.claude/settings.json):
  "statusLine": {"type": "command", "command": "python3 \"<plugin>/scripts/statusline.py\""}
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOME, load_config  # noqa: E402


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    rl = data.get("rate_limits") or {}
    five, seven = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    p5, p7 = _num(five.get("used_percentage")), _num(seven.get("used_percentage"))
    ctx = _num((data.get("context_window") or {}).get("used_percentage"))
    parts = []
    if p5 is not None:
        parts.append(f"5h {p5:.0f}%")
    if p7 is not None:
        parts.append(f"7d {p7:.0f}%")
    if ctx is not None:
        parts.append(f"ctx {ctx:.0f}%")
    try:
        if p5 is not None or p7 is not None:
            os.makedirs(HOME, exist_ok=True)
            path = os.path.join(HOME, "limits.jsonl")
            last = os.path.join(HOME, ".limits_last")
            sig = f"{p5}|{p7}|{five.get('resets_at')}|{seven.get('resets_at')}"
            prev = open(last).read() if os.path.exists(last) else ""
            now = time.time()
            prev_sig, _, prev_t = prev.partition("@")
            if sig != prev_sig or now - float(prev_t or 0) > 600:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": round(now), "five_pct": p5, "five_reset": five.get("resets_at"),
                                        "seven_pct": p7, "seven_reset": seven.get("resets_at")}) + "\n")
                with open(last, "w") as f:
                    f.write(f"{sig}@{now}")
    except OSError:
        pass
    line = " · ".join(parts)
    try:
        chain = load_config().get("statusline_chain")
        if chain:
            r = subprocess.run(chain, input=raw, capture_output=True, text=True, shell=True, timeout=3)
            extra = r.stdout.strip()
            if extra:
                line = f"{line}  {extra}" if line else extra
    except Exception:
        pass
    print(line)


if __name__ == "__main__":
    main()
