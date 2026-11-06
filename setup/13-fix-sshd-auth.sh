#!/usr/bin/env bash
# 13-fix-sshd-auth.sh - QNX SDP 8.0 ships OpenSSH 10.4 (needs sshd-auth) but the
# mkqnximage system.build template only includes sshd-session. Add sshd-auth.
set -eu
F=~/qnx800/host/common/mkqnximage/inputs/system.build
[ -f "$F.orig" ] || cp "$F" "$F.orig"
if ! grep -q "sshd-auth" "$F"; then
  sed -i 's#^bin/sshd-session=usr/libexec/sshd-session#&\nbin/sshd-auth=usr/libexec/sshd-auth#' "$F"
  sed -i 's#^SshdSessionPath /system/bin/sshd-session#&\nSshdAuthPath /system/bin/sshd-auth#' "$F"
fi
grep -n -E "sshd-session|sshd-auth" "$F"
