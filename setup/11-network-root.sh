#!/usr/bin/env bash
# 11-network-root.sh - run as root in the qnx distro. Sets up the NAT bridge
# that mkqnximage's QEMU targets use (virbr0 + libvirt DHCP + qemu-bridge-helper).
set -u
LOG=/mnt/d/QNX/logs/11-network-root.log; exec > >(tee -a "$LOG") 2>&1
echo "== $(date -Is) =="
if ip link show virbr0 >/dev/null 2>&1 && ! pgrep -f "dnsmasq.*default.conf" >/dev/null; then
  echo "removing stale virbr0 (no DHCP behind it)"; ip link delete virbr0
fi
virsh net-start default 2>&1 || true
virsh net-autostart default
virsh net-list --all
mkdir -p /etc/qemu
grep -qs '^allow virbr0' /etc/qemu/bridge.conf || echo "allow virbr0" >> /etc/qemu/bridge.conf
chmod u+s /usr/lib/qemu/qemu-bridge-helper
ls -l /usr/lib/qemu/qemu-bridge-helper; cat /etc/qemu/bridge.conf
ip -br addr show virbr0
