#!/usr/bin/env bash
# A few heavy jobs at a time on this machine: the local CI, build and benchmark
# runs of every session (main checkout and worktrees) share the CPU, so they
# take a slot of the machine lock first. There are DUOFORGE_MACHINE_LOCK_SLOTS
# slots (2 by default); each is a directory in the user's temp folder whose
# owner file names the holder's Windows process, and a slot whose process is
# gone is stale and taken over. The wrapped command is told its share of the
# processors in DUOFORGE_JOBS (processors / slots): build with
# -j"${DUOFORGE_JOBS:-16}" and run tests with -j"${DUOFORGE_JOBS:-16}".
# A measurement takes every slot (--exclusive): it runs alone.
#
# Slot 0 is the lock directory of the one-slot script before 2026-10-10
# ($MACHINE_LOCK), slot k the directory $MACHINE_LOCK.slot<k>, and both
# scripts share the ticket queue: a holder or waiter of the old script (a
# worktree on an older branch) still counts, as a job in slot 0.
#
# usage (Git Bash):
#   tools/ci/machine_lock.sh [--exclusive] <label> <command...>   waits, runs, releases
#   source tools/ci/machine_lock.sh; machine_lock_acquire [--exclusive] <label> || exit; ...; machine_lock_release
# environment:
#   DUOFORGE_MACHINE_LOCK        slot 0, the lock directory (default: $TEMP/duoforge-machine.lock)
#   DUOFORGE_MACHINE_LOCK_SLOTS  jobs at once (default 2); the same in every session
# exported to the holder:
#   DUOFORGE_JOBS                processors / slots (at least 1); every processor with --exclusive
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

machine_lock_slot() { # k: the directory of slot k
    if [ "$1" -eq 0 ]; then echo "$MACHINE_LOCK"; else echo "$MACHINE_LOCK.slot$1"; fi
}

machine_lock_acquire() { # [--exclusive] label
    # First come, first served: a waiter takes a ticket in $MACHINE_LOCK.queue (its name sorts by the time it was
    # taken; an exclusive waiter's ticket says so on its second line). A waiter with w older live tickets ahead may
    # take a slot when more than w slots are free and none of those waiters is exclusive; an exclusive waiter needs
    # to be first and every slot free. The head of the queue takes the lowest free slot, a later waiter the highest,
    # so that slot 0 stays for the head (the old script knows only slot 0). A dead waiter's ticket is removed.
    local exclusive=0
    if [ "${1:-}" = --exclusive ]; then
        exclusive=1
        shift
    fi
    local label=$1 waited=0 holder pid me ticket t k dir ahead blocked free slots cpus
    local queue="$MACHINE_LOCK.queue"
    slots=${DUOFORGE_MACHINE_LOCK_SLOTS-2}
    case "$slots" in
    '' | *[!0-9]* | 0*)
        echo "machine lock: DUOFORGE_MACHINE_LOCK_SLOTS must be a positive number, not '$slots'" >&2
        return 2
        ;;
    esac
    cpus=${NUMBER_OF_PROCESSORS:-$(nproc 2> /dev/null || true)}
    case "$cpus" in
    '' | *[!0-9]* | 0*)
        echo "machine lock: cannot tell the number of processors (NUMBER_OF_PROCESSORS, nproc): '$cpus'" >&2
        return 2
        ;;
    esac
    me=$(machine_lock_pid)
    mkdir -p "$queue"
    ticket="$queue/$(printf '%019d' "$(date +%s%N)")-$me"
    if [ "$exclusive" = 1 ]; then
        printf '%s\nexclusive\n' "$me $label since $(date '+%Y-%m-%d %H:%M:%S')" > "$ticket"
    else
        echo "$me $label since $(date '+%Y-%m-%d %H:%M:%S')" > "$ticket"
    fi
    while :; do
        for t in "$queue"/*; do
            [ -e "$t" ] && [ "$t" != "$ticket" ] || continue
            machine_lock_alive "${t##*-}" || rm -f "$t"
        done
        free=()
        holder=
        for ((k = 0; k < slots; k++)); do
            dir=$(machine_lock_slot "$k")
            if [ -d "$dir" ]; then
                t=$(cat "$dir/owner" 2> /dev/null || true)
                pid=${t%% *}
                if [ -n "$pid" ] && ! machine_lock_alive "$pid"; then
                    echo "machine lock: removing a stale lock ($t)" >&2
                    rm -rf "$dir"
                    free+=("$k")
                else
                    holder="${holder:+$holder; }${t:-a job that is starting}"
                fi
            else
                free+=("$k")
            fi
        done
        ahead=0
        blocked=
        while IFS= read -r t; do
            [ "$t" = "$ticket" ] && break
            [ -e "$t" ] || continue
            [ "$ahead" -eq 0 ] && blocked=$(head -n 1 "$t" 2> /dev/null || true)
            ahead=$((ahead + 1))
            if [ "$(sed -n 2p "$t" 2> /dev/null)" = exclusive ]; then
                ahead=$slots # nobody passes an exclusive waiter
            fi
        done < <(printf '%s\n' "$queue"/* | sort)
        if [ "$exclusive" = 1 ]; then
            if [ "$ahead" -eq 0 ] && [ "${#free[@]}" -eq "$slots" ]; then
                local got=()
                for k in "${free[@]}"; do
                    dir=$(machine_lock_slot "$k")
                    if mkdir "$dir" 2> /dev/null; then got+=("$dir"); else break; fi
                done
                if [ "${#got[@]}" -eq "$slots" ]; then
                    for dir in "${got[@]}"; do
                        echo "$me $label since $(date '+%Y-%m-%d %H:%M:%S')" > "$dir/owner"
                    done
                    export DUOFORGE_JOBS=$cpus
                    break
                fi
                for dir in "${got[@]}"; do rmdir "$dir" 2> /dev/null; done # somebody was faster: all or nothing
            fi
        elif [ "$ahead" -lt "${#free[@]}" ]; then
            local order=("${free[@]}") i
            if [ "$ahead" -gt 0 ]; then
                order=()
                for ((i = ${#free[@]} - 1; i >= 0; i--)); do order+=("${free[i]}"); done
            fi
            dir=
            for k in "${order[@]}"; do
                if mkdir "$(machine_lock_slot "$k")" 2> /dev/null; then
                    dir=$(machine_lock_slot "$k")
                    break
                fi
            done
            if [ -n "$dir" ]; then
                echo "$me $label since $(date '+%Y-%m-%d %H:%M:%S')" > "$dir/owner"
                export DUOFORGE_JOBS=$((cpus / slots > 0 ? cpus / slots : 1))
                break
            fi
        fi
        if [ "${#free[@]}" -gt 0 ] && [ -n "$blocked" ]; then
            holder=$blocked # a slot is free: an older waiter goes first
        fi
        if [ $((waited % 300)) -eq 0 ]; then
            echo "machine lock: waiting for ${holder:-another job} ($((waited / 60)) min so far)" >&2
        fi
        sleep 15
        waited=$((waited + 15))
    done
    rm -f "$ticket"
}

machine_lock_release() {
    # Every slot this shell holds (all of them after --exclusive), up to the configured count and beyond it.
    local me dir holder
    me=$(machine_lock_pid)
    for dir in "$MACHINE_LOCK" "$MACHINE_LOCK".slot*; do
        [ -d "$dir" ] || continue
        holder=$(cat "$dir/owner" 2> /dev/null || true)
        if [ "${holder%% *}" = "$me" ]; then
            rm -rf "$dir"
        fi
    done
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    exclusive=()
    if [ "${1:-}" = --exclusive ]; then
        exclusive=(--exclusive)
        shift
    fi
    if [ $# -lt 2 ]; then
        echo "usage: $0 [--exclusive] <label> <command...>" >&2
        exit 2
    fi
    label=$1
    shift
    machine_lock_acquire "${exclusive[@]}" "$label" || exit $?
    trap machine_lock_release EXIT
    "$@"
fi
