#!/usr/bin/env bash
# target/build.sh - build Jolt's target programs and copy them to a QNX target.
#   target/build.sh qnxvm      # QEMU x86_64
#   target/build.sh qnxpi      # Raspberry Pi 5 (aarch64le)
#   target/build.sh qnxvm --no-deploy
set -euo pipefail
HOST="${1:-qnxvm}"; DEPLOY=1; [ "${2:-}" = "--no-deploy" ] && DEPLOY=0
SDP="${QNX_SDP:-$HOME/qnx800}"
# shellcheck disable=SC1091
source "$SDP/qnxsdp-env.sh" >/dev/null
case "$HOST" in qnxpi*) V=gcc_ntoaarch64le ;; *) V=gcc_ntox86_64 ;; esac

cd "$(dirname "$0")"
OUT="build/$V"; mkdir -p "$OUT"
CF="-V$V -Wall -O2"
for b in imu planner actuator; do qcc $CF -o "$OUT/$b" demo-stack/node.c; done
qcc $CF -o "$OUT/watchdog"    demo-stack/watchdog.c
qcc $CF -o "$OUT/jolt_starve" tools/jolt_starve.c
qcc $CF -o "$OUT/jolt_watch"  tools/jolt_watch.c
qcc $CF -o "$OUT/jolt_interpose" tools/jolt_interpose.c
cp demo-stack/stack.sh "$OUT/"
echo "built $(ls "$OUT" | tr '\n' ' ') for $V"

if [ "$DEPLOY" = 1 ]; then
  ssh "$HOST" 'mkdir -p /tmp/jolt'
  scp -q "$OUT"/* "$HOST:/tmp/jolt/"
  echo "deployed to $HOST:/tmp/jolt  (start the stack: ssh $HOST sh /tmp/jolt/stack.sh start)"
fi
