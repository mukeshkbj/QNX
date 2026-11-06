# Jolt resilience report: qnxvm

**Score: 14/100** (1 of 7 exercised checks passed; 0 idle; seed 1)

| Fault | Client | Verdict | Longest block (s) | Fix |
| --- | --- | --- | --- | --- |
| delay+1500ms:imu | planner | slow-intolerant | 1.49 | Arm TimerTimeout before each request to a server that can be slow; a live server honours the unblock, so the client gets ETIMEDOUT and carries on. |
| freeze:actuator | planner | hang-no-timeout | 4.83 | Arm TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND|_NTO_TIMEOUT_REPLY, ...) before MsgSend and handle ETIMEDOUT. |
| freeze:imu | planner | hang-no-timeout | 4.83 | Arm TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND|_NTO_TIMEOUT_REPLY, ...) before MsgSend and handle ETIMEDOUT. |
| kill:imu | planner | server-not-restarted | 0.0 | Supervise the server (e.g. a watchdog or the System Launch and Monitor) so it is restarted after it dies. |
| starve@p60:actuator | planner | starved | 0.0 | The client runs below background load. Give the critical loop a priority above it (e.g. `on -p 61 <cmd>` or pthread_setschedparam) or use adaptive partitioning. |
| starve@p60:imu | planner | starved | 0.0 | The client runs below background load. Give the critical loop a priority above it (e.g. `on -p 61 <cmd>` or pthread_setschedparam) or use adaptive partitioning. |
| kill:actuator | planner | pass | 0.0 |  |

## What each fault checks

- **kill**: Clients get an error, reconnect, and the server is restarted.
- **freeze**: No client waits longer than its timeout; nobody blocks for the whole freeze.
- **starve**: With every CPU busy at priority 60, no client is starved or blocked on its server for more than 1 s. Clients above the load keep running, and QNX priority inheritance lets their servers run at the client's priority.
- **delay**: Against a slow (but alive) server, no client waits longer than 1 s per request.

**idle** means the client sent the server no request during a freeze or delay, so that check was not exercised. Idle checks are excluded from the score.
