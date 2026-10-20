"""Shared settings and paths for Token Analyzer.

User data lives outside the plugin, so plugin updates never touch it:
    ~/.claude-token-analyzer/   (override with CTA_HOME)
        config.json   your settings (missing keys fall back to DEFAULTS)
        labels.json   manual project / task-type overrides per session
        limits.jsonl  plan-limit samples written by the optional status line
        cache/        parse cache, so refreshes only read new or changed logs
        out/          generated tables, report and dashboard.html
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

VERSION = "0.2.0"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "claude_projects_dir": "",          # empty = ~/.claude/projects
    "extra_log_dirs": "auto",           # "auto" adds Claude Desktop local-agent sessions if present; or a list of folders
    "plan": "subscription",             # "subscription" (prompt cache lives 1 hour) or "api" (5 minutes)
    "cache_ttl_minutes": None,          # None = 60 for subscription, 5 for api
    "day_start_hour": 6,                # a "day" runs from this hour to the same hour next day
    "context_target": "auto",           # "auto" = your 30-day median context per request, clamped to [60k, 150k]; or a number
    "min_reprefill_tokens": 20000,      # re-sent context below this size is not flagged
    "polling_min_requests": 100,        # an hour with at least this many requests...
    "polling_max_output_per_request": 50,  # ...averaging fewer output tokens is a loop
    "duplicate_window_hours": 24,       # same first prompt within this window = duplicate
    "noisy_tool_output_chars": 20000,   # tool results bigger than this are flagged
    "reference_model": "sonnet-5",      # weighted tokens are expressed in this model's input-token price
    "report_history_days": 30,
    "privacy_mode": False,              # hide session titles in the dashboard
    "auto_refresh_on_session_start": True,
    "open_dashboard_after_refresh": False,
    "nudges": True,                     # one-line warnings while you work (UserPromptSubmit hook)
    "statusline_chain": "",             # your previous status line command, shown after ours
}

HOME = os.environ.get("CTA_HOME") or os.path.join(os.path.expanduser("~"), ".claude-token-analyzer")
OUT = os.path.join(HOME, "out")
CACHE = os.path.join(HOME, "cache")


def ensure_home():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CACHE, exist_ok=True)
    cfg = os.path.join(HOME, "config.json")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in DEFAULTS.items()}, f, indent=2)
    lab = os.path.join(HOME, "labels.json")
    if not os.path.exists(lab):
        with open(lab, "w", encoding="utf-8") as f:
            json.dump({"_help": "Override labels per session: \"<first 8 chars of session id>\": [\"Project\", \"Task type\"]"}, f, indent=2)


def load_config():
    ensure_home()
    with open(os.path.join(HOME, "config.json"), encoding="utf-8-sig") as f:
        user = json.load(f)
    cfg = {**DEFAULTS, **{k: v for k, v in user.items() if not k.startswith("_")}}
    # 0.1.x keys (context_target as a number, resume_idle_hours, weights) are still accepted;
    # resume_idle_hours and weights are superseded by the cache TTL rule and pricing.json.
    if not cfg["claude_projects_dir"]:
        cfg["claude_projects_dir"] = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    if cfg["cache_ttl_minutes"] is None:
        cfg["cache_ttl_minutes"] = 5 if cfg["plan"] == "api" else 60
    return cfg


def log_dirs(cfg):
    dirs = [cfg["claude_projects_dir"]]
    extra = cfg["extra_log_dirs"]
    if extra == "auto":
        home = os.path.expanduser("~")
        cands = [os.path.join(os.environ.get("APPDATA", ""), "Claude", "local-agent-mode-sessions"),
                 os.path.join(home, "Library", "Application Support", "Claude", "local-agent-mode-sessions"),
                 os.path.join(home, ".config", "Claude", "local-agent-mode-sessions")]
        extra = [c for c in cands if c and os.path.isdir(c)]
    return dirs + [d for d in (extra or []) if os.path.isdir(d)]


def load_labels():
    ensure_home()
    with open(os.path.join(HOME, "labels.json"), encoding="utf-8-sig") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def load_pricing():
    with open(os.path.join(PLUGIN_ROOT, "data", "pricing.json"), encoding="utf-8") as f:
        p = json.load(f)
    for m in p["models"]:
        m["rx"] = re.compile(m["match"])
    return p


def price_for(pricing, model):
    for m in pricing["models"]:
        if m["rx"].search(model or ""):
            return m
    return None


def day_of(dt, cfg):
    """Usage day of a local datetime, honouring day_start_hour."""
    return (dt - timedelta(hours=cfg["day_start_hour"])).date()


def current_day(cfg):
    return day_of(datetime.now().astimezone(), cfg)


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)


def py():
    return sys.executable
