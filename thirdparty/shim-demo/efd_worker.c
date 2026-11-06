/*
 * efd_worker.c - TEST HARNESS (written for Jolt, not part of QNX's shim-demo).
 * A long-running user of QNX's eventfd shim, written the way typical ported
 * Linux code uses eventfd: blocking calls, no timeouts.
 * Every 200 ms: write(1) then read() the counter through libeventfd -> /dev/eventfd.
 */
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include "sys/eventfd.h"

int main(void)
{
    int efd = -1;
    for (unsigned n = 1;; n++) {
        if (efd < 0) {
            efd = eventfd(0, 0);
            if (efd < 0) { printf("efd_worker: eventfd: %s\n", strerror(errno)); sleep(1); continue; }
        }
        uint64_t one = 1, v = 0;
        if (write(efd, &one, sizeof(one)) != sizeof(one) || read(efd, &v, sizeof(v)) != sizeof(v)) {
            printf("efd_worker: I/O error: %s - reopening\n", strerror(errno));
            close(efd);
            efd = -1;
        }
        if (n % 50 == 0) { printf("efd_worker: alive, cycle %u\n", n); fflush(stdout); }
        usleep(200 * 1000);
    }
}
