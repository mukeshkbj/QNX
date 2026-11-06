#!/usr/bin/env bash
# Build QNX's shim-demo sources UNCHANGED (from ../../../thirdparty/shim-demo) plus the harness.
set -e
source ~/qnx800/qnxsdp-env.sh >/dev/null
H="${1:-qnxvm}"; case "$H" in qnxpi*) V=gcc_ntoaarch64le ;; *) V=gcc_ntox86_64 ;; esac
SRC=/mnt/d/QNX/thirdparty/shim-demo
cd "$(dirname "$0")"; OUT=build/$V; mkdir -p $OUT
qcc -V$V -O2 -I$SRC/eventfd-shim/public -o $OUT/eventfd-mgr $SRC/eventfd-mgr.c
qcc -V$V -O2 -I$SRC/eventfd-shim/public -o $OUT/efd_worker efd_worker.c $SRC/eventfd-shim/eventfd.c
cp stack.sh $OUT/shim-stack.sh
scp -q $OUT/eventfd-mgr $OUT/efd_worker $OUT/shim-stack.sh $H:/tmp/jolt/
echo "built + deployed shim-demo ($(cd $SRC && git log --oneline -1)) for $V"
