"""End-to-end test on synthetic logs: python -m unittest discover -s tests"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Pipeline(unittest.TestCase):
    def test_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs, home = os.path.join(tmp, "projects"), os.path.join(tmp, "home")
            subprocess.check_call([sys.executable, os.path.join(ROOT, "tests", "make_fixture.py"), logs, "30"])
            os.makedirs(home)
            with open(os.path.join(home, "config.json"), "w") as f:
                json.dump({"claude_projects_dir": logs}, f)
            env = {**os.environ, "CTA_HOME": home}
            subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "refresh.py")], env=env)
            out = os.path.join(home, "out")
            for name in ["usage_hourly.csv", "daily.csv", "events.csv", "report.json", "report.md", "dashboard.html"]:
                self.assertTrue(os.path.exists(os.path.join(out, name)), name)
            with open(os.path.join(out, "daily.csv")) as f:
                daily = list(csv.DictReader(f))
            self.assertTrue(any(float(r["requests"] or 0) > 0 for r in daily))
            with open(os.path.join(out, "usage_hourly.csv")) as f:
                hourly = list(csv.DictReader(f))
            self.assertEqual(sum(int(r["requests"]) for r in hourly), sum(int(float(r["requests"] or 0)) for r in daily))
            # second report run for the same day is skipped
            r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "make_report.py")], env=env, capture_output=True, text=True, cwd=os.path.join(ROOT, "scripts"))
            self.assertTrue(r.stdout.startswith("SKIP"), r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
