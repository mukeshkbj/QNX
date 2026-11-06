"""Deterministic fault coverage over the discovered graph.

Every server that has at least one client gets every enabled fault type.
The order is shuffled with a seed so runs are reproducible: same graph + same
seed = same plan. The LLM never chooses faults; it only explains results.
"""
from __future__ import annotations

import random

from .faults import Fault
from .model import Graph

DEFAULT_KINDS = ("kill", "freeze", "starve", "delay")


def make_plan(g: Graph, kinds=DEFAULT_KINDS, seed: int = 1, duration: float = 5.0,
              starve_priority: int = 60, delay_ms: int = 1500,
              only: list[str] | None = None) -> list[Fault]:
    servers = sorted({g.name(pid) for pid in g.servers() if g.clients_of(pid)})
    # resource-manager paths clients use to reach each server (name_attach names are exclusive
    # and can't be interposed, so /dev/name/... is skipped)
    rm_path = {}
    for e in g.edges:
        if e.path and e.path.startswith("/") and not e.path.startswith("/dev/name/"):
            rm_path.setdefault(g.name(e.server_pid), e.path)
    if only:
        servers = [s for s in servers if s in only]
    plan = []
    for s in servers:
        for k in kinds:
            if k == "delay" and s not in rm_path:
                continue
            plan.append(Fault(kind=k, server=s, duration=duration,
                              priority=starve_priority if k == "starve" else 0,
                              delay_ms=delay_ms if k == "delay" else 0,
                              path=rm_path.get(s, "") if k == "delay" else ""))
    random.Random(seed).shuffle(plan)
    return plan


def coverage(g: Graph, plan: list[Fault]) -> dict:
    """How many (client -> server edge, fault kind) pairs the plan exercises."""
    names = {f.server for f in plan}
    kinds = sorted({f.kind for f in plan})
    edges = [e for e in g.edges if g.name(e.server_pid) in names]
    pairs = sum(1 for f in plan for e in g.edges if g.name(e.server_pid) == f.server)
    return {"servers": len(names), "edges": len(edges), "fault_kinds": kinds,
            "edge_fault_pairs": pairs, "experiments": len(plan)}
