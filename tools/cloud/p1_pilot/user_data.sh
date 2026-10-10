#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge p1 watchdog: at most @MAX_MINUTES@ minutes"
# The user data of the P1 pilot box (tools/cloud/p1_pilot/README.md), rendered by launch.sh and check.sh, which fill
# the four @...@ placeholders with values they have validated. The first command above is the hard wall cap: whatever
# happens below, the box powers off after @MAX_MINUTES@ minutes, and the instance-initiated shutdown behaviour is
# terminate (so is the spot request's interruption behaviour).
#
# This is the launcher's side only. The workload is tools/cloud/p1_pilot/run.sh of the exact commit (written
# elsewhere); it is run with BUCKET, RUN_PREFIX (p1/<run id>/), RUN_ID, COMMIT and OUT_DIR in its environment. What the
# box adds around it:
#  - the log (this script's and run.sh's output) is copied to s3://<BUCKET>/p1/<run id>/log/ every minute and at the end;
#  - OUT_DIR is synced to s3://<BUCKET>/p1/<run id>/out/ at the end, whatever the end is;
#  - a spot interruption notice (IMDSv2, spot/instance-action) runs `run.sh --on-interrupt` when run.sh mentions that
#    option, then the final sync, and the box leaves;
#  - five minutes before the wall cap the workload is stopped and the end runs (sync, power off), so the results are
#    in S3 before the hard cap cuts the box;
#  - the end (success or failure, through the EXIT trap) uploads what exists and runs `shutdown -h now`.
# There is no secret on the box: S3 is reached with the instance profile.
set -uo pipefail

DF_COMMIT='@COMMIT@'
DF_BUCKET='@BUCKET@'
DF_RUN_ID='@RUN_ID@'
DF_PILOT_RUN_ID='@PILOT_RUN_ID@'  # empty, or the earlier run whose pilot run.sh reads (read only)
DF_MAX_MINUTES=@MAX_MINUTES@
DF_REGION=eu-central-1
DF_REPO_URL=https://github.com/chrismaghuhn/duoforge.git
DF_SOFT_MARGIN_MINUTES=5   # the workload is stopped this long before the wall cap
DF_LOG_EVERY=60            # seconds between two log uploads
DF_POLL_EVERY=5            # seconds between two polls of the interruption notice
DF_HOOK_SECONDS=60         # the most the interruption hook may take (the notice comes two minutes ahead)
DF_IMDS=http://169.254.169.254
DF_SOFT_DEADLINE_SECONDS=$(((DF_MAX_MINUTES - DF_SOFT_MARGIN_MINUTES) * 60))

export AWS_DEFAULT_REGION=$DF_REGION AWS_REGION=$DF_REGION
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a HOME=/root
WORK=/opt/duoforge-p1
OUT="$WORK/out"
LOG=/var/log/duoforge-p1.log
RUN_PREFIX="p1/$DF_RUN_ID/"
S3_BASE="s3://$DF_BUCKET/$RUN_PREFIX"
REPO="$WORK/duoforge"
RUN_SH="$REPO/tools/cloud/p1_pilot/run.sh"
BOOT=$(date -u +%Y%m%dT%H%M%SZ)
MAIN_PID=$$
WORKLOAD_PID=''
BG_PIDS=()
mkdir -p "$WORK" "$OUT"
: > "$LOG"
# the workload's environment, exported before anything is started (the interruption hook gets it too)
export BUCKET="$DF_BUCKET" RUN_PREFIX RUN_ID="$DF_RUN_ID" COMMIT="$DF_COMMIT" OUT_DIR="$OUT"
if [ -n "$DF_PILOT_RUN_ID" ]; then export PILOT_RUN_ID="$DF_PILOT_RUN_ID"; fi

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }

sync_log() {
    command -v aws > /dev/null 2>&1 || return 0
    aws s3 cp "$LOG" "${S3_BASE}log/$BOOT.log" --only-show-errors || true
}

sync_out() {
    command -v aws > /dev/null 2>&1 || return 0
    aws s3 sync "$OUT" "${S3_BASE}out/" --only-show-errors || log 'the sync of the results failed'
}

# The workload runs in a session of its own, so that stopping it reaches every process it started.
stop_workload() {
    local pid=$WORKLOAD_PID i
    [ -n "$pid" ] || return 0
    kill -0 "$pid" 2> /dev/null || return 0
    log "stopping the workload ($pid)"
    kill -TERM -- "-$pid" 2> /dev/null || kill -TERM "$pid" 2> /dev/null || true
    for ((i = 0; i < 30; i++)); do
        kill -0 "$pid" 2> /dev/null || return 0
        sleep 1
    done
    kill -KILL -- "-$pid" 2> /dev/null || kill -KILL "$pid" 2> /dev/null || true
}

# Self-termination, part two: every way out of this script ends here, uploads what exists and powers off.
finish() {
    local rc=$? p
    trap - EXIT TERM INT
    log "leaving with status $rc"
    stop_workload
    for p in "${BG_PIDS[@]}"; do kill "$p" 2> /dev/null || true; done
    sync_out
    sync_log
    shutdown -h now
}
trap finish EXIT
trap 'exit 143' TERM INT # a stop (soft deadline, interruption, the system going down) leaves through the exit trap

fail() {
    log "FAILED: $*"
    exit 1
}

# run.sh has an interruption hook when it exists and mentions the option.
has_hook() { [ -f "$RUN_SH" ] && grep -q -e '--on-interrupt' "$RUN_SH"; }

imds_token() {
    curl -fsS -X PUT "$DF_IMDS/latest/api/token" -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600'
}

# The spot interruption notice: on a 200 from spot/instance-action, the hook (if run.sh has one), the final sync, and
# the end of the main script.
poll_interruption() {
    local token code
    token=$(imds_token) || {
        log 'no IMDSv2 token: the interruption notice is not polled'
        return 0
    }
    while sleep "$DF_POLL_EVERY"; do
        code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-aws-ec2-metadata-token: $token" \
            "$DF_IMDS/latest/meta-data/spot/instance-action" || true)
        if [ "$code" = 200 ]; then
            log 'spot interruption notice'
            if has_hook; then
                log 'running run.sh --on-interrupt'
                (cd "$REPO" && timeout "$DF_HOOK_SECONDS" bash "$RUN_SH" --on-interrupt) >> "$LOG" 2>&1 ||
                    log 'the interruption hook failed or timed out'
            fi
            sync_out
            sync_log
            kill -TERM "$MAIN_PID" 2> /dev/null || true
            return 0
        fi
    done
}

soft_deadline() {
    sleep "$DF_SOFT_DEADLINE_SECONDS"
    log "soft deadline: $DF_SOFT_MARGIN_MINUTES minutes before the wall cap of $DF_MAX_MINUTES minutes"
    kill -TERM "$MAIN_PID" 2> /dev/null || true
}

log_syncer() {
    while sleep "$DF_LOG_EVERY"; do sync_log; done
}

log "box up: run $DF_RUN_ID, commit $DF_COMMIT, at most $DF_MAX_MINUTES minutes, $(nproc) cpus"
log_syncer &
BG_PIDS+=("$!")
soft_deadline &
BG_PIDS+=("$!")
poll_interruption &
BG_PIDS+=("$!")

# --- the tools: the DLAMI has them; install what is missing
if ! command -v git > /dev/null 2>&1; then
    if ! { apt-get update -qq && apt-get install -y -qq git; }; then fail 'git could not be installed'; fi
fi
if ! command -v aws > /dev/null 2>&1; then
    curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip || fail 'no AWS CLI download'
    (cd /tmp && unzip -q awscli.zip && ./aws/install > /dev/null) || fail 'the AWS CLI could not be installed'
fi
aws --version >> "$LOG" 2>&1 || fail 'no AWS CLI'
nvidia-smi -L >> "$LOG" 2>&1 || log 'nvidia-smi -L failed'

# --- the public repository at the exact commit
mkdir -p "$REPO"
git -C "$REPO" init -q || fail 'git init'
git -C "$REPO" remote add origin "$DF_REPO_URL" || fail 'git remote add'
git -C "$REPO" fetch -q --depth 1 origin "$DF_COMMIT" >> "$LOG" 2>&1 || fail "cannot fetch $DF_COMMIT"
git -C "$REPO" checkout -q --detach FETCH_HEAD || fail 'git checkout'
[ "$(git -C "$REPO" rev-parse HEAD)" = "$DF_COMMIT" ] || fail "the checkout is not at $DF_COMMIT"
[ -f "$RUN_SH" ] || fail "commit $DF_COMMIT has no tools/cloud/p1_pilot/run.sh"

log "run.sh found; interruption hook: $(has_hook && echo yes || echo no)"

printf '{"run_id":"%s","commit":"%s","boot":"%s","max_minutes":%s,"cpus":%s}\n' \
    "$DF_RUN_ID" "$DF_COMMIT" "$BOOT" "$DF_MAX_MINUTES" "$(nproc)" > "$OUT/launcher.json"

# --- the workload
cd "$REPO" || fail "cannot enter $REPO"
log 'starting run.sh'
setsid bash "$RUN_SH" >> "$LOG" 2>&1 < /dev/null &
WORKLOAD_PID=$!
wait "$WORKLOAD_PID"
rc=$?
WORKLOAD_PID=''
log "run.sh exited with status $rc"
exit "$rc"
