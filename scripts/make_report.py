"""Writes the daily report with fixed rules (no AI, no tokens) after build_usage.py.

Output in ~/.claude-token-analyzer/out/:
    report.json  report rows for the last N days (shown in the dashboard)
    report.md    the latest report as Markdown
Prints "SKIP <day>" when that day's report already exists, else "OK <day>".
Options: --day YYYY-MM-DD (report a specific day), --force (rewrite it).
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta

from common import OUT, current_day, load_config

F = lambda n: f"{n / 1e9:.1f}B" if n >= 1e9 else f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else f"{n:.0f}"
pct = lambda x: f"{x * 100:.0f}%"
label = lambda d: datetime.fromisoformat(d).strftime("%a %b ") + str(datetime.fromisoformat(d).day)
num = lambda r, k: float(r.get(k) or 0)

FIX = {
    "Context bloat": lambda e: f"In \"{e['title']}\", run /compact after each milestone, or start a new session per task.",
    "Old session resumed": lambda e: f"Retire \"{e['title']}\": ask it once for a short handoff note, then continue in a fresh session.",
    "Duplicate session": lambda e: "Close one of two parallel sessions before repeating the same request.",
    "Polling / loop": lambda e: f"\"{e['title']}\" ran a wait-and-check loop; ask for one final report instead.",
    "Context overflow": lambda e: "Split big tasks before the context fills; reloading from a summary is expensive.",
}


def read(name):
    with open(os.path.join(OUT, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv):
    cfg = load_config()
    now = datetime.now().astimezone()
    report_day = (current_day(cfg) - timedelta(days=1)).isoformat()
    if "--day" in argv:
        report_day = argv[argv.index("--day") + 1]
    rp = os.path.join(OUT, "report.json")
    rows = json.load(open(rp, encoding="utf-8")) if os.path.exists(rp) else []
    if any(r["date"] == report_day for r in rows) and "--force" not in argv:
        print("SKIP", report_day)
        return 0

    daily = {r["day"]: r for r in read("daily.csv")}
    events = read("events.csv")
    hourly = read("usage_hourly.csv")
    active = [d for d in sorted(daily) if num(daily[d], "requests") > 0 and d < report_day]
    d = daily.get(report_day, {})
    written = now.strftime("%b ") + str(now.day) + now.strftime(", %H:%M")
    out = []

    def add(kind, text):
        out.append({"date": report_day, "order": len(out) + 1, "kind": kind, "text": text, "written": written})

    extra = []
    if not d or num(d, "requests") == 0:
        add("summary", f"{label(report_day)}: no Claude Code usage.")
        since = (datetime.fromisoformat(report_day) - timedelta(days=7)).date().isoformat()
        recent = [e for e in events if since <= e["day"] < report_day]
        if recent:
            kinds = {}
            for e in recent:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + float(e["waste_est"])
            top = max(kinds, key=kinds.get)
            add("heading", "What to do today")
            add("tip", FIX[top](max((e for e in recent if e["kind"] == top), key=lambda e: float(e["waste_est"]))))
    else:
        w, req, ses, ctx = num(d, "weighted"), num(d, "requests"), num(d, "sessions"), num(d, "avg_context")
        waste, share = num(d, "waste_est"), num(d, "waste_share")
        s = f"{label(report_day)}: {F(w)} weighted tokens, {int(req)} requests, {int(ses)} session{'s' if ses != 1 else ''}."
        if active:
            p = daily[active[-1]]
            pw, pc = num(p, "weighted"), num(p, "avg_context")
            if pw:
                s += f" {'Down' if w < pw else 'Up'} {pct(abs(w - pw) / pw)} from {label(active[-1])} ({F(pw)}); context per request {F(ctx)} vs {F(pc)}."
        s += f" About {pct(share)} ({F(waste)}) avoidable."
        add("summary", s)
        hrs = {}
        for h in hourly:
            if h["day"] == report_day:
                hrs[h["hour"][:13]] = hrs.get(h["hour"][:13], 0) + float(h["weighted"])
        wins, cur = [], None
        for k in sorted(hrs):
            t = datetime.fromisoformat(k + ":00:00")
            if not cur or t >= cur[0] + timedelta(hours=5):
                cur = [t, 0.0]
                wins.append(cur)
            cur[1] += hrs[k]
        if wins:
            b = max(wins, key=lambda x: x[1])
            extra.append(f"Busiest 5-hour window: {b[0]:%H:00}-{b[0] + timedelta(hours=5):%H:00} ({F(b[1])} weighted; {len(wins)} window{'s' if len(wins) != 1 else ''} that day).")
        evs = sorted((e for e in events if e["day"] == report_day), key=lambda e: -float(e["waste_est"]))
        if evs:
            add("heading", "What leaked")
            for e in evs[:3]:
                add("tip", f"{e['title']}: {e['kind'].lower()}, about {F(float(e['waste_est']))} ({e['detail']}).")
            add("heading", "What to do today")
            seen = set()
            for e in evs:
                if e["kind"] not in seen and len(seen) < 3:
                    seen.add(e["kind"])
                    add("tip", FIX[e["kind"]](e))
        if len(active) >= 7:
            a7 = [daily[x] for x in active[-7:]]
            avg = sum(num(x, "weighted") for x in a7) / 7
            sh = sum(num(x, "waste_est") for x in a7) / max(1, sum(num(x, "weighted") for x in a7))
            if avg:
                add("heading", "Trend")
                add("tip", f"{'Below' if w < avg else 'Above'} your 7-active-day average of {F(avg)} by {pct(abs(w - avg) / avg)}. "
                           f"Avoidable share {pct(share)} vs {pct(sh)} over those days ({'better' if share < sh else 'worse'}).")

    cut = (datetime.fromisoformat(report_day) - timedelta(days=cfg["report_history_days"])).date().isoformat()
    rows = [r for r in rows if r["date"] != report_day and r["date"] >= cut] + out
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    md = [f"# Claude usage report: {label(report_day)}", "", out[0]["text"], *extra]
    for r in out[1:]:
        md.append(f"\n## {r['text']}\n" if r["kind"] == "heading" else f"- {r['text']}")
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("OK", report_day)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
