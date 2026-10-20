"""Turns parsed requests into costs, token-leak findings and dashboard aggregates.

Costs use data/pricing.json (per model, 1-hour vs 5-minute cache writes). "Weighted tokens" are that
cost expressed as input tokens of the reference model (Sonnet 5 by default), so models compare fairly.

Each request is given at most one leak cause, in this order, so nothing is counted twice:
  likely:   Duplicate session > Polling / loop > Context overflow > Auto-compaction > Cache expired > Model switch
  possible: Noisy tool output > Model overkill > Context bloat
"Avoidable" is shown as a range: likely causes only (low) to likely + possible (high).
"""
import csv
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from common import OUT, current_day, day_of, load_labels, load_pricing, price_for

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
LIKELY = ["Duplicate session", "Polling / loop", "Context overflow", "Auto-compaction", "Cache expired", "Model switch"]
POSSIBLE = ["Noisy tool output", "Model overkill", "Context bloat"]
LIGHT_TOOLS = {"Read", "Grep", "Glob", "LS", "Bash", "TodoWrite", "TaskUpdate", "TaskCreate", "TaskList", "TaskGet", "ToolSearch"}
TOP_N = 8


def task_type(text):
    t = text.lower()
    for name, rx in TASK_RULES:
        if re.search(rx, t):
            return name
    return "Other"


def fmt_k(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else f"{n:.0f}"


class Acc:
    """Running totals for one period (a day, week, month, year or all time)."""
    __slots__ = ("w", "cost", "raw", "inp", "out", "cr", "cw", "req", "ses", "days", "ctx", "ctxn", "lo", "hi",
                 "task", "proj", "tool", "model", "leak", "leak_ses", "series")

    def __init__(self):
        self.w = self.cost = self.raw = self.inp = self.out = self.cr = self.cw = self.lo = self.hi = 0.0
        self.req = self.ctx = self.ctxn = 0
        self.ses, self.days = set(), set()
        self.task, self.proj, self.tool, self.model, self.leak, self.leak_ses = (defaultdict(float) for _ in range(6))
        self.series = defaultdict(lambda: [0.0, 0.0, 0.0, 0, set(), 0, 0])  # w, lo, hi, req, sessions, ctx, ctxn

    def export(self, series_keys, label):
        top = lambda d: sorted(([k, round(v)] for k, v in d.items() if v > 0), key=lambda x: -x[1])
        series = []
        for k in series_keys:
            s = self.series.get(k)
            series.append([k, label(k), round(s[0]), round(s[1]), round(s[2]), s[3], len(s[4]), round(s[5] / s[6]) if s and s[6] else 0] if s
                          else [k, label(k), 0, 0, 0, 0, 0, 0])
        return {"weighted": round(self.w), "cost": round(self.cost, 2), "total": round(self.raw), "input": round(self.inp), "output": round(self.out),
                "cache_read": round(self.cr), "cache_write": round(self.cw), "requests": self.req, "sessions": len(self.ses),
                "active_days": len(self.days), "avg_context": round(self.ctx / self.ctxn) if self.ctxn else 0,
                "avoid_low": round(self.lo), "avoid_high": round(self.hi),
                "by_task": top(self.task)[:TOP_N], "by_project": top(self.proj)[:TOP_N], "by_tool": top(self.tool)[:12],
                "by_model": top(self.model), "leaks": top(self.leak), "leak_sessions": top(self.leak_ses)[:12], "series": series}


def analyze(requests, sessions, compactions, cfg, limits=None):
    pricing = load_pricing()
    labels = load_labels()
    ref = next((m for m in pricing["models"] if m["key"] == cfg["reference_model"]), pricing["models"][0])
    ref_in = ref["input"]
    unknown = set()
    ttl = cfg["cache_ttl_minutes"] * 60
    mintok = cfg["min_reprefill_tokens"]

    # ---------- per-request cost ----------
    R = []
    for ts, sid, side, model, i, o, cr, cw5, cw1, tools, trc in requests:
        p = price_for(pricing, model)
        if p is None:
            unknown.add(model)
            p = ref
        cost = (i * p["input"] + cw5 * p["cache_write_5m"] + cw1 * p["cache_write_1h"] + cr * p["cache_read"] + o * p["output"]) / 1e6
        dt = datetime.fromtimestamp(ts).astimezone()
        R.append({"ts": ts, "dt": dt, "day": day_of(dt, cfg), "sid": sid, "side": side, "model": p["key"], "raw_model": model, "p": p,
                  "i": i, "o": o, "cr": cr, "cw5": cw5, "cw1": cw1, "ctx": i + cr + cw5 + cw1, "tools": tools, "trc": trc,
                  "cost": cost, "w": cost / ref_in * 1e6, "cause": None, "waste": 0.0, "detail": ""})
    if not R:
        return None
    to_w = lambda usd: usd / ref_in * 1e6

    # ---------- labels ----------
    def label(sid):
        s = sessions.get(sid, {})
        if sid[:8] in labels:
            return labels[sid[:8]]
        proj = os.path.basename(os.path.normpath(s.get("cwd") or "")) or "Unknown project"
        return [proj, task_type((s.get("title") or "") + " " + (s.get("prompt") or ""))]

    lab = {sid: label(sid) for sid in {r["sid"] for r in R}}
    title = {sid: (sessions.get(sid, {}).get("title") or lab[sid][0] + " session") for sid in lab}

    # ---------- personal context baseline ----------
    last_day = max(r["day"] for r in R)
    recent = [r["ctx"] for r in R if not r["side"] and (last_day - r["day"]).days < 30]
    median_ctx = statistics.median(recent) if recent else 0
    target = cfg["context_target"]
    target = int(min(150000, max(60000, median_ctx))) if target in (None, "auto") else int(target)

    def flag(r, cause, waste_usd, detail):
        if r["cause"] is None and waste_usd > 0:
            r["cause"], r["waste"], r["detail"] = cause, waste_usd, detail

    reprefill = lambda r: (r["cw5"] * (r["p"]["cache_write_5m"] - r["p"]["cache_read"]) + r["cw1"] * (r["p"]["cache_write_1h"] - r["p"]["cache_read"])) / 1e6

    by_sess = defaultdict(list)
    for r in R:
        by_sess[r["sid"]].append(r)

    # a. duplicate sessions
    starts = {sid: min(x["ts"] for x in rs) for sid, rs in by_sess.items()}
    cost_of = {sid: sum(x["cost"] for x in rs) for sid, rs in by_sess.items()}
    first = {}
    for sid in sorted(by_sess, key=starts.get):
        p = (sessions.get(sid, {}).get("prompt") or "")[:150]
        if len(p) < 25 or p.startswith("This session is being continued"):
            continue
        other = first.get(p)
        if other and starts[sid] - starts[other] < cfg["duplicate_window_hours"] * 3600:
            small = sid if cost_of[sid] <= cost_of[other] else other
            for r in by_sess[small]:
                flag(r, "Duplicate session", r["cost"], "same request was running in another session")
        else:
            first[p] = sid

    # b. polling loops
    hourly = defaultdict(list)
    for r in R:
        hourly[(r["sid"], int(r["ts"] // 3600))].append(r)
    for rs in hourly.values():
        n, out = len(rs), sum(x["o"] for x in rs)
        if n >= cfg["polling_min_requests"] and out / n < cfg["polling_max_output_per_request"]:
            for r in rs:
                flag(r, "Polling / loop", r["cost"], f"{n} requests in one hour, avg {out / n:.0f} output tokens each")

    # c. re-sent context (main chain only)
    comp_by_sess = defaultdict(list)
    for ts, sid, trig, pre in compactions:
        comp_by_sess[sid].append((ts, trig, pre))
    for sid, rs in by_sess.items():
        main = [r for r in rs if not r["side"]]
        cont = (sessions.get(sid, {}).get("prompt") or "").startswith("This session is being continued")
        for k, r in enumerate(main):
            cw = r["cw5"] + r["cw1"]
            if k == 0:
                if cont and cw >= mintok:
                    flag(r, "Context overflow", reprefill(r), "previous chat ran out of context and was reloaded from a summary")
                continue
            prev = main[k - 1]
            if cw < mintok:
                continue
            autos = [c for c in comp_by_sess.get(sid, []) if prev["ts"] < c[0] <= r["ts"] and c[1] == "auto"]
            gap = r["ts"] - prev["ts"]
            if autos:
                flag(r, "Auto-compaction", reprefill(r), f"context hit {fmt_k(autos[0][2])} and was compacted automatically")
            elif gap > ttl:
                hrs = gap / 3600
                when = f"{hrs / 24:.0f}d" if hrs >= 48 else f"{hrs:.1f}h" if hrs >= 1 else f"{gap / 60:.0f}min"
                flag(r, "Cache expired", reprefill(r), f"idle {when}; {cw:,} tokens of context re-sent at the cache-write price")
            elif r["model"] != prev["model"]:
                flag(r, "Model switch", reprefill(r), f"switched {prev['model']} to {r['model']} mid-session; {cw:,} tokens re-sent")

    # possible causes
    for sid, rs in by_sess.items():
        main = [r for r in rs if not r["side"]]
        for k, r in enumerate(main):
            if r["trc"] > cfg["noisy_tool_output_chars"]:
                carried = min(len(main) - k - 1, 30)
                est = r["trc"] / 4
                flag(r, "Noisy tool output", est * carried * r["p"]["cache_read"] / 1e6, f"~{fmt_k(est)} tokens of tool output carried for {carried} more turns")
    sonnet = next((m for m in pricing["models"] if m["key"] == "sonnet-5"), ref)
    for r in R:
        if r["model"].startswith(("opus", "fable")) and r["o"] < 300 and set(r["tools"]) <= LIGHT_TOOLS:
            alt = (r["i"] * sonnet["input"] + r["cw5"] * sonnet["cache_write_5m"] + r["cw1"] * sonnet["cache_write_1h"] + r["cr"] * sonnet["cache_read"] + r["o"] * sonnet["output"]) / 1e6
            flag(r, "Model overkill", r["cost"] - alt, f"{r['model']} used for a light step ({', '.join(r['tools']) or 'short reply'})")
        if r["ctx"] > target:
            flag(r, "Context bloat", (r["ctx"] - target) * r["p"]["cache_read"] / 1e6, f"{fmt_k(r['ctx'])} context per request (target {fmt_k(target)})")

    # ---------- aggregates ----------
    ds = cfg["day_start_hour"]
    week_of = lambda d: d - timedelta(days=d.weekday())
    today = max(current_day(cfg), last_day)
    first_day = min(r["day"] for r in R)
    acc = {lvl: defaultdict(Acc) for lvl in ("day", "week", "month", "year", "all")}
    keycache = {}
    for r in R:
        d = r["day"]
        if d not in keycache:
            iso, ym = d.isoformat(), f"{d.year:04d}-{d.month:02d}"
            keycache[d] = ({"day": iso, "week": week_of(d).isoformat(), "month": ym, "year": f"{d.year:04d}", "all": "all"},
                           {"week": iso, "month": iso, "year": ym, "all": ym})
        keys, sub0 = keycache[d]
        sub = {**sub0, "day": f"{r['dt'].hour:02d}"}
        ww = to_w(r["waste"])
        lo = ww if r["cause"] in LIKELY else 0.0
        proj, task = lab[r["sid"]]
        share = r["w"] / max(1, len(r["tools"]))
        for lvl, key in keys.items():
            a = acc[lvl][key]
            a.w += r["w"]; a.cost += r["cost"]; a.raw += r["ctx"] + r["o"]; a.inp += r["i"]; a.out += r["o"]
            a.cr += r["cr"]; a.cw += r["cw5"] + r["cw1"]; a.req += 1; a.ses.add(r["sid"]); a.days.add(d)
            a.lo += lo; a.hi += ww
            if not r["side"]:
                a.ctx += r["ctx"]; a.ctxn += 1
            a.task[task] += r["w"]; a.proj[proj] += r["w"]; a.model[r["model"]] += r["w"]
            for t in r["tools"] or ["(text reply)"]:
                a.tool[t] += share if r["tools"] else r["w"]
            if r["cause"]:
                a.leak[r["cause"]] += ww
                a.leak_ses[r["sid"]] += ww
            s = a.series[sub[lvl]]
            s[0] += r["w"]; s[1] += lo; s[2] += ww; s[3] += 1; s[4].add(r["sid"])
            if not r["side"]:
                s[5] += r["ctx"]; s[6] += 1

    def days_between(a, b):
        out, d = [], a
        while d <= b:
            out.append(d)
            d += timedelta(days=1)
        return out

    months_between = lambda a, b: sorted({d.strftime("%Y-%m") for d in days_between(a, b)})
    mlabel = lambda m: datetime.strptime(m, "%Y-%m").strftime("%b")
    dlabel = lambda d: str(int(d[8:]))
    levels = {}
    for lvl, table in acc.items():
        levels[lvl] = {}
        for key, a in table.items():
            if lvl == "day":
                keys_ = [f"{(ds + h) % 24:02d}" for h in range(24)]
                lab_ = lambda k: k
            elif lvl == "week":
                start = datetime.fromisoformat(key).date()
                keys_ = [(start + timedelta(days=i)).isoformat() for i in range(7)]
                lab_ = lambda k: datetime.fromisoformat(k).strftime("%a")
            elif lvl == "month":
                start = datetime.strptime(key + "-01", "%Y-%m-%d").date()
                end = min(today, (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
                keys_ = [d.isoformat() for d in days_between(start, end)]
                lab_ = dlabel
            elif lvl == "year":
                keys_ = [m for m in months_between(datetime(int(key), 1, 1).date(), min(today, datetime(int(key), 12, 31).date()))]
                lab_ = mlabel
            else:
                keys_ = months_between(first_day, today)
                multi = first_day.year != today.year
                lab_ = lambda m, multi=multi: datetime.strptime(m, "%Y-%m").strftime("%b '%y" if multi else "%b")
            levels[lvl][key] = a.export(keys_, lab_)
            levels[lvl][key]["leak_sessions"] = [[sid, title[sid], v] for sid, v in levels[lvl][key]["leak_sessions"]]
        prev = None
        for key in sorted(levels[lvl]):
            m = levels[lvl][key]
            m["prev_key"] = prev
            m["change"] = round((m["weighted"] - levels[lvl][prev]["weighted"]) / levels[lvl][prev]["weighted"], 4) if prev and levels[lvl][prev]["weighted"] else None
            prev = key

    # ---------- exact 5-hour windows (all sessions together, like the plan limit) ----------
    windows, cur = [], None
    for r in R:
        if cur is None or r["ts"] >= cur["start"] + 5 * 3600:
            cur = {"start": r["ts"], "w": 0.0, "lo": 0.0, "req": 0, "day": r["day"].isoformat()}
            windows.append(cur)
        cur["w"] += r["w"]; cur["req"] += 1
        cur["lo"] += to_w(r["waste"]) if r["cause"] in LIKELY else 0
    windows = [[round(x["start"]), round(x["start"] + 5 * 3600), x["day"], round(x["w"]), x["req"], round(x["lo"])] for x in windows]

    # ---------- session drill-down (last 180 days) ----------
    cutoff = today - timedelta(days=180)
    comp_marks = defaultdict(list)
    for ts, sid, trig, pre in compactions:
        comp_marks[sid].append([round(ts), "Compaction (" + trig + ")"])
    drill = {}
    for sid, rs in by_sess.items():
        if max(x["day"] for x in rs) < cutoff:
            continue
        main = [r for r in rs if not r["side"]] or rs
        step = max(1, len(main) // 240)
        pts = [[round(r["ts"]), r["ctx"], r["o"], r["model"]] for r in main[::step]]
        marks = [[round(r["ts"]), r["cause"], round(to_w(r["waste"]))] for r in rs if r["cause"] in LIKELY or r["cause"] in ("Noisy tool output", "Model overkill")]
        if len(marks) > 60:
            marks = sorted(marks, key=lambda m: -m[2])[:60]
        drill[sid[:8]] = {"title": title[sid], "project": lab[sid][0], "task": lab[sid][1], "weighted": round(sum(x["w"] for x in rs)),
                          "cost": round(sum(x["cost"] for x in rs), 2), "requests": len(rs), "subagent_requests": sum(x["side"] for x in rs),
                          "first": round(rs[0]["ts"]), "last": round(rs[-1]["ts"]), "points": pts, "marks": marks + comp_marks.get(sid, [])}
    for lvl in levels.values():
        for m in lvl.values():
            m["leak_sessions"] = [[sid[:8], t, v] for sid, t, v in m["leak_sessions"]]

    # ---------- flat tables (also read by the skill) ----------
    write_tables(R, lab, title, cfg, to_w, first_day, today)

    rhythm = [[0] * 24 for _ in range(7)]
    for r in R:
        rhythm[r["dt"].weekday()][r["dt"].hour] += 1
    calendar = [[d.isoformat(), levels["day"].get(d.isoformat(), {}).get("weighted", 0)] for d in days_between(first_day, today)]
    meta = {"context_target": target, "median_context": round(median_ctx), "cache_ttl_minutes": cfg["cache_ttl_minutes"],
            "reference_model": ref["key"], "reference_input_price": ref_in, "unknown_models": sorted(unknown),
            "first_day": first_day.isoformat(), "last_day": today.isoformat(), "day_start_hour": ds,
            "cache_write_1h_share": round(sum(r["cw1"] for r in R) / max(1, sum(r["cw1"] + r["cw5"] for r in R)), 3),
            "subagent_share": round(sum(r["w"] for r in R if r["side"]) / max(1, sum(r["w"] for r in R)), 3)}
    return {"levels": levels, "windows": windows, "sessions": drill, "calendar": calendar, "rhythm": rhythm, "meta": meta, "_R": R}


def write_tables(R, lab, title, cfg, to_w, first_day, today):
    hours = defaultdict(lambda: [0, 0, 0, 0, 0, 0.0, 0.0, 0])
    for r in R:
        k = (r["sid"], r["dt"].replace(minute=0, second=0, microsecond=0))
        h = hours[k]
        h[0] += r["i"]; h[1] += r["o"]; h[2] += r["cr"]; h[3] += r["cw5"] + r["cw1"]; h[4] += 1; h[5] += r["w"]; h[6] += r["cost"]
    model_of = defaultdict(lambda: defaultdict(int))
    for r in R:
        model_of[r["sid"]][r["raw_model"]] += 1
    with open(os.path.join(OUT, "usage_hourly.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hour", "day", "week_start", "session", "title", "project", "task_type", "model", "input", "output", "cache_read", "cache_write", "total", "weighted", "requests", "cost_usd"])
        for (sid, dt), h in sorted(hours.items(), key=lambda x: x[0][1]):
            d = day_of(dt, cfg)
            m = model_of[sid]
            w.writerow([dt.strftime("%Y-%m-%dT%H:00:00"), d.isoformat(), (d - timedelta(days=d.weekday())).isoformat(), sid[:8], title[sid], *lab[sid],
                        max(m, key=m.get), h[0], h[1], h[2], h[3], sum(h[:4]), round(h[5]), h[4], round(h[6], 4)])
    ev = {}
    for r in R:
        if not r["cause"]:
            continue
        k = (r["day"].isoformat(), r["sid"], r["cause"])
        e = ev.setdefault(k, [k[0], r["sid"][:8], title[r["sid"]], r["cause"], 0.0, r["detail"], 0, "likely" if r["cause"] in LIKELY else "possible", 0.0])
        e[4] += to_w(r["waste"]); e[6] += 1
        if r["waste"] > e[8]:
            e[5], e[8] = r["detail"], r["waste"]
    with open(os.path.join(OUT, "events.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "session", "title", "kind", "waste_est", "detail", "requests", "confidence"])
        for e in sorted(ev.values()):
            w.writerow([e[0], e[1], e[2], e[3], round(e[4]), e[5], e[6], e[7]])
    days = defaultdict(lambda: {"v": [0, 0, 0, 0, 0], "w": 0.0, "c": 0.0, "lo": 0.0, "hi": 0.0, "s": set(), "ctx": 0, "n": 0})
    for r in R:
        a = days[r["day"]]
        a["v"] = [a["v"][0] + r["i"], a["v"][1] + r["o"], a["v"][2] + r["cr"], a["v"][3] + r["cw5"] + r["cw1"], a["v"][4] + 1]
        a["w"] += r["w"]; a["c"] += r["cost"]; a["s"].add(r["sid"])
        ww = to_w(r["waste"])
        a["hi"] += ww
        a["lo"] += ww if r["cause"] in LIKELY else 0
        if not r["side"]:
            a["ctx"] += r["ctx"]; a["n"] += 1
    nev = defaultdict(int)
    for e in ev.values():
        nev[e[0]] += 1
    with open(os.path.join(OUT, "daily.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "total", "weighted", "output", "requests", "sessions", "avg_context", "cache_write_share", "waste_est", "waste_share", "events", "avoid_low", "cost_usd"])
        d = first_day
        while d <= today:
            a = days.get(d)
            if a:
                i, o, cr, cw, n = a["v"]
                w.writerow([d.isoformat(), i + o + cr + cw, round(a["w"]), o, n, len(a["s"]), round(a["ctx"] / a["n"]) if a["n"] else 0,
                            round(cw / max(1, i + cr + cw), 4), round(a["hi"]), round(min(1, a["hi"] / a["w"]), 4) if a["w"] else 0,
                            nev[d.isoformat()], round(a["lo"]), round(a["c"], 4)])
            else:
                w.writerow([d.isoformat(), 0, 0, 0, 0, 0, "", "", 0, "", 0, 0, 0])
            d += timedelta(days=1)
