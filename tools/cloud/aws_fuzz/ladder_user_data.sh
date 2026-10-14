#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge ladder watchdog: at most @MAX_MINUTES@ minutes"
# The user data of a ladder box (#484; tools/cloud/aws_fuzz/README.md, "Ladder campaigns"), rendered by launch_ladder.sh,
# which fills the @...@ placeholders with values it has validated. The first command above is the watchdog: whatever
# happens below, the box is gone after @MAX_MINUTES@ minutes (the instance-initiated shutdown behaviour is terminate).
#
# One ladder arm, as campaigns/<id>/campaign.conf at the exact commit names it (ladder_conf.py builds the command
# line):
# - the public repository at the commit and its library (Release, the target duoforge_shared, as the search lane's
#   local builds do);
# - Python from ladder_requirements.txt, exactly those versions;
# - the networks from the private bucket's nets/<sha256>.npz, each checked against its sha256;
# - the run pinned to the local machine: XLA's instruction set (AVX2), OpenBLAS's kernel (Haswell, one thread), 16
#   CPUs (taskset);
# - the aggregates up to fuzz/ladder/<campaign>/<run id>/: ladder.json (decision digests, scores, counts), env.json (the
#   pins, the versions, the library's sha256, the machine) and the logs. No decision file and no network leaves the box.
#
# nets/ must be read-only for the box (HauptSession): a probe write there that succeeds is a refusal by name
# (nets_writable), and so is a network that cannot be read (nets_unreadable) or has another sha256 (net_sha_mismatch).
# Every refusal and failure is named in status.json, uploaded with the log; then the box powers itself off. There is no
# secret on the box: S3 is reached with the instance profile.
set -euo pipefail

DF_CAMPAIGN='@CAMPAIGN@'
DF_COMMIT='@COMMIT@'
DF_BUCKET='@BUCKET@'
DF_RUN_ID='@RUN_ID@'
DF_MAX_MINUTES=@MAX_MINUTES@
DF_REGION=eu-central-1
DF_REPO_URL=https://github.com/chrismaghuhn/duoforge.git
DF_CPUS=16 # the local machine's logical CPUs: XLA's thread pool follows the affinity (taskset)

export AWS_DEFAULT_REGION=$DF_REGION AWS_REGION=$DF_REGION
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a HOME=/root
WORK=/opt/duoforge-ladder
LOG=/var/log/duoforge-ladder.log
S3_BASE="s3://$DF_BUCKET/fuzz/ladder/$DF_CAMPAIGN/$DF_RUN_ID"
NETS_KEY_PREFIX=nets
STATUS=failed
REASON=unknown
mkdir -p "$WORK"
: > "$LOG"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

finish() {
    local rc=$?
    [ "$rc" -eq 0 ] && STATUS=done && REASON=none
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
trap 'exit 143' TERM INT

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
REPO="$WORK/duoforge"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" remote add origin "$DF_REPO_URL"
git -C "$REPO" fetch -q --depth 1 origin "$DF_COMMIT"
git -C "$REPO" checkout -q --detach FETCH_HEAD
[ "$(git -C "$REPO" rev-parse HEAD)" = "$DF_COMMIT" ] || refuse wrong_commit "the checkout is not at $DF_COMMIT"
case $DF_RUN_ID in "${DF_COMMIT:0:12}-ladder-"*) ;; *) refuse wrong_run "run $DF_RUN_ID is not of $DF_COMMIT" ;; esac
TOOLS="$REPO/tools/cloud/aws_fuzz"
CONF="$TOOLS/campaigns/$DF_CAMPAIGN/campaign.conf"
[ -f "$CONF" ] || refuse no_campaign "no campaign.conf for $DF_CAMPAIGN at $DF_COMMIT"
python3 "$TOOLS/ladder_conf.py" check "$CONF" 2>> "$LOG" || refuse bad_conf "the campaign.conf is not a valid ladder conf"

log 'building the library (Release, duoforge_shared)'
cmake -S "$REPO" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Release > "$WORK/cmake.log" 2>&1 || refuse build "cmake configure"
cmake --build "$WORK/build" --target duoforge_shared -j"$(nproc)" >> "$WORK/cmake.log" 2>&1 || refuse build "cmake build"
LIB="$WORK/build/libduoforge_shared.so"
[ -f "$LIB" ] || LIB=$(find "$WORK/build" -name libduoforge_shared.so -type f | head -n 1)
[ -f "$LIB" ] || refuse build 'libduoforge_shared.so was not built'
LIB_SHA=$(sha256sum "$LIB" | cut -d' ' -f1)
log "library $LIB_SHA"

# --- Python: exactly the pinned versions, and a consistent set
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q --no-deps -r "$TOOLS/ladder_requirements.txt" >> "$LOG" 2>&1 || refuse python_env 'pip install'
"$WORK/venv/bin/pip" check >> "$LOG" 2>&1 || refuse python_env 'pip check: the pinned set is not consistent'

# --- nets/: read-only for the box, every network by its sha256
NETS="$WORK/nets"
mkdir -p "$NETS"
probe="$NETS_KEY_PREFIX/.write-probe-$DF_RUN_ID"
if out=$(aws s3api put-object --bucket "$DF_BUCKET" --key "$probe" --body /dev/null 2>&1); then
    aws s3api delete-object --bucket "$DF_BUCKET" --key "$probe" > /dev/null 2>&1 || true
    refuse nets_writable "the box could write to s3://$DF_BUCKET/$NETS_KEY_PREFIX/ (it must be read-only)"
fi
case $out in
    *AccessDenied*) log "nets/ is read-only for the box (the probe write was denied)" ;;
    *) refuse nets_probe_unclear "the probe write failed, but not with AccessDenied: $out" ;;
esac
mapfile -t SHAS < <(python3 "$TOOLS/ladder_conf.py" shas "$CONF")
for sha in "${SHAS[@]}"; do
    aws s3 cp "s3://$DF_BUCKET/$NETS_KEY_PREFIX/$sha.npz" "$NETS/$sha.npz" --only-show-errors >> "$LOG" 2>&1 ||
        refuse nets_unreadable "nets/$sha.npz could not be read"
    [ "$(sha256sum "$NETS/$sha.npz" | cut -d' ' -f1)" = "$sha" ] || refuse net_sha_mismatch "nets/$sha.npz has another sha256"
done
log "${#SHAS[@]} networks read and checked"

# --- the pins: the local machine's instruction set, BLAS kernel and CPU count
export JAX_PLATFORMS=cpu XLA_FLAGS=--xla_cpu_max_isa=AVX2 OPENBLAS_CORETYPE=Haswell OPENBLAS_NUM_THREADS=1
export DUOFORGE_LIBRARY="$LIB" PYTHONPATH="$REPO/python"
[ "$(nproc)" -ge "$DF_CPUS" ] || refuse cpus "the box has $(nproc) CPUs, fewer than $DF_CPUS"
TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)
TYPE=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-type || echo unknown)
"$WORK/venv/bin/python" - "$WORK/env.json" "$LIB_SHA" "$TYPE" "$DF_CPUS" "$DF_COMMIT" << 'PY'
import json, os, platform, subprocess, sys
out, lib, kind, cpus, commit = sys.argv[1:6]
flags = next((l.split(":", 1)[1].split() for l in open("/proc/cpuinfo") if l.startswith("flags")), [])
model = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), "")
freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout.split()
json.dump({"commit": commit, "library_sha256": lib, "instance_type": kind, "cpu": model, "cpus_pinned": int(cpus),
           "nproc": os.cpu_count(), "avx512": any(f.startswith("avx512") for f in flags), "python": platform.python_version(),
           "pip_freeze": freeze, "pins": {k: os.environ.get(k) for k in ("JAX_PLATFORMS", "XLA_FLAGS", "OPENBLAS_CORETYPE",
                                                                         "OPENBLAS_NUM_THREADS")}},
          open(out, "w"), indent=1)
PY
aws s3 cp "$WORK/env.json" "$S3_BASE/env.json" --only-show-errors

# --- the arm
OUT="$WORK/out"
mapfile -t ARGS < <(python3 "$TOOLS/ladder_conf.py" argv "$CONF" "$NETS" "$OUT")
log "ladder ${ARGS[*]}"
(cd "$REPO" && taskset -c "0-$((DF_CPUS - 1))" "$WORK/venv/bin/python" -u -m duoforge_search.ladder "${ARGS[@]}") \
    > "$WORK/ladder.log" 2>&1 || { tail -n 40 "$WORK/ladder.log" >> "$LOG"; refuse ladder_failed 'the ladder run failed'; }
[ -f "$OUT/ladder.json" ] || refuse ladder_failed 'no ladder.json'

# --- the aggregates only: ladder.json and its log; the decision files and the networks stay on the box
aws s3 cp "$OUT/ladder.json" "$S3_BASE/ladder.json" --only-show-errors
tail -n 200 "$WORK/ladder.log" > "$WORK/ladder-tail.log"
aws s3 cp "$WORK/ladder-tail.log" "$S3_BASE/log/ladder-tail.log" --only-show-errors
log 'done'
