#!/bin/sh
# stack.sh - start/stop Jolt's demo robot stack ON THE TARGET.
#   sh /tmp/jolt/stack.sh start        BEFORE: no timeouts, imu unsupervised, no hang detection
#   sh /tmp/jolt/stack.sh start-fixed  AFTER:  timeouts, both servers supervised, heartbeat hang detection
#   sh /tmp/jolt/stack.sh stop
D=/tmp/jolt
killall_stack() {   # guard and watchdog first so nothing restarts what we kill; SIGKILL also reaches stopped processes
  [ -f $D/guard.pid ] && kill -9 $(cat $D/guard.pid) >/dev/null 2>&1; rm -f $D/guard.pid
  # a running jolt_interpose is left alone on (re)start: Jolt starts it BEFORE restarting the stack
  for n in watchdog planner imu actuator jolt_starve $1; do slay -s KILL -f $n >/dev/null 2>&1; done
  sleep 1
}
case "$1" in
  start|start-fixed)
    killall_stack
    if [ "$1" = start-fixed ]; then
      # guard loop: who watches the watchdog? (found by Jolt). A real system would use its
      # launcher (e.g. SLM) for this; the loop restarts the watchdog about 1 s after it dies.
      nohup sh -c "echo \$\$ > $D/guard.pid; while :; do on -p 62 $D/watchdog -n jolt_watchdog -H 1000 \
          -r 'actuator=$D/actuator -s actuator -h jolt_watchdog' \
          -r '/dev/imu=$D/imu -r /dev/imu -h jolt_watchdog' >> $D/watchdog.log 2>&1; sleep 1; done" >/dev/null 2>&1 &
      sleep 2                     # watchdog starts the servers itself
      on -p 61 $D/planner -d /dev/imu -c actuator -t 500 > $D/planner.log 2>&1 &   # critical loop above background load
    else
      $D/imu -r /dev/imu > $D/imu.log 2>&1 &
      $D/actuator -s actuator > $D/actuator.log 2>&1 &
      sleep 1
      $D/planner -d /dev/imu -c actuator > $D/planner.log 2>&1 &
      $D/watchdog -r "actuator=$D/actuator -s actuator" > $D/watchdog.log 2>&1 &
    fi
    sleep 1
    pidin -F "%a %N %J %B" | grep -E "imu|planner|actuator|watchdog"
    ;;
  stop)
    killall_stack jolt_interpose
    echo stopped
    ;;
  *) echo "usage: $0 start|start-fixed|stop"; exit 1 ;;
esac
