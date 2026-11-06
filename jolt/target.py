"""Talking to a QNX target over SSH (QEMU VM or Raspberry Pi)."""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


@dataclass
class Target:
    host: str                      # an ssh alias such as "qnxvm" or "qnxpi", or user@host
    remote_dir: str = "/tmp/jolt"
    timeout: float = 30.0

    def _ssh(self) -> list[str]:
        # ControlMaster keeps one SSH connection open so repeated pidin samples are fast.
        return ["ssh", "-o", "ConnectTimeout=10",
                "-o", "ControlMaster=auto", "-o", "ControlPath=~/.ssh/jolt-%r@%h-%p",
                "-o", "ControlPersist=120", self.host]

    def run(self, cmd: str, timeout: float | None = None, check: bool = False) -> str:
        """Run a shell command on the target and return stdout (stderr folded in)."""
        p = subprocess.run(self._ssh() + [cmd], capture_output=True, text=True,
                           timeout=timeout or self.timeout)
        if check and p.returncode != 0:
            raise RuntimeError(f"{self.host}: '{cmd}' failed ({p.returncode}): {p.stderr.strip()}")
        return p.stdout + (p.stderr if p.returncode != 0 else "")

    def push(self, *local_files: str) -> None:
        self.run(f"mkdir -p {shlex.quote(self.remote_dir)}", check=True)
        subprocess.run(["scp", "-q", *local_files, f"{self.host}:{self.remote_dir}/"],
                       check=True, timeout=self.timeout * 4)

    def pid_of(self, name: str) -> int | None:
        out = self.run(f'pidin -p {shlex.quote(name)} -F "%a" 2>/dev/null')
        for line in out.split():
            if line.isdigit():
                return int(line)
        return None

    def signal(self, pid: int, sig: str) -> str:
        return self.run(f"kill -{sig} {pid}")
