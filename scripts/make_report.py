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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT, current_day, load_config  # noqa: E402

F = lambda n: f"{n / 1e9:.1f}B" if n >= 1e9 else f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else f"{n:.0f}"
pct = lambda x: f"{x * 100:.0f}%"
label = lambda d: datetime.fromisoformat(d).strftime("%a %b ") + str(datetime.fromisoformat(d).day)

HANDOFF = ("Before we stop: write a handoff note for a fresh session. Include the goal, what is done, what is left, "
           "key file paths and decisions, and anything I must not forget. Keep it under 200 words.")


def fix(e, cfg):
    """(tip, copyable action) for one leak row."""
    t, k = e["title"], e["kind"]
    ttl = cfg["cache_ttl_minutes"]
    ttl_txt = "an hour" if ttl >= 60 else f"{ttl} minutes"
    return {
        "Context bloat": (f"\"{t}\" is carrying a large context. Run /compact after each milestone, /clear between unrelated tasks, "
                          "and start a new session per task.", "/compact Keep only the current goal, decisions made, and open TODOs."),
        "Cache expired": (f"\"{t}\" was resumed after the prompt cache expired (it lasts about {ttl_txt} on your plan), so the whole "
                          "context was sent again at the cache-write price. Retire long sessions with a handoff note, or /compact before a break.", HANDOFF),
        "Model switch": (f"\"{t}\" switched models mid-session, which re-sends the full context. Pick the model at the start or right after /clear.", None),
        "Auto-compaction": (f"\"{t}\" filled its context and was compacted automatically. Compact by hand earlier, while it is cheaper, "
                            "and tell it what to keep.", "/compact Keep only the current goal, decisions made, and open TODOs."),
        "Context overflow": ("A session ran out of context and continued from a summary. Split large tasks into separate sessions before that happens.", HANDOFF),
        "Duplicate session": ("The same request ran in two sessions. Close one before repeating a request.", None),
        "Polling / loop": (f"\"{t}\" ran a wait-and-check loop. Ask for one final report instead of repeated checks.", "Don't poll or wait in a loop. Do the work once and give me one final report."),
        "Noisy tool output": (f"A command in \"{t}\" returned very long output that stayed in the context. Use quiet flags, trim to the relevant lines, "
                              "or run noisy jobs in a subagent.", "When a command's output is long, show me only the lines that matter and summarise the rest."),
        "Model overkill": (f"\"{t}\" used a top-tier model for light steps (reading, searching, short replies). Use Sonnet or Haiku for routine work.", "/model sonnet"),
    }.get(k, (f"Review \"{t}\".", None))


def read_csv(name):
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
    with open(os.path.join(OUT, "agg.json"), encoding="utf-8") as f:
        agg = json.load(f)
    days = agg["levels"]["day"]
    events = [e for e in read_csv("events.csv")]
    active = [d for d in sorted(days) if days[d]["requests"] > 0 and d < report_day]
    d = days.get(report_day)
    written = now.strftime("%b ") + str(now.day) + now.strftime(", %H:%M")
    out, extra = [], []

    def add(kind, text, copy=None):
        out.append({"date": report_day, "order": len(out) + 1, "kind": kind, "text": text, "written": written, **({"copy": copy} if copy else {})})

    if not d or d["requests"] == 0:
        add("summary", f"{label(report_day)}: no Claude Code usage.")
        since = (datetime.fromisoformat(report_day) - timedelta(days=7)).date().isoformat()
        recent = [e for e in events if since <= e["day"] < report_day]
        if recent:
            top = max(recent, key=lambda e: float(e["waste_est"]))
            tip, copy = fix(top, cfg)
            add("heading", "What to do today")
            add("tip", tip, copy)
    else:
        w = d["weighted"]
        s = f"{label(report_day)}: {F(w)} weighted tokens (about ${d['cost']:.2f} at API prices), {d['requests']} requests, {d['sessions']} session{'s' if d['sessions'] != 1 else ''}."
        if active:
            p = days[active[-1]]
            if p["weighted"]:
                s += f" {'Down' if w < p['weighted'] else 'Up'} {pct(abs(w - p['weighted']) / p['weighted'])} from {label(active[-1])}; context per request {F(d['avg_context'])} vs {F(p['avg_context'])}."
        s += f" Avoidable: {F(d['avoid_low'])} likely, up to {F(d['avoid_high'])}."
        add("summary", s)
        wins = [x for x in agg["windows"] if x[2] == report_day]
        if wins:
            b = max(wins, key=lambda x: x[3])
            st = datetime.fromtimestamp(b[0])
            extra.append(f"Busiest 5-hour window: {st:%H:%M}-{st + timedelta(hours=5):%H:%M} ({F(b[3])} weighted; {len(wins)} window{'s' if len(wins) != 1 else ''} that day).")
        evs = sorted((e for e in events if e["day"] == report_day), key=lambda e: -float(e["waste_est"]))
        if evs:
            add("heading", "What leaked")
            for e in evs[:3]:
                add("tip", f"{e['title']}: {e['kind'].lower()} ({e['confidence']}), about {F(float(e['waste_est']))}. {e['detail'][0].upper() + e['detail'][1:]}.")
            add("heading", "What to do today")
            seen = set()
            for e in evs:
                if e["kind"] not in seen and len(seen) < 3:
                    seen.add(e["kind"])
                    tip, copy = fix(e, cfg)
                    add("tip", tip, copy)
        if len(active) >= 7:
            a7 = [days[x] for x in active[-7:]]
            avg = sum(x["weighted"] for x in a7) / 7
            sh = sum(x["avoid_low"] for x in a7) / max(1, sum(x["weighted"] for x in a7))
            today_sh = d["avoid_low"] / w if w else 0
            if avg:
                add("heading", "Trend")
                add("tip", f"{'Below' if w < avg else 'Above'} your 7-active-day average of {F(avg)} by {pct(abs(w - avg) / avg)}. "
                           f"Likely-avoidable share {pct(today_sh)} vs {pct(sh)} over those days ({'better' if today_sh <= sh else 'worse'}).")
    fc = (agg.get("limits") or {}).get("forecast") or {}
    if fc.get("seven_day"):
        sd = fc["seven_day"]
        msg = f"Weekly limit at {sd['pct']:.0f}% (last reading)."
        if sd.get("hits_at"):
            msg += f" At the recent pace it runs out {datetime.fromtimestamp(sd['hits_at']):%a %H:%M}, before it resets."
        extra.append(msg)

    cut = (datetime.fromisoformat(report_day) - timedelta(days=cfg["report_history_days"])).date().isoformat()
    rows = [r for r in rows if r["date"] != report_day and r["date"] >= cut] + out
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    md = [f"# Claude usage report: {label(report_day)}", "", out[0]["text"], *extra]
    for r in out[1:]:
        md.append(f"\n## {r['text']}\n" if r["kind"] == "heading" else f"- {r['text']}" + (f"\n  `{r['copy']}`" if r.get("copy") else ""))
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("OK", report_day)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
