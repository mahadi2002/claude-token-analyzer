"""Builds a single self-contained, offline dashboard.html from the generated tables."""
import csv
import json
import os

from common import OUT, load_config

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(os.path.dirname(HERE), "dashboard")


def rows(name):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else list(csv.DictReader(f))


def read(name):
    with open(os.path.join(DASH, name), encoding="utf-8") as f:
        return f.read()


def main():
    data = {"usage": rows("usage_hourly.csv"), "daily": rows("daily.csv"), "events": rows("events.csv"), "report": rows("report.json"),
            "config": {"day_start_hour": load_config()["day_start_hour"]}}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Token Analyzer</title>
<style>{read("theme.css")}</style>
<script>{read("d3.v7.9.0.min.js")}</script>
<script>window.__CTA_DATA = {blob};</script>
<script>{read("shim.js")}</script>
</head><body><div id="dash-root">
{read("page.html")}
</div><script>dash.__start();</script></body></html>
"""
    path = os.path.join(OUT, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("Dashboard:", path)
    return path


if __name__ == "__main__":
    main()
