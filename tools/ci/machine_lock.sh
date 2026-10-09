#!/usr/bin/env bash
# One heavy job at a time on this machine: the local CI and benchmark runs of
# every session (main checkout and worktrees) share the CPU, so they take a
# lock first. The lock is a directory in the user's temp folder; its owner
# file names the holder's Windows process, and a lock whose process is gone
# is stale and taken over.
#
# usage (Git Bash):
#   tools/ci/machine_lock.sh <label> <command...>   waits, runs, releases
#   source tools/ci/machine_lock.sh; machine_lock_acquire <label>; ...; machine_lock_release
# environment:
#   DUOFORGE_MACHINE_LOCK  the lock directory (default: $TEMP/duoforge-machine.lock)
set -u

MACHINE_LOCK=${DUOFORGE_MACHINE_LOCK:-"${TEMP:-/tmp}/duoforge-machine.lock"}

# The Windows process id of this shell (Git Bash), or its own pid elsewhere.
machine_lock_pid() {
    if [ -r "/proc/$$/winpid" ]; then cat "/proc/$$/winpid"; else echo "$$"; fi
}

machine_lock_alive() { # pid
    local out
    if command -v tasklist > /dev/null 2>&1; then
        # No path conversion, whatever the caller exported (a wsl.exe command needs MSYS_NO_PATHCONV=1): the
        # switches go to tasklist as written. A tasklist that cannot answer counts as alive: a lock is taken over
        # only when its holder is known to be gone.
        out=$(MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' tasklist /FI "PID eq $1" /NH 2> /dev/null) || return 0
        printf '%s\n' "$out" | grep -q " $1 "
    else
        kill -0 "$1" 2> /dev/null
    fi
}

machine_lock_acquire() { # label
    local label=$1 waited=0 holder pid
    while ! mkdir "$MACHINE_LOCK" 2> /dev/null; do
        holder=$(cat "$MACHINE_LOCK/owner" 2> /dev/null || true)
        pid=${holder%% *}
        if [ -n "$pid" ] && ! machine_lock_alive "$pid"; then
            echo "machine lock: removing a stale lock ($holder)" >&2
            rm -rf "$MACHINE_LOCK"
            continue
        fi
        if [ $((waited % 300)) -eq 0 ]; then
            echo "machine lock: waiting for ${holder:-another job} ($((waited / 60)) min so far)" >&2
        fi
        sleep 15
        waited=$((waited + 15))
    done
    echo "$(machine_lock_pid) $label since $(date '+%Y-%m-%d %H:%M:%S')" > "$MACHINE_LOCK/owner"
}

machine_lock_release() {
    local holder
    holder=$(cat "$MACHINE_LOCK/owner" 2> /dev/null || true)
    if [ "${holder%% *}" = "$(machine_lock_pid)" ]; then
        rm -rf "$MACHINE_LOCK"
    fi
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    if [ $# -lt 2 ]; then
        echo "usage: $0 <label> <command...>" >&2
        exit 2
    fi
    label=$1
    shift
    machine_lock_acquire "$label"
    trap machine_lock_release EXIT
    "$@"
fi
