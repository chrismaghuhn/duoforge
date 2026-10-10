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
# scripts share the ticket queue. This script writes "slots" on the second
# line of its owner files and tickets; a job of the old script (a worktree on
# an older branch) writes no such line and keeps the machine to itself: an
# unmarked owner of slot 0 holds every slot, an unmarked ticket lets nobody
# pass it, and while one waits a new job takes only slot 0 (the one the old
# script waits for). A job that already runs in another slot when an old one
# arrives is not stopped: the old job can start beside it once slot 0 is free.
#
# The slot count is recorded in $MACHINE_LOCK.queue/.slots by the first job;
# a job with another DUOFORGE_MACHINE_LOCK_SLOTS is refused while any job
# holds or waits (the record of an idle machine is replaced).
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
# A slot directory without an owner file this long (seconds) was left by a job killed between mkdir and writing
# the owner: it is stale.
MACHINE_LOCK_ORPHAN=300

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

machine_lock_marked() { # file: written by this script (second line "slots ...")
    local mark
    mark=$(sed -n 2p "$1" 2> /dev/null)
    [ "${mark%% *}" = slots ]
}

# Whether slot directory $1 is held, after taking over a stale one; prints the holder's line when held.
machine_lock_held() { # dir
    local dir=$1 line again pid age
    [ -d "$dir" ] || return 1
    line=$(head -n 1 "$dir/owner" 2> /dev/null || true)
    if [ -z "$line" ]; then
        age=$(($(date +%s) - $(stat -c %Y "$dir" 2> /dev/null || date +%s)))
        if [ "$age" -ge "$MACHINE_LOCK_ORPHAN" ] && [ ! -e "$dir/owner" ]; then
            echo "machine lock: removing an ownerless lock ($dir, $((age / 60)) min old)" >&2
            rm -rf "$dir"
            return 1
        fi
        echo "a job that is starting"
        return 0
    fi
    pid=${line%% *}
    if ! machine_lock_alive "$pid"; then
        # Read again right before removing: another waiter may have taken the stale slot over meanwhile, and the
        # directory now belongs to a live holder.
        again=$(head -n 1 "$dir/owner" 2> /dev/null || true)
        if [ "$again" = "$line" ]; then
            echo "machine lock: removing a stale lock ($line)" >&2
            rm -rf "$dir"
            return 1
        fi
        line=${again:-a job that is starting}
    fi
    echo "$line"
}

# True when no slot directory exists and no live ticket waits (other than this shell's).
machine_lock_idle() { # queue
    local t dir me
    me=$(machine_lock_pid)
    for dir in "$MACHINE_LOCK" "$MACHINE_LOCK".slot*; do
        [ -d "$dir" ] && return 1
    done
    for t in "$1"/*; do
        [ -e "$t" ] && [ "${t##*-}" != "$me" ] || continue
        machine_lock_alive "${t##*-}" && return 1
    done
    return 0
}

machine_lock_acquire() { # [--exclusive] label
    # First come, first served: a waiter takes a ticket in $MACHINE_LOCK.queue (its name sorts by the time it was
    # taken). A waiter with w older live tickets ahead may take a slot when more than w slots are free and none of
    # those waiters is exclusive or of the old script; an exclusive waiter needs to be first and every slot free.
    # The head of the queue takes the lowest free slot, a later waiter the highest, so that slot 0 stays for the
    # head. A dead waiter's ticket is removed.
    local exclusive=0
    if [ "${1:-}" = --exclusive ]; then
        exclusive=1
        shift
    fi
    local label=$1 waited=0 holder line me ticket t k dir ahead blocked legacy free slots cpus mark recorded
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
    if [ ! -e "$queue/.slots" ]; then
        (set -o noclobber; echo "$slots" > "$queue/.slots") 2> /dev/null
    fi
    recorded=$(cat "$queue/.slots" 2> /dev/null || true)
    if [ "$recorded" != "$slots" ]; then
        if machine_lock_idle "$queue"; then
            echo "$slots" > "$queue/.slots" # nobody holds or waits: the record is out of date
        else
            echo "machine lock: DUOFORGE_MACHINE_LOCK_SLOTS is $slots here, but the jobs that hold or wait run with" \
                "'$recorded' ($queue/.slots): set the same value in every session" >&2
            return 2
        fi
    fi
    mark=slots
    [ "$exclusive" = 1 ] && mark="slots exclusive"
    ticket="$queue/$(printf '%019d' "$(date +%s%N)")-$me"
    printf '%s\n%s\n' "$me $label since $(date '+%Y-%m-%d %H:%M:%S')" "$mark" > "$ticket"
    while :; do
        for t in "$queue"/*; do
            [ -e "$t" ] && [ "$t" != "$ticket" ] || continue
            machine_lock_alive "${t##*-}" || rm -f "$t"
        done
        free=()
        holder=
        legacy=0
        for ((k = 0; k < slots; k++)); do
            dir=$(machine_lock_slot "$k")
            if line=$(machine_lock_held "$dir"); then
                holder="${holder:+$holder; }$line"
                # An owner of slot 0 without the mark runs the old script: it holds the whole machine.
                if [ "$k" -eq 0 ] && [ -e "$dir/owner" ] && ! machine_lock_marked "$dir/owner"; then
                    legacy=2
                fi
            else
                free+=("$k")
            fi
        done
        ahead=0
        blocked=
        while IFS= read -r t; do
            [ -e "$t" ] && [ "$t" != "$ticket" ] || continue
            local marked=1
            if ! machine_lock_marked "$t"; then
                marked=0
                [ "$legacy" -eq 0 ] && legacy=1 # an old-script waiter, before or after this one
            fi
            [[ "$t" < "$ticket" ]] || continue # behind this ticket: only the mark matters
            [ "$ahead" -eq 0 ] && blocked=$(head -n 1 "$t" 2> /dev/null || true)
            ahead=$((ahead + 1))
            if [ "$marked" = 0 ] || [ "$(sed -n 2p "$t" 2> /dev/null)" = "slots exclusive" ]; then
                ahead=$((ahead + slots)) # nobody passes an exclusive waiter or one of the old script
            fi
        done < <(printf '%s\n' "$queue"/* | sort)
        if [ "$legacy" -eq 2 ]; then
            free=() # the old script's holder runs alone
        elif [ "$legacy" -eq 1 ] && [ "$exclusive" = 0 ]; then
            # An old-script waiter knows only slot 0: a new job takes no other slot, so that the old one never
            # starts beside it.
            if [ "${#free[@]}" -gt 0 ] && [ "${free[0]}" -eq 0 ]; then free=(0); else free=(); fi
        fi
        if [ "$exclusive" = 1 ]; then
            if [ "$ahead" -eq 0 ] && [ "${#free[@]}" -eq "$slots" ]; then
                local got=()
                for k in "${free[@]}"; do
                    dir=$(machine_lock_slot "$k")
                    if mkdir "$dir" 2> /dev/null; then got+=("$dir"); else break; fi
                done
                if [ "${#got[@]}" -eq "$slots" ]; then
                    local since
                    since=$(date '+%Y-%m-%d %H:%M:%S') # one owner line for every slot of the job
                    for dir in "${got[@]}"; do
                        printf '%s\nslots\n' "$me $label since $since" > "$dir/owner"
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
                printf '%s\nslots\n' "$me $label since $(date '+%Y-%m-%d %H:%M:%S')" > "$dir/owner"
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
    # Every slot this shell holds (all of them after --exclusive), up to the configured count and beyond it. The
    # record of the slot count goes when the machine is left idle.
    local me dir holder queue="$MACHINE_LOCK.queue"
    me=$(machine_lock_pid)
    for dir in "$MACHINE_LOCK" "$MACHINE_LOCK".slot*; do
        [ -d "$dir" ] || continue
        holder=$(head -n 1 "$dir/owner" 2> /dev/null || true)
        if [ "${holder%% *}" = "$me" ]; then
            rm -rf "$dir"
        fi
    done
    if [ -d "$queue" ] && machine_lock_idle "$queue"; then
        rm -f "$queue/.slots"
    fi
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
