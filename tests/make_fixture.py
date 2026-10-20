"""Generates synthetic Claude Code logs (no real data) for tests and screenshots.

    python tests/make_fixture.py <output projects dir> [days] [seed]

Covers every leak rule: duplicates, polling loops, idle resumes past the cache lifetime, model switches,
auto-compaction, continued sessions, noisy tool output, top-tier models on light steps, subagents.
"""
import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

PROJECTS = [
    ("shop-api", "Build checkout API with FastAPI", "build the checkout endpoints for the shop API"),
    ("portfolio", "Personal portfolio website", "create a modern portfolio website from my CV"),
    ("infra", "Deploy app to VPS with Docker", "deploy the app to my VPS using docker compose"),
    ("ml-notebook", "Fine-tune a small LLM", "help me fine-tune a small LLM on my dataset"),
    ("blog", "Fix broken image uploads", "fix the error when uploading images in the blog"),
    ("auth-service", "Security review of login flow", "review the auth service for security issues"),
]
Z = lambda t: t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Session:
    def __init__(self, root, project, title, prompt, start, rng, model="claude-sonnet-5", continued=False):
        self.sid, self.rng, self.t, self.model, self.k = str(uuid.uuid4()), rng, start, model, 0
        self.ctx = rng.randint(18000, 40000)
        folder = os.path.join(root, "C--work-" + project)
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, self.sid + ".jsonl")
        text = ("This session is being continued from a previous conversation that ran out of context. " + prompt) if continued else prompt
        self.lines = [{"type": "ai-title", "aiTitle": title, "sessionId": self.sid},
                      {"type": "user", "sessionId": self.sid, "cwd": "/work/" + project, "timestamp": Z(start), "message": {"role": "user", "content": text}}]
        self.first = True

    def turn(self, gap_s, growth, out=None, side=False, tools=("Read",), tool_chars=0, cold=False):
        self.t += timedelta(seconds=gap_s)
        if tool_chars:
            self.lines.append({"type": "user", "sessionId": self.sid, "timestamp": Z(self.t), "message": {"role": "user", "content": [{"type": "tool_result", "content": "x" * tool_chars}]}})
            self.ctx += tool_chars // 4
        self.ctx += growth
        cw = self.ctx if (self.first or cold) else self.rng.randint(300, 3000)
        cr = 0 if (self.first or cold) else self.ctx
        self.first = False
        one_h = int(cw * 0.8)
        self.k += 1
        self.lines.append({"type": "assistant", "sessionId": self.sid, "isSidechain": side, "requestId": f"req_{self.sid[:6]}_{self.k}", "timestamp": Z(self.t),
                           "message": {"id": f"msg_{self.sid[:6]}_{self.k}", "model": self.model,
                                       "content": [{"type": "tool_use", "name": n, "input": {}} for n in tools],
                                       "usage": {"input_tokens": self.rng.randint(1, 10), "output_tokens": out if out is not None else self.rng.randint(150, 2500),
                                                 "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw,
                                                 "cache_creation": {"ephemeral_1h_input_tokens": one_h, "ephemeral_5m_input_tokens": cw - one_h}}}})

    def compact(self, trigger="auto"):
        self.t += timedelta(seconds=30)
        self.lines.append({"type": "system", "subtype": "compact_boundary", "sessionId": self.sid, "timestamp": Z(self.t),
                           "compactMetadata": {"trigger": trigger, "preTokens": self.ctx}})
        self.ctx = self.rng.randint(20000, 30000)
        self.first = True

    def save(self):
        with open(self.path, "a", encoding="utf-8") as f:
            for o in self.lines:
                f.write(json.dumps(o) + "\n")


def main(root, days=45, seed=7):
    rng = random.Random(seed)
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(days, 0, -1):
        if rng.random() < 0.3:
            continue
        day = today - timedelta(days=d)
        lean = d < days / 2  # the user gets leaner over time
        for _ in range(rng.randint(1, 3)):
            proj, title, prompt = rng.choice(PROJECTS)
            start = day + timedelta(hours=rng.choice([9, 11, 14, 16, 20, 22]), minutes=rng.randint(0, 59))
            model = "claude-opus-5" if rng.random() < 0.2 else "claude-sonnet-5"
            s = Session(root, proj, title, prompt, start, rng, model, continued=rng.random() < 0.05)
            growth = rng.randint(400, 2000) if lean else rng.randint(1500, 5000)
            for k in range(rng.randint(20, 120)):
                r = rng.random()
                if r < 0.02:
                    s.turn(rng.randint(4000, 30000), growth, cold=True)          # idle past the cache lifetime
                elif r < 0.03:
                    s.model = "claude-opus-5-5" if s.model != "claude-opus-5-5" else "claude-sonnet-5"
                    s.turn(60, growth, cold=True)                                 # model switch
                elif r < 0.05:
                    s.turn(30, growth, tool_chars=rng.randint(25000, 90000), tools=("Bash",))  # noisy output
                elif r < 0.15:
                    s.turn(20, 500, side=True, tools=("Grep",))                   # subagent work
                elif r < 0.25:
                    s.turn(25, 300, out=rng.randint(20, 200), tools=("mcp__browser__navigate",))
                else:
                    s.turn(rng.randint(20, 240), growth, tools=rng.choice([("Read",), ("Edit",), ("Bash",), ("Write", "Read"), ()]))
                if s.ctx > 400000:
                    s.compact("auto")
            if rng.random() < 0.04:  # polling loop
                for _ in range(130):
                    s.turn(20, 0, out=12, tools=("Bash",))
            s.save()
            if rng.random() < 0.06:  # duplicate session
                dup = Session(root, proj, title, prompt, start + timedelta(minutes=5), rng, model)
                for _ in range(rng.randint(10, 40)):
                    dup.turn(60, growth)
                dup.save()
    print("fixture written to", root)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 45, int(sys.argv[3]) if len(sys.argv) > 3 else 7)
