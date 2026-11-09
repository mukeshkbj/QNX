/*
 * interpose_check.c - checks that jolt_interpose forwards replies faithfully.
 *   interpose_check /dev/imu
 * Prints what fstat() and read() return through an fd on <path>. Run it once
 * directly and once with jolt_interpose in front of the path: the lines must match
 * (except the sample value read). Before the reply-length fix, fstat() through the
 * interposer returned mode 0 and a wrong inode.
 */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

int main(int argc, char **argv)
{
    const char *p = argc > 1 ? argv[1] : "/dev/imu";
    int fd = open(p, O_RDONLY);
    if (fd == -1) { perror("open"); return 1; }
    struct stat sb;
    memset(&sb, 0, sizeof(sb));
    int r = fstat(fd, &sb);
    printf("fstat rc %d mode %o ino %llu\n", r, (unsigned)sb.st_mode, (unsigned long long)sb.st_ino);
    char buf[256] = "";
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    printf("read rc %zd\n", n);
    close(fd);
    return 0;
}
