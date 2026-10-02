#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge fuzz watchdog: at most @MAX_MINUTES@ minutes"
# The user data of a fuzz box (tools/cloud/aws_fuzz/README.md), rendered by launch.sh and check.sh, which fill the four
# @...@ placeholders with values they have validated. The first command above is the watchdog: whatever happens below,
# the box is gone after @MAX_MINUTES@ minutes (the instance-initiated shutdown behaviour is terminate).
#
# What it does, as the hosted linux-full job does it (.github/workflows/ci.yml): the packages, Node 22, the public
# repository at the exact commit, the pinned Pokemon Showdown (npm ci, node build), the engine in Release and the
# differential runner. With bench=1 in the campaign.conf it then measures the raw speed of the engine (bench_run.py:
# the native batch benchmark on all vCPUs, bench.json to S3). Then it plays the chunks of the campaign
# (campaigns/<id>/campaign.conf at that commit), as chunks.sh schedules them: a chunk is the random mode over
# chunk_battles battles of one seed (base seed + chunk index), several chunks are computed at the same time and the
# upload of a finished one runs while the others compute; a done-manifest in S3, written after the upload, lets a
# relaunch skip what is finished. A spot interruption notice uploads every chunk in flight; a rate under twice the
# local rate in the first ten minutes aborts the campaign. At the end, or on any error, the box powers itself off.
# There is no secret on the box: S3 is reached with the instance profile.
set -euo pipefail

DF_CAMPAIGN='@CAMPAIGN@'
DF_COMMIT='@COMMIT@'
DF_BUCKET='@BUCKET@'
DF_RUN_ID='@RUN_ID@'
DF_RESUME=@RESUME@ # yes: continue the run DF_RUN_ID (its manifest must be exactly this campaign's); no: a new run
DF_MAX_MINUTES=@MAX_MINUTES@
DF_REGION=eu-central-1
DF_REPO_URL=https://github.com/chrismaghuhn/duoforge.git
DF_SHOWDOWN_URL=https://github.com/smogon/pokemon-showdown.git
DF_SHOWDOWN_PIN=b2cb775b0616115b775534eaeff50300e1fc81fc
DF_DEFAULT_CHUNK_BATTLES=2000 # campaign.conf: chunk_battles
DF_VCPUS_PER_DRIVER=20       # campaign.conf: parallel=auto is vCPUs / this (at least 1)
DF_LOCAL_RATE=24 # battles per second on the development machine
DF_MIN_FACTOR=2  # the rate of the first ten minutes must be this many times the local one
DF_RATE_WINDOW=600

export AWS_DEFAULT_REGION=$DF_REGION AWS_REGION=$DF_REGION
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a HOME=/root
WORK=/opt/duoforge-fuzz
LOG=/var/log/duoforge-fuzz.log
S3_BASE="s3://$DF_BUCKET/fuzz/$DF_CAMPAIGN/$DF_RUN_ID"
BOOT=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$WORK"
: > "$LOG"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

upload_log() {
    if command -v aws > /dev/null 2>&1; then
        aws s3 cp "$LOG" "$S3_BASE/log/$BOOT.log" --only-show-errors || true
    fi
}

finish() {
    local rc=$?
    log "leaving with status $rc"
    if [ "$rc" -ne 0 ] && declare -F upload_partial > /dev/null; then upload_partial; fi
    upload_log
    shutdown -h now
}
trap finish EXIT
trap 'exit 143' TERM INT # the abort of the monitor: leave through the exit trap (upload, power off)

fail() {
    log "FAILED: $*"
    exit 1
}

# --- the packages, Node 22, the AWS CLI
log "box up: campaign $DF_CAMPAIGN, commit $DF_COMMIT, at most $DF_MAX_MINUTES minutes, $(nproc) cpus"
apt-get update -qq
apt-get install -y -qq build-essential cmake git python3 curl unzip xz-utils ca-certificates time
curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip
unzip -q /tmp/awscli.zip -d /tmp
/tmp/aws/install > /dev/null
aws --version

NODE_BASE=https://nodejs.org/dist/latest-v22.x
curl -fsSL "$NODE_BASE/SHASUMS256.txt" -o /tmp/node-sums
[ "$(grep -c -E ' node-v22\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz$' /tmp/node-sums)" = 1 ] || fail 'no unique Node 22 tarball in SHASUMS256.txt'
NODE_LINE=$(grep -E ' node-v22\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz$' /tmp/node-sums)
NODE_FILE=${NODE_LINE##* }
curl -fsSL "$NODE_BASE/$NODE_FILE" -o "/tmp/$NODE_FILE"
(cd /tmp && grep " $NODE_FILE\$" node-sums | sha256sum -c -)
tar -xJf "/tmp/$NODE_FILE" -C /usr/local --strip-components=1
node --version

# --- the sources at the exact commits
fetch_commit() { # directory url sha
    mkdir -p "$1"
    git -C "$1" init -q
    git -C "$1" remote add origin "$2"
    git -C "$1" fetch -q --depth 1 origin "$3"
    git -C "$1" checkout -q --detach FETCH_HEAD
    [ "$(git -C "$1" rev-parse HEAD)" = "$3" ] || fail "$2 is not at $3"
}
REPO="$WORK/duoforge"
PS="$WORK/pokemon-showdown"
fetch_commit "$REPO" "$DF_REPO_URL" "$DF_COMMIT"
fetch_commit "$PS" "$DF_SHOWDOWN_URL" "$DF_SHOWDOWN_PIN"

log 'building the pinned Showdown'
(cd "$PS" && npm ci --ignore-scripts --omit=dev && node build)

log 'building the engine (Release) and the differential runner'
CC=gcc CXX=g++ cmake -S "$REPO" -B "$REPO/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
    -DDUOFORGE_WARNINGS_AS_ERRORS=ON -DDUOFORGE_ENABLE_IPO=ON > /dev/null
cmake --build "$REPO/build" --parallel --target duoforge_diff_runner > /dev/null
RUNNER=$(find "$REPO/build" -name duoforge_diff_runner -type f | head -n 1)
[ -x "$RUNNER" ] || fail 'the differential runner was not built'

# --- the campaign: tools/cloud/aws_fuzz/campaigns/<id>/campaign.conf, key=value lines
CAMP_DIR="$REPO/tools/cloud/aws_fuzz/campaigns/$DF_CAMPAIGN"
[ -f "$CAMP_DIR/campaign.conf" ] || fail "no campaign.conf for $DF_CAMPAIGN at $DF_COMMIT"
PAIRINGS=''
TEAMS=''
BASE_SEED=''
CHUNKS=''
CHUNK_BATTLES=$DF_DEFAULT_CHUNK_BATTLES
PARALLEL=auto
BENCH=0
while IFS='=' read -r key value; do
    case $key in
        '' | '#'*) ;;
        pairings) PAIRINGS=$value ;;
        teams) TEAMS=$value ;;
        base_seed) BASE_SEED=$value ;;
        chunks) CHUNKS=$value ;;
        chunk_battles) CHUNK_BATTLES=$value ;;
        parallel) PARALLEL=$value ;;
        bench) BENCH=$value ;;
        *) fail "campaign.conf: unknown key '$key'" ;;
    esac
done < "$CAMP_DIR/campaign.conf"
[[ $PAIRINGS =~ ^[A-Za-z0-9,-]+$ ]] || fail 'campaign.conf: bad pairings'
[[ $BASE_SEED =~ ^[0-9]{1,12}$ ]] || fail 'campaign.conf: bad base_seed'
[[ $CHUNKS =~ ^[0-9]{1,3}$ ]] || fail 'campaign.conf: bad chunks'
[[ $CHUNK_BATTLES =~ ^[0-9]{3,5}$ ]] && [ "$CHUNK_BATTLES" -ge 100 ] && [ "$CHUNK_BATTLES" -le 20000 ] ||
    fail 'campaign.conf: chunk_battles must be between 100 and 20000'
[[ $BENCH =~ ^[01]$ ]] || fail 'campaign.conf: bench must be 0 or 1'
VCPUS=$(nproc)
PARALLEL_CONF=$PARALLEL
case $DF_RUN_ID in
    "${DF_COMMIT:0:12}-$CHUNK_BATTLES-$BASE_SEED-"*) ;;
    *) fail "the run id $DF_RUN_ID is not of this commit, chunk_battles $CHUNK_BATTLES and base_seed $BASE_SEED" ;;
esac
RUN_ID=$DF_RUN_ID
RESUME=$DF_RESUME
if [ "$PARALLEL" = auto ]; then
    PARALLEL=$((VCPUS / DF_VCPUS_PER_DRIVER))
    [ "$PARALLEL" -ge 1 ] || PARALLEL=1
fi
[[ $PARALLEL =~ ^[0-9]{1,2}$ ]] && [ "$PARALLEL" -ge 1 ] && [ "$PARALLEL" -le 16 ] || fail 'campaign.conf: parallel must be auto or 1 to 16'
TEAM_ARGS=()
read -r -a TEAM_LIST <<< "$TEAMS"
for team in "${TEAM_LIST[@]}"; do # an id of the registry, or LETTER=file in the campaign's directory
    if [[ $team =~ ^[A-Z]=([A-Za-z0-9._-]+)$ ]]; then
        [ -f "$CAMP_DIR/${BASH_REMATCH[1]}" ] || fail "campaign.conf: no file ${BASH_REMATCH[1]}"
        TEAM_ARGS+=(--team "${team%%=*}=$CAMP_DIR/${BASH_REMATCH[1]}")
    elif [[ $team =~ ^[A-Za-z0-9_]+$ ]]; then
        TEAM_ARGS+=(--team "$team")
    else
        fail "campaign.conf: bad team '$team'"
    fi
done
WORKERS_PER=$((VCPUS / PARALLEL))
[ "$WORKERS_PER" -ge 1 ] || WORKERS_PER=1

# --- the scheduler of the chunks, the done-manifest (one finished chunk index per line)
run_driver() { # idx seed dir: the random mode over one chunk, timed (user and system seconds of all it ran in "$dir.time")
    mkdir -p "$WORK/out"
    (cd "$REPO" && /usr/bin/time -f '%U %S' -o "$3.time" python3 tools/reference/diff_driver.py random \
        --checkout "$PS" --runner "$RUNNER" --battles "$CHUNK_BATTLES" --seed "$2" --pairings "$PAIRINGS" \
        "${TEAM_ARGS[@]}" --workers "$WORKERS_PER" --no-lock --out "$3") >> "$LOG" 2>&1
}
# shellcheck source=chunks.sh
. "$REPO/tools/cloud/aws_fuzz/chunks.sh"
done_manifest_open
log "$CHUNKS chunks of $CHUNK_BATTLES battles, $PARALLEL at a time, $WORKERS_PER workers each, $VCPUS vCPUs"

# --- the monitors: battles per minute (and the abort), the spot interruption notice
count_done() { find "$WORK/out" -path '*/partial/*.json' -newer "$WORK/fuzz-started" 2> /dev/null | wc -l || true; }

MAIN_PID=$$
monitor() {
    local start=$SECONDS last=0 total elapsed rate judged=no busy_now total_now busy_before total_before util
    read -r busy_before total_before <<< "$(cpu_ticks)"
    while sleep 60; do
        total=$(count_done)
        elapsed=$((SECONDS - start))
        rate=$(awk -v a="$total" -v s="$elapsed" 'BEGIN { printf "%.1f", (s > 0 ? a / s : 0) }')
        read -r busy_now total_now <<< "$(cpu_ticks)"
        util=$(awk -v b="$((busy_now - busy_before))" -v t="$((total_now - total_before))" 'BEGIN { printf "%.0f", (t > 0 ? 100 * b / t : 0) }')
        busy_before=$busy_now
        total_before=$total_now
        log "rate: $total battles in $elapsed s, $((total - last)) in the last minute, $rate battles/s overall; the machine was $util% busy"
        last=$total
        if [ "$judged" = no ] && [ "$elapsed" -ge "$DF_RATE_WINDOW" ]; then
            judged=yes
            if awk -v r="$rate" -v m=$((DF_LOCAL_RATE * DF_MIN_FACTOR)) 'BEGIN { exit !(r < m) }'; then
                log "ABORT: $rate battles/s in the first $DF_RATE_WINDOW s is under $DF_MIN_FACTOR x the local $DF_LOCAL_RATE"
                touch "$WORK/abort"
                kill -TERM "$MAIN_PID"
                return 0
            fi
        fi
    done
}

poll_interruption() {
    local token code
    token=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600') || {
        log 'no IMDSv2 token: the interruption notice is not polled'
        return 0
    }
    while sleep 5; do
        code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-aws-ec2-metadata-token: $token" \
            http://169.254.169.254/latest/meta-data/spot/instance-action || true)
        if [ "$code" = 200 ]; then
            log 'spot interruption notice: uploading the chunks in flight'
            upload_partial
            upload_log
            return 0
        fi
    done
}

# --- the raw speed of the engine (bench=1): before the campaign, on an idle machine
instance_type() {
    local token
    token=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 600') || return 0
    curl -fsS -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/instance-type || true
}
# A benchmark that fails is a result (bench.json says why), never the end of the campaign.
bench_error() { # text
    printf '{"campaign":"%s","commit":"%s","error":"%s"}\n' "$DF_CAMPAIGN" "$DF_COMMIT" "$1" > "$WORK/bench.json"
}
if [ "$BENCH" = 1 ]; then
    log 'bench=1: building duoforge_bench'
    BENCH_EXE=''
    if cmake --build "$REPO/build" --parallel --target duoforge_bench > /dev/null 2>> "$LOG"; then
        BENCH_EXE=$(find "$REPO/build" -name duoforge_bench -type f | head -n 1)
    fi
    if [ -z "$BENCH_EXE" ] || [ ! -x "$BENCH_EXE" ]; then
        log 'duoforge_bench was not built'
        bench_error 'duoforge_bench was not built'
    elif ! python3 "$REPO/tools/cloud/aws_fuzz/bench_run.py" --bench "$BENCH_EXE" --vcpus "$VCPUS" --seconds 30 \
        --instance-type "$(instance_type)" --campaign "$DF_CAMPAIGN" --commit "$DF_COMMIT" --out "$WORK/bench.json" >> "$LOG" 2>&1; then
        log 'the benchmark failed; bench.json says why'
        [ -f "$WORK/bench.json" ] || bench_error 'bench_run.py failed before it wrote a result'
    fi
    aws s3 cp "$WORK/bench.json" "$S3_BASE/bench.json" --only-show-errors || log 'the upload of bench.json failed'
    log "bench.json: $(python3 -c 'import json, sys
d = json.load(open(sys.argv[1]))
print("ERROR: " + d["error"] if "error" in d else "%s games/s on %s threads" % (d["games_per_second"], d["threads"]))' "$WORK/bench.json" || echo unreadable)"
fi

printf '{"campaign":"%s","commit":"%s","boot":"%s","cpus":%s,"parallel":%s,"workers_per_driver":%s,"chunk_battles":%s,"node":"%s","pin":"%s"}\n' \
    "$DF_CAMPAIGN" "$DF_COMMIT" "$BOOT" "$VCPUS" "$PARALLEL" "$WORKERS_PER" "$CHUNK_BATTLES" "$(node --version)" "$DF_SHOWDOWN_PIN" > "$WORK/meta.json"
aws s3 cp "$WORK/meta.json" "$S3_BASE/meta-$BOOT.json" --only-show-errors

mkdir -p "$WORK/out"
touch "$WORK/fuzz-started"
monitor &
MON_PID=$!
poll_interruption &
POLL_PID=$!

run_chunks

kill "$MON_PID" "$POLL_PID" 2> /dev/null || true
TOTAL=$(count_done)
SPENT=$((SECONDS))
log "campaign $DF_CAMPAIGN finished: $TOTAL battles this boot in $SPENT s ($(awk -v a="$TOTAL" -v s="$SPENT" 'BEGIN { printf "%.1f", (s > 0 ? a / s : 0) }') battles/s including the build)"
exit 0
