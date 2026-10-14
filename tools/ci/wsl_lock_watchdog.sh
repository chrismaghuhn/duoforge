#!/usr/bin/env bash
# Runs a command inside WSL for as long as the Windows job that holds its machine lock lives (HauptSession, 2026-10-14).
#
# tools/ci/machine_lock.sh is held by a Git Bash process on Windows; a job it starts in the WSL VM (wsl.exe) is no
# Windows child of it. When that wrapper is killed (by Claude Code under memory pressure, by hand), the lock is released
# or later taken over, while the WSL job runs on unlocked (2026-10-13/14: CTS, Search and D2). This watchdog ends such a
# job: every DUOFORGE_WATCHDOG_INTERVAL seconds (default 10) it checks that
#   - the lock's owner file (DUOFORGE_MACHINE_LOCK_OWNER_FILE) still begins with the holder's line
#     (DUOFORGE_MACHINE_LOCK_OWNER_LINE: "<windows pid> <label> since <time>"), and
#   - the holder's Windows process (the pid of that line) is alive (tasklist.exe through WSL's interop; a tasklist that
#     cannot answer counts as alive, as machine_lock_alive does).
# If not, it stops the command and every process of its group (TERM, then KILL after 5 seconds), names the reason on
# stderr and exits with status 76. Otherwise it exits with the command's status.
#
# usage, under the lock (machine_lock.sh exports the variables and lists them in WSLENV, so they reach WSL):
#   tools/ci/machine_lock.sh <label> wsl.exe -d <distro> -- bash <checkout>/tools/ci/wsl_lock_watchdog.sh <command...>
# Without the variables it refuses (status 2): it has no holder to watch, so it runs nothing.
# For tests: DUOFORGE_WATCHDOG_ALIVE (a command given the pid: status 0 alive, 1 dead; default the tasklist check).
set -u

WATCHDOG_STOPPED=76
interval=${DUOFORGE_WATCHDOG_INTERVAL:-10}
file=${DUOFORGE_MACHINE_LOCK_OWNER_FILE:-}
line=${DUOFORGE_MACHINE_LOCK_OWNER_LINE:-}

if [ $# -lt 1 ]; then
    echo "usage: $0 <command...>" >&2
    exit 2
fi
if [ -z "$file" ] || [ -z "$line" ]; then
    echo "machine lock watchdog: refused: no lock holder to watch (DUOFORGE_MACHINE_LOCK_OWNER_FILE and _LINE are not" \
        "set): run it under tools/ci/machine_lock.sh" >&2
    exit 2
fi
case "$interval" in '' | *[!0-9]* | 0) echo "machine lock watchdog: bad interval '$interval'" >&2; exit 2 ;; esac
pid=${line%% *}
case "$pid" in '' | *[!0-9]*) echo "machine lock watchdog: the owner line '$line' names no pid" >&2; exit 2 ;; esac

holder_alive() { # pid: 0 alive, 1 dead
    if [ -n "${DUOFORGE_WATCHDOG_ALIVE:-}" ]; then
        $DUOFORGE_WATCHDOG_ALIVE "$1"
        return
    fi
    local out
    out=$(tasklist.exe /FI "PID eq $1" /NH 2> /dev/null | tr -d '\r') || return 0 # cannot answer: alive
    [ -n "$out" ] || return 0
    case "$out" in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

holds() { # the owner file still begins with the holder's line
    local first
    first=$(head -n 1 "$file" 2> /dev/null) || return 1
    [ "$first" = "$line" ]
}

set -m # the command runs in a process group of its own: stopping it stops its children too
"$@" &
job=$!
set +m

reason=''
while :; do
    sleep "$interval" &
    sleeper=$!
    finished=''
    wait -n -p finished "$job" "$sleeper" 2> /dev/null
    status=$?
    if [ "$finished" = "$job" ]; then # the command ended: its status
        kill "$sleeper" 2> /dev/null
        exit "$status"
    fi
    if ! holds; then
        reason="the lock's owner file $file no longer names the holder '$line'"
    elif ! holder_alive "$pid"; then
        reason="the holder's Windows process $pid ('$line') is gone"
    fi
    if [ -n "$reason" ]; then
        echo "machine lock watchdog: stopping the job: $reason" >&2
        kill -TERM -- "-$job" 2> /dev/null
        for _ in 1 2 3 4 5; do
            kill -0 "$job" 2> /dev/null || break
            sleep 1
        done
        kill -KILL -- "-$job" 2> /dev/null
        wait "$job" 2> /dev/null
        exit "$WATCHDOG_STOPPED"
    fi
done
