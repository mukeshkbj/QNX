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
    # 2 servers x (kill, freeze) + ONE system-wide starve; no rm paths in the fixture -> no delay/error
    assert len(a) == 5 and sum(i.startswith("starve") for i in a) == 1
    assert "starve@p60:all" in a


def test_path_faults_need_a_resource_manager_path():
    t = (FX / "threads_qemu_stack.txt").read_text()
    f = (FX / "fds_qemu_stack.txt").read_text()
    g = build_graph(t, f).subgraph(["imu", "planner", "actuator", "watchdog"])
    ids = [x.id for x in make_plan(g)]
    # in this capture imu was still a name_attach server: names can't be interposed
    assert not any(i.startswith(("delay", "error")) for i in ids)


def _res(kind, block, restarted=True, recovered=True, alive=True, episodes=-1):
    return ExperimentResult({"kind": kind, "id": f"{kind}:imu", "server": "imu", "duration": 5.0},
                            4100, 4200 if restarted else 4100, restarted, recovered, 0.5,
                            [ClientResult("planner", block, alive, episodes=episodes)])


def test_error_fault_idle_without_injected_errors():
    assert judge(_res("error", 0.0, episodes=0))[0]["verdict"] == "idle"
    assert judge(_res("error", 0.0, episodes=12))[0]["verdict"] == "pass"
    assert judge(_res("error", 0.0, episodes=12, alive=False))[0]["verdict"] == "client-crashed"


def test_lost_stdio_is_a_failure():
    r = _res("error", 0.0, episodes=11)
    r.clients[0].lost_stdio = [1]
    assert judge(r)[0]["verdict"] == "lost-stdio"


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


def test_check_gate_on_recorded_runs():
    from jolt.cli import check
    root = pathlib.Path(__file__).resolve().parent.parent / "jolt-out"
    assert check(root / "after", 100) == 0          # fixed stack passes the strictest gate
    assert check(root / "before", 50) == 1          # unfixed stack fails a lenient one
    assert check(root / "before", 0) == 0
