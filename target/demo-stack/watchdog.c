/*
 * watchdog.c - supervises demo-stack servers.
 *
 *   watchdog -r "actuator=/tmp/jolt/actuator -s actuator" -r "/dev/imu=/tmp/jolt/imu -r /dev/imu"
 *            [-n jolt_watchdog] [-H 1000]
 *
 * Two checks per server:
 *  1. Death: is the server's name still registered under /dev/name/local?
 *     (served by procnto, so the check never blocks on the server itself).
 *     If not, restart it.
 *  2. Hang (only with -n): servers started with "-h jolt_watchdog" send a
 *     heartbeat pulse every 200 ms. If a server that has been sending
 *     heartbeats goes silent for -H ms, it is hung (frozen, starved or
 *     deadlocked): SIGKILL it. The kernel then unblocks every client that
 *     was REPLY-blocked on it with an error, and check 1 restarts it.
 *
 * Pulses never block the sender, and the watchdog only ever RECEIVEs with a
 * timeout, so a hung server can't hang the watchdog.
 */
#include <dirent.h>
#include <errno.h>
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

#define MAX_RULES 8
#define HB_PULSE_CODE (_PULSE_CODE_MINAVAIL + 1)

typedef struct {
    char *name, *cmd;
    pid_t pid;          /* last pid seen sending heartbeats */
    double last_hb;     /* ms, 0 = never */
} rule_t;

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

/* Is the server registered? "actuator" -> /dev/name/local/actuator, "/dev/imu" -> entry
   "imu" in /dev. Directory listings of these come from procnto's pathname space, so
   the check never blocks on the (possibly frozen) server itself. */
static int registered(const char *name)
{
    char dir[256] = "/dev/name/local";
    const char *entry = name;
    if (name[0] == '/') {
        const char *slash = strrchr(name, '/');
        snprintf(dir, sizeof(dir), "%.*s", (int)(slash - name ? slash - name : 1), name);
        entry = slash + 1;
    }
    DIR *d = opendir(dir);
    if (!d) return 0;
    struct dirent *e;
    int found = 0;
    while ((e = readdir(d))) if (strcmp(e->d_name, entry) == 0) { found = 1; break; }
    closedir(d);
    return found;
}

static const char *label(const char *name)          /* "/dev/imu" -> "imu" */
{
    const char *b = strrchr(name, '/');
    return b ? b + 1 : name;
}

/* basename of /proc/<pid>/exefile, or "" */
static void exe_name(pid_t pid, char *out, size_t n)
{
    char path[64], buf[256] = "";
    snprintf(path, sizeof(path), "/proc/%d/exefile", pid);
    FILE *f = fopen(path, "r");
    out[0] = '\0';
    if (!f) return;
    if (fgets(buf, sizeof(buf), f)) {
        buf[strcspn(buf, "\n")] = '\0';
        const char *b = strrchr(buf, '/');
        snprintf(out, n, "%s", b ? b + 1 : buf);
    }
    fclose(f);
}

int main(int argc, char **argv)
{
    rule_t r[MAX_RULES];
    int n = 0, opt, hang_ms = 1000;
    const char *my_name = NULL;
    while ((opt = getopt(argc, argv, "r:n:H:")) != -1) {
        if (opt == 'r' && n < MAX_RULES) {
            char *eq = strchr(optarg, '=');
            if (!eq) { fprintf(stderr, "bad rule %s\n", optarg); return 1; }
            *eq = '\0';
            r[n] = (rule_t){ optarg, eq + 1, 0, 0 };
            n++;
        }
        if (opt == 'n') my_name = optarg;
        if (opt == 'H') hang_ms = atoi(optarg);
    }

    name_attach_t *att = NULL;
    if (my_name && !(att = name_attach(NULL, my_name, 0))) { perror("name_attach"); return 1; }
    printf("watchdog: supervising %d server(s)%s\n", n, att ? ", heartbeats on" : "");
    fflush(stdout);

    for (;;) {
        /* 1. collect heartbeats for up to 100 ms */
        if (att) {
            union { struct _pulse p; char raw[512]; uint16_t type; } m;
            uint64_t ns = 100 * 1000000ULL;
            TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_RECEIVE, NULL, &ns, NULL);
            int rcvid = MsgReceive(att->chid, &m, sizeof(m), NULL);
            if (rcvid == 0 && m.p.code == HB_PULSE_CODE) {
                pid_t pid = m.p.value.sival_int;
                char exe[64];
                exe_name(pid, exe, sizeof(exe));
                for (int i = 0; i < n; i++)
                    if (strcmp(exe, label(r[i].name)) == 0) { r[i].pid = pid; r[i].last_hb = now_ms(); }
            } else if (rcvid == 0 && m.p.code == _PULSE_CODE_DISCONNECT) {
                ConnectDetach(m.p.scoid);
            } else if (rcvid > 0) {
                if (m.type == _IO_CONNECT) MsgReply(rcvid, EOK, NULL, 0);
                else MsgError(rcvid, ENOSYS);
            }
        } else {
            usleep(100 * 1000);
        }

        /* 2. hang detection, 3. death detection */
        double t = now_ms();
        for (int i = 0; i < n; i++) {
            if (att && r[i].last_hb > 0 && t - r[i].last_hb > hang_ms) {
                printf("watchdog: %s (pid %d) silent for %.0f ms - hung, killing\n",
                       r[i].name, r[i].pid, t - r[i].last_hb);
                fflush(stdout);
                kill(r[i].pid, SIGKILL);
                r[i].last_hb = 0;
            }
            if (!registered(r[i].name)) {
                char buf[512];
                snprintf(buf, sizeof(buf), "%s >/dev/null 2>&1 &", r[i].cmd);
                printf("watchdog: %s missing, restarting\n", r[i].name);
                fflush(stdout);
                system(buf);
                r[i].last_hb = 0;
                usleep(500 * 1000);
            }
        }
    }
}
