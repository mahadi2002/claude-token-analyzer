"""SessionStart hook. Once per usage day it starts a refresh in the background and returns at once,
so Claude Code never waits and no tokens are used. Every other session that day it does nothing."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HOME, current_day, load_config  # noqa: E402


def main():
    try:
        cfg = load_config()
        if not cfg.get("auto_refresh_on_session_start", True):
            return
        mark = os.path.join(HOME, "last_refresh_day.txt")
        today = current_day(cfg).isoformat()
        if os.path.exists(mark) and open(mark).read().strip() == today:
            return
        with open(mark, "w") as f:
            f.write(today)
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refresh.py")
        log = open(os.path.join(HOME, "refresh.log"), "w")
        kw = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, script, "--quiet"], **kw)
    except Exception:
        pass  # never break session start


if __name__ == "__main__":
    main()
