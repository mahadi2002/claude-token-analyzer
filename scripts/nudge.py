"""UserPromptSubmit hook: one-line warnings while you work. No tokens, no network.

Reads the hook input (session_id, transcript_path), looks at the last request in the transcript and
warns once per session per kind, for example:
  - context is far above your target  -> suggest /compact or /clear
  - the session sat idle past the prompt-cache lifetime and is large -> this prompt re-sends it all
The warning is shown to you as a system message; it is not added to Claude's context.
"""
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CACHE, OUT, load_config  # noqa: E402


def last_request(path, tail=400_000):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - tail))
        lines = f.read().decode("utf-8", "ignore").splitlines()
    for line in reversed(lines):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "assistant" and not o.get("isSidechain"):
            u = (o.get("message") or {}).get("usage")
            if u and o.get("timestamp"):
                ctx = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                return ctx, datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp()
    return None, None


def main():
    try:
        cfg = load_config()
        if not cfg.get("nudges", True):
            return
        data = json.loads(sys.stdin.read() or "{}")
        sid, tp = data.get("session_id"), data.get("transcript_path")
        if not sid or not tp or not os.path.exists(tp):
            return
        ctx, ts = last_request(tp)
        if not ctx:
            return
        target = cfg["context_target"]
        if target in (None, "auto"):
            try:
                with open(os.path.join(OUT, "agg.json"), encoding="utf-8") as f:
                    target = json.load(f)["meta"]["context_target"]
            except (OSError, ValueError, KeyError):
                target = 150000
        target = int(target)
        state_path = os.path.join(CACHE, "nudges.json")
        state = {}
        if os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        done = state.setdefault(sid, [])
        msg, kind = None, None
        idle = time.time() - ts
        if idle > cfg["cache_ttl_minutes"] * 60 and ctx > max(50000, target // 2) and "idle" not in done:
            kind = "idle"
            msg = (f"Token Analyzer: this session was idle {idle / 60:.0f} min, so the prompt cache expired. This message re-sends "
                   f"~{ctx / 1000:.0f}k tokens at the cache-write price. A fresh session with a short handoff note is usually cheaper.")
        elif ctx > 2 * target and "bloat2" not in done:
            kind = "bloat2"
            msg = f"Token Analyzer: context is ~{ctx / 1000:.0f}k tokens, over twice your {target / 1000:.0f}k target. Consider /compact (say what to keep) or /clear before a new task."
        elif ctx > target and "bloat" not in done:
            kind = "bloat"
            msg = f"Token Analyzer: context is ~{ctx / 1000:.0f}k tokens, above your {target / 1000:.0f}k target. /compact at the next milestone keeps the session lean."
        if msg:
            done.append(kind)
            if len(state) > 500:
                state = dict(list(state.items())[-200:])
            os.makedirs(CACHE, exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f)
            print(json.dumps({"systemMessage": msg}))
    except Exception:
        pass  # never block a prompt


if __name__ == "__main__":
    main()
