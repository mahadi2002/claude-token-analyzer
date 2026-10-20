"""Reads Claude Code logs and writes everything the dashboard and report need.

Output in ~/.claude-token-analyzer/out/:
    agg.json          aggregates for every day, week, month, year and all time, 5-hour windows,
                      session timelines, plan-limit history and forecast
    usage_hourly.csv  one row per session per hour (local time)
    daily.csv         one row per usage day
    events.csv        token leaks, one row per day, session and cause
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import analyze  # noqa: E402
from common import OUT, VERSION, load_config, write_json  # noqa: E402
from limits import calibrate, forecast, load_samples  # noqa: E402
from parse_logs import load_all  # noqa: E402


def main():
    t0 = time.time()
    cfg = load_config()
    requests, sessions, compactions, stats = load_all(cfg)
    res = analyze(requests, sessions, compactions, cfg)
    if res is None:
        print("No Claude Code usage found in", cfg["claude_projects_dir"])
        return 1
    R = res.pop("_R")
    samples = load_samples()
    res["limits"] = {"samples": [[s[0], s[1], s[3]] for s in samples[-4000:]], "calibration": calibrate(samples, R), "forecast": forecast(samples)}
    res["meta"].update({"generated_at": datetime.now().astimezone().isoformat(timespec="minutes"), "version": VERSION,
                        "privacy_mode": bool(cfg["privacy_mode"]), "files": stats["files"]})
    write_json(os.path.join(OUT, "agg.json"), res)
    print(f"{len(sessions)} sessions, {len(requests)} requests, {stats['reread']}/{stats['files']} log files read, "
          f"context target {res['meta']['context_target']:,}, {time.time() - t0:.1f}s")
    if res["meta"]["unknown_models"]:
        print("Priced as", res["meta"]["reference_model"], "(not in pricing.json):", ", ".join(res["meta"]["unknown_models"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
