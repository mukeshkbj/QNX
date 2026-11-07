"""Turn experiment results into verdicts and a 0-100 resilience score."""
from __future__ import annotations

from .runner import ExperimentResult, STUCK_AFTER

# What "pass" means per fault kind, in plain words (shown in reports).
EXPECTATIONS = {
    "kill":   "Clients get an error, reconnect, and the server is restarted.",
    "freeze": "No client waits longer than its timeout; nobody blocks for the whole freeze.",
    "starve": "(One system-wide experiment.) With every CPU busy at priority 60, no client is starved or blocked on a server for "
              "more than 1 s. Clients above the load keep running, and QNX priority inheritance "
              "lets their servers run at the client's priority.",
    "delay":  "Against a slow (but alive) server, no client waits longer than 1 s per request.",
    "error":  "When every request fails with EIO, clients survive and recover once the path works again.",
}

FIX_HINTS = {
    "hang-no-timeout": "Arm TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND|_NTO_TIMEOUT_REPLY, ...) "
                       "before MsgSend and handle ETIMEDOUT.",
    "server-not-restarted": "Supervise the server (e.g. a watchdog or the System Launch and "
                            "Monitor) so it is restarted after it dies.",
    "lost-stdio": "The client lost a standard stream (fd 0-2) while handling the fault: some error "
                  "path returned or closed the wrong descriptor. Check every fd-returning "
                  "function returns -1 (not EXIT_FAILURE) on error.",
    "client-crashed": "Handle MsgSend errors (ESRCH/EBADF) by reconnecting instead of exiting.",
    "not-recovered": "The system did not return to a healthy state within the recovery window.",
    "slow-intolerant": "Arm TimerTimeout before each request to a server that can be slow; a live "
                       "server honours the unblock, so the client gets ETIMEDOUT and carries on.",
    "starved": "The client runs below background load. Give the critical loop a priority above it "
               "(e.g. `on -p 61 <cmd>` or pthread_setschedparam) or use adaptive partitioning.",
    "priority-inversion": "The client was blocked on a server starved by lower-priority load. Check for "
                          "_NTO_CHF_FIXED_PRIORITY channels or pulse-driven work, which bypass "
                          "QNX priority inheritance.",
}


def judge(r: ExperimentResult) -> list[dict]:
    """One verdict per (experiment, client)."""
    kind, dur = r.fault["kind"], r.fault["duration"]
    out = []
    if r.server_pid_before is None:
        return out
    for c in r.clients:
        if not c.survived:
            v = "client-crashed"
        elif getattr(c, "lost_stdio", None):
            v = "lost-stdio"      # e.g. a library returned a standard stream as a resource fd
        elif kind == "starve" and c.ready_s > 1.0:
            v = "starved"         # the client itself could not get the CPU
        elif kind == "starve" and c.longest_block_s > 1.0:
            v = "priority-inversion"   # client blocked on a server that the load starved
        elif kind in ("freeze", "delay", "error") and c.episodes == 0:
            v = "idle"            # never sent the server a request during the fault: not exercised
        elif kind == "freeze" and c.longest_block_s >= max(dur - 1.0, STUCK_AFTER):
            v = "hang-no-timeout"
        elif kind == "kill" and not r.server_restarted:
            v = "server-not-restarted"
        elif kind == "delay" and c.longest_block_s > 1.0:
            v = "slow-intolerant"
        elif not r.recovered:
            v = "not-recovered"
        else:
            v = "pass"
        c.verdict = v
        out.append({"fault": r.fault["id"], "kind": kind, "server": r.fault["server"],
                    "client": c.client, "verdict": v, "longest_block_s": c.longest_block_s,
                    "recovery_s": r.recovery_s, "episodes": c.episodes, "fix": FIX_HINTS.get(v)})
    return out


def scored(verdicts: list[dict]) -> list[dict]:
    """Verdicts that count towards the score ("idle" = the client never exercised the fault)."""
    return [v for v in verdicts if v["verdict"] != "idle"]


def score(verdicts: list[dict]) -> int | None:
    """0-100 over exercised checks; None if no check was exercised."""
    counted = scored(verdicts)
    if not counted:
        return None
    return round(100 * sum(v["verdict"] == "pass" for v in counted) / len(counted))
