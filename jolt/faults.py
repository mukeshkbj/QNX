"""Fault types Jolt injects into a QNX system.

Each fault targets one server process and is undone afterwards, so the system
returns to its starting state between experiments.

  kill    SIGKILL the server. The kernel unblocks its clients with an error.
          Tests: do clients handle the error, and does anything restart the server?
  freeze  SIGSTOP for `duration` s, then SIGCONT. Nothing unblocks clients.
          Tests: does every client use a timeout (TimerTimeout) on MsgSend?
  starve  ONE system-wide experiment: jolt_starve spins on every CPU at `priority`
          for `duration` s. Tests: are critical clients above background load, and do
          their servers (via priority inheritance) keep serving them?
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
    path: str = ""               # delay/error: the resource-manager path to interpose (e.g. /dev/imu)
    errno: int = 5               # error: errno returned to every request (5 = EIO)

    @property
    def id(self) -> str:
        extra = {"starve": f"@p{self.priority}", "delay": f"+{self.delay_ms}ms",
                 "error": f"=errno{self.errno}"}.get(self.kind, "")
        return f"{self.kind}{extra}:{'all' if self.server == '*' else self.server}"

    def to_dict(self) -> dict:
        return asdict(self) | {"id": self.id}


KINDS = ("kill", "freeze", "starve", "delay", "error")
