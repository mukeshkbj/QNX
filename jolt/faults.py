"""Fault types Jolt injects into a QNX system.

Each fault targets one server process and is undone afterwards, so the system
returns to its starting state between experiments.

  kill    SIGKILL the server. The kernel unblocks its clients with an error.
          Tests: do clients handle the error, and does anything restart the server?
  freeze  SIGSTOP for `duration` s, then SIGCONT. Nothing unblocks clients.
          Tests: does every client use a timeout (TimerTimeout) on MsgSend?
  starve  Run jolt_starve at a priority above the server, pinned to its CPU, for
          `duration` s. Tests: priority design and deadline handling.
  delay   jolt_interpose registers in front of the server's resource-manager path
          (_RESMGR_FLAG_BEFORE) and holds each request `delay_ms`. Needs --reset so
          clients reconnect through it. Tests: do clients time out against a slow
          (but alive) server?
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Fault:
    kind: str                    # kill | freeze | starve | delay
    server: str                  # process short name
    duration: float = 5.0        # seconds the fault is held (freeze/starve/delay)
    priority: int = 0            # starve: priority of the hog thread
    delay_ms: int = 0            # delay: added reply latency
    path: str = ""               # delay: the resource-manager path to interpose (e.g. /dev/imu)

    @property
    def id(self) -> str:
        extra = {"starve": f"@p{self.priority}", "delay": f"+{self.delay_ms}ms"}.get(self.kind, "")
        return f"{self.kind}{extra}:{self.server}"

    def to_dict(self) -> dict:
        return asdict(self) | {"id": self.id}


KINDS = ("kill", "freeze", "starve", "delay")
