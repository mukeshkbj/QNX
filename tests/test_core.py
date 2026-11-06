"""Offline tests. Fixtures are SYNTHETIC until replaced by real pidin captures."""
import pathlib
from jolt.discover import build_graph, parse_threads
from jolt.plan import make_plan, coverage
from jolt.runner import ExperimentResult, ClientResult
from jolt.score import judge, score
from jolt.report import to_junit, to_markdown

FX = pathlib.Path(__file__).parent / "fixtures"
T = (FX / "threads_synthetic.txt").read_text()
F = (FX / "fds_synthetic.txt").read_text()


def test_parse_threads():
    p = parse_threads(T)
    assert p[4102].threads[0].state == "REPLY" and p[4102].threads[0].blocked_pid == 4100
    assert p[4100].threads[0].blocked_pid is None          # RECEIVE is not a client edge


def test_graph_edges():
    g = build_graph(T, F)
    pairs = {(g.name(e.client_pid), g.name(e.server_pid)) for e in g.edges}
    assert pairs == {("planner", "imu"), ("planner", "actuator")}
    assert g.subgraph(["planner", "imu"]).edges


def test_plan_is_deterministic():
    g = build_graph(T, F)
    a = [f.id for f in make_plan(g, seed=7)]
    assert a == [f.id for f in make_plan(g, seed=7)]
    assert len(a) == 6 and coverage(g, make_plan(g))["edge_fault_pairs"] == 6


def _res(kind, block, restarted=True, recovered=True, alive=True, episodes=-1):
    return ExperimentResult({"kind": kind, "id": f"{kind}:imu", "server": "imu", "duration": 5.0},
                            4100, 4200 if restarted else 4100, restarted, recovered, 0.5,
                            [ClientResult("planner", block, alive, episodes=episodes)])


def test_idle_clients_do_not_count():
    idle = judge(_res("freeze", 0.0, episodes=0))
    assert idle[0]["verdict"] == "idle"
    assert score(idle + judge(_res("freeze", 5.0, episodes=1))) == 0      # 1 exercised, failed
    assert score(idle + judge(_res("freeze", 0.4, episodes=6))) == 100    # 1 exercised, passed
    assert score(idle) is None                                            # nothing exercised


def test_verdicts():
    assert judge(_res("freeze", 5.0))[0]["verdict"] == "hang-no-timeout"
    assert judge(_res("freeze", 0.5))[0]["verdict"] == "pass"
    assert judge(_res("kill", 0.0, restarted=False))[0]["verdict"] == "server-not-restarted"
    assert judge(_res("kill", 0.0, alive=False))[0]["verdict"] == "client-crashed"
    v = judge(_res("freeze", 5.0)) + judge(_res("freeze", 0.5))
    assert score(v) == 50
    assert 'failures="1"' in to_junit(v)
    assert "Score: 50/100" in to_markdown({"target": "x", "seed": 1}, v, 50)


# ---- real captures from a QNX 8.0 x86_64 QEMU target (mkqnximage) ----
def test_real_qemu_capture_parses():
    t = (FX / "threads_qemu_idle.txt").read_text()
    f = (FX / "fds_qemu_idle.txt").read_text()
    procs = parse_threads(t)
    names = {p.short_name for p in procs.values()}
    assert {"procnto-smp-instr", "slogger2", "pci-server"} <= names
    assert all(th.state for p in procs.values() for th in p.threads)
    g = build_graph(t, f)              # procnto (pid 1) edges are ignored by default
    assert all(e.server_pid != 1 and e.client_pid != 1 for e in g.edges)
