#!/usr/bin/env bash
# shellcheck shell=bash
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

# 0 present, 1 absent, anything else is an error
s3_has() { # s3 url
    local rc=0
    aws s3 ls "$1" > /dev/null 2>&1 || rc=$?
    [ "$rc" -le 1 ] || fail "aws s3 ls $1 failed (status $rc)"
    return "$rc"
}

# busy and total CPU ticks of the machine (user, nice, system, irq, softirq of all: user..steal)
cpu_ticks() {
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

# All the chunks: PARALLEL computing at a time, uploads in the background, the manifest after each upload.
run_chunks() {
    local next=0 running=0 uploading=0 idx kind done_pid rc dir
    local -A KIND=() IDX=()
    : > "$WORK/inflight"
    while :; do
        while [ "$running" -lt "$PARALLEL" ] && [ "$next" -lt "$CHUNKS" ]; do
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
