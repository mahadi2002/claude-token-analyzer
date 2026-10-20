"""Full refresh: read logs, write the report, render the dashboard.

    python refresh.py           refresh everything
    python refresh.py --open    ...and open the dashboard in your browser
    python refresh.py --quiet   no output (used by the session-start hook)
"""
import contextlib
import io
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_usage  # noqa: E402
import make_report  # noqa: E402
import render_dashboard  # noqa: E402
from common import load_config  # noqa: E402


def run(argv):
    if build_usage.main() != 0:
        return 1
    make_report.main([])
    path = render_dashboard.main()
    if "--open" in argv or load_config()["open_dashboard_after_refresh"]:
        webbrowser.open("file://" + os.path.abspath(path))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--quiet" in args:
        with contextlib.redirect_stdout(io.StringIO()):
            raise SystemExit(run(args))
    raise SystemExit(run(args))
