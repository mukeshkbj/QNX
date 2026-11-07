# Codelab: Why your QNX client hangs

**Timeouts, `_NTO_CHF_UNBLOCK` and heartbeats on QNX 8.0**

| | |
| --- | --- |
| Time | About 45 minutes |
| Level | Intermediate: you have written C and are new to QNX message passing |
| You need | QNX SDP 8.0, a QNX 8.0 target reachable as root over SSH (a QEMU VM from `mkqnximage`, or a Raspberry Pi 5), and this repository |
| You'll learn | How to read client and server states in `pidin`, why `TimerTimeout` saves you from a slow server but not a frozen one, how to detect hangs with heartbeat pulses, and what priority inheritance does and doesn't protect |

Every command was run on QNX 8.0 (x86_64 QEMU), and outputs are copied from those runs unless marked *abridged*. Your pids and timings will differ.

---

## 1. Build and deploy the demo stack

The demo is a small robot control stack:

- `imu` is a **resource manager** at `/dev/imu`. Every `read()` returns a sample.
- `actuator` is a `name_attach()` server.
- `planner` reads `/dev/imu` and sends a command to `actuator` every 200 ms.
- `watchdog` restarts servers that disappear.

```bash
source ~/qnx800/qnxsdp-env.sh
target/build.sh qnxvm               # qcc for x86_64; use qnxpi for a Raspberry Pi 5
ssh qnxvm sh /tmp/jolt/stack.sh start
```

## 2. Read the system the way the kernel sees it

```sh
# on the target
pidin -F "%a %N %J %p %B" | grep -E "imu|planner|actuator|watchdog"
```

- Healthy servers sit **RECEIVE**-blocked, waiting in `MsgReceive()`.
- `planner` spends most of its time in **NANOSLEEP**.
- While it waits for a server, it is **SEND**-blocked (the server hasn't received yet) or **REPLY**-blocked (the server received but hasn't replied). `%B` shows which pid it is waiting on.

`pidin fds` shows who is connected to whom, even when nobody is blocked (abridged):

```
    4102 planner
        3   4100 r-   0 /dev/imu        <- fd to the imu resource manager
        4s  4101 --   0                 <- side channel (coid) to actuator
```

## 3. Freeze a server

```sh
I=$(pidin -p imu -F "%a" | tail -1 | tr -d " ")
kill -STOP $I; sleep 2
pidin -F "%a %N %J %B" | grep -E "planner|imu"
```

```
 7909398 imu        STOPPED
 7925784 planner    REPLY    7909398      <- stuck in read(), waiting on the frozen imu
```

`planner` stays REPLY-blocked until you run `kill -CONT $I`. If the server had died instead, the kernel would have unblocked `planner` with an error. **A dead server is visible; a hung one isn't.**

## 4. "Just add a timeout" - and watch it not work

`planner` supports a per-request kernel timeout (`-t`). Internally it calls `TimerTimeout()` before each request:

```c
uint64_t ns = timeout_ms * 1000000ULL;
TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND | _NTO_TIMEOUT_REPLY, NULL, &ns, NULL);
ssize_t n = read(fd, buf, sizeof(buf));     /* read() is a MsgSend() to the resource manager */
```

Restart `planner` with `-t 500`, freeze the server again, and measure with `jolt_watch`. It reads client thread states from the kernel every 20 ms:

```sh
/tmp/jolt/planner -d /dev/imu -c actuator -t 500 > /tmp/jolt/planner.log 2>&1 &
kill -STOP $I; /tmp/jolt/jolt_watch -d 3 -i 20 -s $I $(pidin -p planner -F "%a" | tail -1); kill -CONT $I
```

```
client 7573528 longest_ms 2793 episodes 1 ...      <- blocked for the whole 3 s freeze, despite -t 500
```

**Why?** Look at the server's channel:

```sh
pidin -p actuator channels
#   00000001: flags 0000004a ...
```

`0x4a` is `_NTO_CHF_COID_DISCONNECT | _NTO_CHF_DISCONNECT | _NTO_CHF_UNBLOCK`. `name_attach()` and the resource-manager framework create channels with `_NTO_CHF_UNBLOCK`.

With that flag set, when a **REPLY**-blocked client's timeout fires, the kernel doesn't release it. It sends the server a `_PULSE_CODE_UNBLOCK` pulse and lets the server decide. A frozen server never decides.

> A timeout only frees a client that is still **SEND**-blocked. Once the server has received the message, the server must cooperate.

## 5. A slow (but alive) server does honour your timeout

`jolt_interpose` is a resource manager that registers **in front of** `/dev/imu` using `_RESMGR_FLAG_BEFORE`. It holds each request for 1.5 s, then forwards it to the real `imu`.

To reach the real server, it opens `/dev/imu` itself. It answers its own connect with `ENOENT`, so libc falls through to the next server on the path. Crucially, it handles `_PULSE_CODE_UNBLOCK` by replying `ETIMEDOUT` immediately.

```sh
sh /tmp/jolt/stack.sh stop
/tmp/jolt/jolt_interpose -p /dev/imu -u imu -d 1500 > /tmp/jolt/interpose.log 2>&1 &
sleep 1; sh /tmp/jolt/stack.sh start        # clients reconnect -> through the interposer
```

| planner | longest block | interposer log |
| --- | --- | --- |
| no timeout | **1492 ms** per read | `forwarded 4` |
| `-t 500` | **483 ms** | `released-by-client-timeout 11` |

So the same `TimerTimeout` that failed in step 4 works here, because this server is alive and answers the unblock pulse.

## 6. Detect hangs from outside: heartbeats

If a frozen server can't release its clients, something else has to notice. QNX's usual answer is to kill the hung process: when a server dies, the kernel unblocks every client with an error.

- Each server sends a heartbeat **pulse** every 200 ms (`MsgSendPulse`, which never blocks the sender).
- The watchdog receives with a timeout (`_NTO_TIMEOUT_RECEIVE`). After 1 s of silence, it sends `SIGKILL`, then restarts the server.
- The watchdog checks liveness by listing `/dev/name/local` and `/dev`. procnto serves those listings, so the check never blocks on the server it watches.

```sh
sh /tmp/jolt/stack.sh start-fixed
I=$(pidin -p imu -F "%a" | tail -1 | tr -d " "); P=$(pidin -p planner -F "%a" | tail -1 | tr -d " ")
(kill -STOP $I; sleep 3; kill -CONT $I) &
/tmp/jolt/jolt_watch -d 3 -i 20 -s $I $P
tail -2 /tmp/jolt/watchdog.log
```

```
client 43409435 longest_ms 777 episodes 1 ...
watchdog: /dev/imu (pid 43319326) silent for 1005 ms - hung, killing
watchdog: /dev/imu missing, restarting
```

The freeze now costs `planner` 0.78 s instead of forever.

## 7. Priorities: what inheritance protects - and what it doesn't

`start-fixed` runs `planner` at priority 61 (`on -p 61 ...`). With the stack running, look at `imu`:

```sh
pidin -F "%a %N %J %p" | grep -E "imu|planner"
```

```
43319326 imu        RECEIVE   61r       <- serving planner at planner's priority
43409435 planner    NANOSLEEP 61r
```

`imu` runs at priority 10, yet its receive thread shows **61**: the priority of the client it last served. That's QNX priority inheritance through message passing. Now load every CPU at priority 60 with `/tmp/jolt/jolt_starve -p 60 -t 5 -c -1 &`: `planner` keeps working, because `imu` serves it at 61.

The heartbeat threads and the watchdog get no such protection. If they run at 10, they starve, heartbeats stop, and the watchdog kills healthy servers once the load ends. `start-fixed` therefore runs the heartbeat threads and the watchdog at priority 62.

## 8. Automate all of this with Jolt

```bash
python3 -m jolt serve &      # http://localhost:8765/dashboard.html?run=jolt-out/after&compare=jolt-out/before
python3 -m jolt run --target qnxvm --only imu,planner,actuator,watchdog --seed 1 \
        --out jolt-out/before --reset "sh /tmp/jolt/stack.sh start"
python3 -m jolt run --target qnxvm --only imu,planner,actuator,watchdog --seed 1 \
        --out jolt-out/after  --reset "sh /tmp/jolt/stack.sh start-fixed"
```

Jolt does the following:

- discovers the graph from `pidin`
- runs every fault (kill, freeze, starve, delay, error) against every server
- measures each client with `jolt_watch`
- scores the run and writes `report.md` and `junit.xml` for CI

Our runs: **14/100 before, 100/100 after**, with three rounds of fixes in between, each pointed to by the previous run.

## Summary

| Situation | Does `TimerTimeout` free the client? | What does |
| --- | --- | --- |
| Server dead | Not needed: the kernel returns an error | Reconnect on `ESRCH`/`EBADF`; supervise and restart the server |
| Server slow but alive | **Yes**, because the server handles `_PULSE_CODE_UNBLOCK` | Timeouts on every request |
| Server frozen or deadlocked after receiving | **No** (`_NTO_CHF_UNBLOCK`) | External hang detection (heartbeat pulses), then `SIGKILL`; the kernel then unblocks clients |
| CPU saturated below the client's priority | n/a | Priority inheritance protects the client's servers; give heartbeats and supervisors priorities above the load too |
