"""jolt explain - turn a run's verdicts into a plain-English report with suggested fixes.

The LLM only EXPLAINS: faults, measurements and verdicts all come from the
deterministic run. Give it the source tree (--src) and it also sees the call
sites (MsgSend/read/write/open/name_open/TimerTimeout) around each failing client,
so it can propose concrete diffs.

Uses the Anthropic Messages API if ANTHROPIC_API_KEY is set; otherwise it writes
the prompt to explain-prompt.md so you can paste it into any LLM.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import urllib.request

MODEL = os.environ.get("JOLT_MODEL", "claude-sonnet-5-5")
CALLS = re.compile(r"\b(MsgSend\w*|MsgReceive\w*|MsgReply|TimerTimeout|name_open|name_attach|"
                   r"resmgr_attach|open|read|write|pthread_setschedparam|ChannelCreate)\s*\(")

SYSTEM = """You are a QNX Neutrino real-time systems expert reviewing the results of Jolt, a
chaos-engineering tool for QNX 8.0. You are given deterministic fault-injection results
(verdicts are facts measured from kernel thread states - do not dispute or re-score them)
and optionally source excerpts. For each failing check, explain in plain English what
happened inside QNX (message passing states, _NTO_CHF_UNBLOCK, priorities and priority
inheritance, supervision) and give the smallest concrete fix, as a unified diff when the
source is available. Group findings by root cause. Mark anything you infer rather than
read from the evidence as an assumption. Be concise; no preamble."""


def _sources(src: pathlib.Path, names: set[str], limit: int = 12000) -> str:
    out, used = [], 0
    for f in sorted(src.rglob("*.c")):
        text = f.read_text(errors="replace")
        if not (names & set(re.findall(r"\w+", f.stem)) or any(n in text for n in names)):
            continue
        lines = text.splitlines()
        hits = sorted({i for i, l in enumerate(lines) if CALLS.search(l)})
        chunks, last = [], -10
        for i in hits:
            if i - last > 6:
                chunks.append(f"--- {f.relative_to(src)}:{i + 1}")
            chunks.extend(f"{j + 1:5}: {lines[j]}" for j in range(max(0, i - 3), min(len(lines), i + 4))
                          if j > last)
            last = i + 3
        block = "\n".join(chunks)
        if used + len(block) > limit:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


def build_prompt(run: pathlib.Path, src: pathlib.Path | None) -> str:
    rep = json.loads((run / "report.json").read_text())
    failing = [v for v in rep["verdicts"] if v["verdict"] not in ("pass", "idle")]
    names = {v["client"] for v in failing} | {v["server"] for v in failing}
    parts = [f"Target: {rep['meta'].get('target')}  seed: {rep['meta'].get('seed')}  "
             f"score: {rep['score']}", "",
             "Message-passing graph (client -> server, via):"]
    pid = {p["pid"]: p["name"] for p in rep["graph"]["processes"]}
    parts += [f"  {pid.get(e['client_pid'], e['client_pid'])} -> {pid.get(e['server_pid'], e['server_pid'])}"
              f" ({e['via']})" for e in rep["graph"]["edges"]]
    parts += ["", "Verdicts (fault, client, verdict, longest block s, blocking episodes):"]
    parts += [f"  {v['fault']:<22} {v['client']:<14} {v['verdict']:<22} {v['longest_block_s']:>5} "
              f"{v.get('episodes', '')}" for v in rep["verdicts"]]
    if src and failing:
        parts += ["", "Source excerpts around call sites:", _sources(src, names)]
    return "\n".join(parts)


def explain(run: pathlib.Path, src: pathlib.Path | None = None) -> pathlib.Path:
    prompt = build_prompt(run, src)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        p = run / "explain-prompt.md"
        p.write_text(f"<!-- system -->\n{SYSTEM}\n\n<!-- user -->\n{prompt}\n")
        print(f"ANTHROPIC_API_KEY not set: prompt written to {p}")
        return p
    body = json.dumps({"model": MODEL, "max_tokens": 4000, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    text = "".join(b.get("text", "") for b in resp.get("content", []))
    p = run / "explain.md"
    p.write_text(f"# Jolt explanation ({MODEL})\n\n{text}\n")
    print(f"explanation written to {p}")
    return p
