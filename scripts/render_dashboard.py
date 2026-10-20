"""Builds one self-contained, offline dashboard.html from agg.json and report.json."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import OUT, PLUGIN_ROOT  # noqa: E402

DASH = os.path.join(PLUGIN_ROOT, "dashboard")


def load(name, default):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read(name):
    with open(os.path.join(DASH, name), encoding="utf-8") as f:
        return f.read()


def main():
    data = {"agg": load("agg.json", None), "report": load("report.json", [])}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Token Analyzer</title>
<style>{read("theme.css")}</style>
<script>{read("d3.v7.9.0.min.js")}</script>
</head><body><div id="dash-root">
{read("page.html")}
</div>
<script>window.__CTA_DATA = {blob};</script>
<script>{read("app.js")}</script>
</body></html>
"""
    path = os.path.join(OUT, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("Dashboard:", path)
    return path


if __name__ == "__main__":
    main()
