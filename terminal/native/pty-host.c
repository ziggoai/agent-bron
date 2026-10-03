// Local PTY host. Frames are one type byte, a big-endian uint32 length, then bytes.
#include <sys/types.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#ifdef __APPLE__
#include <util.h>
#include <libproc.h>
#else
#include <pty.h>
#endif
#include <unistd.h>
#include <signal.h>
#include <poll.h>
#include <fcntl.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT (2 * 1024 * 1024)
static volatile sig_atomic_t stopping = 0;
static void stop(int sig) { (void)sig; stopping = 1; }
static uint32_t unpack(const unsigned char *p) { return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3]; }
static void pack(unsigned char *p, uint32_t v) { p[0]=v>>24; p[1]=v>>16; p[2]=v>>8; p[3]=v; }
static int write_all(int fd, const void *buffer, size_t length) {
  const unsigned char *p = buffer;
  while (length) {
    ssize_t n = write(fd, p, length);
    if (n < 0 && errno == EINTR && !stopping) continue;
    if (n <= 0) return -1;
    p += n; length -= n;
  }
  return 0;
}
static int frame(char type, const void *data, uint32_t length) {
  unsigned char header[5]; header[0] = type; pack(header + 1, length);
  if (write_all(STDOUT_FILENO, header, 5)) return -1;
  return length ? write_all(STDOUT_FILENO, data, length) : 0;
}
static void error_frame(const char *message) { frame('E', message, (uint32_t)strlen(message)); }

int main(int argc, char **argv) {
  if (argc < 5) { fprintf(stderr, "usage: pty-host cwd cols rows executable [args...]\n"); return 2; }
  unsigned long cols = strtoul(argv[2], NULL, 10), rows = strtoul(argv[3], NULL, 10);
  if (!cols || cols > 1000 || !rows || rows > 1000) { error_frame("Invalid terminal dimensions"); return 2; }
  signal(SIGPIPE, SIG_IGN);
  signal(SIGTERM, stop); signal(SIGINT, stop); signal(SIGHUP, stop);
  struct winsize size = { .ws_row = (unsigned short)rows, .ws_col = (unsigned short)cols };
  int master;
  pid_t child = forkpty(&master, NULL, NULL, &size);
  if (child < 0) { error_frame(strerror(errno)); return 1; }
  if (child == 0) {
    signal(SIGPIPE, SIG_DFL); signal(SIGTERM, SIG_DFL); signal(SIGINT, SIG_DFL); signal(SIGHUP, SIG_DFL);
    if (chdir(argv[1])) { perror("Working folder"); _exit(126); }
    setenv("TERM", "xterm-256color", 1); setenv("COLORTERM", "truecolor", 1);
    execv(argv[4], &argv[4]);
    perror("Start agent"); _exit(127);
  }
  unsigned char pidbytes[4]; pack(pidbytes, (uint32_t)child);
  frame('S', pidbytes, 4);
  fcntl(master, F_SETFL, fcntl(master, F_GETFL) | O_NONBLOCK);
  unsigned char *input = malloc(LIMIT + 5), *pending = malloc(LIMIT);
  if (!input || !pending) { stopping = 1; error_frame("Out of memory"); }
  size_t used = 0, queued = 0;
  int status = 0, reaped = 0, failed = 0;
  pid_t foreground = -1;
  char foreground_name[256] = "";
  while (!stopping) {
    pid_t current = tcgetpgrp(master);
    char current_name[256] = "";
#ifdef __APPLE__
    if (current > 0) proc_name(current, current_name, sizeof current_name);
#endif
    if (current > 0 && (current != foreground || strcmp(current_name, foreground_name))) {
      foreground = current;
      memcpy(foreground_name, current_name, sizeof foreground_name);
      unsigned char groupbytes[260]; pack(groupbytes, (uint32_t)current);
      size_t name_length = strlen(current_name);
      memcpy(groupbytes + 4, current_name, name_length);
      if (frame('F', groupbytes, (uint32_t)(4 + name_length))) break;
    }
    struct pollfd fds[2] = {{STDIN_FILENO, POLLIN, 0}, {master, POLLIN | (queued ? POLLOUT : 0), 0}};
    int ready = poll(fds, 2, 100);
    if (ready < 0 && errno != EINTR) { failed = 1; break; }
    if (fds[0].revents & (POLLIN | POLLHUP | POLLERR)) {
      ssize_t n = read(STDIN_FILENO, input + used, LIMIT + 5 - used);
      if (n <= 0) break;
      used += (size_t)n;
      while (used >= 5) {
        uint32_t length = unpack(input + 1);
        if (length > LIMIT) { failed = 1; stopping = 1; break; }
        if (used < length + 5u) break;
        unsigned char type = input[0], *data = input + 5;
        if (type == 'I' && length <= LIMIT - queued) { memcpy(pending + queued, data, length); queued += length; }
        else if (type == 'R' && length == 8) {
          uint32_t c = unpack(data), r = unpack(data + 4);
          if (c && c <= 1000 && r && r <= 1000) { size.ws_col = c; size.ws_row = r; ioctl(master, TIOCSWINSZ, &size); }
        } else if (type == 'K' && !length) stopping = 1;
        else { failed = 1; stopping = 1; }
        used -= length + 5u; memmove(input, input + length + 5u, used);
      }
    }
    if ((fds[1].revents & POLLOUT) && queued) {
      ssize_t n = write(master, pending, queued);
      if (n > 0) { queued -= n; memmove(pending, pending + n, queued); }
      else if (n < 0 && errno != EAGAIN && errno != EINTR) break;
    }
    if (fds[1].revents & (POLLIN | POLLHUP | POLLERR)) {
      unsigned char output[16384]; ssize_t n;
      while ((n = read(master, output, sizeof output)) > 0) if (frame('D', output, (uint32_t)n)) { stopping = 1; break; }
      if (n == 0 || (n < 0 && errno == EIO)) { waitpid(child, &status, 0); reaped = 1; break; }
    }
    if (waitpid(child, &status, WNOHANG) == child) {
      unsigned char output[16384]; ssize_t n;
      while ((n = read(master, output, sizeof output)) > 0) if (frame('D', output, (uint32_t)n)) break;
      reaped = 1; break;
    }
  }
  if (failed) error_frame("Invalid terminal input frame");
  // Each forkpty child owns a new session and process group.
  // Interactive shells put each foreground job in a separate process group.
  if (foreground > 0 && foreground != child) kill(-foreground, SIGHUP);
  kill(-child, SIGHUP);
  close(master);
  if (!reaped) {
    for (int i = 0; i < 30; i++) { if (waitpid(child, &status, WNOHANG) == child) { reaped = 1; break; } usleep(10000); }
    if (!reaped) { kill(-child, SIGKILL); kill(child, SIGKILL); waitpid(child, &status, 0); }
  }
  if (foreground > 0 && foreground != child) kill(-foreground, SIGKILL);
  unsigned char exitbytes[4];
  pack(exitbytes, WIFEXITED(status) ? (uint32_t)WEXITSTATUS(status) : (uint32_t)(128 + WTERMSIG(status)));
  frame('X', exitbytes, 4);
  free(input); free(pending);
  return failed ? 1 : 0;
}
