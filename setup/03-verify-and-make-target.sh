#!/usr/bin/env bash
# 03-verify-and-make-target.sh - run inside Ubuntu (WSL2) AFTER QNX SDP 8.0 is installed.
#   bash 03-verify-and-make-target.sh
# Checks the SDP and compiler, builds an x86_64 QEMU QNX target, boots it
# headless, finds its IP and writes ssh shortcuts:  ssh qnxvm   /   ssh qnxpi
set -euo pipefail

LOG=/mnt/d/QNX/logs/03-verify-and-make-target.log
mkdir -p "$(dirname "$LOG")" 2>/dev/null && exec > >(tee -a "$LOG") 2>&1 || true
say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
SDP="${QNX_SDP:-$HOME/qnx800}"
TARGET_DIR="$HOME/qnxtargets/qnxvm"

say "Checking the SDP at $SDP"
if [ ! -f "$SDP/qnxsdp-env.sh" ]; then
  echo "Not found: $SDP/qnxsdp-env.sh"
  echo "Install SDP 8.0 with the Software Center as '$SDP' first (or set QNX_SDP=/path)."
  exit 1
fi
# shellcheck disable=SC1091
source "$SDP/qnxsdp-env.sh"
grep -q "qnxsdp-env.sh" "$HOME/.bashrc" || echo "source \"$SDP/qnxsdp-env.sh\" >/dev/null" >> "$HOME/.bashrc"
echo "QNX_HOST=$QNX_HOST"
echo "QNX_TARGET=$QNX_TARGET"

say "Checking the compiler"
qcc 2>&1 | head -n1 || true   # expect: "cc: no files to process"
for v in gcc_ntox86_64 gcc_ntoaarch64le; do
  if echo 'int main(void){return 0;}' | qcc -V$v -x c - -o /tmp/qcc_test_$v 2>/dev/null; then
    echo "  $v: OK"
  else
    echo "  $v: FAILED (is that target architecture installed in the SDP?)"
  fi
done

say "Checking libvirt (QEMU networking)"
if ! systemctl is-active --quiet libvirtd 2>/dev/null; then
  sudo systemctl enable --now libvirtd || echo "libvirtd did not start - see SETUP.md troubleshooting."
fi
sudo virsh net-start default 2>/dev/null || true
sudo virsh net-autostart default 2>/dev/null || true

say "Building the QEMU x86_64 target in $TARGET_DIR"
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"
mkqnximage --type=qemu --arch=x86_64 --hostname=qnxvm --build

say "Booting it headless"
mkqnximage --run=-h || true
echo "Waiting for an IP address (up to a couple of minutes)..."
IP=$(timeout 180 mkqnximage --getip 2>/dev/null | tail -n1 || true)
if [ -z "$IP" ]; then
  echo "Could not get the VM's IP yet. Try later:  cd $TARGET_DIR && mkqnximage --getip"
  exit 0
fi
echo "QEMU target IP: $IP"

say "Writing ssh shortcuts to ~/.ssh/config"
mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/config"; chmod 600 "$HOME/.ssh/config"
sed -i '/^# >>> jolt targets >>>/,/^# <<< jolt targets <<</d' "$HOME/.ssh/config"
cat >> "$HOME/.ssh/config" <<EOF
# >>> jolt targets >>>
Host qnxvm
  HostName $IP
  User root
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
Host qnxpi
  HostName qnxpi.local
  User qnxuser
  MACs hmac-sha2-256
# <<< jolt targets <<<
EOF

echo
echo "Done. Try:   ssh qnxvm        (password: root)"
echo "On the target try:  uname -a ; pidin | head ; pidin channels | head"
echo "Stop the VM:  cd $TARGET_DIR && mkqnximage --stop      Start again:  mkqnximage --run=-h"
