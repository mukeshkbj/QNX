/*
 * jolt_starve.c - Jolt's CPU-starvation fault.
 *
 *   jolt_starve -p 60 -t 5 -c 1     spin at priority 60 (FIFO) on CPU 1 for 5 s
 *   jolt_starve -p 60 -t 5 -c -1    spin on every CPU (one thread per CPU)
 *   jolt_starve ... -w 300          wait 300 ms before starting (lets an observer start first)
 *
 * A thread at a higher priority than the victim, pinned to the victim's CPU,
 * takes all of that CPU until it exits. Priorities above 63 need root.
 */
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

static double seconds = 5.0;

static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void *spin(void *arg)
{
    int cpu = (int)(intptr_t)arg;
    if (ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)(1u << cpu)) == -1)
        perror("ThreadCtl(RUNMASK)");
    double end = now() + seconds;
    volatile uint64_t x = 0;
    while (now() < end) x++;
    return NULL;
}

int main(int argc, char **argv)
{
    int prio = 60, cpu = -1, wait_ms = 0, opt;
    while ((opt = getopt(argc, argv, "p:t:c:w:")) != -1) {
        if (opt == 'w') wait_ms = atoi(optarg);
        if (opt == 'p') prio = atoi(optarg);
        if (opt == 't') seconds = atof(optarg);
        if (opt == 'c') cpu = atoi(optarg);
    }
    if (wait_ms > 0) usleep(wait_ms * 1000);
    int ncpu = _syspage_ptr->num_cpu;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setinheritsched(&a, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&a, SCHED_FIFO);
    struct sched_param sp = { .sched_priority = prio };
    pthread_attr_setschedparam(&a, &sp);

    int first = cpu < 0 ? 0 : cpu, last = cpu < 0 ? ncpu - 1 : cpu;
    pthread_t th[64];
    int n = 0;
    for (int c = first; c <= last && n < 64; c++) {
        int rc = pthread_create(&th[n], &a, spin, (void *)(intptr_t)c);
        if (rc) { fprintf(stderr, "pthread_create prio %d: %s\n", prio, strerror(rc)); return 1; }
        n++;
    }
    printf("jolt_starve: %d thread(s) at priority %d for %.1f s\n", n, prio, seconds);
    fflush(stdout);
    for (int i = 0; i < n; i++) pthread_join(th[i], NULL);
    return 0;
}
