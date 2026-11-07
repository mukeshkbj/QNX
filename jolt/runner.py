"""Run experiments: inject one fault, watch the clients, undo, check recovery."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Callable

from .discover import THREADS_CMD, parse_threads
from .faults import Fault
from .target import Target

SAMPLE_EVERY = 0.5          # seconds between pidin samples
RECOVERY_WINDOW = 10.0      # seconds allowed for the system to heal after a fault
STUCK_AFTER = 1.0           # a client blocked longer than this on a dead/frozen server is "stuck"


@dataclass
class ClientResult:
    client: str
    longest_block_s: float          # longest continuous SEND/REPLY block on the faulted server
    survived: bool                  # client process still alive at the end
    verdict: str = ""               # pass/fail label, filled by score.py
    episodes: int = -1              # blocking episodes seen by jolt_watch (-1 = not measured)
    ready_s: float = 0.0            # longest stretch runnable-but-not-running (CPU starvation)
    lost_stdio: list = field(default_factory=list)   # standard fds (0-2) closed during the fault


@dataclass
class ExperimentResult:
    fault: dict
    server_pid_before: int | None
    server_pid_after: int | None
    server_restarted: bool
    recovered: bool                 # all watched processes alive, nobody stuck, within window
    recovery_s: float | None
    clients: list[ClientResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _snapshot(t: Target):
    return parse_threads(t.run(THREADS_CMD))


def _by_name(procs) -> dict[str, int]:
    return {p.short_name: pid for pid, p in procs.items()}


def std_fds(t: Target, pid: int) -> set[int]:
    """Which of the standard streams (fd 0, 1, 2) a process has open, from `pidin fds`."""
    out = t.run(f"pidin -p {pid} fds")
    fds = set()
    for line in out.splitlines():
        tok = line.split()
        if len(tok) >= 2 and tok[0] in ("0", "1", "2") and tok[1].isdigit():
            fds.add(int(tok[0]))
    return fds


def wait_for(t: Target, names: list[str], timeout: float = 15.0) -> bool:
    """Wait until every named process is running (after a reset)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if set(names) <= set(_by_name(_snapshot(t))):
            time.sleep(1.0)            # let clients reconnect
            return True
        time.sleep(0.5)
    return False


def run_experiment(t: Target, fault: Fault, watched: list[str], clients: list[str],
                   log: Callable[[str], None] = print, reset: str | None = None) -> ExperimentResult:
    procs = _snapshot(t)
    names = _by_name(procs)
    spid = 0 if fault.server == "*" else names.get(fault.server)   # "*": system-wide (starve)
    res = ExperimentResult(fault.to_dict(), spid, None, False, False, None)
    starve_prefix = ""
    n_err = -1
    # standard streams each client has open before the fault (by name: clients restart on reset)
    base_std = {c: std_fds(t, names[c]) for c in clients if c in names} \
        if fault.kind in ("error", "delay") else {}
    lost_std: dict[str, list[int]] = {}
    if spid is None:
        res.notes.append(f"server {fault.server} not running; skipped")
        return res

    # --- inject -----------------------------------------------------------
    log(f"  inject {fault.id}")
    if fault.kind == "kill":
        t.signal(spid, "KILL")
    elif fault.kind == "freeze":
        # self-healing: the target resumes the server itself, so a freeze of a service the
        # SSH connection depends on (network, logging) can't leave it stopped
        # nohup sh -c: a plain "( ... ) &" subshell does not survive the SSH session closing
        t.run(f"nohup sh -c 'kill -STOP {spid}; sleep {int(round(fault.duration))}; kill -CONT {spid}' "
              f">/dev/null 2>&1 &")
    elif fault.kind == "starve":
        # hog EVERY CPU at fault.priority; started from the same target command as jolt_watch
        # (below) with a 300 ms head start for the watcher, because once the hog runs, nothing
        # below its priority - sshd included - gets the CPU.
        starve_prefix = (f"nohup {t.remote_dir}/jolt_starve -p {fault.priority} -t {fault.duration} "
                         f"-c -1 -w 300 >/dev/null 2>&1 & ")
        res.notes.append(f"starve: all CPUs at priority {fault.priority}")
    elif fault.kind in ("delay", "error"):
        if not reset:
            res.notes.append(f"{fault.kind} needs --reset so clients reconnect through the interposer; skipped")
            res.server_pid_before = None
            return res
        mode = f"-d {fault.delay_ms}" if fault.kind == "delay" else f"-e {fault.errno}"
        t.run(f"{t.remote_dir}/jolt_interpose -p {fault.path} -u {fault.server} "
              f"{mode} > {t.remote_dir}/interpose.log 2>&1 &")
        time.sleep(1.0)
        t.run(reset, timeout=60)                       # clients reconnect -> through the interposer
        wait_for(t, watched)
        ipid = t.pid_of("jolt_interpose")
        if ipid is None:
            res.notes.append("jolt_interpose failed to start: " + t.run(f"cat {t.remote_dir}/interpose.log"))
            res.server_pid_before = None
            return res
        procs = _snapshot(t)
        names = _by_name(procs)
        spid = ipid                                    # clients now block on the interposer

    # --- observe during the fault -----------------------------------------
    # jolt_watch reads client thread states from the kernel every 20 ms on the
    # target (devctl DCMD_PROC_TIDSTATUS), so retry loops with timeouts are not
    # mistaken for one long hang.
    block_start: dict[str, float] = {}
    longest: dict[str, float] = {c: 0.0 for c in clients}
    hold = fault.duration if fault.kind != "kill" else 2.0
    cpids = {c: names[c] for c in clients if c in names}
    watched_out = ""
    if cpids:
        watched_out = t.run(starve_prefix + f"{t.remote_dir}/jolt_watch -d {hold} -i 20 -s {spid} "
                            + " ".join(str(p) for p in cpids.values()), timeout=hold + 30)
    elif starve_prefix:
        t.run(starve_prefix)
    res.notes.append("watch: server " + str(spid) + " clients " + str(cpids) + " -> "
                     + " | ".join(l for l in watched_out.splitlines() if l.strip()))
    by_pid = {v: k for k, v in cpids.items()}
    episodes: dict[str, int] = {}
    ready: dict[str, float] = {}
    for line in watched_out.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] == "client" and parts[1].isdigit():
            c = by_pid.get(int(parts[1]))
            if c:
                longest[c] = max(longest[c], float(parts[3]) / 1000.0)
                episodes[c] = int(parts[5])
                if len(parts) >= 12 and parts[10] == "ready_ms":
                    ready[c] = float(parts[11]) / 1000.0
    if not watched_out:
        time.sleep(hold)

    # --- undo ---------------------------------------------------------------
    if fault.kind == "freeze":
        t.signal(spid, "CONT")                        # normally already resumed by the target
    elif fault.kind in ("delay", "error"):
        # before removing the interposer: did a client lose a standard stream (e.g. a library
        # handed it fd 1 as a resource and it later close()d it)?
        for c, before in base_std.items():
            pid_now = _by_name(_snapshot(t)).get(c)
            if pid_now:
                missing = sorted(before - std_fds(t, pid_now))
                if missing:
                    lost_std[c] = missing
                    res.notes.append(f"{c} lost standard stream(s) {missing} during the fault")
        t.run("slay -s TERM -f jolt_interpose")
        time.sleep(0.5)
        summary = t.run(f"tail -1 {t.remote_dir}/interpose.log").strip()
        res.notes.append(summary)
        m = __import__("re").search(r"errors (\d+)", summary)
        n_err = int(m.group(1)) if m else -1
        if reset:
            t.run(reset, timeout=60)                   # reconnect directly to the real server
            wait_for(t, watched)

    # --- recovery -----------------------------------------------------------
    t1 = time.monotonic()
    while time.monotonic() - t1 < RECOVERY_WINDOW:
        procs = _snapshot(t)
        names = _by_name(procs)
        new_spid = names.get(fault.server)
        _observe(t, new_spid or spid, clients, block_start, longest, procs)
        alive = all(n in names for n in watched)
        stuck = any(th.state in ("SEND", "REPLY") and th.blocked_pid is not None
                    and th.blocked_pid not in procs           # waiting on a dead pid
                    for p in procs.values() if p.short_name in clients for th in p.threads)
        if alive and not stuck:
            res.recovered = True
            res.recovery_s = round(time.monotonic() - t1, 2)
            break
        time.sleep(SAMPLE_EVERY)

    procs = _snapshot(t)
    names = _by_name(procs)
    res.server_pid_after = names.get(fault.server)
    res.server_restarted = fault.kind == "kill" and res.server_pid_after not in (None, spid)
    for c in clients:
        # error fault: "exercised" = the interposer actually failed requests (its own count)
        ep = n_err if fault.kind == "error" else episodes.get(c, -1)
        res.clients.append(ClientResult(c, round(longest.get(c, 0.0), 2), c in names,
                                        episodes=ep,
                                        ready_s=round(ready.get(c, 0.0), 2),
                                        lost_stdio=lost_std.get(c, [])))
    return res


def _observe(t, spid, clients, block_start, longest, procs=None):
    procs = procs or _snapshot(t)
    now = time.monotonic()
    for p in procs.values():
        if p.short_name not in clients:
            continue
        blocked = any(th.state in ("SEND", "REPLY") and th.blocked_pid == spid for th in p.threads)
        if blocked:
            block_start.setdefault(p.short_name, now)
            longest[p.short_name] = max(longest.get(p.short_name, 0.0),
                                        now - block_start[p.short_name])
        else:
            block_start.pop(p.short_name, None)
