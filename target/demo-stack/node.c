/*
 * node.c - one building block of Jolt's demo robot stack. Built three times so
 * each role has its own name in pidin: imu, planner, actuator.
 *
 *   imu      -r /dev/imu -h jolt_watchdog   resource manager: each read() returns a fresh sample
 *   actuator -s actuator                    name_attach server for motor commands
 *   planner  -d /dev/imu -c actuator        every 200 ms: read the imu, command the actuator
 *            [-t 500]                       per-request kernel timeout (TimerTimeout)
 *   any server [-h jolt_watchdog]           heartbeat pulse to the watchdog every 200 ms
 *
 * What the demo teaches (see README):
 *  - A SLOW server that is alive honours client timeouts (it gets
 *    _PULSE_CODE_UNBLOCK and replies), so -t fixes it.
 *  - A FROZEN server does not: once it has received the request the client is
 *    REPLY-blocked and, because resmgr and name_attach channels set
 *    _NTO_CHF_UNBLOCK, its timeout cannot free it. Only external hang
 *    detection (heartbeats + kill) does.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/dispatch.h>
#include <sys/iofunc.h>
#include <sys/iomsg.h>
#include <sys/neutrino.h>

#define MSG_TYPE      0x4A01
#define MAX_PEERS     4
#define HB_PULSE_CODE (_PULSE_CODE_MINAVAIL + 1)

typedef struct { uint16_t type; int32_t value; } node_msg_t;
typedef union { uint16_t type; struct _pulse pulse; node_msg_t msg; char raw[512]; } recv_buf_t;

static const char *me = "node";
static unsigned samples = 0;

/* ---- name_attach server (actuator) ------------------------------------ */
static void *serve_name(void *arg)
{
    name_attach_t *att = name_attach(NULL, (const char *)arg, 0);
    if (!att) { perror("name_attach"); exit(1); }
    printf("%s: serving name '%s'\n", me, (const char *)arg);
    fflush(stdout);
    for (;;) {
        recv_buf_t b;
        int rcvid = MsgReceive(att->chid, &b, sizeof(b), NULL);
        if (rcvid == -1) continue;
        if (rcvid == 0) {
            if (b.pulse.code == _PULSE_CODE_DISCONNECT) ConnectDetach(b.pulse.scoid);
            continue;
        }
        if (b.type == _IO_CONNECT) { MsgReply(rcvid, EOK, NULL, 0); continue; }
        if (b.type != MSG_TYPE)    { MsgError(rcvid, ENOSYS); continue; }
        node_msg_t r = { MSG_TYPE, b.msg.value + 1 };
        MsgReply(rcvid, EOK, &r, sizeof(r));
    }
    return NULL;
}

/* ---- resource manager (imu) -------------------------------------------- */
static resmgr_connect_funcs_t rcf;
static resmgr_io_funcs_t rif;
static iofunc_attr_t rattr;

static int io_read(resmgr_context_t *ctp, io_read_t *msg, RESMGR_OCB_T *ocb)
{
    int st = iofunc_read_verify(ctp, msg, ocb, NULL);
    if (st != EOK) return st;
    if ((msg->i.xtype & _IO_XTYPE_MASK) != _IO_XTYPE_NONE) return ENOSYS;
    char buf[64];
    int n = snprintf(buf, sizeof(buf), "%s sample %u\n", me, ++samples);
    size_t len = msg->i.nbytes < (size_t)n ? msg->i.nbytes : (size_t)n;
    MsgReply(ctp->rcvid, len, buf, len);     /* every read is a fresh sample */
    return _RESMGR_NOREPLY;
}

static void *serve_dev(void *arg)
{
    const char *path = arg;
    dispatch_t *dpp = dispatch_create();
    iofunc_func_init(_RESMGR_CONNECT_NFUNCS, &rcf, _RESMGR_IO_NFUNCS, &rif);
    rif.read = io_read;
    iofunc_attr_init(&rattr, S_IFCHR | 0666, NULL, NULL);
    resmgr_attr_t ra;
    memset(&ra, 0, sizeof(ra));
    ra.nparts_max = 1;
    ra.msg_max_size = 2048;
    if (!dpp || resmgr_attach(dpp, &ra, path, _FTYPE_ANY, 0, &rcf, &rif, &rattr) == -1) {
        perror("resmgr_attach");
        exit(1);
    }
    printf("%s: resource manager at %s\n", me, path);
    fflush(stdout);
    dispatch_context_t *ctp = dispatch_context_alloc(dpp);
    for (;;) {
        dispatch_context_t *c = dispatch_block(ctp);
        if (c) { ctp = c; dispatch_handler(ctp); }
    }
    return NULL;
}

/* ---- heartbeat ------------------------------------------------------------ */
static void *heartbeat(void *arg)
{
    /* Run above background load: a starved heartbeat looks exactly like a hung server and
       gets a healthy process killed (found by Jolt's starve experiment). */
    struct sched_param sp = { .sched_priority = 62 };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    int coid = -1;
    for (;;) {
        if (coid == -1) coid = name_open((const char *)arg, 0);
        if (coid != -1 && MsgSendPulse(coid, -1, HB_PULSE_CODE, getpid()) == -1) {
            name_close(coid);
            coid = -1;
        }
        usleep(200 * 1000);
    }
    return NULL;
}

/* ---- client side ----------------------------------------------------------- */
static void arm_timeout(long ms)
{
    if (ms <= 0) return;
    uint64_t ns = (uint64_t)ms * 1000000ULL;
    TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_SEND | _NTO_TIMEOUT_REPLY, NULL, &ns, NULL);
}

static int call_name(const char *peer, int *coid, long timeout_ms, int value)
{
    if (*coid == -1 && (*coid = name_open(peer, 0)) == -1) return -1;
    node_msg_t q = { MSG_TYPE, value }, r;
    arm_timeout(timeout_ms);
    if (MsgSend(*coid, &q, sizeof(q), &r, sizeof(r)) == -1) {
        int e = errno;
        if (e != ETIMEDOUT) { name_close(*coid); *coid = -1; }
        errno = e;
        return -1;
    }
    return r.value;
}

static int read_dev(const char *path, int *fd, long timeout_ms)
{
    if (*fd == -1 && (*fd = open(path, O_RDONLY)) == -1) return -1;
    char buf[64];
    arm_timeout(timeout_ms);
    ssize_t n = read(*fd, buf, sizeof(buf));
    if (n == -1) {
        int e = errno;
        if (e != ETIMEDOUT) { close(*fd); *fd = -1; }
        errno = e;
        return -1;
    }
    return (int)n;
}

int main(int argc, char **argv)
{
    const char *serve = NULL, *dev_serve = NULL, *hb = NULL, *peers[MAX_PEERS], *devs[MAX_PEERS];
    int npeers = 0, ndevs = 0, coids[MAX_PEERS], fds[MAX_PEERS];
    long timeout_ms = 0, interval_ms = 200;
    me = strrchr(argv[0], '/') ? strrchr(argv[0], '/') + 1 : argv[0];

    int opt;
    while ((opt = getopt(argc, argv, "s:r:c:d:t:i:h:")) != -1) {
        switch (opt) {
        case 's': serve = optarg; break;
        case 'r': dev_serve = optarg; break;
        case 'c': if (npeers < MAX_PEERS) peers[npeers++] = optarg; break;
        case 'd': if (ndevs < MAX_PEERS) devs[ndevs++] = optarg; break;
        case 't': timeout_ms = strtol(optarg, NULL, 10); break;
        case 'i': interval_ms = strtol(optarg, NULL, 10); break;
        case 'h': hb = optarg; break;
        }
    }
    for (int i = 0; i < MAX_PEERS; i++) coids[i] = fds[i] = -1;

    pthread_t th;
    if (serve)     { pthread_create(&th, NULL, serve_name, (void *)serve); pthread_setname_np(th, "server"); }
    if (dev_serve) { pthread_create(&th, NULL, serve_dev, (void *)dev_serve); pthread_setname_np(th, "resmgr"); }
    if (hb)        { pthread_create(&th, NULL, heartbeat, (void *)hb); pthread_setname_np(th, "heartbeat"); }
    if (npeers == 0 && ndevs == 0) { for (;;) pause(); }

    struct timespec ival = { interval_ms / 1000, (interval_ms % 1000) * 1000000L };
    for (unsigned n = 1;; n++) {
        for (int i = 0; i < ndevs; i++)
            if (read_dev(devs[i], &fds[i], timeout_ms) == -1 && (errno == ETIMEDOUT || n % 25 == 0))
                printf("%s: read %s failed: %s\n", me, devs[i], strerror(errno));
        for (int i = 0; i < npeers; i++)
            if (call_name(peers[i], &coids[i], timeout_ms, (int)n) == -1 && (errno == ETIMEDOUT || n % 25 == 0))
                printf("%s: %s failed: %s\n", me, peers[i], strerror(errno));
        if (n % 50 == 0) printf("%s: alive, cycle %u\n", me, n);
        fflush(stdout);
        nanosleep(&ival, NULL);
    }
}
