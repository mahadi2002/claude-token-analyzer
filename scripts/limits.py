"""Reads plan-limit samples recorded by statusline.py and relates them to logged usage.

calibrate() estimates how many weighted tokens one percent of the 5-hour and weekly limit is
(the median over samples taken at 5% or more). claude.ai and phone usage share the same limits
but leave no local logs, so if you use those a lot the estimate runs high; treat it as a guide.
"""
import bisect
import json
import os
import statistics
from datetime import datetime

from common import HOME


def _epoch(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e12 else float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def load_samples():
    path = os.path.join(HOME, "limits.jsonl")
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            out.append([o.get("ts"), o.get("five_pct"), _epoch(o.get("five_reset")), o.get("seven_pct"), _epoch(o.get("seven_reset"))])
    out.sort(key=lambda s: s[0] or 0)
    return out


def calibrate(samples, R):
    """R: analysed requests with 'ts' and 'w'. Returns weighted tokens per 1% for 5h and 7d (or None)."""
    ts = [r["ts"] for r in R]
    cum = [0.0]
    for r in R:
        cum.append(cum[-1] + r["w"])
    used = lambda a, b: cum[bisect.bisect_right(ts, b)] - cum[bisect.bisect_left(ts, a)]
    per5, per7 = [], []
    for t, p5, r5, p7, r7 in samples:
        if p5 and p5 >= 5 and r5:
            u = used(r5 - 5 * 3600, t)
            if u > 0:  # no local usage means the limit was used elsewhere (claude.ai, phone)
                per5.append(u / p5)
        if p7 and p7 >= 5 and r7:
            u = used(r7 - 7 * 86400, t)
            if u > 0:
                per7.append(u / p7)
    med = lambda xs: round(statistics.median(xs)) if xs else None
    return {"weighted_per_pct_5h": med(per5), "weighted_per_pct_7d": med(per7), "samples": len(samples)}


def forecast(samples, now=None):
    """Latest limit levels and, from the recent pace, when each limit would be reached."""
    if not samples:
        return None
    now = now or samples[-1][0]
    last = samples[-1]
    out = {"at": last[0]}
    for name, ip, ir, span in (("five_hour", 1, 2, 3600), ("seven_day", 3, 4, 6 * 3600)):
        pct, reset = last[ip], last[ir]
        if pct is None:
            continue
        item = {"pct": pct, "resets_at": reset, "hits_at": None}
        same = [s for s in samples if s[ir] == reset and s[ip] is not None and last[0] - s[0] <= span]
        if len(same) >= 2 and same[-1][0] > same[0][0]:
            pace = (same[-1][ip] - same[0][ip]) / (same[-1][0] - same[0][0])
            if pace > 0:
                eta = last[0] + (100 - pct) / pace
                if not reset or eta < reset:
                    item["hits_at"] = round(eta)
        out[name] = item
    return out
