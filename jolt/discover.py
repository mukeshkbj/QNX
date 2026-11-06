"""Discover the live message-passing graph from pidin output.

Jolt runs two pidin queries on the target:

  THREADS: pidin -F "%a|%b|%N|%J|%B|%p"   pid | tid | name | state | blocked-on | priority
  FDS:     pidin fds                       per-process connections and open files

Parsing is deliberately tolerant: pidin's column layout differs a little between
builds, so we use explicit '|' separators where we control the format and
regexes elsewhere. Fixtures in tests/ hold real captured output.
"""
from __future__ import annotations

import re
from typing import Iterable

from .model import Edge, Graph, Process, Thread, WAITING_ON_SERVER

THREADS_CMD = 'pidin -F "%a|%b|%N|%J|%B|%p"'
FDS_CMD = "pidin fds"

_INT = re.compile(r"-?\d+")


def _first_int(text: str) -> int | None:
    m = _INT.search(text or "")
    return int(m.group()) if m else None


def parse_threads(text: str) -> dict[int, Process]:
    """Parse THREADS_CMD output into processes with their threads."""
    procs: dict[int, Process] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue                          # header or junk
        pid, tid = int(parts[0]), _first_int(parts[1]) or 0
        name, state = parts[2], parts[3].upper()
        blocked = parts[4] if len(parts) > 4 and parts[4] else None
        prio = _first_int(parts[5]) if len(parts) > 5 else None
        blocked_pid = _first_int(blocked) if (blocked and state in WAITING_ON_SERVER) else None
        proc = procs.setdefault(pid, Process(pid=pid, name=name))
        if name and not proc.name:
            proc.name = name
        proc.threads.append(Thread(pid, tid, name, state, blocked, blocked_pid, prio))
    return procs


# `pidin fds` prints a process header ("<pid> <name>", pid right-aligned) followed
# by indented rows: "<fd>[s] <server-pid> <flags> <offset> [<path>]".
def parse_fds(text: str) -> list[Edge]:
    """Turn `pidin fds` output into client->server edges (side channels included)."""
    edges: list[Edge] = []
    current: int | None = None
    for line in text.splitlines():
        tok = line.split()
        if len(tok) < 2:
            continue
        fd, second = tok[0], tok[1]
        if fd.isdigit() and not second.isdigit() and len(tok) == 2:
            current = int(fd)                       # process header
            continue
        if current is not None and fd.rstrip("s").isdigit() and second.isdigit():
            path = tok[-1] if tok[-1].startswith("/") else None
            via = ("coid" if fd.endswith("s") else "fd") + (f":{path}" if path else "")
            edges.append(Edge(current, int(second), via, path))
    return edges


SYSTEM_PIDS = {1}          # procnto: every process talks to the kernel/process manager


def build_graph(threads_text: str, fds_text: str = "",
                ignore_pids: Iterable[int] = SYSTEM_PIDS) -> Graph:
    g = Graph(parse_threads(threads_text))
    ignore = set(ignore_pids)
    for proc in g.processes.values():
        for t in proc.threads:
            if t.blocked_pid is not None and t.blocked_pid not in ignore:
                g.add_edge(Edge(proc.pid, t.blocked_pid, "blocked"))
    for e in parse_fds(fds_text):
        if e.server_pid in ignore or e.client_pid in ignore:
            continue
        if e.server_pid in g.processes and e.client_pid in g.processes:
            g.add_edge(e)
    return g
