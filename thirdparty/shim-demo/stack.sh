#!/bin/sh
# QNX shim-demo (eventfd-mgr + libeventfd shim) with a long-running harness client.
D=/tmp/jolt
case "$1" in
  start)
    for n in efd_worker eventfd-mgr; do slay -s KILL -f $n >/dev/null 2>&1; done
    sleep 1
    $D/eventfd-mgr > $D/eventfd-mgr.log 2>&1 &
    sleep 1
    $D/efd_worker > $D/efd_worker.log 2>&1 &
    sleep 1 ;;
  stop)
    for n in efd_worker eventfd-mgr jolt_interpose jolt_starve; do slay -s KILL -f $n >/dev/null 2>&1; done ;;
esac
