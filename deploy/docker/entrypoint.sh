#!/bin/sh
# Container entrypoint.
# 1. Persistent volumes (Render disks, Docker volumes) are mounted root-owned
#    while the app runs as the unprivileged `openjarvis` user; when started as
#    root, make $OPENJARVIS_HOME writable by `openjarvis`, then drop privileges.
# 2. Seed config.toml and the persona files from deploy/render/ when they are
#    missing (first boot on an empty disk). Set OPENJARVIS_RESEED=1 to overwrite
#    them from the image on the next start (e.g. after editing them in git).
set -e
OJ_HOME="${OPENJARVIS_HOME:-/home/openjarvis/.openjarvis}"
SEED_DIR="${OPENJARVIS_SEED_DIR:-/app/deploy/render}"

seed() {  # seed <src> <dst>
    if [ -f "$1" ] && { [ ! -f "$2" ] || [ "${OPENJARVIS_RESEED:-0}" = "1" ]; }; then
        mkdir -p "$(dirname "$2")"
        cp "$1" "$2"
        echo "entrypoint: seeded $2"
    fi
}

mkdir -p "$OJ_HOME"
seed "$SEED_DIR/config.toml" "$OJ_HOME/config.toml"
if [ -d "$SEED_DIR/personas" ]; then
    for f in $(cd "$SEED_DIR/personas" && find . -type f); do
        seed "$SEED_DIR/personas/$f" "$OJ_HOME/personas/$f"
    done
fi

# Render "Secret Files" (and any other secrets mount) override the repo copies
# on every start, so private persona text never has to live in git.
SECRETS_DIR="${OPENJARVIS_SECRETS_DIR:-/etc/secrets}"
if [ -d "$SECRETS_DIR" ]; then
    [ -f "$SECRETS_DIR/config.toml" ] && cp "$SECRETS_DIR/config.toml" "$OJ_HOME/config.toml" && echo "entrypoint: config.toml from secrets"
    for n in SOUL MEMORY USER; do
        if [ -f "$SECRETS_DIR/$n.md" ]; then
            mkdir -p "$OJ_HOME/personas/stonepoint"
            cp "$SECRETS_DIR/$n.md" "$OJ_HOME/personas/stonepoint/$n.md"
            echo "entrypoint: $n.md from secrets"
        fi
    done
fi

if [ "$(id -u)" = "0" ]; then
    chown -R openjarvis:openjarvis "$OJ_HOME" 2>/dev/null || chown openjarvis:openjarvis "$OJ_HOME"
    exec runuser -u openjarvis -- "$@"
fi
exec "$@"
