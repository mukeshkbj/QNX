/*
 * jolt_watch.c - high-rate observer for Jolt experiments (run as root on the target).
 *
 *   jolt_watch -d 5 -i 20 -s <server_pid> <client_pid> [<client_pid> ...]
 *   jolt_watch -d 5 -i 20 -s 0 <client_pid> ...        blocking on ANY server (system-wide faults)
 *
 * Every <interval> ms, reads every thread of each client straight from the
 * kernel (devctl DCMD_PROC_TIDSTATUS on /proc/<pid>/ctl) and records whether
 * it is SEND- or REPLY-blocked on <server_pid>. Prints one line per client:
 *
 *   client <pid> longest_ms <n> episodes <n> samples <n> alive <0|1> ready_ms <n>
 *
 * "ready_ms" is the longest stretch the client was runnable but not running
 * (a thread READY, none RUNNING) - i.e. starved of CPU. jolt_watch raises its own
 * priority to 63 so it keeps sampling while a CPU hog runs below that.
 *
 * "longest_ms" is the longest continuous block on the server. A client with a
 * TimerTimeout shows many short episodes; a client without one shows a single
 * episode as long as the fault.
 */
#include <devctl.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/procfs.h>

#define MAXC 16

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

static int open_proc(pid_t pid)
{
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/ctl", pid);
    int fd = open(path, O_RDONLY);
    if (fd == -1) {
        snprintf(path, sizeof(path), "/proc/%d/as", pid);
        fd = open(path, O_RDONLY);
    }
    return fd;
}

/* 1 if any thread of the process is SEND/REPLY blocked on server; -1 if gone.
   *starved = 1 if some thread is READY and none is RUNNING. */
static int blocked_on(pid_t pid, pid_t server, int *starved)
{
    int fd = open_proc(pid);
    if (fd == -1) return -1;
    procfs_status st;
    int blocked = 0, ready = 0, running = 0;
    memset(&st, 0, sizeof(st));
    st.tid = 1;
    while (devctl(fd, DCMD_PROC_TIDSTATUS, &st, sizeof(st), NULL) == EOK) {
        if ((st.state == STATE_SEND || st.state == STATE_REPLY) &&
            (server == 0 ? st.blocked.connect.pid != 1 : st.blocked.connect.pid == server))
            blocked = 1;          /* server 0 = any server except procnto */
        if (st.state == STATE_READY) ready = 1;
        if (st.state == STATE_RUNNING) running = 1;
        st.tid++;
    }
    close(fd);
    *starved = ready && !running;
    return blocked;
}

int main(int argc, char **argv)
{
    double dur_s = 5.0;
    int interval_ms = 20, opt;
    pid_t server = 0;
    while ((opt = getopt(argc, argv, "d:i:s:")) != -1) {
        if (opt == 'd') dur_s = atof(optarg);
        if (opt == 'i') interval_ms = atoi(optarg);
        if (opt == 's') server = atoi(optarg);
    }
    int n = 0;
    pid_t cl[MAXC];
    for (int i = optind; i < argc && n < MAXC; i++) cl[n++] = atoi(argv[i]);
    if (server < 0 || !n) {
        fprintf(stderr, "usage: jolt_watch -d secs -i ms -s server_pid client_pid...\n");
        return 2;
    }

    /* sample from above any CPU hog (needs root for priorities > 63 limits) */
    struct sched_param sp = { .sched_priority = 63 };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);

    double start[MAXC], longest[MAXC], rstart[MAXC], rlongest[MAXC];
    int episodes[MAXC], alive[MAXC], in_block[MAXC], in_ready[MAXC], pre[MAXC];
    for (int i = 0; i < n; i++) {
        start[i] = longest[i] = rstart[i] = rlongest[i] = 0;
        episodes[i] = 0; alive[i] = 1; in_block[i] = in_ready[i] = pre[i] = 0;
    }

    struct timespec iv = { interval_ms / 1000, (interval_ms % 1000) * 1000000L };
    double t_end = now_ms() + dur_s * 1000.0;
    long samples = 0;
    while (now_ms() < t_end) {
        double t = now_ms();
        for (int i = 0; i < n; i++) {
            int starved = 0;
            int b = blocked_on(cl[i], server, &starved);
            if (b < 0) { alive[i] = 0; in_block[i] = in_ready[i] = 0; continue; }
            if (starved && !in_ready[i]) { in_ready[i] = 1; rstart[i] = t; }
            if (!starved) in_ready[i] = 0;
            if (in_ready[i] && t - rstart[i] > rlongest[i]) rlongest[i] = t - rstart[i];
            /* system-wide mode (-s 0): a block already in progress at the first sample
               (e.g. a shell waiting for console input) was not caused by the fault */
            if (server == 0 && samples == 0 && b) pre[i] = 1;
            if (pre[i]) { if (!b) pre[i] = 0; continue; }
            if (b && !in_block[i]) { in_block[i] = 1; start[i] = t; episodes[i]++; }
            if (!b) in_block[i] = 0;
            if (in_block[i] && t - start[i] > longest[i]) longest[i] = t - start[i];
        }
        samples++;
        nanosleep(&iv, NULL);
    }
    for (int i = 0; i < n; i++)
        printf("client %d longest_ms %.0f episodes %d samples %ld alive %d ready_ms %.0f\n",
               cl[i], longest[i], episodes[i], samples, alive[i], rlongest[i]);
    return 0;
}
