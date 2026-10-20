"""Maintainer helper: bump the version everywhere, stamp the changelog, commit, tag and push.

    python tools/release.py 0.2.1            # patch release
    python tools/release.py 0.3.0 --no-push  # prepare locally only
Write the release notes under "## Unreleased" in CHANGELOG.md first.
"""
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def edit_json(path, fn):
    p = os.path.join(ROOT, path)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    fn(data)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main(argv):
    if not argv or not re.fullmatch(r"\d+\.\d+\.\d+", argv[0]):
        sys.exit("usage: python tools/release.py X.Y.Z [--no-push]")
    v = argv[0]
    edit_json(".claude-plugin/plugin.json", lambda d: d.__setitem__("version", v))
    edit_json(".claude-plugin/marketplace.json", lambda d: [p.__setitem__("version", v) for p in d["plugins"]])
    common = os.path.join(ROOT, "scripts", "common.py")
    s = open(common, encoding="utf-8").read()
    open(common, "w", encoding="utf-8", newline="\n").write(re.sub(r'VERSION = "[^"]+"', f'VERSION = "{v}"', s))
    ch = os.path.join(ROOT, "CHANGELOG.md")
    s = open(ch, encoding="utf-8").read()
    if "## Unreleased" not in s:
        sys.exit("Add your notes under '## Unreleased' in CHANGELOG.md first.")
    s = s.replace("## Unreleased", f"## {v} ({datetime.date.today().isoformat()})", 1)
    open(ch, "w", encoding="utf-8", newline="\n").write(s)
    subprocess.check_call([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT)
    subprocess.check_call(["git", "add", "-A"], cwd=ROOT)
    subprocess.check_call(["git", "commit", "-m", f"Release v{v}"], cwd=ROOT)
    subprocess.check_call(["git", "tag", f"v{v}"], cwd=ROOT)
    if "--no-push" not in argv:
        subprocess.check_call(["git", "push", "--follow-tags"], cwd=ROOT)
    print("Released", v)


if __name__ == "__main__":
    main(sys.argv[1:])
