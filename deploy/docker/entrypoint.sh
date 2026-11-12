#!/bin/sh
# Container entrypoint. Persistent volumes (Render disks, Docker volumes) are
# mounted root-owned, and the app runs as the unprivileged `openjarvis` user,
# so it could not create/chmod its home there (PermissionError on startup).
# When started as root: make the OpenJarvis home writable by `openjarvis`,
# then drop privileges and run the command. When started as a non-root user
# (e.g. `docker run --user`), just run the command.
set -e
OJ_HOME="${OPENJARVIS_HOME:-/home/openjarvis/.openjarvis}"
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$OJ_HOME"
    chown -R openjarvis:openjarvis "$OJ_HOME" 2>/dev/null || chown openjarvis:openjarvis "$OJ_HOME"
    exec runuser -u openjarvis -- "$@"
fi
exec "$@"
