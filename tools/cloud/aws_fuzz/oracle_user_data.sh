#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge oracle watchdog: at most @MAX_MINUTES@ minutes"
# The user data of a preview-oracle box (#458; tools/cloud/aws_fuzz/README.md, "Preview-oracle campaigns"), rendered by
# launch_oracle.sh, which fills the @...@ placeholders with values it has validated. The first command above is the
# watchdog: whatever happens below, the box is gone after @MAX_MINUTES@ minutes (shutdown behaviour terminate).
#
# One predeclared series of `python -m duoforge_search.preview_series`, as campaigns/<id>/campaign.conf at the exact
# commit names it (oracle_conf.py builds the command line); the box pins as the ladder box does (ladder_user_data.sh):
# the library at the commit (Release, duoforge_shared), Python from ladder_requirements.txt, XLA's AVX2, OpenBLAS's
# Haswell kernel on one thread; 3 processes of 16 CPUs each (preview_series pins them itself, process i on CPUs 16i to
# 16i+15), 16 CPUs left to the box. nets/ and teams/ of the bucket must be read-only for the box (probes), every
# network and the foe team are checked by sha256, our team against data/teams/index.json.
#
# The foe team (teams/<sha256>.txt) is private: it is never printed, logged or uploaded. Only the aggregates leave the
# box: series.json, equality.json, matrix/*.json, runs/*/{conditions,oracle}.json, runs/*/arms/*.json, log tails,
# env.json, status.json and the box log. No decision file, no network, no team file.
# Every refusal is named in status.json; a failure without one is failed_in_<step>, a TERM or INT is "terminated". Then
# the box powers itself off. There is no secret on the box: S3 is reached with the instance profile.
set -euo pipefail

DF_CAMPAIGN='@CAMPAIGN@'
DF_COMMIT='@COMMIT@'
DF_BUCKET='@BUCKET@'
DF_RUN_ID='@RUN_ID@'
DF_MAX_MINUTES=@MAX_MINUTES@
DF_RESUME='@RESUME@' # yes: continue the series of DF_RUN_ID from its saved state (launch_oracle.sh --resume); no: a new one
DF_REGION=eu-central-1
DF_REPO_URL=https://github.com/chrismaghuhn/duoforge.git
DF_PROCESSES=3 # preview_series --parallel
DF_CPUS=16 # CPUs per process, the local machine's logical CPUs
DF_SPARE=16 # CPUs left to the box beside the processes

export AWS_DEFAULT_REGION=$DF_REGION AWS_REGION=$DF_REGION
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a HOME=/root
WORK=/opt/duoforge-oracle
LOG=/var/log/duoforge-oracle.log
S3_BASE="s3://$DF_BUCKET/fuzz/oracle/$DF_CAMPAIGN/$DF_RUN_ID"
NETS_KEY_PREFIX=nets
TEAMS_KEY_PREFIX=teams
STATUS=failed
REASON=unknown
STEP=packages
BOX_START=$(date +%s)
BOX_TIME=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$WORK"
: > "$LOG"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

finish() {
    local rc=$?
    set +e # whatever fails below (a full disk), the box still powers itself off
    [ "$rc" -eq 0 ] && STATUS='done' && REASON='none'
    [ "$REASON" = unknown ] && REASON="failed_in_$STEP"
    log "leaving with status $rc ($STATUS: $REASON)"
    printf '{"run_id": "%s", "commit": "%s", "status": "%s", "reason": "%s"}\n' "$DF_RUN_ID" "$DF_COMMIT" "$STATUS" \
        "$REASON" > "$WORK/status.json"
    if command -v aws > /dev/null 2>&1; then
        aws s3 cp "$WORK/status.json" "$S3_BASE/status.json" --only-show-errors || true
        aws s3 cp "$LOG" "$S3_BASE/log/box.log" --only-show-errors || true
        aws s3 cp "$LOG" "$S3_BASE/log/box-$BOX_TIME.log" --only-show-errors || true # each launch's
    fi
    shutdown -h now
}
trap finish EXIT
trap 'REASON=terminated; exit 143' TERM INT

refuse() { # name message
    REASON=$1
    log "REFUSED ($1): $2"
    exit 1
}

# --- the packages and the AWS CLI
log "box up: oracle campaign $DF_CAMPAIGN, commit $DF_COMMIT, run $DF_RUN_ID, at most $DF_MAX_MINUTES minutes"
apt-get update -qq
apt-get install -y -qq build-essential cmake git python3 python3-venv curl unzip ca-certificates
curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip
unzip -q /tmp/awscli.zip -d /tmp
/tmp/aws/install > /dev/null
aws --version >> "$LOG"

# --- the source at the exact commit, its conf and its library
STEP=checkout
REPO="$WORK/duoforge"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" remote add origin "$DF_REPO_URL"
git -C "$REPO" fetch -q --depth 1 origin "$DF_COMMIT"
git -C "$REPO" checkout -q --detach FETCH_HEAD
[ "$(git -C "$REPO" rev-parse HEAD)" = "$DF_COMMIT" ] || refuse wrong_commit "the checkout is not at $DF_COMMIT"
case $DF_RUN_ID in "${DF_COMMIT:0:12}-oracle-"*) ;; *) refuse wrong_run "run $DF_RUN_ID is not of $DF_COMMIT" ;; esac
case $DF_RESUME in yes | no) ;; *) refuse wrong_resume "resume is '$DF_RESUME', not yes or no" ;; esac
TOOLS="$REPO/tools/cloud/aws_fuzz"
. "$TOOLS/ladder_box_lib.sh"
CONF="$TOOLS/campaigns/$DF_CAMPAIGN/campaign.conf"
[ -f "$CONF" ] || refuse no_campaign "no campaign.conf for $DF_CAMPAIGN at $DF_COMMIT"
python3 "$TOOLS/oracle_conf.py" check "$CONF" 2>> "$LOG" || refuse bad_conf "the campaign.conf is not a valid oracle conf"

STEP=build
log 'building the library (Release, duoforge_shared)'
cmake -S "$REPO" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Release > "$WORK/cmake.log" 2>&1 || refuse build "cmake configure"
cmake --build "$WORK/build" --target duoforge_shared -j"$(nproc)" >> "$WORK/cmake.log" 2>&1 || refuse build "cmake build"
LIB="$WORK/build/libduoforge_shared.so"
[ -f "$LIB" ] || LIB=$(find "$WORK/build" -name libduoforge_shared.so -type f | head -n 1)
[ -f "$LIB" ] || refuse build 'libduoforge_shared.so was not built'
LIB_SHA=$(sha256sum "$LIB" | cut -d' ' -f1)
log "library $LIB_SHA"

# --- Python: exactly the pinned versions, and a consistent set
STEP=python
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q --no-deps -r "$TOOLS/ladder_requirements.txt" >> "$LOG" 2>&1 || refuse python_env 'pip install'
"$WORK/venv/bin/pip" check >> "$LOG" 2>&1 || refuse python_env 'pip check: the pinned set is not consistent'

# --- nets/ and teams/: read-only for the box (three probes each, ladder_box_lib.sh)
STEP=nets
verdict=$(ladder_nets_probe "$DF_BUCKET" "$NETS_KEY_PREFIX/.write-probe-$DF_RUN_ID") && probe_rc=0 || probe_rc=$?
case $probe_rc in
    0) log "nets/ is read-only for the box: $verdict" ;;
    3) refuse nets_writable "s3://$DF_BUCKET/$NETS_KEY_PREFIX/ must be read-only for the box: $verdict" ;;
    *) refuse nets_probe_unclear "$verdict" ;;
esac
verdict=$(ladder_nets_probe "$DF_BUCKET" "$TEAMS_KEY_PREFIX/.write-probe-$DF_RUN_ID") && probe_rc=0 || probe_rc=$?
case $probe_rc in
    0) log "teams/ is read-only for the box: $verdict" ;;
    3) refuse teams_writable "s3://$DF_BUCKET/$TEAMS_KEY_PREFIX/ must be read-only for the box: $verdict" ;;
    *) refuse teams_probe_unclear "$verdict" ;;
esac

# --- every network by its sha256
NETS="$WORK/nets"
mkdir -p "$NETS"
list=$(python3 "$TOOLS/oracle_conf.py" shas "$CONF") || refuse bad_conf 'oracle_conf.py shas'
mapfile -t SHAS <<< "$list"
[ -n "$list" ] || refuse bad_conf 'the conf names no network'
for sha in "${SHAS[@]}"; do
    aws s3 cp "s3://$DF_BUCKET/$NETS_KEY_PREFIX/$sha.npz" "$NETS/$sha.npz" --only-show-errors >> "$LOG" 2>&1 ||
        refuse nets_unreadable "nets/$sha.npz could not be read"
    [ "$(sha256sum "$NETS/$sha.npz" | cut -d' ' -f1)" = "$sha" ] || refuse net_sha_mismatch "nets/$sha.npz has another sha256"
done
log "${#SHAS[@]} networks read and checked"

# --- the foe team by its sha256: private, never printed, logged or uploaded (only its key and sha256 are logged)
STEP=teams
TEAMS="$WORK/teams"
mkdir -p "$TEAMS"
chmod 700 "$TEAMS"
TEAM_SHA=$(python3 "$TOOLS/oracle_conf.py" team "$CONF") || refuse bad_conf 'oracle_conf.py team'
[[ $TEAM_SHA =~ ^[0-9a-f]{64}$ ]] || refuse bad_conf 'the conf names no foe team'
TEAM_FILE="$TEAMS/$TEAM_SHA.txt"
aws s3 cp "s3://$DF_BUCKET/$TEAMS_KEY_PREFIX/$TEAM_SHA.txt" "$TEAM_FILE" --only-show-errors >> "$LOG" 2>&1 ||
    refuse team_unreadable "teams/$TEAM_SHA.txt could not be read"
[ "$(sha256sum < "$TEAM_FILE" | cut -d' ' -f1)" = "$TEAM_SHA" ] ||
    refuse team_sha_mismatch "teams/$TEAM_SHA.txt has another sha256"
chmod 400 "$TEAM_FILE"
log "the foe team teams/$TEAM_SHA.txt read and checked"

# --- our team: data/teams/<id>.txt at the commit must have the sha256 of data/teams/index.json
OURS=$(python3 "$TOOLS/oracle_conf.py" ours "$CONF") || refuse bad_conf 'oracle_conf.py ours'
WANT=$(python3 - "$REPO/data/teams/index.json" "$OURS" << 'PY'
import json, sys
teams = json.load(open(sys.argv[1], encoding="utf-8"))["teams"]
print(next((t["sha256"] for t in teams if t["id"] == sys.argv[2]), "none"))
PY
) || WANT=none
[ -f "$REPO/data/teams/$OURS.txt" ] || refuse ours_mismatch "data/teams/$OURS.txt is not at $DF_COMMIT"
GOT=$(sha256sum "$REPO/data/teams/$OURS.txt" | cut -d' ' -f1)
[ "$GOT" = "$WANT" ] || refuse ours_mismatch "data/teams/$OURS.txt has $GOT, data/teams/index.json says $WANT"
log "our team data/teams/$OURS.txt checked ($GOT)"

# --- the pins: the local machine's instruction set, BLAS kernel and CPU count
STEP=series
export JAX_PLATFORMS=cpu XLA_FLAGS=--xla_cpu_max_isa=AVX2 OPENBLAS_CORETYPE=Haswell OPENBLAS_NUM_THREADS=1
export DUOFORGE_LIBRARY="$LIB" PYTHONPATH="$REPO/python"
NEED=$((DF_PROCESSES * DF_CPUS + DF_SPARE))
[ "$(nproc)" -ge "$NEED" ] || refuse cpus "the box has $(nproc) CPUs, fewer than $DF_PROCESSES x $DF_CPUS + $DF_SPARE"
TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)
TYPE=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-type || echo unknown)
"$WORK/venv/bin/python" - "$WORK/env.json" "$LIB_SHA" "$TYPE" "$DF_CPUS" "$DF_COMMIT" "$DF_PROCESSES" << 'PY'
import json, os, platform, subprocess, sys
out, lib, kind, cpus, commit, procs = sys.argv[1:7]
flags = next((l.split(":", 1)[1].split() for l in open("/proc/cpuinfo") if l.startswith("flags")), [])
model = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "")
freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout.split()
json.dump({"commit": commit, "library_sha256": lib, "instance_type": kind, "cpu": model, "processes": int(procs),
           "cpus_per_process": int(cpus), "nproc": os.cpu_count(), "avx512": any(f.startswith("avx512") for f in flags),
           "python": platform.python_version(), "pip_freeze": freeze,
           "pins": {k: os.environ.get(k) for k in ("JAX_PLATFORMS", "XLA_FLAGS", "OPENBLAS_CORETYPE",
                                                   "OPENBLAS_NUM_THREADS")}},
          open(out, "w"), indent=1)
PY
aws s3 cp "$WORK/env.json" "$S3_BASE/env.json" --only-show-errors
aws s3 cp "$WORK/env.json" "$S3_BASE/log/env-$BOX_TIME.json" --only-show-errors # each launch's, a resumed one too

# --- the series: one command; preview_series pins its processes itself (taskset, process i on CPUs 16i to 16i+15).
# Its deadline lies 30 minutes before the watchdog, so that it stops itself (refused: deadline) and its aggregates
# still go up. Its state (the aggregates so far) goes to state/ after every round (round.txt changes) and every 10
# minutes: a launch with --resume <run id> continues the series from there after a spot interruption, drawing nothing
# anew (HauptSession, 2026-10-15). The state is the aggregates: never a network, the team file, a decision file, a part
# directory or a log.
OUT="$WORK/out"
list=$(python3 "$TOOLS/oracle_conf.py" argv "$CONF" "$NETS" "$TEAMS" "$OUT") || refuse bad_conf 'oracle_conf.py argv'
mapfile -t ARGS <<< "$list"
STATE_FILTERS=(--exclude '*' --include series.json --include round.txt --include equality.json --include 'matrix/*.json'
    --include 'runs/*/conditions.json' --include 'runs/*/oracle.json' --include 'runs/*/arms/*.json'
    --exclude 'runs/*.parts/*' --exclude '*decision*' --exclude '*.tmp' --exclude 'logs/*')
RESUME_ARGS=()
if [ "$DF_RESUME" = yes ]; then
    mkdir -p "$OUT"
    aws s3 cp "$S3_BASE/state/" "$OUT/" --recursive --only-show-errors "${STATE_FILTERS[@]}" >> "$LOG" 2>&1 ||
        refuse no_state "the saved state of $DF_RUN_ID could not be read"
    [ -f "$OUT/series.json" ] || refuse no_state "the run $DF_RUN_ID has no saved state (state/series.json)"
    RESUME_ARGS=(--resume)
    log "resuming the series of $DF_RUN_ID from its saved state"
fi
DEADLINE=$((DF_MAX_MINUTES * 60 - ($(date +%s) - BOX_START) - 1800))
[ "$DEADLINE" -gt 0 ] || refuse deadline "no time is left for the series before the watchdog ($DEADLINE s)"
log "series: preview_series ${ARGS[*]} ${RESUME_ARGS[*]} --parallel 3 --cpus-per-process 16 --deadline-seconds $DEADLINE"
save_state() {
    aws s3 sync "$OUT" "$S3_BASE/state" --only-show-errors "${STATE_FILTERS[@]}" >> "$LOG" 2>&1
}
state_loop() { # after every round (round.txt is newer than the last save) and every 10 minutes; a failed copy is
    # tried again next time. A TERM waits for a copy in flight (bash runs the trap after the foreground command).
    local stamp="$WORK/state.stamp" waited=0
    trap 'exit 0' TERM
    : > "$stamp"
    while sleep 30; do
        waited=$((waited + 30))
        if [ "$OUT/round.txt" -nt "$stamp" ] || [ "$waited" -ge 600 ]; then
            touch "$stamp"
            waited=0
            save_state || true
        fi
    done
}
state_loop &
STATE_LOOP=$!
cd "$REPO" && "$WORK/venv/bin/python" -u -m duoforge_search.preview_series "${ARGS[@]}" "${RESUME_ARGS[@]}" --parallel 3 --cpus-per-process 16 --deadline-seconds "$DEADLINE" > "$WORK/series.log" 2>&1 && rc=0 || rc=$?
kill "$STATE_LOOP" 2> /dev/null || true
wait "$STATE_LOOP" 2> /dev/null || true # no copy of the loop is still in flight below
log "preview_series exited with $rc"
rm -f "$TEAM_FILE"

# --- the aggregates only, whatever the exit, in one recursive copy (the later filter wins): never a network, the team
# file, a decision file, a part directory or a log of the series or the oracle (a refusal there can name a member of
# the foe team; series.json names every refusal). A failed upload does not hide the series' own refusal: it is named
# after it (upload_failed).
STEP=upload
UPLOAD_FAILED=''
if [ -d "$OUT" ]; then
    save_state || UPLOAD_FAILED=' the state' # the last state, for a --resume after a deadline or a failure
    aws s3 cp "$OUT" "$S3_BASE/" --recursive --only-show-errors --exclude '*' --include series.json \
        --include equality.json --include 'matrix/*.json' --include 'runs/*/conditions.json' \
        --include 'runs/*/oracle.json' --include 'runs/*/arms/*.json' --exclude 'runs/*.parts/*' --exclude '*decision*' \
        --exclude 'logs/*' >> "$LOG" 2>&1 || UPLOAD_FAILED=' the aggregates'
fi
case $rc in
    0) "$WORK/venv/bin/python" -c 'import json, sys; sys.exit(json.load(open(sys.argv[1])).get("status") != "done")' \
        "$OUT/series.json" 2>> "$LOG" || refuse oracle_failed 'preview_series exited 0, but series.json does not say done' ;;
    3) refuse oracle_beside_differs 'the alone-vs-beside equality check failed (equality.json)' ;;
    *) refuse oracle_failed "preview_series exited with $rc" ;;
esac
[ -z "$UPLOAD_FAILED" ] || refuse upload_failed "not uploaded:$UPLOAD_FAILED"
log 'done'
