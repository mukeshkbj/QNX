#!/usr/bin/env bash
pkill -f "ssh qnxvm sh /tmp/jolt/stack.sh" 2>/dev/null
ssh -o ConnectTimeout=5 qnxvm 'for n in watchdog planner imu actuator jolt_starve jolt_interpose; do slay -s KILL -f $n 2>/dev/null; done; sleep 1; pidin -F "%a %N %J" | grep -E "imu|planner|actuator|watchdog" || echo clean'
