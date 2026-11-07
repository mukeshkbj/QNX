#!/usr/bin/env bash
# find the qnxvm IP (MAC 52:54:00:fa:4c:11) from libvirt DHCP leases and update ~/.ssh/config
ip -br addr show virbr0
L=$(virsh -c qemu:///system net-dhcp-leases default 2>/dev/null | grep -i 52:54:00:fa:4c:11 | grep -Eo '([0-9]+\.){3}[0-9]+' | tail -1)
echo "lease: ${L:-none}"
[ -z "$L" ] && L=$(ip neigh show dev virbr0 | grep -i 52:54:00:fa:4c:11 | awk '{print $1}' | head -1)
echo "ip: ${L:-unknown}"
if [ -n "$L" ]; then sed -i "/^Host qnxvm/,/^Host /s/^  HostName .*/  HostName $L/" ~/.ssh/config; grep -A2 "^Host qnxvm" ~/.ssh/config; timeout 8 ssh -o ConnectTimeout=4 qnxvm 'echo up'; fi
