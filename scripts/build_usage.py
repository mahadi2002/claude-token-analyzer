"""Reads Claude Code session logs and writes usage tables to ~/.claude-token-analyzer/out/.

    usage_hourly.csv  one row per session per hour (local time)
    daily.csv         one row per usage day, every calendar day from first use to today
    events.csv        token leaks found by the rules in config.json

Weighted tokens = input*w_in + cache_write*w_cw + cache_read*w_cr + output*w_out
(defaults 1 / 1.25 / 0.1 / 5, the relative prices Anthropic publishes for Claude models).
"""
import csv
import glob
import json
import os
import re
from datetime import datetime, timedelta

from common import OUT, current_day, day_of, load_config, load_labels

TASK_RULES = [
    ("Deployment & hosting", r"deploy|cpanel|hosting|nginx|docker|vercel|netlify|domain|dns|ssl|server"),
    ("Database", r"database|\bsql\b|mysql|postgres|mongo|mariadb|sqlite|schema|migrat"),
    ("Debugging", r"\bbug|error|\bfix|debug|crash|failing|traceback|exception|not working"),
    ("Code review & audit", r"review|audit|inspect|refactor|clean ?up"),
    ("Security", r"secur|vulnerab|pentest|\bxss\b|csrf|encrypt|\bauth\b|owasp"),
    ("UI/UX design", r"\bdesign|figma|\bui\b|\bux\b|prototype|mockup|\bcss\b|layout|landing page"),
    ("Docs & writing", r"document|\bdocs?\b|readme|\bwrite\b|report|\bpdf\b|guide|essay|paper"),
    ("AI / ML", r"\bllm|\bagent|\bml\b|machine learning|model train|dataset|embedding|\brag\b|prompt"),
    ("Tooling & setup", r"install|set ?up|configur|plugin|skill|\bmcp\b|\bgit\b|extension|\bcli\b"),
    ("Research & advice", r"suggest|compare|\bbest\b|should i|recommend|which one|explain"),
    ("App development", r"build|create|implement|feature|\bapp\b|website|\bapi\b|component|react|backend|frontend"),
]


def task_type(text):
    t = text.lower()
    for name, rx in TASK_RULES:
        if re.search(rx, t):
            return name
    return "Other"


def main():
    cfg = load_config()
    labels = load_labels()
    wt = cfg["weights"]
    W = lambda i, o, cr, cw: i * wt["input"] + cw * wt["cache_write"] + cr * wt["cache_read"] + o * wt["output"]
    day = lambda dt: day_of(dt, cfg)

    sess, hours, seen = {}, {}, set()
    for fp in glob.glob(os.path.join(cfg["claude_projects_dir"], "**", "*.jsonl"), recursive=True):
        with open(fp, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                sid = o.get("sessionId")
                if not sid:
                    continue
                s = sess.setdefault(sid, {"title": "", "prompt": "", "cwd": "", "models": {}})
                t = o.get("type")
                if t == "ai-title" and o.get("aiTitle"):
                    s["title"] = o["aiTitle"]
                if t == "user" and not s["prompt"] and not o.get("isSidechain") and not o.get("isMeta"):
                    c = (o.get("message") or {}).get("content")
                    if isinstance(c, list):
                        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                    if isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
                        s["prompt"] = " ".join(c.split())[:300]
                        s["cwd"] = o.get("cwd", "")
                if t != "assistant":
                    continue
                m = o.get("message") or {}
                u, ts = m.get("usage"), o.get("timestamp")
                if not u or not ts or m.get("model") == "<synthetic>":
                    continue
                key = (m.get("id"), o.get("requestId"))
                if key in seen:  # streamed chunks repeat the same usage
                    continue
                seen.add(key)
                s["models"][m.get("model", "?")] = s["models"].get(m.get("model", "?"), 0) + 1
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(minute=0, second=0, microsecond=0)
                d = hours.setdefault((sid, dt), [0, 0, 0, 0, 0])
                for i, k in enumerate(["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]):
                    d[i] += u.get(k, 0) or 0
                d[4] += 1

    if not hours:
        print("No Claude Code usage found in", cfg["claude_projects_dir"])
        return 1

    def label(sid):
        s = sess[sid]
        if sid[:8] in labels:
            return labels[sid[:8]]
        proj = os.path.basename(os.path.normpath(s["cwd"])) if s["cwd"] else "Unknown project"
        return [proj or s["cwd"] or "Unknown project", task_type(s["title"] + " " + s["prompt"])]

    def title(sid):
        return sess[sid]["title"] or (label(sid)[0] + " session")

    # ---------- leak detection ----------
    events = []
    by_sess = {}
    for (sid, dt), d in hours.items():
        by_sess.setdefault(sid, []).append((dt, d))
    for sid, hs in by_sess.items():
        hs.sort(key=lambda x: x[0])
        if sess[sid]["prompt"].startswith("This session is being continued"):
            dt, d = hs[0]
            events.append([day(dt), sid, "Context overflow", wt["cache_write"] * d[3], "previous chat ran out of context and was reloaded from a summary"])
        for k, (dt, d) in enumerate(hs):
            i, o, cr, cw, n = d
            ctx = (i + cr + cw) / n
            gap = dt - hs[k - 1][0] if k else None
            if gap and gap > timedelta(hours=cfg["resume_idle_hours"]) and cw > cfg["resume_min_cache_write"]:
                events.append([day(dt), sid, "Old session resumed", wt["cache_write"] * cw, f"idle {gap.days}d, {cw:,} tokens re-cached"])
            if n >= cfg["polling_min_requests"] and o / n < cfg["polling_max_output_per_request"]:
                events.append([day(dt), sid, "Polling / loop", W(i, o, cr, cw), f"{n} requests in one hour, avg {o / n:.0f} output tokens each"])
            elif ctx > cfg["context_target"]:
                events.append([day(dt), sid, "Context bloat", wt["cache_read"] * (ctx - cfg["context_target"]) * n, f"avg {ctx / 1000:.0f}k context per request over {n} requests"])
    starts = {sid: min(dt for dt, _ in v) for sid, v in by_sess.items()}
    tw = lambda sid: sum(W(*d[:4]) for _, d in by_sess[sid])
    first_seen = {}
    for sid in sorted(by_sess, key=lambda x: starts[x]):
        p = sess[sid]["prompt"][:150]
        if len(p) < 25:
            continue
        other = first_seen.get(p)
        if other and starts[sid] - starts[other] < timedelta(hours=cfg["duplicate_window_hours"]):
            small = sid if tw(sid) <= tw(other) else other
            events.append([day(starts[sid]), small, "Duplicate session", tw(small), "same request run in two sessions"])
        else:
            first_seen[p] = sid
    merged = {}
    for dday, sid, kind, tok, detail in events:
        g = merged.setdefault((dday, sid, kind), [dday.isoformat(), sid[:8], title(sid), kind, 0.0, detail, 0])
        g[4] += tok
        g[6] += 1
    with open(os.path.join(OUT, "events.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "session", "title", "kind", "waste_est", "detail"])
        for g in sorted(merged.values()):
            detail = f"{g[6]} hours flagged, e.g. {g[5]}" if g[6] > 1 else g[5]
            w.writerow([g[0], g[1], g[2], g[3], round(g[4]), detail])

    # ---------- hourly ----------
    ds = cfg["day_start_hour"]
    with open(os.path.join(OUT, "usage_hourly.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hour", "day", "week_start", "session", "title", "project", "task_type", "model", "input", "output", "cache_read", "cache_write", "total", "weighted", "requests"])
        for (sid, dt), d in sorted(hours.items(), key=lambda x: x[0][1]):
            dd = day(dt)
            proj, task = label(sid)
            model = max(sess[sid]["models"], key=sess[sid]["models"].get)
            w.writerow([dt.strftime("%Y-%m-%dT%H:00:00"), dd.isoformat(), (dd - timedelta(days=dd.weekday())).isoformat(), sid[:8], title(sid), proj, task, model,
                        *d[:4], sum(d[:4]), round(W(*d[:4])), d[4]])

    # ---------- daily ----------
    agg = {}
    for (sid, dt), d in hours.items():
        a = agg.setdefault(day(dt), {"v": [0] * 5, "s": set()})
        a["v"] = [x + y for x, y in zip(a["v"], d)]
        a["s"].add(sid)
    waste = {}
    for g in merged.values():
        waste[g[0]] = waste.get(g[0], 0) + g[4]
    first, last = min(agg), max(max(agg), current_day(cfg))
    with open(os.path.join(OUT, "daily.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "total", "weighted", "output", "requests", "sessions", "avg_context", "cache_write_share", "waste_est", "waste_share", "events"])
        dd = first
        while dd <= last:
            a, key = agg.get(dd), dd.isoformat()
            if a:
                i, o, cr, cw, n = a["v"]
                wsum, ws = W(i, o, cr, cw), waste.get(key, 0)
                w.writerow([key, i + o + cr + cw, round(wsum), o, n, len(a["s"]), round((i + cr + cw) / n), round(cw / max(1, i + cr + cw), 4),
                            round(ws), round(min(1, ws / wsum), 4) if wsum else 0, sum(1 for g in merged.values() if g[0] == key)])
            else:
                w.writerow([key, 0, 0, 0, 0, 0, "", "", 0, "", 0])
            dd += timedelta(days=1)
    print(f"{len(sess)} sessions, {len(hours)} session-hours, {len(merged)} leak events, day starts {ds:02d}:00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
