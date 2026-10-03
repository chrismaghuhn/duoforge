#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034
# The chunk scheduler of the fuzz box (tools/cloud/aws_fuzz/README.md), sourced by user_data.sh once the repository is
# checked out, and by the offline tests with stand-ins for the driver and for aws.
#
# A campaign is CHUNKS chunks of CHUNK_BATTLES battles; chunk c plays the seed BASE_SEED + c. Up to PARALLEL chunks are
# computed at the same time (one driver process each: a single driver is bound by the interpreter lock of its Python
# side, so one process cannot keep 64 vCPUs busy), and the upload of a finished chunk runs while the next ones compute.
# A chunk is in the done-manifest only after every file of it is uploaded, so an interruption at any moment loses
# at most the chunks that are not in it, and their partial results are uploaded on the notice.
#
# Expects from the caller: the functions log and fail and run_driver <idx> <seed> <dir> (plays the chunk into <dir>
# and, when it can, writes "<user seconds> <system seconds>" of the whole driver to "<dir>.time"), and the variables
# WORK, S3_BASE (the prefix of this run), CHUNKS, PARALLEL, CHUNK_BATTLES, BASE_SEED and VCPUS, and for the manifest
# RUN_ID, RESUME (yes or no), DF_CAMPAIGN, DF_COMMIT and PARALLEL_CONF (the parallel of the campaign.conf: auto or a
# number).

DF_DEFAULT_CHUNK_BATTLES=2000 # campaign.conf: chunk_battles
# parallel=auto is vCPUs / this (at least 1): one driver gets about 58 battles/s however many workers it has (its Python
# side is bound by the interpreter lock) and keeps about 9 vCPUs busy (pilot 3: 3 x 21 workers on 64 vCPUs gave 55.6 to
# 58.8 battles/s each at 13 to 14% of the vCPUs). The sweep of pilot 4 on 64 vCPUs: 5 drivers 213 battles/s over the phase
# at 56% busy, 7 drivers 239 at 64%, 9 drivers 274 at 70%: still rising, so 7 vCPUs per driver (9 drivers on 64).
DF_VCPUS_PER_DRIVER=7

# --- the campaign.conf: key=value lines (pairings, teams, base_seed and chunks are required)
campaign_conf_load() { # file; sets PAIRINGS TEAMS BASE_SEED CHUNKS CHUNK_BATTLES PARALLEL_CONF SWEEP BENCH
    local key value parallel_set=no
    PAIRINGS=''
    TEAMS=''
    BASE_SEED=''
    CHUNKS=''
    SWEEP=''
    BENCH=0
    CHUNK_BATTLES=$DF_DEFAULT_CHUNK_BATTLES
    PARALLEL_CONF=auto
    while IFS='=' read -r key value; do
        case $key in
            '' | '#'*) ;;
            pairings) PAIRINGS=$value ;;
            teams) TEAMS=$value ;;
            base_seed) BASE_SEED=$value ;;
            chunks) CHUNKS=$value ;;
            chunk_battles) CHUNK_BATTLES=$value ;;
            parallel) PARALLEL_CONF=$value; parallel_set=yes ;;
            sweep) SWEEP=$value ;;
            bench) BENCH=$value ;;
            *) fail "campaign.conf: unknown key '$key'" ;;
        esac
    done < "$1"
    [[ $PAIRINGS =~ ^[A-Za-z0-9_,-]+$ ]] || fail 'campaign.conf: bad pairings'
    [[ $BASE_SEED =~ ^[0-9]{1,12}$ ]] || fail 'campaign.conf: bad base_seed'
    [[ $CHUNKS =~ ^[1-9][0-9]{0,2}$ ]] || fail 'campaign.conf: bad chunks'
    [[ $CHUNK_BATTLES =~ ^[1-9][0-9]{2,4}$ ]] && [ "$CHUNK_BATTLES" -ge 100 ] && [ "$CHUNK_BATTLES" -le 20000 ] ||
        fail 'campaign.conf: chunk_battles must be between 100 and 20000'
    [[ $BENCH =~ ^[01]$ ]] || fail 'campaign.conf: bench must be 0 or 1'
    if [ -n "$SWEEP" ] && [ "$parallel_set" = yes ]; then
        fail 'campaign.conf: sweep and parallel exclude each other'
    fi
}

# parallel=auto or a number -> RESOLVED_PARALLEL
resolve_parallel() { # conf vcpus
    RESOLVED_PARALLEL=$1
    if [ "$RESOLVED_PARALLEL" = auto ]; then
        RESOLVED_PARALLEL=$(($2 / DF_VCPUS_PER_DRIVER))
        [ "$RESOLVED_PARALLEL" -ge 1 ] || RESOLVED_PARALLEL=1
    fi
    [[ $RESOLVED_PARALLEL =~ ^[1-9][0-9]?$ ]] && [ "$RESOLVED_PARALLEL" -le 16 ] ||
        fail 'campaign.conf: parallel must be auto or 1 to 16'
}

# The phases of the campaign: PHASES (the parallel of each, in order), CHUNKS_PER_PHASE, CHUNKS (all of them) and the
# PARALLEL_CONF that the manifest records. Without a sweep there is one phase of `chunks` chunks. With
# `sweep=5,7,9` there is a phase for each value, each of `chunks` chunks (so the campaign has 3 x chunks), playing one
# after the other: the chunks of phase k come after those of phase k-1 in the seed order, so no battle is played twice.
campaign_plan() { # vcpus
    local p seen=' '
    CHUNKS_PER_PHASE=$CHUNKS
    PHASES=()
    if [ -n "$SWEEP" ]; then
        [[ $SWEEP =~ ^[1-9][0-9]?(,[1-9][0-9]?){0,5}$ ]] || fail 'campaign.conf: sweep must be 1 to 6 numbers (1 to 16) separated by commas'
        IFS=, read -r -a PHASES <<< "$SWEEP"
        for p in "${PHASES[@]}"; do
            [ "$p" -le 16 ] || fail "campaign.conf: sweep value $p is above 16"
            case $seen in *" $p "*) fail "campaign.conf: sweep value $p is listed twice" ;; esac
            seen="$seen$p "
            # the steady state of a phase is read from the chunks that started before the last `parallel` ones: at
            # least 3 of them (3 x parallel chunks or more give the drivers three full waves to settle)
            [ "$CHUNKS_PER_PHASE" -ge $((p + 3)) ] ||
                fail "campaign.conf: the sweep phase with parallel $p needs at least $((p + 3)) chunks per phase (3 x $p or more is better)"
        done
        PARALLEL_CONF="sweep=$SWEEP"
    else
        resolve_parallel "$PARALLEL_CONF" "$1"
        PHASES=("$RESOLVED_PARALLEL")
    fi
    CHUNKS=$((CHUNKS_PER_PHASE * ${#PHASES[@]}))
}

# 0 present, 1 absent, anything else is an error
s3_has() { # s3 url
    local rc=0
    aws s3 ls "$1" > /dev/null 2>&1 || rc=$?
    [ "$rc" -le 1 ] || fail "aws s3 ls $1 failed (status $rc)"
    return "$rc"
}

# busy and total CPU ticks of the machine (user, nice, system, irq, softirq of all: user..steal)
cpu_ticks() {
    if [ ! -r /proc/stat ]; then
        echo '0 0'
        return 0
    fi
    awk '/^cpu /{busy = $2 + $3 + $4 + $7 + $8; total = 0; for (i = 2; i <= NF; i++) total += $i; print busy, total}' /proc/stat
}

# --- the manifest of a run: manifest/run.json says which run it is, manifest/done.txt lists its finished chunks.
# A run never reads a manifest of another geometry or commit: a new run needs a prefix without a manifest, a resumed
# run needs the manifest of exactly this run.
manifest_json() {
    printf '{"run_id":"%s","campaign":"%s","commit":"%s","chunk_battles":%s,"base_seed":%s,"chunks":%s,"parallel":"%s"}\n' \
        "$RUN_ID" "$DF_CAMPAIGN" "$DF_COMMIT" "$CHUNK_BATTLES" "$BASE_SEED" "$CHUNKS" "$PARALLEL_CONF"
}

# A done-list is a hard error unless it holds distinct chunk numbers of this campaign: more finished than exist means
# that it belongs to another run.
done_check() { # file
    local n bad dup c
    n=$(grep -c . "$1" || true)
    if [ "$n" -gt "$CHUNKS" ]; then
        fail "the done-manifest lists $n finished chunks but the campaign has only $CHUNKS: it belongs to another run"
    fi
    bad=$(grep -v -E '^[0-9]{4}$' "$1" | grep . || true)
    [ -z "$bad" ] || fail "the done-manifest has a malformed line: $bad"
    dup=$(sort "$1" | uniq -d)
    [ -z "$dup" ] || fail "the done-manifest lists a chunk twice: $dup"
    while read -r c; do
        if [ -n "$c" ] && [ "$((10#$c))" -ge "$CHUNKS" ]; then
            fail "the done-manifest lists chunk $c but the campaign has only $CHUNKS chunks"
        fi
    done < "$1"
}

done_manifest_open() {
    local run_json="$S3_BASE/manifest/run.json" differences
    : > "$WORK/done.txt"
    manifest_json > "$WORK/run.json"
    if [ "$RESUME" = yes ]; then
        s3_has "$run_json" || fail "resume $RUN_ID: there is no such run (no manifest at $run_json)"
        aws s3 cp "$run_json" "$WORK/run-remote.json" --only-show-errors
        differences=$(python3 -c 'import json, sys
a = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
print(", ".join("%s: this launch %r, the run %r" % (k, a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)))' \
            "$WORK/run.json" "$WORK/run-remote.json")
        [ -z "$differences" ] || fail "resume $RUN_ID: the manifest of the run differs from this launch ($differences)"
        if s3_has "$S3_BASE/manifest/done.txt"; then
            aws s3 cp "$S3_BASE/manifest/done.txt" "$WORK/done.txt" --only-show-errors
        fi
        done_check "$WORK/done.txt"
    else
        if s3_has "$run_json" || s3_has "$S3_BASE/manifest/done.txt"; then
            fail "run $RUN_ID already has a manifest: relaunch with --resume $RUN_ID, or start a new launch"
        fi
        aws s3 cp "$WORK/run.json" "$run_json" --only-show-errors
    fi
    log "run $RUN_ID ($([ "$RESUME" = yes ] && echo resumed || echo new)): $(grep -c . "$WORK/done.txt" || true) of $CHUNKS chunks finished"
}

# --- the chunks in flight: computing, or computed and not yet in the done-manifest ("<idx> <dir>" per line)
inflight_add() { # idx dir
    printf '%s %s\n' "$1" "$2" >> "$WORK/inflight"
}

inflight_remove() { # idx
    grep -v "^$1 " "$WORK/inflight" > "$WORK/inflight.tmp" || true
    mv "$WORK/inflight.tmp" "$WORK/inflight"
}

# The partial results of every chunk in flight go to S3 (the spot interruption notice, or an abort): a relaunch resumes.
upload_partial() {
    local idx dir
    [ -f "$WORK/inflight" ] || return 0
    while read -r idx dir; do
        if [ -d "$dir" ]; then
            log "uploading the partial chunk $idx"
            aws s3 sync "$dir" "$S3_BASE/partial/chunk-$idx/" --only-show-errors || true
        fi
    done < "$WORK/inflight"
}

# Takes the partial results of an interrupted run if the same Node made them.
resume_partial() { # idx dir
    local idx=$1 dir=$2 had
    if s3_has "$S3_BASE/partial/chunk-$idx/run.json"; then
        mkdir -p "$dir"
        aws s3 sync "$S3_BASE/partial/chunk-$idx/" "$dir" --only-show-errors
        had=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["node"])' "$dir/run.json")
        if [ "$had" != "$(node --version)" ]; then
            log "partial chunk $idx was made with Node $had, not $(node --version): starting it again"
            rm -rf "$dir"
        else
            log "resuming chunk $idx from its partial results"
        fi
    fi
}

# Every file of a chunk, not the manifest (the scheduler adds the chunk to it when this has succeeded).
upload_chunk() { # idx dir
    local dest="$S3_BASE/chunk-$1" f
    for f in summary.json run.json battles.jsonl timing.json; do
        if [ -f "$2/$f" ]; then aws s3 cp "$2/$f" "$dest/$f" --only-show-errors; fi
    done
    if [ -d "$2/cases" ]; then aws s3 cp "$2/cases" "$dest/cases" --recursive --only-show-errors; fi
}

# One chunk, as a background job: play it, and say how busy it kept the machine (CPU seconds over wall seconds times
# vCPUs: the share of the machine that this chunk used while it ran; the chunks that overlap add up).
chunk_job() { # idx
    local idx=$1 dir="$WORK/out/chunk-$1" seed t0 wall cpu line rate util
    seed=$((BASE_SEED + 10#$idx))
    resume_partial "$idx" "$dir"
    t0=$SECONDS
    log "chunk $idx: seed $seed, $CHUNK_BATTLES battles, started"
    run_driver "$idx" "$seed" "$dir" || fail "chunk $idx: the driver failed"
    wall=$((SECONDS - t0))
    [ "$wall" -ge 1 ] || wall=1
    rate=$(awk -v b="$CHUNK_BATTLES" -v w="$wall" 'BEGIN { printf "%.1f", b / w }')
    if [ -f "$dir.time" ]; then
        read -r line < "$dir.time" || line=''
        cpu=$(awk -v l="$line" 'BEGIN { split(l, p, " "); printf "%.1f", p[1] + p[2] }')
        util=$(awk -v c="$cpu" -v w="$wall" -v v="$VCPUS" 'BEGIN { printf "%.0f", 100 * c / (w * v) }')
        log "chunk $idx: $CHUNK_BATTLES battles in $wall s ($rate battles/s), $cpu CPU-s, $util% of the $VCPUS vCPUs while it ran"
    else
        log "chunk $idx: $CHUNK_BATTLES battles in $wall s ($rate battles/s), no CPU time measured"
    fi
}

# The chunks FIRST to LAST-1 (default: all): PARALLEL computing at a time, uploads in the background, the manifest after
# each upload. When each chunk finished computing and when it started go to completions.txt ("<phase> <idx> <end epoch>
# <start epoch>").
run_chunks() { # [first [last]]
    local first=${1:-0} last=${2:-$CHUNKS} next running=0 uploading=0 idx kind done_pid rc dir
    next=$first
    local -A KIND=() IDX=() STARTED=()
    : > "$WORK/inflight"
    while :; do
        while [ "$running" -lt "$PARALLEL" ] && [ "$next" -lt "$last" ]; do
            idx=$(printf '%04d' "$next")
            next=$((next + 1))
            if grep -qx "$idx" "$WORK/done.txt"; then
                log "chunk $idx is in the done-manifest: skipped"
                continue
            fi
            dir="$WORK/out/chunk-$idx"
            inflight_add "$idx" "$dir"
            chunk_job "$idx" &
            KIND[$!]=compute
            IDX[$!]=$idx
            STARTED[$!]=${EPOCHREALTIME/,/.}
            running=$((running + 1))
        done
        [ $((running + uploading)) -gt 0 ] || break
        rc=0
        wait -n -p done_pid "${!KIND[@]}" || rc=$?
        kind=${KIND[$done_pid]}
        idx=${IDX[$done_pid]}
        unset "KIND[$done_pid]" "IDX[$done_pid]"
        [ "$rc" -eq 0 ] || fail "chunk $idx: the $kind step failed (status $rc)"
        if [ "$kind" = compute ]; then
            running=$((running - 1))
            printf '%s %s %s %s\n' "${PHASE:-0}" "$idx" "${EPOCHREALTIME/,/.}" "${STARTED[$done_pid]}" >> "$WORK/completions.txt"
            upload_chunk "$idx" "$WORK/out/chunk-$idx" &
            KIND[$!]=upload
            IDX[$!]=$idx
            uploading=$((uploading + 1))
        else
            uploading=$((uploading - 1))
            printf '%s\n' "$idx" >> "$WORK/done.txt"
            done_check "$WORK/done.txt"
            aws s3 cp "$WORK/done.txt" "$S3_BASE/manifest/done.txt" --only-show-errors
            inflight_remove "$idx"
            log "chunk $idx uploaded and in the done-manifest"
        fi
    done
}

# What one phase achieved. The overall rate is all its chunks over the whole phase: the ramp-up and the tail (the last
# chunks run with fewer neighbours, and the last wave is often not full) are in it, so it understates what the machine
# does with every driver busy. The steady rate is what it does with all PARALLEL drivers busy: PARALLEL x chunk_battles
# over the median duration of the chunks that started before the last PARALLEL ones (those ran with all their
# neighbours; the median ignores a slow first wave and a stray slow chunk). Drivers that start and finish in waves, which
# they do when the chunks take equally long, make a rate over completion times meaningless (a straight line through
# the steps of a staircase is biased by where the window cuts the waves), a median of durations does not care. The steady
# rate is never reported below the overall rate: with a ramp and a tail it cannot be lower, so a lower figure means a
# phase too short to say, and the overall rate is given instead, marked. It needs at least 3 such chunks.
phase_summary() { # phase parallel t0 busy_percent
    local fields steady overall n m median clamped json_steady
    touch "$WORK/completions.txt"
    fields=$(awk -v ph="$1" -v p="$2" -v t0="$3" -v b="$CHUNK_BATTLES" '
        $1 == ph { n++; s[n] = $4; d[n] = $3 - $4; if ($3 > last) last = $3 }
        END {
            if (n == 0) { print "- 0 0 0 0 no"; exit }
            all = (last > t0 ? b * n / (last - t0) : 0)
            m = n - p
            if (m < 3) { printf "- %.1f %d %d 0 no\n", all, n, m; exit }
            for (i = 1; i <= n; i++) o[i] = i
            for (i = 1; i <= n; i++) for (j = i + 1; j <= n; j++) if (s[o[j]] < s[o[i]]) { x = o[i]; o[i] = o[j]; o[j] = x }
            for (i = 1; i <= m; i++) q[i] = d[o[i]]
            for (i = 1; i <= m; i++) for (j = i + 1; j <= m; j++) if (q[j] < q[i]) { x = q[i]; q[i] = q[j]; q[j] = x }
            med = (m % 2 == 1) ? q[(m + 1) / 2] : (q[m / 2] + q[m / 2 + 1]) / 2
            est = (med > 0 ? p * b / med : 0)
            if (est < all) printf "%.1f %.1f %d %d %.2f yes\n", all, all, n, m, med
            else printf "%.1f %.1f %d %d %.2f no\n", est, all, n, m, med
        }' "$WORK/completions.txt")
    read -r steady overall n m median clamped <<< "$fields"
    if [ "$steady" = - ]; then
        log "phase $1 (parallel $2): no steady state ($n chunks: fewer than 3 started before the last $2); $overall battles/s over the phase; the machine was $4% busy"
        json_steady=null
    else
        log "phase $1 (parallel $2): $steady battles/s steady state ($2 x $CHUNK_BATTLES over the median chunk time of $median s, from $m of $n chunks)$([ "$clamped" = yes ] && echo ', not below the phase rate: the phase is too short to say'), $overall battles/s over the phase; the machine was $4% busy"
        json_steady=$steady
    fi
    printf '{"phase":%s,"parallel":%s,"workers_per_driver":%s,"chunks":%s,"chunk_battles":%s,"steady_battles_per_second":%s,"overall_battles_per_second":%s,"steady_chunks":%s,"median_chunk_seconds":%s,"steady_clamped":%s,"machine_busy_percent":%s}\n' \
        "$1" "$2" "$WORKERS_PER" "$n" "$CHUNK_BATTLES" "$json_steady" "$overall" "$m" "${median:-0}" "$([ "$clamped" = yes ] && echo true || echo false)" "$4" >> "$WORK/sweep.jsonl"
}

# One phase: chunks FIRST to LAST-1 with PARALLEL drivers of VCPUS / PARALLEL workers each.
run_phase() { # phase first last parallel
    local t0 busy0 total0 busy1 total1 util
    PHASE=$1
    PARALLEL=$4
    WORKERS_PER=$((VCPUS / PARALLEL))
    [ "$WORKERS_PER" -ge 1 ] || WORKERS_PER=1
    printf '%s\n' "$PHASE" > "$WORK/phase"
    t0=${EPOCHREALTIME/,/.}
    read -r busy0 total0 <<< "$(cpu_ticks)"
    log "phase $PHASE: chunks $2 to $(($3 - 1)), parallel $PARALLEL, $WORKERS_PER workers per driver, $VCPUS vCPUs"
    run_chunks "$2" "$3"
    read -r busy1 total1 <<< "$(cpu_ticks)"
    util=$(awk -v b="$((busy1 - busy0))" -v t="$((total1 - total0))" 'BEGIN { printf "%.0f", (t > 0 ? 100 * b / t : 0) }')
    phase_summary "$PHASE" "$PARALLEL" "$t0" "$util"
}
