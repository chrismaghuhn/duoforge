#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge ladder watchdog: at most @MAX_MINUTES@ minutes"
# The user data of a ladder box (#484; tools/cloud/aws_fuzz/README.md, "Ladder campaigns"), rendered by launch_ladder.sh,
# which fills the @...@ placeholders with values it has validated. The first command above is the watchdog: whatever
# happens below, the box is gone after @MAX_MINUTES@ minutes (the instance-initiated shutdown behaviour is terminate).
#
# Up to three ladder arms side by side, as campaigns/<id>/campaign.conf at the exact commit names them (ladder_conf.py
# builds each arm's command line):
# - the public repository at the commit and its library (Release, the target duoforge_shared, as the search lane's
#   local builds do);
# - Python from ladder_requirements.txt, exactly those versions;
# - the networks from the private bucket's nets/<sha256>.npz, each checked against its sha256;
# - each arm pinned as the local machine runs one: XLA's instruction set (AVX2), OpenBLAS's kernel (Haswell, one
#   thread), 16 CPUs of its own (taskset: arm i on CPUs 16i to 16i+15), 8 workers; 16 CPUs stay free for the box
#   (HauptSession: three arms on a c7a.16xlarge);
# - the aggregates up to fuzz/ladder/<campaign>/<run id>/: each arm's ladder.json under <arm>/ (decision digests,
#   scores, counts), env.json (the pins, the versions, the library's sha256, the machine, the arms' CPUs) and the logs.
#   No decision file and no network leaves the box.
#
# nets/ must be read-only for the box (HauptSession): a probe write there that succeeds is a refusal by name
# (nets_writable), and so is a network that cannot be read (nets_unreadable) or has another sha256 (net_sha_mismatch).
# Every refusal is named in status.json, uploaded with the log; a failure without a refusal is named by its step
# (failed_in_<step>), a TERM or INT (the watchdog's shutdown) is "terminated". Then the box powers itself off. A failure
# before the AWS CLI is installed (failed_in_packages) uploads nothing: the console output is all that is left of it.
# There is no secret on the box: S3 is reached with the instance profile.
set -euo pipefail

DF_CAMPAIGN='@CAMPAIGN@'
DF_COMMIT='@COMMIT@'
DF_BUCKET='@BUCKET@'
DF_RUN_ID='@RUN_ID@'
DF_MAX_MINUTES=@MAX_MINUTES@
DF_REGION=eu-central-1
DF_REPO_URL=https://github.com/chrismaghuhn/duoforge.git
DF_CPUS=16 # CPUs per arm, the local machine's logical CPUs: XLA's thread pool follows the affinity (taskset)
DF_SPARE=16 # CPUs left to the box beside the arms

export AWS_DEFAULT_REGION=$DF_REGION AWS_REGION=$DF_REGION
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a HOME=/root
WORK=/opt/duoforge-ladder
LOG=/var/log/duoforge-ladder.log
S3_BASE="s3://$DF_BUCKET/fuzz/ladder/$DF_CAMPAIGN/$DF_RUN_ID"
NETS_KEY_PREFIX=nets
STATUS=failed
REASON=unknown
STEP=packages
mkdir -p "$WORK"
: > "$LOG"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

finish() {
    local rc=$?
    [ "$rc" -eq 0 ] && STATUS='done' && REASON='none'
    [ "$REASON" = unknown ] && REASON="failed_in_$STEP"
    log "leaving with status $rc ($STATUS: $REASON)"
    printf '{"run_id": "%s", "commit": "%s", "status": "%s", "reason": "%s"}\n' "$DF_RUN_ID" "$DF_COMMIT" "$STATUS" \
        "$REASON" > "$WORK/status.json"
    if command -v aws > /dev/null 2>&1; then
        aws s3 cp "$WORK/status.json" "$S3_BASE/status.json" --only-show-errors || true
        aws s3 cp "$LOG" "$S3_BASE/log/box.log" --only-show-errors || true
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
log "box up: ladder campaign $DF_CAMPAIGN, commit $DF_COMMIT, run $DF_RUN_ID, at most $DF_MAX_MINUTES minutes"
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
case $DF_RUN_ID in "${DF_COMMIT:0:12}-ladder-"*) ;; *) refuse wrong_run "run $DF_RUN_ID is not of $DF_COMMIT" ;; esac
TOOLS="$REPO/tools/cloud/aws_fuzz"
. "$TOOLS/ladder_box_lib.sh"
CONF="$TOOLS/campaigns/$DF_CAMPAIGN/campaign.conf"
[ -f "$CONF" ] || refuse no_campaign "no campaign.conf for $DF_CAMPAIGN at $DF_COMMIT"
python3 "$TOOLS/ladder_conf.py" check "$CONF" 2>> "$LOG" || refuse bad_conf "the campaign.conf is not a valid ladder conf"

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

# --- nets/: read-only for the box, every network by its sha256
STEP=nets
NETS="$WORK/nets"
mkdir -p "$NETS"
verdict=$(ladder_nets_probe "$DF_BUCKET" "$NETS_KEY_PREFIX/.write-probe-$DF_RUN_ID") && probe_rc=0 || probe_rc=$?
case $probe_rc in
    0) log "nets/ is read-only for the box: $verdict" ;;
    3) refuse nets_writable "s3://$DF_BUCKET/$NETS_KEY_PREFIX/ must be read-only for the box: $verdict" ;;
    *) refuse nets_probe_unclear "$verdict" ;;
esac
list=$(python3 "$TOOLS/ladder_conf.py" shas "$CONF") || refuse bad_conf 'ladder_conf.py shas'
mapfile -t SHAS <<< "$list"
[ -n "$list" ] || refuse bad_conf 'the conf names no network'
for sha in "${SHAS[@]}"; do
    aws s3 cp "s3://$DF_BUCKET/$NETS_KEY_PREFIX/$sha.npz" "$NETS/$sha.npz" --only-show-errors >> "$LOG" 2>&1 ||
        refuse nets_unreadable "nets/$sha.npz could not be read"
    [ "$(sha256sum "$NETS/$sha.npz" | cut -d' ' -f1)" = "$sha" ] || refuse net_sha_mismatch "nets/$sha.npz has another sha256"
done
log "${#SHAS[@]} networks read and checked"

# --- the pins: the local machine's instruction set, BLAS kernel and CPU count
STEP=arms
export JAX_PLATFORMS=cpu XLA_FLAGS=--xla_cpu_max_isa=AVX2 OPENBLAS_CORETYPE=Haswell OPENBLAS_NUM_THREADS=1
export DUOFORGE_LIBRARY="$LIB" PYTHONPATH="$REPO/python"
list=$(python3 "$TOOLS/ladder_conf.py" arms "$CONF") || refuse bad_conf 'ladder_conf.py arms'
[ -n "$list" ] || refuse bad_conf 'the conf names no arm'
mapfile -t ARMS <<< "$list"
NEED=$((${#ARMS[@]} * DF_CPUS + DF_SPARE))
[ "$(nproc)" -ge "$NEED" ] || refuse cpus "the box has $(nproc) CPUs, fewer than ${#ARMS[@]} arms x $DF_CPUS + $DF_SPARE"
TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)
TYPE=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-type || echo unknown)
"$WORK/venv/bin/python" - "$WORK/env.json" "$LIB_SHA" "$TYPE" "$DF_CPUS" "$DF_COMMIT" "${ARMS[@]}" << 'PY'
import json, os, platform, subprocess, sys
out, lib, kind, cpus, commit = sys.argv[1:6]
arms = sys.argv[6:]
flags = next((l.split(":", 1)[1].split() for l in open("/proc/cpuinfo") if l.startswith("flags")), [])
model = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "")
freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout.split()
json.dump({"commit": commit, "library_sha256": lib, "instance_type": kind, "cpu": model, "cpus_per_arm": int(cpus),
           "arms": {a: f"{i * int(cpus)}-{(i + 1) * int(cpus) - 1}" for i, a in enumerate(arms)},
           "nproc": os.cpu_count(), "avx512": any(f.startswith("avx512") for f in flags), "python": platform.python_version(),
           "pip_freeze": freeze, "pins": {k: os.environ.get(k) for k in ("JAX_PLATFORMS", "XLA_FLAGS", "OPENBLAS_CORETYPE",
                                                                         "OPENBLAS_NUM_THREADS")}},
          open(out, "w"), indent=1)
PY
aws s3 cp "$WORK/env.json" "$S3_BASE/env.json" --only-show-errors

# --- the arms, side by side, each on CPUs of its own; each writes its own ladder.json
declare -A PIDS
for i in "${!ARMS[@]}"; do
    arm=${ARMS[$i]}
    mkdir -p "$WORK/arms/$arm"
    list=$(python3 "$TOOLS/ladder_conf.py" argv "$CONF" "$arm" "$NETS" "$WORK/arms/$arm/out") ||
        refuse bad_conf "ladder_conf.py argv $arm"
    mapfile -t ARGS <<< "$list"
    log "arm $arm on CPUs $((i * DF_CPUS))-$(((i + 1) * DF_CPUS - 1)): ladder ${ARGS[*]}"
    cpus="$((i * DF_CPUS))-$(((i + 1) * DF_CPUS - 1))"
    (cd "$REPO" && exec taskset -c "$cpus" "$WORK/venv/bin/python" -u -m duoforge_search.ladder "${ARGS[@]}") \
        > "$WORK/arms/$arm/ladder.log" 2>&1 &
    PIDS[$arm]=$!
done
failed=''
declare -A GOOD
for arm in "${ARMS[@]}"; do
    if wait "${PIDS[$arm]}" && [ -f "$WORK/arms/$arm/out/ladder.json" ]; then
        log "arm $arm done"
        GOOD[$arm]=1
    else
        tail -n 40 "$WORK/arms/$arm/ladder.log" >> "$LOG"
        failed="$failed $arm"
    fi
done

# --- the aggregates only: the ladder.json of each arm that succeeded (a failed arm's would pass for a result) and every
# arm's log tail; the decision files and the networks stay on the box
STEP=upload
for arm in "${ARMS[@]}"; do
    if [ -n "${GOOD[$arm]:-}" ]; then
        aws s3 cp "$WORK/arms/$arm/out/ladder.json" "$S3_BASE/$arm/ladder.json" --only-show-errors
    fi
    tail -n 200 "$WORK/arms/$arm/ladder.log" > "$WORK/arms/$arm/ladder-tail.log"
    aws s3 cp "$WORK/arms/$arm/ladder-tail.log" "$S3_BASE/$arm/ladder-tail.log" --only-show-errors
done
[ -z "$failed" ] || refuse ladder_failed "the arm(s)$failed failed"
log 'done'
