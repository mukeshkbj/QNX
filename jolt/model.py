"""Data model: the live message-passing graph of a QNX system."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# Thread states as printed by pidin (%J). Healthy idle servers sit in RECEIVE;
# a client waiting on a server is SEND-blocked (server hasn't received yet) or
# REPLY-blocked (server received but hasn't replied).
WAITING_ON_SERVER = {"SEND", "REPLY"}


@dataclass
class Thread:
    pid: int
    tid: int
    name: str
    state: str                     # e.g. RECEIVE, REPLY, SEND, NANOSLEEP, READY, RUNNING, STOPPED
    blocked_on: Optional[str] = None   # raw %B text
    blocked_pid: Optional[int] = None  # parsed server pid for SEND/REPLY
    priority: Optional[int] = None


@dataclass
class Process:
    pid: int
    name: str
    threads: list[Thread] = field(default_factory=list)

    @property
    def short_name(self) -> str:
        return self.name.rsplit("/", 1)[-1]


@dataclass
class Edge:
    """client -> server: the client has a connection to, or is blocked on, the server."""
    client_pid: int
    server_pid: int
    via: str                       # "blocked" (seen SEND/REPLY-blocked) or "fd:<path>" / "coid"
    path: Optional[str] = None


@dataclass
class Graph:
    processes: dict[int, Process] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_edge(self, e: Edge) -> None:
        if e.client_pid == e.server_pid:
            return
        for x in self.edges:
            if x.client_pid == e.client_pid and x.server_pid == e.server_pid:
                if x.path is None and e.path:
                    x.path = e.path
                return
        self.edges.append(e)

    def servers(self) -> list[int]:
        return sorted({e.server_pid for e in self.edges})

    def clients_of(self, server_pid: int) -> list[int]:
        return sorted({e.client_pid for e in self.edges if e.server_pid == server_pid})

    def name(self, pid: int) -> str:
        p = self.processes.get(pid)
        return p.short_name if p else f"pid{pid}"

    def subgraph(self, names: list[str]) -> "Graph":
        """Keep only processes whose short name is in `names` and edges among them."""
        keep = {pid for pid, p in self.processes.items() if p.short_name in names}
        g = Graph({pid: self.processes[pid] for pid in keep})
        for e in self.edges:
            if e.client_pid in keep and e.server_pid in keep:
                g.add_edge(e)
        return g

    def to_dict(self) -> dict:
        return {
            "processes": [
                {"pid": p.pid, "name": p.short_name, "path": p.name,
                 "threads": [asdict(t) for t in p.threads]}
                for p in sorted(self.processes.values(), key=lambda p: p.pid)
            ],
            "edges": [asdict(e) for e in self.edges],
        }
