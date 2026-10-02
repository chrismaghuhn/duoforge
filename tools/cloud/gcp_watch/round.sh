#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034
# One round of the watchdog (tools/cloud/gcp_watch/README.md), run by startup.sh from the head of main on every boot,
# and sourced by the offline tests (RD_SOURCE_ONLY=1) with stand-ins for the network, the build and the driver.
#
# A round is: the head of main (given by startup.sh), a rebuild only when it differs from the head that the cached
# build on the disk was made from, then every step campaign of tools/cloud/aws_fuzz/campaigns (and registry-mix) once with
# fresh seeds, a short differential run each, uploaded to gs://<bucket>/watch/<commit12>/<round>/<campaign>/, and then the
# VM powers itself off. A spot preemption ends the round early (the next boot plays a new, complete round: nothing of
# a half round is resumed, and what a campaign had uploaded stays). The hard limit of a boot is the shutdown that
# startup.sh schedules first, and every campaign has its own cap (RD_CAMPAIGN_CAP_MINUTES).
#
# No secret: the bucket comes from the instance metadata, the token of the service account from the metadata server, in
# memory only (never logged, never written).
set -euo pipefail

RD_SHOWDOWN_URL=https://github.com/smogon/pokemon-showdown.git
RD_SHOWDOWN_PIN=b2cb775b0616115b775534eaeff50300e1fc81fc # the pin of .github/workflows/ci.yml (a test compares them)
RD_ROUND_BATTLES=${RD_ROUND_BATTLES:-600}               # battles per campaign and round
RD_CAMPAIGN_CAP_MINUTES=${RD_CAMPAIGN_CAP_MINUTES:-20}  # the hard cap of one campaign
RD_SEED_OFFSET=10000000                                  # keeps the seeds away from the campaigns of the AWS runs
RD_UPLOAD_TRIES=3

RD_WORK=${GW_WORK:-/opt/duoforge-watch}
RD_REPO=${GW_REPO:-$RD_WORK/duoforge}
RD_HEAD=${GW_HEAD:-}
RD_STATE=$RD_WORK/state
RD_BOOT=$(date -u +%Y%m%dT%H%M%SZ)
RD_LOG=${GW_BOOT_LOG:-$RD_WORK/boot.log}
RD_ROUND_ID=r$RD_BOOT
RD_BUCKET=${RD_BUCKET:-}
RD_ROUND_STATUSES=()

rd_log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

fail() { # the name chunks.sh's campaign_conf_load expects
    rd_log "FAILED: $*"
    exit 1
}

# ---------------------------------------------------------------------------------------------- the bucket

rd_metadata() { # key
    curl -fsS -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"
}

# gs://<bucket>/<object> from a local file, with the token of the instance's service account. The token stays in a
# variable of this function. Needs objectUser on the bucket, and nothing else.
rd_gcs_put() { # file object
    local file=$1 object=$2 token enc try
    enc=$(printf '%s' "$object" | sed 's|/|%2F|g')
    for ((try = 1; try <= RD_UPLOAD_TRIES; try++)); do
        if token=$(curl -fsS -H 'Metadata-Flavor: Google' \
            http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token |
            python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])') &&
            curl -fsS -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/octet-stream' \
                --data-binary @"$file" \
                "https://storage.googleapis.com/upload/storage/v1/b/$RD_BUCKET/o?uploadType=media&name=$enc" > /dev/null; then
            return 0
        fi
        sleep $((try * 3))
    done
    rd_log "the upload of $object failed (the round goes on)"
    return 1
}

# ---------------------------------------------------------------------------------------------- what a round plays

# The campaigns of the round, one name per line, in order: every campaigns/<id>/campaign.conf of the checkout except the
# throughput sweeps (they measure the machine, they do not test the engine) and anything with a `sweep` key.
rd_campaigns() { # repo
    local dir name
    for dir in "$1"/tools/cloud/aws_fuzz/campaigns/*/; do
        name=$(basename "$dir")
        [ -f "$dir/campaign.conf" ] || continue
        case $name in throughput-*) continue ;; esac
        grep -q '^sweep=.' "$dir/campaign.conf" && continue
        printf '%s\n' "$name"
    done
}

# A fresh seed per campaign and round: the base seed of the campaign, an offset, and the minutes since the epoch
# (RD_NOW, seconds, only for the tests), so no round replays the seeds of another and none replays an AWS run.
rd_seed() { # base_seed
    local now=${RD_NOW:-$(date +%s)}
    printf '%s' $(($1 + RD_SEED_OFFSET + now / 60))
}

rd_object() { # campaign file: the place of one file of one campaign of this round
    printf 'watch/%s/%s/%s/%s' "${RD_HEAD:0:12}" "$RD_ROUND_ID" "$1" "$2"
}

# ---------------------------------------------------------------------------------------------- state and heartbeat

rd_set_state() { # state [campaign]
    printf '%s %s\n' "$1" "${2:--}" > "$RD_STATE/hb"
}

rd_heartbeat() {
    local state campaign
    read -r state campaign < "$RD_STATE/hb" 2> /dev/null || { state=unknown; campaign=-; }
    printf '{"time":"%s","boot":"%s","round":"%s","head":"%s","state":"%s","campaign":"%s"}\n' \
        "$(date -u +%FT%TZ)" "$RD_BOOT" "$RD_ROUND_ID" "$RD_HEAD" "$state" "$campaign" > "$RD_STATE/heartbeat.json"
    rd_gcs_put "$RD_STATE/heartbeat.json" watch/heartbeat.json || true
}

rd_heartbeat_loop() {
    while sleep 60; do rd_heartbeat; done
}

# ---------------------------------------------------------------------------------------------- the build

# A rebuild is needed only when the head is not the one that the build on the disk was made from.
rd_needs_build() { # head
    [ "$(cat "$RD_STATE/built-head" 2> /dev/null || true)" != "$1" ] || [ ! -x "$(rd_runner)" ]
}

rd_runner() {
    find "$RD_WORK/build" -name duoforge_diff_runner -type f 2> /dev/null | head -n 1
}

rd_ensure_tools() {
    if ! command -v cmake > /dev/null 2>&1 || ! command -v gcc > /dev/null 2>&1 || ! command -v python3 > /dev/null 2>&1; then
        apt-get update -qq
        apt-get install -y -qq build-essential cmake git python3 curl unzip xz-utils ca-certificates time
    fi
    if ! node --version 2> /dev/null | grep -q '^v22\.'; then
        local base=https://nodejs.org/dist/latest-v22.x line file
        curl -fsSL "$base/SHASUMS256.txt" -o /tmp/node-sums
        [ "$(grep -c -E ' node-v22\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz$' /tmp/node-sums)" = 1 ] || fail 'no unique Node 22 tarball'
        line=$(grep -E ' node-v22\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz$' /tmp/node-sums)
        file=${line##* }
        curl -fsSL "$base/$file" -o "/tmp/$file"
        (cd /tmp && grep " $file\$" node-sums | sha256sum -c -)
        tar -xJf "/tmp/$file" -C /usr/local --strip-components=1
    fi
}

rd_build_showdown() {
    local ps=$RD_WORK/pokemon-showdown
    if [ -d "$ps/.git" ] && [ "$(git -C "$ps" rev-parse HEAD 2> /dev/null)" = "$RD_SHOWDOWN_PIN" ] && [ -d "$ps/dist/sim" ]; then
        rd_log 'the pinned Showdown is cached'
        return 0
    fi
    rm -rf "$ps"
    mkdir -p "$ps"
    git -C "$ps" init -q
    git -C "$ps" remote add origin "$RD_SHOWDOWN_URL"
    git -C "$ps" fetch -q --depth 1 origin "$RD_SHOWDOWN_PIN"
    git -C "$ps" checkout -q --detach FETCH_HEAD
    [ "$(git -C "$ps" rev-parse HEAD)" = "$RD_SHOWDOWN_PIN" ] || fail "Showdown is not at $RD_SHOWDOWN_PIN"
    rd_log 'building the pinned Showdown'
    (cd "$ps" && npm ci --ignore-scripts --omit=dev && node build)
}

rd_build_engine() {
    rd_log "building the engine (Release) at ${RD_HEAD:0:12}"
    CC=gcc CXX=g++ cmake -S "$RD_REPO" -B "$RD_WORK/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
        -DDUOFORGE_WARNINGS_AS_ERRORS=ON -DDUOFORGE_ENABLE_IPO=ON > /dev/null
    cmake --build "$RD_WORK/build" --parallel --target duoforge_diff_runner > /dev/null
    [ -x "$(rd_runner)" ] || fail 'the differential runner was not built'
}

# ---------------------------------------------------------------------------------------------- one campaign

# Plays one campaign: RD_ROUND_BATTLES battles of the campaign's pairings and teams under a fresh seed, with a hard cap,
# then uploads summary.json, run.json, the kept cases (cases.tgz, only when there are some) and status.json.
rd_run_campaign() { # name
    local name=$1 dir=$RD_REPO/tools/cloud/aws_fuzz/campaigns/$1 out seed start rc=0 status team
    # shellcheck source=../aws_fuzz/chunks.sh
    . "$RD_REPO/tools/cloud/aws_fuzz/chunks.sh"
    campaign_conf_load "$dir/campaign.conf"
    seed=$(rd_seed "$BASE_SEED")
    out=$RD_WORK/out/$name
    rm -rf "$out"
    mkdir -p "$RD_WORK/out"
    local team_args=() teams=()
    read -r -a teams <<< "$TEAMS"
    for team in "${teams[@]}"; do # an id of the registry, or LETTER=file in the campaign's directory
        if [[ $team =~ ^[A-Z]=([A-Za-z0-9._-]+)$ ]]; then
            [ -f "$dir/${BASH_REMATCH[1]}" ] || fail "campaign.conf of $name: no file ${BASH_REMATCH[1]}"
            team_args+=(--team "${team%%=*}=$dir/${BASH_REMATCH[1]}")
        elif [[ $team =~ ^[A-Za-z0-9_]+$ ]]; then
            team_args+=(--team "$team")
        else
            fail "campaign.conf of $name: bad team '$team'"
        fi
    done
    rd_set_state running "$name"
    rd_log "campaign $name: $RD_ROUND_BATTLES battles, seed $seed, cap $RD_CAMPAIGN_CAP_MINUTES minutes"
    start=$SECONDS
    (cd "$RD_REPO" && timeout "${RD_CAMPAIGN_CAP_SECONDS:-$((RD_CAMPAIGN_CAP_MINUTES * 60))}" python3 tools/reference/diff_driver.py random \
        --checkout "$RD_WORK/pokemon-showdown" --runner "$(rd_runner)" --battles "$RD_ROUND_BATTLES" --seed "$seed" \
        --pairings "$PAIRINGS" "${team_args[@]}" --workers "$(nproc)" --no-lock --out "$out") >> "$RD_LOG" 2>&1 || rc=$?
    status=ok
    [ "$rc" -eq 0 ] || status=failed
    [ "$rc" -ne 124 ] || status=capped
    local buckets='{}'
    if [ -f "$out/summary.json" ]; then
        buckets=$(python3 -c 'import json, sys
d = json.load(open(sys.argv[1]))
print(json.dumps({k: v for k, v in d.get("buckets", {}).items() if v}, sort_keys=True))' "$out/summary.json" 2> /dev/null) || buckets='{}'
        rd_gcs_put "$out/summary.json" "$(rd_object "$name" summary.json)" || true
    fi
    [ ! -f "$out/run.json" ] || rd_gcs_put "$out/run.json" "$(rd_object "$name" run.json)" || true
    if [ -d "$out/cases" ] && [ -n "$(ls -A "$out/cases" 2> /dev/null)" ]; then
        (cd "$out" && tar -czf cases.tgz cases)
        rd_gcs_put "$out/cases.tgz" "$(rd_object "$name" cases.tgz)" || true
    fi
    printf '{"campaign":"%s","seed":%s,"battles":%s,"exit":%s,"status":"%s","seconds":%s,"buckets":%s}\n' \
        "$name" "$seed" "$RD_ROUND_BATTLES" "$rc" "$status" "$((SECONDS - start))" "$buckets" > "$out/status.json"
    rd_gcs_put "$out/status.json" "$(rd_object "$name" status.json)" || true
    RD_ROUND_STATUSES+=("$(cat "$out/status.json")")
    rd_log "campaign $name: $status in $((SECONDS - start)) s, buckets $buckets"
}

# ---------------------------------------------------------------------------------------------- the round

rd_finish() {
    local rc=$?
    rd_log "leaving with status $rc"
    rd_set_state off
    [ -z "${HB_PID:-}" ] || kill "$HB_PID" 2> /dev/null || true
    if [ -n "$RD_BUCKET" ] && [ -n "$RD_HEAD" ]; then
        tail -n 3000 "$RD_LOG" > "$RD_STATE/log-tail.txt" 2> /dev/null || true
        rd_gcs_put "$RD_STATE/log-tail.txt" "watch/${RD_HEAD:0:12}/$RD_ROUND_ID/log.txt" || true
        rd_heartbeat || true
    fi
    [ "${RD_NO_SHUTDOWN:-}" = 1 ] || shutdown -h now
    return 0
}

rd_main() {
    mkdir -p "$RD_STATE" "$RD_WORK/out"
    [[ $RD_HEAD =~ ^[0-9a-f]{40}$ ]] || fail 'no head of main was given (startup.sh does that)'
    RD_BUCKET=${RD_BUCKET:-$(rd_metadata duoforge-bucket)}
    [[ $RD_BUCKET =~ ^[a-z0-9][a-z0-9._-]{2,62}$ ]] || fail 'the instance metadata has no usable duoforge-bucket'
    trap rd_finish EXIT
    trap 'exit 143' TERM INT # a preemption notice: leave through the exit trap (the log goes up, then power off)
    rd_set_state starting
    rd_heartbeat
    rd_heartbeat_loop &
    HB_PID=$!
    rd_log "round $RD_ROUND_ID on ${RD_HEAD:0:12}, $(nproc) cpus, $RD_ROUND_BATTLES battles per campaign"

    rd_ensure_tools
    if rd_needs_build "$RD_HEAD"; then
        rd_set_state building
        rd_build_showdown
        rd_build_engine
        printf '%s\n' "$RD_HEAD" > "$RD_STATE/built-head"
    else
        rd_log "the cached build is of ${RD_HEAD:0:12}: no rebuild"
    fi

    local names=() name
    while IFS= read -r name; do names+=("$name"); done < <(rd_campaigns "$RD_REPO")
    [ "${#names[@]}" -gt 0 ] || fail 'no campaign in this checkout'
    printf '{"round":"%s","boot":"%s","head":"%s","cpus":%s,"campaigns":%s,"battles_per_campaign":%s,"node":"%s","pin":"%s"}\n' \
        "$RD_ROUND_ID" "$RD_BOOT" "$RD_HEAD" "$(nproc)" "${#names[@]}" "$RD_ROUND_BATTLES" "$(node --version)" "$RD_SHOWDOWN_PIN" > "$RD_STATE/meta.json"
    rd_gcs_put "$RD_STATE/meta.json" "watch/${RD_HEAD:0:12}/$RD_ROUND_ID/meta.json" || true
    for name in "${names[@]}"; do
        rd_run_campaign "$name"
    done
    local joined
    joined=$(printf '%s,' "${RD_ROUND_STATUSES[@]}")
    printf '{"round":"%s","head":"%s","campaigns":[%s]}\n' "$RD_ROUND_ID" "$RD_HEAD" "${joined%,}" > "$RD_STATE/round.json"
    rd_gcs_put "$RD_STATE/round.json" "watch/${RD_HEAD:0:12}/$RD_ROUND_ID/round.json" || true
    rd_set_state done
    kill "$HB_PID" 2> /dev/null || true
    rd_log "round $RD_ROUND_ID finished"
}

if [ "${RD_SOURCE_ONLY:-}" != 1 ]; then
    rd_main
fi
