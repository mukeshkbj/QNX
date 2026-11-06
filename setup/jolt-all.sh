#!/usr/bin/env bash
# rebuild everything and run: demo before/after, QNX shim-demo, QNX system services
LOG=/mnt/d/QNX/logs/jolt-all.log; exec > >(tee "$LOG") 2>&1
cd /mnt/d/QNX/jolt
ssh qnxvm 'sh /tmp/jolt/stack.sh stop; sh /tmp/jolt/shim-stack.sh stop' >/dev/null 2>&1
bash target/build.sh qnxvm | tail -1 || exit 1
python3 -m pytest -q 2>&1 | tail -2
for M in "start before" "start-fixed after"; do set -- $M
  echo "=================== demo $2"
  python3 -m jolt run --target qnxvm --only imu,planner,actuator,watchdog --seed 1 \
     --out jolt-out/$2 --reset "sh /tmp/jolt/stack.sh $1" | grep -E "^plan|^\[|: |Score"
done
ssh qnxvm 'sh /tmp/jolt/stack.sh stop' >/dev/null
echo "=================== QNX shim-demo"
bash thirdparty/shim-demo/build.sh qnxvm | tail -1
ssh qnxvm 'sh /tmp/jolt/shim-stack.sh start'
python3 -m jolt run --target qnxvm --only eventfd-mgr,efd_worker --seed 1 --out jolt-out/shim-demo \
  --reset "sh /tmp/jolt/shim-stack.sh start" | grep -E "^plan|^\[|: |Score"
ssh qnxvm 'sh /tmp/jolt/shim-stack.sh stop'
echo "=================== QNX system services"
python3 -m jolt run --target qnxvm --servers slogger2,random --kinds freeze,starve --duration 4 \
   --seed 1 --out jolt-out/system | grep -E "^plan|^\[|: |Score"
