"""Generates synthetic Claude Code logs (no real data) for tests and screenshots.

    python tests/make_fixture.py <output projects dir> [days]
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
]


def write_session(root, start, project, title, prompt, turns, ctx0, growth, rng, poll=False):
    sid = str(uuid.uuid4())
    folder = os.path.join(root, "C--work-" + project)
    os.makedirs(folder, exist_ok=True)
    lines = [{"type": "ai-title", "aiTitle": title, "sessionId": sid},
             {"type": "user", "sessionId": sid, "cwd": "/work/" + project, "timestamp": start.isoformat(), "message": {"role": "user", "content": prompt}}]
    t, ctx = start, ctx0
    for k in range(turns):
        t += timedelta(seconds=rng.randint(5, 40) if poll else rng.randint(20, 240))
        ctx += 0 if poll else rng.randint(0, growth)
        cw = rng.randint(200, 4000) if k else ctx0
        lines.append({"type": "assistant", "sessionId": sid, "requestId": f"req_{sid[:6]}_{k}", "timestamp": t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                      "message": {"id": f"msg_{sid[:6]}_{k}", "model": "claude-sonnet-4-5", "usage": {
                          "input_tokens": rng.randint(1, 10), "output_tokens": rng.randint(5, 40) if poll else rng.randint(150, 2500),
                          "cache_read_input_tokens": ctx, "cache_creation_input_tokens": cw}}})
    with open(os.path.join(folder, sid + ".jsonl"), "a", encoding="utf-8") as f:
        for o in lines:
            f.write(json.dumps(o) + "\n")
    return sid


def main(root, days=45, seed=7):
    rng = random.Random(seed)
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(days, 0, -1):
        if rng.random() < 0.3:
            continue
        day = today - timedelta(days=d)
        for _ in range(rng.randint(1, 3)):
            proj, title, prompt = rng.choice(PROJECTS)
            start = day + timedelta(hours=rng.choice([9, 11, 14, 16, 20, 22]), minutes=rng.randint(0, 59))
            lean = d < days / 2  # the user gets leaner over time
            write_session(root, start, proj, title, prompt, rng.randint(20, 160), rng.randint(20000, 60000),
                          rng.randint(500, 2500) if lean else rng.randint(2000, 7000), rng, poll=rng.random() < 0.04)
    print("fixture written to", root)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 45)
