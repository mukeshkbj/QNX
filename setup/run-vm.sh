#!/usr/bin/env bash
# run-vm.sh - run the qnxvm QEMU target in the FOREGROUND (keep this terminal open).
# Stop with Ctrl+C, or from another shell: kill $(cat ~/qnxtargets/qnxvm/output/qemu.pid)
cd ~/qnxtargets/qnxvm
CMD=$(grep -h "QEMU Command" /mnt/d/QNX/logs/12-build-vm.log | tail -1 | sed 's/^QEMU Command: //')
echo "starting: $CMD"
exec $CMD
