#!/usr/bin/env bash
# 12-build-vm.sh - build and boot the x86_64 QEMU QNX 8.0 target "qnxvm" (run as your user).
set -u
LOG=/mnt/d/QNX/logs/12-build-vm.log; exec > >(tee -a "$LOG") 2>&1
echo "== $(date -Is) =="
source ~/qnx800/qnxsdp-env.sh >/dev/null
grep -q qnxsdp-env.sh ~/.bashrc || echo 'source ~/qnx800/qnxsdp-env.sh >/dev/null' >> ~/.bashrc
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -f ~/.ssh/id_ed25519
D=~/qnxtargets/qnxvm; mkdir -p "$D"; cd "$D"
mkqnximage --type=qemu --arch=x86_64 --hostname=qnxvm --cpu=2 --ram=2G \
  --ssh-ident=$HOME/.ssh/id_ed25519.pub --python=yes "$@" --build --run=-h
rc=$?; echo "mkqnximage rc=$rc"
IP=""
for i in $(seq 30); do IP=$(mkqnximage --getip 2>/dev/null | grep -Eo '([0-9]+\.){3}[0-9]+' | tail -1); [ -n "$IP" ] && break; sleep 4; done
echo "IP=$IP"
[ -z "$IP" ] && exit 1
mkdir -p ~/.ssh; touch ~/.ssh/config; chmod 600 ~/.ssh/config
sed -i '/^# >>> jolt targets >>>/,/^# <<< jolt targets <<</d' ~/.ssh/config
cat >> ~/.ssh/config <<CFG
# >>> jolt targets >>>
Host qnxvm
  HostName $IP
  User root
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
Host qnxpi
  HostName qnxpi.local
  User qnxuser
# <<< jolt targets <<<
CFG
for i in $(seq 15); do ssh -o ConnectTimeout=5 qnxvm 'uname -a' && break; sleep 4; done
ssh qnxvm 'pidin info | head -5; which python3'
