#!/usr/bin/env bash
# check-env.sh - quick health check of the qnx WSL distro
whoami; id
ls -l /dev/kvm
echo "systemd: $(systemctl is-system-running 2>&1)"
echo "libvirtd: $(systemctl is-active libvirtd 2>&1)"
virsh -c qemu:///system net-list --all 2>&1
python3 --version; qemu-system-x86_64 --version | head -1; java -version 2>&1 | head -1
echo "DISPLAY=$DISPLAY WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
ls -d ~/qnx800 ~/qnx 2>/dev/null
df -h / | tail -1
