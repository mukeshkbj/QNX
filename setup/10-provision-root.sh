#!/usr/bin/env bash
# 10-provision-root.sh - run ONCE as root in the dedicated 'qnx' WSL distro:
#   wsl -d qnx -u root -e bash /mnt/d/QNX/jolt-setup/setup/10-provision-root.sh mukesh
# Creates the Linux user (passwordless sudo - this distro is a dev sandbox),
# enables systemd, installs build tools, QEMU/KVM, libvirt, SSH and Python.
set -euo pipefail
U="${1:-mukesh}"
LOG=/mnt/d/QNX/logs/10-provision-root.log
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "== $(date -Is) provisioning for user $U =="

if ! id "$U" >/dev/null 2>&1; then
  useradd -m -s /bin/bash -G sudo "$U"
  echo "created user $U"
fi
echo "$U ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-$U-nopasswd
chmod 440 /etc/sudoers.d/90-$U-nopasswd

cat > /etc/wsl.conf <<EOF
[boot]
systemd=true

[user]
default=$U

[interop]
appendWindowsPath=false
EOF

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  build-essential git curl wget unzip zip file jq \
  python3 python3-venv python3-pip \
  openssh-client sshpass \
  qemu-system-x86 qemu-system-arm qemu-utils \
  libvirt-daemon-system libvirt-clients bridge-utils net-tools dnsmasq-base \
  default-jre libswt-gtk-4-java libgtk-3-0 libwebkit2gtk-4.0-37 \
  avahi-utils libnss-mdns xdg-utils

for g in kvm libvirt; do getent group "$g" >/dev/null && gpasswd -a "$U" "$g" || true; done
echo "== done $(date -Is). Now run in PowerShell:  wsl --terminate qnx =="
