# Jolt resilience report: qnxvm

**Score: 77/100** (10 of 13 exercised checks passed; 13 idle; seed 1)

| Fault | Client | Verdict | Longest block (s) | Fix |
| --- | --- | --- | --- | --- |
| starve@p60:all | devb-eide | starved | 0.0 | The client runs below background load. Give the critical loop a priority above it (e.g. `on -p 61 <cmd>` or pthread_setschedparam) or use adaptive partitioning. |
| starve@p60:all | io-sock | starved | 0.0 | The client runs below background load. Give the critical loop a priority above it (e.g. `on -p 61 <cmd>` or pthread_setschedparam) or use adaptive partitioning. |
| starve@p60:all | random | starved | 0.0 | The client runs below background load. Give the critical loop a priority above it (e.g. `on -p 61 <cmd>` or pthread_setschedparam) or use adaptive partitioning. |
| starve@p60:all | devc-pty | pass | 0.0 |  |
| starve@p60:all | dhcpcd | pass | 0.0 |  |
| starve@p60:all | dumper | pass | 0.0 |  |
| starve@p60:all | fsevmgr | pass | 0.0 |  |
| starve@p60:all | io-usb-otg | pass | 0.0 |  |
| starve@p60:all | ksh | pass | 0.0 |  |
| starve@p60:all | pci-server | pass | 0.0 |  |
| starve@p60:all | qconn | pass | 0.0 |  |
| starve@p60:all | sshd | pass | 0.0 |  |
| starve@p60:all | sshd-session | pass | 0.0 |  |
| freeze:random | dhcpcd | idle | 0.0 |  |
| freeze:random | io-sock | idle | 0.0 |  |
| freeze:random | sshd | idle | 0.0 |  |
| freeze:random | sshd-session | idle | 0.0 |  |
| freeze:slogger2 | devb-eide | idle | 0.0 |  |
| freeze:slogger2 | devc-pty | idle | 0.0 |  |
| freeze:slogger2 | dhcpcd | idle | 0.0 |  |
| freeze:slogger2 | dumper | idle | 0.0 |  |
| freeze:slogger2 | fsevmgr | idle | 0.0 |  |
| freeze:slogger2 | io-sock | idle | 0.0 |  |
| freeze:slogger2 | io-usb-otg | idle | 0.0 |  |
| freeze:slogger2 | pci-server | idle | 0.0 |  |
| freeze:slogger2 | random | idle | 0.0 |  |

## What each fault checks

- **kill**: Clients get an error, reconnect, and the server is restarted.
- **freeze**: No client waits longer than its timeout; nobody blocks for the whole freeze.
- **starve**: (One system-wide experiment.) With every CPU busy at priority 60, no client is starved or blocked on a server for more than 1 s. Clients above the load keep running, and QNX priority inheritance lets their servers run at the client's priority.
- **delay**: Against a slow (but alive) server, no client waits longer than 1 s per request.
- **error**: When every request fails with EIO, clients survive and recover once the path works again.

**idle** means the client sent the server no request during a freeze or delay, so that check was not exercised. Idle checks are excluded from the score.
