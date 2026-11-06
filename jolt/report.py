"""Reports: JSON (for the dashboard), JUnit XML (for CI) and Markdown (for people)."""
from __future__ import annotations

import json
from xml.sax.saxutils import escape

from .score import EXPECTATIONS, scored


def to_json(meta: dict, graph: dict, verdicts: list[dict], score: int) -> str:
    return json.dumps({"meta": meta, "graph": graph, "verdicts": verdicts, "score": score}, indent=2)


def to_junit(verdicts: list[dict], name: str = "jolt") -> str:
    fails = sum(v["verdict"] not in ("pass", "idle") for v in verdicts)
    skips = sum(v["verdict"] == "idle" for v in verdicts)
    cases = []
    for v in verdicts:
        case = f'  <testcase classname="{escape(v["server"])}" name="{escape(v["fault"] + " -> " + v["client"])}"'
        if v["verdict"] == "pass":
            cases.append(case + "/>")
        elif v["verdict"] == "idle":
            cases.append(case + '>\n    <skipped message="client sent no request during the fault"/>\n  </testcase>')
        else:
            msg = escape(f'{v["verdict"]}: {v.get("fix") or ""}', {'"': "&quot;"})
            cases.append(case + f'>\n    <failure message="{msg}"/>\n  </testcase>')
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<testsuite name="{escape(name)}" tests="{len(verdicts)}" failures="{fails}" skipped="{skips}">\n'
            + "\n".join(cases) + "\n</testsuite>\n")


def to_markdown(meta: dict, verdicts: list[dict], score: int) -> str:
    lines = [f"# Jolt resilience report: {meta.get('target', '')}", "",
             f"**Score: {'n/a' if score is None else f'{score}/100'}** ({sum(v['verdict'] == 'pass' for v in verdicts)} of "
             f"{len(scored(verdicts))} exercised checks passed; {len(verdicts) - len(scored(verdicts))} idle; "
             f"seed {meta.get('seed')})", "",
             "| Fault | Client | Verdict | Longest block (s) | Fix |", "| --- | --- | --- | --- | --- |"]
    order = lambda v: ({"pass": 1, "idle": 2}.get(v["verdict"], 0), v["fault"])
    for v in sorted(verdicts, key=order):
        lines.append(f"| {v['fault']} | {v['client']} | {v['verdict']} | "
                     f"{v['longest_block_s']} | {v.get('fix') or ''} |")
    lines += ["", "## What each fault checks", ""]
    lines += [f"- **{k}**: {d}" for k, d in EXPECTATIONS.items()]
    lines += ["", "**idle** means the client sent the server no request during a freeze or delay, "
              "so that check was not exercised. Idle checks are excluded from the score."]
    return "\n".join(lines) + "\n"
