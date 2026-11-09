/*
 * jolt_interpose.c - Jolt's "delay" and "error" faults: a transparent proxy that
 * sits IN FRONT of a resource manager's pathname.
 *
 *   jolt_interpose -p /dev/imu -u imu -d 1500      delay every request by 1.5 s
 *   jolt_interpose -p /dev/imu -u imu -e 5         fail every request with errno 5 (EIO)
 *
 * QNX mechanics used:
 *  - resmgr_attach(..., _RESMGR_FLAG_BEFORE): path resolution offers us NEW opens
 *    of <path> before the real server. (Opens made before we started are not
 *    affected, so Jolt restarts the system under test after starting us.)
 *  - Pathname fall-through: to reach the real server, an opener thread calls
 *    open(<path>) itself. That connect comes to us first; we answer our own pid
 *    with ENOENT and libc falls through to the next server on the path - the
 *    real one. The fd we get is a connection to it, used to forward messages.
 *  - Held, not slept on: delayed requests wait in a queue while we keep
 *    receiving. A 10 ms timer pulse releases them.
 *  - _NTO_CHF_UNBLOCK: if a client's TimerTimeout fires while its request is
 *    held, the kernel sends _PULSE_CODE_UNBLOCK and we answer it with ETIMEDOUT
 *    at once - what a well-behaved slow server does.
 *  - name_attach() names (/dev/name/...) are exclusive: resmgr_attach returns
 *    EEXIST, so those services cannot be interposed by path.
 *  - Only plain opens (_IO_CONNECT_OPEN) are interposed. Combined connects such
 *    as stat() or unlink() by path get ENOENT and fall through to the real server.
 *  - Messages of any size: the rest of a large request is fetched with MsgRead.
 *    Replies use the client's own reply-buffer size (dstmsglen), because the
 *    status MsgSend returns is not a reply length (except for _IO_READ).
 *  - Forwarding is synchronous: one request at a time reaches the real server.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/dispatch.h>
#include <sys/iomsg.h>
#include <sys/neutrino.h>

#define MAXQ      64
#define MAXMSG    2048          /* receive buffer; larger requests are completed with MsgRead */
#define MAXFWD    (1 << 20)     /* largest request or reply forwarded (1 MiB) */
#define TICK_CODE (_PULSE_CODE_MINAVAIL + 7)

typedef struct { int rcvid; double due_ms; size_t len, rlen; uint16_t type; char *msg; } held_t;

static held_t q[MAXQ];
static int nq = 0;
static const char *path, *up_name = "server";
static volatile int up_fd = -1;
static long n_fwd = 0, n_unblock = 0, n_err = 0, n_conn = 0;
static volatile sig_atomic_t stop = 0;

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

/* keeps a connection open to the REAL server (via pathname fall-through) */
static void *opener(void *arg)
{
    (void)arg;
    while (!stop) {
        if (up_fd == -1) {
            int fd = open(path, O_RDWR);
            if (fd == -1) fd = open(path, O_RDONLY);
            if (fd != -1) {
                up_fd = fd;
                printf("interpose: upstream %s connected (fd %d)\n", up_name, fd);
                fflush(stdout);
            }
        }
        usleep(100 * 1000);
    }
    return NULL;
}

static void forward(held_t *h)
{
    int fd = up_fd;
    if (fd == -1) { MsgError(h->rcvid, EIO); n_err++; return; }
    char *reply = calloc(1, h->rlen ? h->rlen : 1);
    if (!reply) { MsgError(h->rcvid, ENOMEM); n_err++; return; }
    long st = MsgSend(fd, h->msg, h->len, reply, h->rlen);
    if (st == -1) {
        int e = errno;
        if (e == EBADF || e == ESRCH || e == ENOTCONN) { close(fd); up_fd = -1; e = EIO; }
        MsgError(h->rcvid, e);
        n_err++;
    } else {
        /* For _IO_READ the status is the byte count; for everything else (stat,
         * devctl, write...) the status is not a length, so pass the whole reply
         * buffer back, sized to what the client asked for. */
        size_t n = h->rlen;
        if (h->type == _IO_READ) n = st >= 0 && (size_t)st < h->rlen ? (size_t)st : h->rlen;
        MsgReply(h->rcvid, st, reply, n);
        n_fwd++;
    }
    free(reply);
}

static void drop(int i) { free(q[i].msg); q[i] = q[--nq]; }
static void on_term(int s) { (void)s; stop = 1; }

int main(int argc, char **argv)
{
    int delay_ms = 1000, err = 0, opt;
    while ((opt = getopt(argc, argv, "p:u:d:e:")) != -1) {
        if (opt == 'p') path = optarg;
        if (opt == 'u') up_name = optarg;
        if (opt == 'd') delay_ms = atoi(optarg);
        if (opt == 'e') err = atoi(optarg);
    }
    if (!path) {
        fprintf(stderr, "usage: jolt_interpose -p <path> [-u <name>] [-d ms | -e errno]\n");
        return 2;
    }

    int chid = ChannelCreate(_NTO_CHF_UNBLOCK | _NTO_CHF_DISCONNECT);
    dispatch_t *dpp = dispatch_create_channel(chid, DISPATCH_FLAG_NOLOCK);
    if (chid == -1 || !dpp) { perror("channel/dispatch"); return 1; }
    if (resmgr_attach(dpp, NULL, path, _FTYPE_ANY, _RESMGR_FLAG_BEFORE, NULL, NULL, NULL) == -1) {
        int e = errno;
        perror("resmgr_attach");
        if (e == EEXIST) fprintf(stderr, "interpose: %s is an exclusive name (name_attach?) "
                                         "and cannot be interposed by path\n", path);
        return 1;
    }

    int self = ConnectAttach(0, 0, chid, _NTO_SIDE_CHANNEL, 0);
    struct sigevent ev;
    SIGEV_PULSE_INIT(&ev, self, SIGEV_PULSE_PRIO_INHERIT, TICK_CODE, 0);
    timer_t tid;
    timer_create(CLOCK_MONOTONIC, &ev, &tid);
    struct itimerspec its = { { 0, 10000000 }, { 0, 10000000 } };
    timer_settime(tid, 0, &its, NULL);
    signal(SIGTERM, on_term);
    signal(SIGINT, on_term);

    pthread_t th;
    pthread_create(&th, NULL, opener, NULL);
    printf("interpose: in front of %s (%s), %s %d\n", path, up_name,
           err ? "errno" : "delay_ms", err ? err : delay_ms);
    fflush(stdout);

    while (!stop) {
        union { uint16_t type; struct _pulse p; struct _io_connect c; char raw[MAXMSG]; } m;
        struct _msg_info info;
        int rcvid = MsgReceive(chid, &m, sizeof(m), &info);
        if (rcvid == -1) { if (errno == EINTR) continue; break; }

        if (rcvid == 0) {
            if (m.p.code == TICK_CODE) {
                double t = now_ms();
                for (int i = 0; i < nq; ) if (q[i].due_ms <= t) { forward(&q[i]); drop(i); } else i++;
            } else if (m.p.code == _PULSE_CODE_UNBLOCK) {
                int r = m.p.value.sival_int;
                for (int i = 0; i < nq; i++)
                    if (q[i].rcvid == r) { MsgError(r, ETIMEDOUT); drop(i); n_unblock++; break; }
            } else if (m.p.code == _PULSE_CODE_DISCONNECT) {
                ConnectDetach(m.p.scoid);
            }
            continue;
        }
        if (m.type == _IO_CONNECT) {
            if (info.pid == getpid()) { MsgError(rcvid, ENOENT); continue; }  /* fall through */
            if (m.c.subtype != _IO_CONNECT_OPEN) { MsgError(rcvid, ENOENT); continue; }  /* stat, unlink...: real server */
            n_conn++;
            MsgReply(rcvid, EOK, NULL, 0);
            continue;
        }
        if (m.type == _IO_CLOSE) { MsgReply(rcvid, EOK, NULL, 0); continue; }  /* keep upstream open */
        if (err) { MsgError(rcvid, err); n_err++; continue; }
        if (nq == MAXQ) { MsgError(rcvid, EAGAIN); continue; }
        if (info.srcmsglen > MAXFWD || info.dstmsglen > MAXFWD) { MsgError(rcvid, E2BIG); n_err++; continue; }
        char *buf = malloc(info.srcmsglen ? info.srcmsglen : 1);
        if (!buf) { MsgError(rcvid, ENOMEM); n_err++; continue; }
        size_t got = info.msglen < sizeof(m) ? info.msglen : sizeof(m);
        memcpy(buf, m.raw, got);
        if (info.srcmsglen > got &&                       /* fetch the rest of a large request */
            MsgRead(rcvid, buf + got, info.srcmsglen - got, got) == -1) {
            MsgError(rcvid, errno); free(buf); n_err++; continue;
        }
        q[nq] = (held_t){ rcvid, now_ms() + delay_ms, info.srcmsglen, info.dstmsglen, m.type, buf };
        nq++;
    }
    for (int i = 0; i < nq; i++) { MsgError(q[i].rcvid, EIO); free(q[i].msg); }
    printf("interpose: done. connects %ld, forwarded %ld, released-by-client-timeout %ld, errors %ld\n",
           n_conn, n_fwd, n_unblock, n_err);
    return 0;
}
