"""Shared settings and paths for Claude Token Analyzer.

User data lives outside the plugin, so plugin updates never touch it:
    ~/.claude-token-analyzer/   (override with CTA_HOME)
        config.json   your settings (created from defaults on first run)
        labels.json   your manual project / task-type overrides per session
        out/          generated CSVs, report.json, report.md, dashboard.html
"""
import json
import os
from datetime import datetime, timedelta

DEFAULTS = {
    "claude_projects_dir": "",          # empty = ~/.claude/projects
    "day_start_hour": 6,                # a "day" runs from this hour to the same hour next day
    "context_target": 150000,           # context tokens per request above this count as bloat
    "resume_idle_hours": 24,            # resuming a session idle longer than this is flagged
    "resume_min_cache_write": 50000,    # ...when it re-caches at least this many tokens
    "polling_min_requests": 100,        # an hour with at least this many requests...
    "polling_max_output_per_request": 50,  # ...averaging fewer output tokens is a loop
    "duplicate_window_hours": 24,       # same first prompt within this window = duplicate
    "weights": {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0},
    "report_history_days": 30,
    "auto_refresh_on_session_start": True,
    "open_dashboard_after_refresh": False,
}

HOME = os.environ.get("CTA_HOME") or os.path.join(os.path.expanduser("~"), ".claude-token-analyzer")
OUT = os.path.join(HOME, "out")


def ensure_home():
    os.makedirs(OUT, exist_ok=True)
    cfg = os.path.join(HOME, "config.json")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(DEFAULTS, f, indent=2)
    lab = os.path.join(HOME, "labels.json")
    if not os.path.exists(lab):
        with open(lab, "w", encoding="utf-8") as f:
            json.dump({"_help": "Override labels per session: \"<first 8 chars of session id>\": [\"Project\", \"Task type\"]"}, f, indent=2)


def load_config():
    ensure_home()
    with open(os.path.join(HOME, "config.json"), encoding="utf-8-sig") as f:
        user = json.load(f)
    cfg = {**DEFAULTS, **user}
    cfg["weights"] = {**DEFAULTS["weights"], **user.get("weights", {})}
    if not cfg["claude_projects_dir"]:
        cfg["claude_projects_dir"] = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    return cfg


def load_labels():
    ensure_home()
    with open(os.path.join(HOME, "labels.json"), encoding="utf-8-sig") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def local_tz():
    return datetime.now().astimezone().tzinfo


def day_of(dt, cfg):
    """Usage day of a local datetime, honouring day_start_hour."""
    return (dt - timedelta(hours=cfg["day_start_hour"])).date()


def current_day(cfg):
    return day_of(datetime.now().astimezone(), cfg)
