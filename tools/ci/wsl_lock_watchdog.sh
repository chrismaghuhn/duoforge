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
# If not, it stops the command and every process of its group (TERM, then KILL to whatever of the group still runs
# 5 seconds later), then names the reason on stderr and exits with status 76. It stops the job first: the stderr of a
# killed wsl.exe may be gone, and a write there must not end the watchdog (SIGPIPE is ignored). A TERM, HUP or INT to
# the watchdog itself stops the job the same way (status 76): in its own process group, the job would not get it.
# Otherwise it exits with the command's status. It needs bash 5.1 or later (wait -n -p) and refuses an older one.
#
# usage, under the lock (machine_lock.sh exports the variables and lists them in WSLENV, so they reach WSL):
#   tools/ci/machine_lock.sh <label> wsl.exe -d <distro> -- bash <checkout>/tools/ci/wsl_lock_watchdog.sh <command...>
# Without the variables it refuses (status 2): it has no holder to watch, so it runs nothing.
# It runs inside WSL (Linux) only: anywhere uname -s is not Linux it refuses to start (status 77). Under Git Bash on
# Windows (MSYS, Cygwin) process groups and signals are emulated and do not reach a native Windows program (Git's
# bin/bash.exe launcher, a python.exe) or what it starts, so it could not stop the job (#492's CI, 2026-10-14); a job
# on Windows needs none, it is a Windows child of the lock's holder. Elsewhere (macOS, ...) it is untried.
# For tests: DUOFORGE_WATCHDOG_ALIVE (a command given the pid: status 0 alive, 1 dead; default the tasklist check).
# exit status of a job under the lock (machine_lock.sh, with tools/ci/wsl_lock_watchdog.sh for a WSL job): the
# command's own, or
#   73  machine_lock.sh refused: a live job holds a slot or waits with this label
#   74  machine_lock.sh refused: nested inside a job that holds this lock
#   76  the watchdog stopped the job: its holder's Windows process is gone, or its slot was taken over
#   77  the watchdog refused to start: not on Linux (uname -s), e.g. under Git Bash on Windows
#   78  machine_lock.sh: withdrawn, nothing started (its ticket was deleted while it waited)
#   79  machine_lock.sh refused: DUOFORGE_MACHINE_LOCK_TEST_MV (tests only) is no executable file
#   2   the watchdog refused to start: no holder to watch, or bash older than 5.1
# A command that exits with one of these itself cannot be told from them.
set -u

WATCHDOG_STOPPED=76
WATCHDOG_NOT_HERE=77
interval=${DUOFORGE_WATCHDOG_INTERVAL:-10}
file=${DUOFORGE_MACHINE_LOCK_OWNER_FILE:-}
line=${DUOFORGE_MACHINE_LOCK_OWNER_LINE:-}

if [ $# -lt 1 ]; then
    echo "usage: $0 <command...>" >&2
    exit 2
fi
kernel=$(uname -s 2> /dev/null)
if [ "$kernel" != Linux ]; then
    echo "machine lock watchdog: refused: it runs inside WSL (Linux) only, and this is '${kernel:-an unknown system}';" \
        "under Git Bash on Windows it cannot stop a native Windows process. Start it as" \
        "wsl.exe -d <distro> -- bash .../wsl_lock_watchdog.sh" >&2
    exit "$WATCHDOG_NOT_HERE"
fi
if [ "${BASH_VERSINFO[0]}" -lt 5 ] || { [ "${BASH_VERSINFO[0]}" -eq 5 ] && [ "${BASH_VERSINFO[1]}" -lt 1 ]; }; then
    echo "machine lock watchdog: refused: bash $BASH_VERSION has no 'wait -n -p'; it needs bash 5.1 or later" >&2
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

trap '' PIPE

stop() { # reason: stops the job's whole group, then names the reason, exits 76
    trap '' TERM HUP INT
    kill "$sleeper" 2> /dev/null
    kill -TERM -- "-$job" 2> /dev/null
    for _ in 1 2 3 4 5; do
        kill -0 -- "-$job" 2> /dev/null || break # anything of the group left
        sleep 1
    done
    kill -KILL -- "-$job" 2> /dev/null
    wait "$job" 2> /dev/null
    echo "machine lock watchdog: stopped the job: $1" >&2
    exit "$WATCHDOG_STOPPED"
}

sleeper=''
set -m # the command runs in a process group of its own: stopping it stops its children too
"$@" &
job=$!
set +m
for signal in TERM HUP INT; do
    trap "stop 'the watchdog got SIG$signal'" "$signal"
done

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
        stop "the lock's owner file $file no longer names the holder '$line'"
    elif ! holder_alive "$pid"; then
        stop "the holder's Windows process $pid ('$line') is gone"
    fi
done
