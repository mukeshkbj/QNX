# Jolt resilience report: qnxvm

**Score: 100/100** (11 of 11 exercised checks passed; 2 idle; seed 1)

| Fault | Client | Verdict | Longest block (s) | Fix |
| --- | --- | --- | --- | --- |
| delay+1500ms:imu | planner | pass | 0.48 |  |
| freeze:actuator | planner | pass | 0.69 |  |
| freeze:imu | planner | pass | 0.8 |  |
| kill:actuator | planner | pass | 0.0 |  |
| kill:imu | planner | pass | 0.0 |  |
| kill:watchdog | actuator | pass | 0.0 |  |
| kill:watchdog | imu | pass | 0.0 |  |
| starve@p60:actuator | planner | pass | 0.0 |  |
| starve@p60:imu | planner | pass | 0.0 |  |
| starve@p60:watchdog | actuator | pass | 0.0 |  |
| starve@p60:watchdog | imu | pass | 0.0 |  |
| freeze:watchdog | actuator | idle | 0.0 |  |
| freeze:watchdog | imu | idle | 0.0 |  |

## What each fault checks

- **kill**: Clients get an error, reconnect, and the server is restarted.
- **freeze**: No client waits longer than its timeout; nobody blocks for the whole freeze.
- **starve**: With every CPU busy at priority 60, no client is starved or blocked on its server for more than 1 s. Clients above the load keep running, and QNX priority inheritance lets their servers run at the client's priority.
- **delay**: Against a slow (but alive) server, no client waits longer than 1 s per request.

**idle** means the client sent the server no request during a freeze or delay, so that check was not exercised. Idle checks are excluded from the score.
