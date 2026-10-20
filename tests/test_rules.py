"""Unit tests for pricing, leak rules, windows, limits, nudges and the status line."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp()
os.environ["CTA_HOME"] = TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from analyze import analyze  # noqa: E402
from common import load_config  # noqa: E402
from limits import calibrate, forecast  # noqa: E402

T0 = 1_790_000_000  # a fixed timestamp


def req(ts, sid="s1aaaaaaaa", model="claude-sonnet-5", i=5, o=500, cr=0, cw5=0, cw1=0, side=0, tools=None, trc=0):
    return [ts, sid, side, model, i, o, cr, cw5, cw1, tools or [], trc]


def run(requests, sessions=None, compactions=None, **cfg_over):
    cfg = load_config()
    cfg.update({"context_target": 150000, **cfg_over})
    sessions = sessions or {r[1]: {"title": "T", "prompt": "p", "cwd": "/w/proj"} for r in requests}
    return analyze(requests, sessions, compactions or [], cfg)


def causes(res):
    return [r["cause"] for r in res["_R"]]


class Pricing(unittest.TestCase):
    def test_one_hour_cache_write_costs_double(self):
        res = run([req(T0, o=0, i=0, cw1=1_000_000)])
        self.assertAlmostEqual(res["_R"][0]["cost"], 4.0, places=4)  # Sonnet 5: $4 per M 1-hour writes

    def test_model_specific_rates(self):
        res = run([req(T0, model="claude-opus-5-5", o=1_000_000, i=0), req(T0 + 10, model="claude-sonnet-5", o=1_000_000, i=0)])
        self.assertAlmostEqual(res["_R"][0]["cost"], 20.0, places=4)
        self.assertAlmostEqual(res["_R"][1]["cost"], 10.0, places=4)
        self.assertAlmostEqual(res["_R"][1]["w"], 5_000_000, places=0)  # weighted = cost in Sonnet 5 input tokens

    def test_unknown_model_falls_back_and_is_reported(self):
        res = run([req(T0, model="claude-future-9")])
        self.assertIn("claude-future-9", res["meta"]["unknown_models"])


class Leaks(unittest.TestCase):
    def test_cache_expired_after_ttl(self):
        res = run([req(T0, cw1=60000), req(T0 + 2 * 3600, cr=0, cw1=60000)])
        self.assertEqual(causes(res)[1], "Cache expired")

    def test_no_flag_inside_ttl(self):
        res = run([req(T0, cw1=60000), req(T0 + 30 * 60, cr=60000, cw1=500)])
        self.assertIsNone(causes(res)[1])

    def test_api_plan_uses_five_minutes(self):
        res = run([req(T0, cw1=60000), req(T0 + 30 * 60, cw5=60000)], cache_ttl_minutes=5)
        self.assertEqual(causes(res)[1], "Cache expired")

    def test_model_switch(self):
        res = run([req(T0, cw1=60000), req(T0 + 60, model="claude-opus-5", cw1=60000)])
        self.assertEqual(causes(res)[1], "Model switch")

    def test_auto_compaction(self):
        res = run([req(T0, cr=500000), req(T0 + 120, cw1=40000)], compactions=[[T0 + 60, "s1aaaaaaaa", "auto", 900000]])
        self.assertEqual(causes(res)[1], "Auto-compaction")

    def test_polling_loop(self):
        res = run([req(T0 + k * 10, o=10, cr=30000) for k in range(120)])
        self.assertTrue(all(c == "Polling / loop" for c in causes(res)))

    def test_duplicate_session_flags_the_smaller(self):
        p = "please build the checkout endpoints for the shop api"
        sessions = {"big000000": {"title": "A", "prompt": p, "cwd": "/w/a"}, "small0000": {"title": "B", "prompt": p, "cwd": "/w/a"}}
        rs = [req(T0 + k, sid="big000000", o=3000) for k in range(5)] + [req(T0 + 100 + k, sid="small0000", o=100) for k in range(2)]
        res = run(sorted(rs), sessions=sessions)
        for r in res["_R"]:
            self.assertEqual(r["cause"], "Duplicate session" if r["sid"] == "small0000" else None)

    def test_context_bloat_is_possible_not_likely(self):
        res = run([req(T0, cr=400000), req(T0 + 60, cr=400000)])
        m = res["levels"]["all"]["all"]
        self.assertEqual(m["avoid_low"], 0)
        self.assertGreater(m["avoid_high"], 0)

    def test_one_cause_per_request(self):
        # idle resume with a huge context: only "Cache expired", never also bloat
        res = run([req(T0, cr=400000, cw1=1000), req(T0 + 3 * 3600, cw1=400000)])
        self.assertEqual(causes(res)[1], "Cache expired")
        m = res["levels"]["all"]["all"]
        self.assertLessEqual(m["avoid_high"], m["weighted"])
        self.assertAlmostEqual(sum(v for _, v in m["leaks"]), m["avoid_high"], delta=2)


class Windows(unittest.TestCase):
    def test_exact_five_hour_windows(self):
        res = run([req(T0), req(T0 + 4 * 3600), req(T0 + 6 * 3600)])
        self.assertEqual([w[0] for w in res["windows"]], [T0, T0 + 6 * 3600])


class Limits(unittest.TestCase):
    def test_calibrate_and_forecast(self):
        R = [{"ts": T0 + k * 60, "w": 1000.0} for k in range(100)]
        samples = [[T0 + 99 * 60, 50.0, T0 + 4 * 3600, 20.0, T0 + 5 * 86400]]
        cal = calibrate(samples, R)
        self.assertEqual(cal["weighted_per_pct_5h"], 2000)  # 100k weighted / 50%
        fc = forecast([[T0, 10.0, T0 + 4 * 3600, None, None], [T0 + 1800, 40.0, T0 + 4 * 3600, None, None]])
        self.assertEqual(fc["five_hour"]["hits_at"], round(T0 + 1800 + 60 / (30 / 1800)))


class Hooks(unittest.TestCase):
    def test_nudge_warns_once(self):
        tp = os.path.join(TMP, "t.jsonl")
        with open(tp, "w") as f:
            f.write(json.dumps({"type": "assistant", "timestamp": "2099-01-01T00:00:00Z", "message": {"usage": {"input_tokens": 5, "cache_read_input_tokens": 400000}}}) + "\n")
        env = {**os.environ, "CTA_HOME": TMP}
        inp = json.dumps({"session_id": "abc", "transcript_path": tp})
        run1 = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "nudge.py")], input=inp, capture_output=True, text=True, env=env)
        self.assertIn("systemMessage", run1.stdout)
        run2 = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "nudge.py")], input=inp, capture_output=True, text=True, env=env)
        self.assertIn("systemMessage", run2.stdout)   # second level (over twice the target)
        run3 = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "nudge.py")], input=inp, capture_output=True, text=True, env=env)
        self.assertEqual(run3.stdout.strip(), "")

    def test_statusline_records_limits(self):
        env = {**os.environ, "CTA_HOME": TMP}
        inp = json.dumps({"rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": T0}, "seven_day": {"used_percentage": 18, "resets_at": T0 + 86400}},
                          "context_window": {"used_percentage": 31}})
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "statusline.py")], input=inp, capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.strip(), "5h 42% · 7d 18% · ctx 31%")
        with open(os.path.join(TMP, "limits.jsonl")) as f:
            self.assertEqual(json.loads(f.readline())["five_pct"], 42)


if __name__ == "__main__":
    unittest.main()
