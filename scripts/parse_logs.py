"""Incremental reader for Claude Code session logs (*.jsonl).

Only files that are new or changed since the last run are read again; the rest come from
cache/parse_cache.json. Returns plain lists so analysis stays simple:

  requests:    [ts, session, sidechain, model, input, output, cache_read, cache_write_5m, cache_write_1h, tools, tool_result_chars]
  sessions:    {session: {"title", "prompt", "cwd"}}
  compactions: [ts, session, trigger, pre_tokens]
"""
import glob
import json
import os
from datetime import datetime

from common import CACHE, log_dirs

CACHE_VERSION = 3


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def parse_file(fp):
    reqs, sess, comp, seen = [], {}, [], {}
    pending_chars = {}  # tool-result characters waiting for the next request in that session
    with open(fp, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            sid = o.get("sessionId")
            if not sid:
                continue
            t = o.get("type")
            s = sess.setdefault(sid, {"title": "", "prompt": "", "cwd": ""})
            if not s["cwd"] and o.get("cwd"):
                s["cwd"] = o["cwd"]
            if t in ("ai-title", "custom-title"):
                title = o.get("aiTitle") or o.get("customTitle") or o.get("title")
                if title and (t == "custom-title" or not s.get("custom")):
                    s["title"] = title
                    if t == "custom-title":
                        s["custom"] = True
            elif t == "system" and o.get("subtype") == "compact_boundary" and o.get("timestamp"):
                meta = o.get("compactMetadata") or {}
                comp.append([_ts(o["timestamp"]), sid, meta.get("trigger", "?"), meta.get("preTokens") or 0])
            elif t == "user":
                c = (o.get("message") or {}).get("content")
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            v = b.get("content")
                            pending_chars[sid] = pending_chars.get(sid, 0) + (len(v) if isinstance(v, str) else len(json.dumps(v)))
                if not s["prompt"] and not o.get("isSidechain") and not o.get("isMeta") and not o.get("isCompactSummary"):
                    txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
                    if txt and txt.strip() and not txt.lstrip().startswith("<"):
                        s["prompt"] = " ".join(txt.split())[:300]
            elif t == "assistant":
                m = o.get("message") or {}
                u, ts = m.get("usage"), o.get("timestamp")
                if not u or not ts or m.get("model") == "<synthetic>":
                    continue
                key = (m.get("id"), o.get("requestId"))
                names = {b.get("name", "?") for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use"}
                if key in seen:  # streamed replies log one line per content block with the same usage
                    r = reqs[seen[key]]
                    r[9] = sorted(set(r[9]) | names)
                    continue
                seen[key] = len(reqs)
                cc = u.get("cache_creation") or {}
                cw_total = u.get("cache_creation_input_tokens", 0) or 0
                cw1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
                cw5 = cc.get("ephemeral_5m_input_tokens")
                cw5 = (cw_total - cw1h) if cw5 is None else cw5
                tools = sorted(names)
                reqs.append([_ts(ts), sid, 1 if o.get("isSidechain") else 0, m.get("model", "?"), u.get("input_tokens", 0) or 0,
                             u.get("output_tokens", 0) or 0, u.get("cache_read_input_tokens", 0) or 0, max(0, cw5), cw1h, tools,
                             pending_chars.pop(sid, 0) if not o.get("isSidechain") else 0, "%s|%s" % key])
    for s in sess.values():
        s.pop("custom", None)
    return {"requests": reqs, "sessions": sess, "compactions": comp}


def load_all(cfg):
    path = os.path.join(CACHE, "parse_cache.json")
    cache = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("_v") != CACHE_VERSION:
                cache = {}
        except (ValueError, OSError):
            cache = {}
    files = {}
    for d in log_dirs(cfg):
        for fp in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
            files[os.path.abspath(fp)] = os.stat(fp)
    fresh, reread = {"_v": CACHE_VERSION}, 0
    for fp, st in files.items():
        sig = [st.st_size, int(st.st_mtime)]
        hit = cache.get(fp)
        if hit and hit["sig"] == sig:
            fresh[fp] = hit
        else:
            fresh[fp] = {"sig": sig, **parse_file(fp)}
            reread += 1
    if reread or set(fresh) != set(cache):  # only rewrite the cache when something changed
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(json.dumps(fresh, separators=(",", ":")))
        os.replace(path + ".tmp", path)

    requests, sessions, compactions, seen = [], {}, [], set()
    for fp in sorted(fresh):
        if fp == "_v":
            continue
        e = fresh[fp]
        for r in e["requests"]:
            if r[11] in seen:  # the same request can appear in a resumed session's file too
                continue
            seen.add(r[11])
            requests.append(r[:11])
        for sid, s in e["sessions"].items():
            cur = sessions.setdefault(sid, {"title": "", "prompt": "", "cwd": ""})
            for k in ("title", "prompt", "cwd"):
                if not cur[k] and s.get(k):
                    cur[k] = s[k]
        compactions.extend(e["compactions"])
    requests.sort(key=lambda r: r[0])
    compactions.sort(key=lambda c: c[0])
    return requests, sessions, compactions, {"files": len(files), "reread": reread}
