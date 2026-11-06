#!/usr/bin/env bash
# 02-prepare-ubuntu.sh - run inside Ubuntu 22.04 (WSL2) as your normal user.
#   bash 02-prepare-ubuntu.sh
# Installs build tools, QEMU/KVM, libvirt, SSH tools and Python; enables systemd;
# and launches the QNX Software Center installer if you have downloaded it.
set -euo pipefail

say() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }

say "Enabling systemd in WSL (libvirt needs it)"
if ! grep -q "systemd=true" /etc/wsl.conf 2>/dev/null; then
  printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf >/dev/null
  NEED_RESTART=1
else
  NEED_RESTART=0
fi

say "Installing packages"
sudo apt-get update
sudo apt-get install -y \
  build-essential git curl unzip file \
  python3 python3-venv python3-pip \
  openssh-client sshpass \
  qemu-system-x86 qemu-system-arm qemu-utils \
  libvirt-daemon-system libvirt-clients bridge-utils net-tools \
  default-jre libswt-gtk-4-java libgtk-3-0 \
  avahi-utils libnss-mdns

say "Adding $USER to kvm and libvirt groups"
sudo usermod -aG kvm,libvirt "$USER" || true

say "Checking KVM"
if [ -e /dev/kvm ]; then
  echo "/dev/kvm present - QEMU will be hardware accelerated."
else
  echo "WARNING: /dev/kvm not found. QEMU will still work but slowly."
  echo "Check that 01-install-wsl.ps1 ran and that virtualisation is on in BIOS."
fi

say "Looking for the QNX Software Center installer in your Windows Downloads"
WINUSER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')
DL="/mnt/c/Users/${WINUSER}/Downloads"
INSTALLER=$(ls -t "$DL"/qnx*.run 2>/dev/null | head -n1 || true)
if [ -n "${INSTALLER}" ]; then
  echo "Found: $INSTALLER"
  cp "$INSTALLER" "$HOME/"
  chmod +x "$HOME/$(basename "$INSTALLER")"
  echo "Starting it now. Accept the licence; keep the default path (~/qnx/qnxsoftwarecenter)."
  "$HOME/$(basename "$INSTALLER")"
else
  echo "No qnx*.run file found in $DL."
  echo "Download 'QNX Software Center for Linux hosts' from your myQNX account,"
  echo "save it to Downloads, then rerun this script."
fi

echo
if [ "$NEED_RESTART" = "1" ]; then
  echo "IMPORTANT: systemd was just enabled. In Windows PowerShell run:  wsl --shutdown"
  echo "then reopen Ubuntu before continuing."
fi
echo "Next: open the Software Center (~/qnx/qnxsoftwarecenter/qnxsoftwarecenter),"
echo "install QNX SDP 8.0 as 'qnx800' (see SETUP.md step 3), then run 03-verify-and-make-target.sh."
