<!-- system -->
You are a QNX Neutrino real-time systems expert reviewing the results of Jolt, a
chaos-engineering tool for QNX 8.0. You are given deterministic fault-injection results
(verdicts are facts measured from kernel thread states - do not dispute or re-score them)
and optionally source excerpts. For each failing check, explain in plain English what
happened inside QNX (message passing states, _NTO_CHF_UNBLOCK, priorities and priority
inheritance, supervision) and give the smallest concrete fix, as a unified diff when the
source is available. Group findings by root cause. Mark anything you infer rather than
read from the evidence as an assumption. Be concise; no preamble.

<!-- user -->
Target: qnxvm  seed: 1  score: 14

Message-passing graph (client -> server, via):
  planner -> imu (fd:/dev/imu)
  planner -> actuator (coid)

Verdicts (fault, client, verdict, longest block s, blocking episodes):
  kill:imu               planner        server-not-restarted     0.0 0
  delay+1500ms:imu       planner        slow-intolerant         1.49 4
  starve@p60:imu         planner        starved                  0.0 0
  starve@p60:actuator    planner        starved                  0.0 0
  kill:actuator          planner        pass                     0.0 0
  freeze:imu             planner        hang-no-timeout         4.83 1
  freeze:actuator        planner        hang-no-timeout         4.83 1

Source excerpts around call sites:
--- node.c:5
    2:  * node.c - one building block of Jolt's demo robot stack. Built three times so
    3:  * each role has its own name in pidin: imu, planner, actuator.
    4:  *
    5:  *   imu      -r /dev/imu -h jolt_watchdog   resource manager: each read() returns a fresh sample
    6:  *   actuator -s actuator                    name_attach server for motor commands
    7:  *   planner  -d /dev/imu -c actuator        every 200 ms: read the imu, command the actuator
    8:  *            [-t 500]                       per-request kernel timeout (TimerTimeout)
--- node.c:47
   44: /* ---- name_attach server (actuator) ------------------------------------ */
   45: static void *serve_name(void *arg)
   46: {
   47:     name_attach_t *att = name_attach(NULL, (const char *)arg, 0);
   48:     if (!att) { perror("name_attach"); exit(1); }
   49:     printf("%s: serving name '%s'\n", me, (const char *)arg);
   50:     fflush(stdout);
   51:     for (;;) {
   52:         recv_buf_t b;
   53:         int rcvid = MsgReceive(att->chid, &b, sizeof(b), NULL);
   54:         if (rcvid == -1) continue;
   55:         if (rcvid == 0) {
   56:             if (b.pulse.code == _PULSE_CODE_DISCONNECT) ConnectDetach(b.pulse.scoid);
   57:             continue;
   58:         }
   59:         if (b.type == _IO_CONNECT) { MsgReply(rcvid, EOK, NULL, 0); continue; }
   60:         if (b.type != MSG_TYPE)    { MsgError(rcvid, ENOSYS); continue; }
   61:         node_msg_t r = { MSG_TYPE, b.msg.value + 1 };
   62:         MsgReply(rcvid, EOK, &r, sizeof(r));
   63:     }
   64:     return NULL;
   65: }
--- node.c:80
   77:     char buf[64];
   78:     int n = snprintf(buf, sizeof(buf), "%s sample %u\n", me, ++samples);
   79:     size_t len = msg->i.nbytes < (size_t)n ? msg->i.nbytes : (size_t)n;
   80:     MsgReply(ctp->rcvid, len, buf, len);     /* every read is a fresh sample */
   81:     return _RESMGR_NOREPLY;
   82: }
   83: 
--- node.c:95
   92:     memset(&ra, 0, sizeof(ra));
   93:     ra.nparts_max = 1;
   94:     ra.msg_max_size = 2048;
   95:     if (!dpp || resmgr_attach(dpp, &ra, path, _FTYPE_ANY, 0, &rcf, &rif, &rattr) == -1) {
   96:         perror("resmgr_attach");
   97:         exit(1);
   98:     }
--- node.c:115
  112:     /* Run above background load: a starved heartbeat looks exactly like a hung server and
  113:        gets a healthy process killed (found by Jolt's starve experiment). */
  114:     struct sched_param sp = { .sched_priority = 62 };
  115:     pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
  116:     int coid = -1;
  117:     for (;;) {
  118:         if (coid == -1) coid = name_open((const char *)arg, 0);
  119:         if (coid != -1 && MsgSendPulse(coid, -1, HB_PULSE_CODE, getpid()) == -1) {
  120:             name_close(coid);
  121:             coid = -1;
  122:         }
--- node.c:133
  130: {
  131:     if (ms <= 0) return;
  132:     uint64_t ns = (uint64_t)ms * 1000000ULL;
  133:     TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND | _NTO_TIMEOUT_REPLY, NULL, &ns, NULL);
  134: }
  135: 
  136: static int call_name(const char *peer, int *coid, long timeout_ms, int value)
  137: {
  138:     if (*coid == -1 && (*coid = name_open(peer, 0)) == -1) return -1;
  139:     node_msg_t q = { MSG_TYPE, value }, r;
  140:     arm_timeout(timeout_ms);
  141:     if (MsgSend(*coid, &q, sizeof(q), &r, sizeof(r)) == -1) {
  142:         int e = errno;
  143:         if (e != ETIMEDOUT) { name_close(*coid); *coid = -1; }
  144:         errno = e;
--- node.c:152
  149: 
  150: static int read_dev(const char *path, int *fd, long timeout_ms)
  151: {
  152:     if (*fd == -1 && (*fd = open(path, O_RDONLY)) == -1) return -1;
  153:     char buf[64];
  154:     arm_timeout(timeout_ms);
  155:     ssize_t n = read(*fd, buf, sizeof(buf));
  156:     if (n == -1) {
  157:         int e = errno;
  158:         if (e != ETIMEDOUT) { close(*fd); *fd = -1; }

--- watchdog.c:110
  107:     }
  108: 
  109:     name_attach_t *att = NULL;
  110:     if (my_name && !(att = name_attach(NULL, my_name, 0))) { perror("name_attach"); return 1; }
  111:     printf("watchdog: supervising %d server(s)%s\n", n, att ? ", heartbeats on" : "");
  112:     fflush(stdout);
  113: 
  116:         if (att) {
  117:             union { struct _pulse p; char raw[512]; uint16_t type; } m;
  118:             uint64_t ns = 100 * 1000000ULL;
  119:             TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_RECEIVE, NULL, &ns, NULL);
  120:             int rcvid = MsgReceive(att->chid, &m, sizeof(m), NULL);
  121:             if (rcvid == 0 && m.p.code == HB_PULSE_CODE) {
  122:                 pid_t pid = m.p.value.sival_int;
  123:                 char exe[64];
--- watchdog.c:130
  127:             } else if (rcvid == 0 && m.p.code == _PULSE_CODE_DISCONNECT) {
  128:                 ConnectDetach(m.p.scoid);
  129:             } else if (rcvid > 0) {
  130:                 if (m.type == _IO_CONNECT) MsgReply(rcvid, EOK, NULL, 0);
  131:                 else MsgError(rcvid, ENOSYS);
  132:             }
  133:         } else {
