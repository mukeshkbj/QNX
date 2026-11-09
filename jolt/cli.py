"""jolt - chaos engineering for QNX 8.0.

  jolt discover --target qnxvm [--only a,b,c]           print the message-passing graph
  jolt plan     --target qnxvm --only a,b,c [--seed 1]   show the fault plan (dry run)
  jolt run      --target qnxvm --only a,b,c [--seed 1]   run it, write reports to ./jolt-out
  jolt serve    [--port 8765]                            live dashboard at http://localhost:8765/
  jolt explain  --run jolt-out/before [--src DIR]        LLM explanation + suggested fixes
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import __version__
from .discover import FDS_CMD, THREADS_CMD, build_graph
from .plan import DEFAULT_KINDS, coverage, make_plan
from .report import to_json, to_junit, to_markdown
from .runner import run_experiment, wait_for
from .score import judge, score
from .target import Target


def _graph(t: Target, only: list[str] | None):
    g = build_graph(t.run(THREADS_CMD), t.run(FDS_CMD))
    return g.subgraph(only) if only else g


def _print_graph(g) -> None:
    print(f"{len(g.processes)} processes, {len(g.edges)} edges")
    for e in sorted(g.edges, key=lambda e: (g.name(e.server_pid), g.name(e.client_pid))):
        print(f"  {g.name(e.client_pid):>20} -> {g.name(e.server_pid):<20} ({e.via})")


def _wait_for(t: Target, names: list[str], timeout: float = 15.0) -> None:
    """Wait until every named process is running (after a reset)."""
    import time
    from .discover import parse_threads
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        running = {p.short_name for p in parse_threads(t.run(THREADS_CMD)).values()}
        if set(names) <= running:
            time.sleep(1.0)            # let clients reconnect
            return
        time.sleep(0.5)


def _serve(port: int) -> int:
    """Serve dashboard.html plus ./jolt-out/* so the page can poll events.jsonl."""
    import functools
    import http.server
    import shutil
    here = pathlib.Path.cwd()
    shutil.copy(pathlib.Path(__file__).with_name("dashboard.html"), here / "dashboard.html")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(here))
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Jolt dashboard: http://localhost:{port}/dashboard.html?run=jolt-out/after&compare=jolt-out/before")
    print("  live: start `jolt run ... --out jolt-out/after` in another terminal; replay: add &replay&speed=4")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jolt", description="Chaos engineering for QNX 8.0")
    ap.add_argument("--version", action="version", version=f"jolt {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("--target", required=True, help="ssh alias, e.g. qnxvm or qnxpi")
        s.add_argument("--only", help="comma-separated process names to include in the graph")
        s.add_argument("--servers", help="comma-separated servers to inject faults into "
                       "(default: every server with clients)")
        s.add_argument("--seed", type=int, default=1)
        s.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
        s.add_argument("--duration", type=float, default=5.0)
        s.add_argument("--out", default="jolt-out")
        s.add_argument("--reset", help="command run ON THE TARGET before every experiment to "
                       "restore the baseline, e.g. 'sh /tmp/jolt/stack.sh start'")
        s.add_argument("--min-score", type=int, default=100,
                       help="exit 1 if the score is below this (default 100), for CI gates")
    ck = sub.add_parser("check", help="gate CI on a finished run: exit 1 below --min-score")
    ck.add_argument("--run", default="jolt-out/after")
    ck.add_argument("--min-score", type=int, default=100)
    ck.add_argument("--allow-unexercised", action="store_true",
                    help="pass when no check was exercised (score n/a)")
    ex = sub.add_parser("explain", help="LLM explanation + fixes for a finished run")
    ex.add_argument("--run", default="jolt-out/after")
    ex.add_argument("--src", help="source tree of the system under test (for call-site context)")
    sv = sub.add_parser("serve", help="serve the live dashboard")
    sv.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        return _serve(a.port)
    if a.cmd == "check":
        return check(pathlib.Path(a.run), a.min_score, a.allow_unexercised)
    if a.cmd == "explain":
        from .explain import explain
        explain(pathlib.Path(a.run), pathlib.Path(a.src) if a.src else None)
        return 0

    t = Target(a.target)
    only = a.only.split(",") if a.only else None
    if a.cmd in ("plan", "run") and a.reset:
        t.run(a.reset, timeout=60)           # bring the system to its baseline before discovery
        import time
        time.sleep(2)
    g = _graph(t, only)

    if a.cmd == "discover":
        _print_graph(g)
        return 0

    plan = make_plan(g, kinds=tuple(a.kinds.split(",")), seed=a.seed, duration=a.duration,
                     only=a.servers.split(",") if a.servers else None)
    cov = coverage(g, plan)
    print(f"plan: {cov['experiments']} experiments over {cov['servers']} servers, "
          f"{cov['edges']} edges, kinds={cov['fault_kinds']} (seed {a.seed})")
    for i, f in enumerate(plan, 1):
        print(f"  {i:2}. {f.id}")
    if a.cmd == "plan":
        return 0

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ev_path = out / "events.jsonl"
    ev_path.write_text("")

    def emit(_type: str, **data) -> None:
        """Append one event for the live dashboard (dashboard.html polls this file)."""
        with ev_path.open("a") as fh:
            fh.write(json.dumps({"t": round(dt.datetime.now().timestamp(), 3), "type": _type, **data}) + "\n")

    emit("start", target=a.target, seed=a.seed, graph=g.to_dict(),
         plan=[f.to_dict() for f in plan], coverage=cov)
    watched = sorted(p.short_name for p in g.processes.values())
    # clients per server come from the BASELINE graph, so a server that died in an
    # earlier experiment is still tested once the reset has restored it
    baseline = {g.name(s): sorted({g.name(c) for c in g.clients_of(s)}) for s in g.servers()}
    results, verdicts = [], []
    for i, f in enumerate(plan, 1):
        if a.reset:
            t.run(a.reset, timeout=60)
            wait_for(t, watched)
        clients = (sorted({c for cs in baseline.values() for c in cs}) if f.server == "*"
                   else baseline.get(f.server, []))
        print(f"[{i}/{len(plan)}] {f.id}  clients={clients}")
        emit("inject", n=i, total=len(plan), fault=f.to_dict(), clients=clients)
        r = run_experiment(t, f, watched, clients, reset=a.reset)
        results.append(r)
        for v in judge(r):
            verdicts.append(v)
            emit("verdict", n=i, **v)
            print(f"     {v['client']:>16}: {v['verdict']}  (longest block {v['longest_block_s']} s)")
    if a.reset:
        t.run(a.reset, timeout=60)

    sc = score(verdicts)
    from .score import scored
    emit("done", score=sc, passed=sum(v["verdict"] == "pass" for v in verdicts),
         total=len(scored(verdicts)), idle=len(verdicts) - len(scored(verdicts)))
    meta = {"target": a.target, "seed": a.seed, "reset": a.reset, "time": dt.datetime.now().isoformat(timespec="seconds"),
            "coverage": cov, "jolt": __version__}
    (out / "report.json").write_text(to_json(meta, g.to_dict(), verdicts, sc))
    (out / "results.json").write_text(json.dumps([r.to_dict() for r in results], indent=2))
    (out / "junit.xml").write_text(to_junit(verdicts))
    (out / "report.md").write_text(to_markdown(meta, verdicts, sc))
    shown = "n/a (no check was exercised)" if sc is None else f"{sc}/100"
    print(f"\nScore {shown}. Reports in {out}/ (report.md, report.json, junit.xml)")
    return 0 if sc is None or sc >= a.min_score else 1


def check(run: pathlib.Path, min_score: int, allow_unexercised: bool = False) -> int:
    """CI gate on a recorded run: print the failing checks, exit 1 below min_score."""
    rep = json.loads((run / "report.json").read_text())
    sc = rep["score"]
    failing = [v for v in rep["verdicts"] if v["verdict"] not in ("pass", "idle")]
    for v in failing:
        print(f"FAIL {v['fault']:<24} {v['client']:<14} {v['verdict']}")
    if sc is None:
        print(f"{run}: score n/a (no check was exercised)")
        return 0 if allow_unexercised else 1
    ok = sc >= min_score
    print(f"{run}: score {sc}/100, minimum {min_score}: {'OK' if ok else 'BELOW MINIMUM'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
