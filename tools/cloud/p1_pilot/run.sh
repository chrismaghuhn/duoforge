#!/usr/bin/env bash
# Stage 3 P1 pilot: the non-interactive run on one GPU machine (collection, distillation, continuation control,
# evaluation). See README_run.md for the phases, the environment and the exit codes.
#
#   run.sh                          the run: inputs from s3://$BUCKET/p1/inputs/, state in s3://$BUCKET/$RUN_PREFIX
#   run.sh --on-interrupt           stop the running phase, upload the current state now, exit 0
#   run.sh --dry-run INPUTS_DIR     tiny local rehearsal: no aws call at all, inputs from INPUTS_DIR
#
# Every phase is idempotent: a done-marker in $OUT/markers, and the collector, distill and train resume their own
# state. Nothing private is written inside the repository (the tools refuse it as well).
set -euo pipefail

# ---- exit codes (README_run.md) ----
EX_DONE=0 EX_CRASH=1 EX_USAGE=2
EX_INPUTS=10 EX_SETUP=11 EX_REFUSED=13
EX_SMOKE_T0=20 EX_GEN_BUDGET=21 EX_WORK_FALLBACK=22 EX_PROD_INCOMPLETE=23
EX_INFEASIBLE=30 EX_COMPUTE=31 EX_CONTROL_NO_BUDGET_STOP=32
EX_EVAL_SMOKE=40 EX_EXPERT_EVAL=41
EX_NO_M12_TOOL=50 EX_INTERRUPTED=60

# ---- fixed run constants (the same on every start; recorded in run-info) ----
PARAMS_49333_SHA256=ef1abe65f63711eb47e335d6169aad34584e50d4f2df321e4e9cbbbdcaf961cb
COLLECT_SEED=0x2026100900000101
COLLECT_SPLIT_SEED=0x2026100900000102
SMOKE_FIRST_GAME_ID=0
PRODUCTION_FIRST_GAME_ID=512
DISTILL_SEED=0
CONTROL_SEED=0x2026100200000021  # train's default seed, given explicitly
EVAL_SEED=0x2026100900000301
EVAL_FIRST_GAME_ID=1000000000
GENERATION_CPU_BUDGET=28800
LABELS=16384

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)

MODE=run
LOCAL_INPUTS=
case "${1:-}" in
    "") ;;
    --dry-run)
        MODE=dry
        LOCAL_INPUTS=${2:-}
        [[ -n $LOCAL_INPUTS && -d $LOCAL_INPUTS ]] || { echo "usage: run.sh --dry-run LOCAL_INPUTS_DIR" >&2; exit $EX_USAGE; }
        LOCAL_INPUTS=$(cd "$LOCAL_INPUTS" && pwd)
        [[ $# -eq 2 ]] || { echo "run.sh --dry-run takes one directory" >&2; exit $EX_USAGE; }
        ;;
    --on-interrupt)
        MODE=interrupt
        [[ $# -eq 1 ]] || { echo "run.sh --on-interrupt takes no argument" >&2; exit $EX_USAGE; }
        ;;
    *) echo "usage: run.sh [--dry-run LOCAL_INPUTS_DIR | --on-interrupt]" >&2; exit $EX_USAGE ;;
esac

WORKERS=${WORKERS:-14}
case $WORKERS in 4|8|14) ;; *) echo "WORKERS must be 4, 8 or 14 (the P1 probe's counts), not $WORKERS" >&2; exit $EX_USAGE ;; esac
AFFINITY=${AFFINITY:-0-$((WORKERS - 1))}
LADDER_FILE=${LADDER_FILE:-params-39400.npz}
TEAMS_DIR=${TEAMS_DIR:-teams}
INTERRUPT_WAIT=${INTERRUPT_WAIT:-60}
UPLOAD_EVERY=${UPLOAD_EVERY:-900}
if [[ $MODE != dry && -n ${DRY_DISTILL_DEVICE:-} ]]; then
    echo "DRY_DISTILL_DEVICE is for --dry-run only" >&2; exit $EX_USAGE
fi
if [[ $MODE == dry ]]; then
    WORK_DIR=${WORK_DIR:-$HOME/p1-dry/work}
else
    WORK_DIR=${WORK_DIR:-$HOME/p1-work}
fi
mkdir -p "$WORK_DIR"
WORK_DIR=$(cd "$WORK_DIR" && pwd)
OUT=$WORK_DIR/out
case "$WORK_DIR/" in "$REPO"/*) echo "WORK_DIR $WORK_DIR lies inside the repository $REPO" >&2; exit $EX_USAGE ;; esac

log() { printf '%s run.sh: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { local code=$1; shift; log "EXIT $code: $*"; exit "$code"; }

# The only AWS calls this script makes: aws s3 cp / sync / ls, never in a dry run.
s3() {
    [[ $MODE != dry ]] || { log "internal error: an aws call in a dry run: s3 $*"; exit $EX_CRASH; }
    case "${1:-}" in cp|sync|ls) ;; *) log "internal error: aws s3 $1 is not allowed"; exit $EX_CRASH ;; esac
    aws s3 "$@" --only-show-errors
}

require_cloud_env() {
    [[ -n ${BUCKET:-} && -n ${RUN_PREFIX:-} && -n ${RUN_ID:-} ]] || die $EX_USAGE "BUCKET, RUN_PREFIX and RUN_ID are required"
    [[ $RUN_PREFIX == "p1/$RUN_ID/" ]] || die $EX_USAGE "RUN_PREFIX must be p1/<RUN_ID>/ (got $RUN_PREFIX, RUN_ID $RUN_ID)"
    [[ $RUN_ID =~ ^[A-Za-z0-9._-]+$ ]] || die $EX_USAGE "RUN_ID may hold letters, digits, . _ - only"
}

# Uploads the whole output tree; --delete because the local tree was restored from the prefix first and is the
# authoritative state (an interrupted collector round moves its partial shards to discarded/, which must not come
# back on the next restore). Without a completed restore nothing is uploaded except the logs.
upload_state() {
    [[ $MODE != dry ]] || return 0
    [[ -n ${BUCKET:-} && -n ${RUN_PREFIX:-} ]] || return 0
    (
        flock -w 600 9 || { log "upload: lock busy"; exit 1; }
        if [[ -e $WORK_DIR/.restored ]]; then
            s3 sync "$OUT" "s3://$BUCKET/$RUN_PREFIX" --delete
        elif [[ -d $OUT/logs ]]; then
            s3 sync "$OUT/logs" "s3://$BUCKET/${RUN_PREFIX}logs-unrestored/"
        fi
    ) 9>"$WORK_DIR/.upload.lock"
}

# ---- --on-interrupt: stop the running phase (it saves what it can), upload, exit 0 ----
if [[ $MODE == interrupt ]]; then
    require_cloud_env
    mkdir -p "$OUT/logs"
    exec >>"$OUT/logs/interrupt.log" 2>&1
    touch "$WORK_DIR/INTERRUPTED"
    log "interrupt requested"
    pid=
    if [[ -f $WORK_DIR/phase.pid ]]; then
        pid=$(cat "$WORK_DIR/phase.pid")
        if kill -0 "$pid" 2>/dev/null; then
            log "SIGTERM to phase process $pid (collector, distill and train save their state on it)"
            kill -TERM "$pid" 2>/dev/null || true
        fi
    fi
    upload_state || log "first upload failed"  # at once: whatever the phase has written so far
    log "first upload done"
    if [[ -n $pid ]]; then
        for _ in $(seq "$INTERRUPT_WAIT"); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
        kill -0 "$pid" 2>/dev/null && log "phase process $pid still running after ${INTERRUPT_WAIT}s"
        upload_state || log "second upload failed"  # what the phase saved on SIGTERM
        log "second upload done"
    fi
    exit 0
fi

[[ $MODE == dry ]] || require_cloud_env
rm -f "$WORK_DIR/INTERRUPTED" "$WORK_DIR/phase.pid"
mkdir -p "$OUT"/{logs,markers,manifests,ledgers,run-info,status}
STARTED=$(date -u +%Y%m%dT%H%M%SZ)
# One log per start: the restore below may replace files of out/logs with their uploaded copies.
exec > >(tee -a "$OUT/logs/run-$STARTED.log") 2>&1
log "start mode=$MODE work=$WORK_DIR repo=$REPO"

on_exit() {
    local code=$?
    trap - EXIT
    local meaning
    case $code in
        0) meaning=done ;; 1) meaning=crash ;; 2) meaning=usage ;; 10) meaning=input-sha-mismatch-or-missing ;;
        11) meaning=setup-failed ;; 13) meaning=phase-cli-refusal ;; 20) meaning=smoke-t0 ;;
        21) meaning=generation-cpu-budget ;; 22) meaning=work-fallback-above-1pct ;; 23) meaning=production-incomplete ;;
        30) meaning=matching-infeasible ;; 31) meaning=compute-mismatch ;; 32) meaning=control-no-budget-stop ;;
        40) meaning=eval-smoke-stop ;; 41) meaning=expert-eval-refusal ;; 50) meaning=missing-m12-tool ;;
        60) meaning=interrupted ;; *) meaning=unknown ;;
    esac
    [[ -n ${UPLOADER:-} ]] && kill "$UPLOADER" 2>/dev/null || true
    local child
    if [[ -f $WORK_DIR/phase.pid ]]; then
        child=$(cat "$WORK_DIR/phase.pid")
        kill -0 "$child" 2>/dev/null && kill -TERM "$child" 2>/dev/null || true
    fi
    printf '{"exit": %d, "meaning": "%s", "mode": "%s", "started": "%s", "ended": "%s"}\n' \
        "$code" "$meaning" "$MODE" "$STARTED" "$(date -u +%Y%m%dT%H%M%SZ)" | tee "$OUT/status/exit-$STARTED.json" >"$OUT/STATUS.json"
    log "exit $code ($meaning)"
    upload_state || log "final upload failed"  # also after an interrupt: the flock orders it after run.sh --on-interrupt's
    exit "$code"
}
trap on_exit EXIT
trap 'log "SIGTERM/SIGINT"; touch "$WORK_DIR/INTERRUPTED"; [[ -f $WORK_DIR/phase.pid ]] && kill -TERM "$(cat "$WORK_DIR/phase.pid")" 2>/dev/null; exit $EX_INTERRUPTED' TERM INT

# ---- restore the run's state ----
if [[ $MODE == run ]]; then
    log "restore s3://$BUCKET/$RUN_PREFIX"
    s3 sync "s3://$BUCKET/$RUN_PREFIX" "$OUT"
fi
touch "$WORK_DIR/.restored"
if [[ $MODE == run ]]; then  # long phases (production collection, the control) upload their progress meanwhile
    ( trap - EXIT TERM INT; while sleep "$UPLOAD_EVERY"; do upload_state || log "periodic upload failed"; done ) &
    UPLOADER=$!
fi

marked() { [[ -e $OUT/markers/$1.done ]]; }
mark() { date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/markers/$1.done"; log "phase $1 done"; upload_state || log "upload after $1 failed"; }
timing() { printf '{"phase": "%s", "event": "%s", "t": %s}\n' "$1" "$2" "$(date +%s)" >>"$OUT/logs/timings.jsonl"; }

# ---- inputs ----
if [[ $MODE == run ]]; then
    IN=$WORK_DIR/inputs
    mkdir -p "$IN"
    log "download s3://$BUCKET/p1/inputs/"
    s3 sync "s3://$BUCKET/p1/inputs/" "$IN/"
else
    IN=$LOCAL_INPUTS
fi
case "$IN/" in "$REPO"/*) die $EX_INPUTS "the inputs $IN lie inside the repository" ;; esac

verify_inputs() {
    local f
    [[ -f $IN/SHA256SUMS ]] || die $EX_INPUTS "$IN/SHA256SUMS is missing"
    for f in params-49333.npz params-0.npz params-3600.npz params-11000.npz teams.txt team_weights.txt; do
        [[ -f $IN/$f ]] || die $EX_INPUTS "input $f is missing"
    done
    [[ -f $IN/$LADDER_FILE ]] || die $EX_INPUTS "the ladder checkpoint LADDER_FILE=$LADDER_FILE is missing in the inputs (its name is set by M12/owner; upload it with its SHA256SUMS line or set LADDER_FILE)"
    [[ -d $IN/$TEAMS_DIR ]] || die $EX_INPUTS "the team registry $TEAMS_DIR/ is missing in the inputs"
    local pinned
    pinned=$(sha256sum "$IN/params-49333.npz" | cut -d' ' -f1)
    [[ $pinned == "$PARAMS_49333_SHA256" ]] || die $EX_INPUTS "params-49333.npz is $pinned, P1 pins $PARAMS_49333_SHA256"
    (cd "$IN" && sha256sum --check --strict --quiet SHA256SUMS) || die $EX_INPUTS "SHA256SUMS check failed"
    local listed present
    listed=$(awk '{p=$2; sub(/^\*/, "", p); sub(/^\.\//, "", p); print p}' "$IN/SHA256SUMS" | LC_ALL=C sort)
    present=$(cd "$IN" && find . -type f ! -name SHA256SUMS | sed 's#^\./##' | LC_ALL=C sort)
    if [[ $listed != "$present" ]]; then
        diff <(echo "$listed") <(echo "$present") | head -20 || true
        die $EX_INPUTS "SHA256SUMS does not list exactly the input files (lines '<': listed only, '>': present only)"
    fi
    log "inputs verified: $(echo "$present" | wc -l) files, params-49333 pinned, ladder $LADDER_FILE"
}
verify_inputs
TEAM_IDS=$(tr -d '\r\n' <"$IN/teams.txt")
TEAM_WEIGHTS=$(tr -d '\r\n' <"$IN/team_weights.txt")
TEAMS_ROOT=$IN/$TEAMS_DIR
INIT=$IN/params-49333.npz

# ---- the commit ----
HEAD_COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
COMMIT=${DUOFORGE_COMMIT:-$HEAD_COMMIT}
[[ $COMMIT =~ ^[0-9a-f]{40}$ ]] || die $EX_SETUP "no 40-digit commit (DUOFORGE_COMMIT or git HEAD of $REPO)"
if [[ -n $HEAD_COMMIT && $HEAD_COMMIT != "$COMMIT" ]]; then
    die $EX_SETUP "DUOFORGE_COMMIT $COMMIT is not the checked-out HEAD $HEAD_COMMIT"
fi
DIRTY=$(git -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null | wc -l) || DIRTY=unknown

# ---- setup: native library, Python, runtime environment ----
setup() {
    local tool
    for tool in cmake gcc g++ taskset flock sha256sum python3; do
        command -v "$tool" >/dev/null || die $EX_SETUP "$tool is not installed"
    done
    BUILD=$WORK_DIR/build
    local gen=()
    command -v ninja >/dev/null && gen=(-G Ninja)
    log "build duoforge_shared (Release) in $BUILD"
    timing build start
    cmake -S "$REPO" -B "$BUILD" "${gen[@]}" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF >"$OUT/logs/build-cmake.log" 2>&1 \
        || die $EX_SETUP "cmake configure failed (logs/build-cmake.log)"
    cmake --build "$BUILD" --target duoforge_shared --parallel "$(nproc)" >"$OUT/logs/build.log" 2>&1 \
        || die $EX_SETUP "build failed (logs/build.log)"
    timing build end
    LIB=$(find "$BUILD" -name 'libduoforge_shared.so*' -type f | head -1)
    [[ -n $LIB ]] || die $EX_SETUP "no libduoforge_shared.so in $BUILD"
    if [[ -n ${VENV:-} ]]; then
        log "Python from VENV=$VENV"
    else
        VENV=$WORK_DIR/venv
        if [[ ! -x $VENV/bin/python ]]; then
            command -v python3.12 >/dev/null || die $EX_SETUP "python3.12 is not installed"
            python3.12 -m venv "$VENV" || die $EX_SETUP "python3.12 -m venv failed (python3.12-venv?)"
        fi
        "$VENV/bin/pip" install --quiet --disable-pip-version-check numpy==2.5.3 "jax[cuda12]==0.11.2" optax==0.2.8 \
            >"$OUT/logs/pip.log" 2>&1 || die $EX_SETUP "pip install failed (logs/pip.log)"
    fi
    PY=$VENV/bin/python
    [[ -x $PY ]] || die $EX_SETUP "$PY is missing"

    # The runtime environment: identical for every phase of both arms (the collector adds JAX_PLATFORMS=cpu,
    # as its manifest pins device cpu). Written to the log and to run-info.
    unset JAX_PLATFORMS JAX_ENABLE_X64 XLA_PYTHON_CLIENT_MEM_FRACTION CUDA_VISIBLE_DEVICES
    export DUOFORGE_LIBRARY=$LIB
    export PYTHONPATH=$REPO/python
    export PYTHONDONTWRITEBYTECODE=1
    export XLA_FLAGS=--xla_gpu_deterministic_ops=true
    export XLA_PYTHON_CLIENT_PREALLOCATE=false
    # The platform allocator (cudaMalloc/cudaFree, no BFC pool): with the default pool and no preallocation, the
    # memory distill's held-out evaluation grew stays reserved, and loading the next kernel (jit__step) fails with
    # CUDA out of memory on an 8 GB card. Same for both arms (README_run.md).
    export XLA_PYTHON_CLIENT_ALLOCATOR=platform
    export OMP_NUM_THREADS=4
    export OPENBLAS_NUM_THREADS=4
    RUNTIME_ENV=(DUOFORGE_LIBRARY PYTHONPATH PYTHONDONTWRITEBYTECODE XLA_FLAGS XLA_PYTHON_CLIENT_PREALLOCATE
                 XLA_PYTHON_CLIENT_ALLOCATOR OMP_NUM_THREADS OPENBLAS_NUM_THREADS)
    local name
    for name in "${RUNTIME_ENV[@]}"; do log "env $name=${!name}"; done
    log "affinity taskset -c $AFFINITY, workers $WORKERS"

    "$PY" - <<'EOF' || die $EX_SETUP "the Python environment is not the pinned one or has no GPU (logs/run-$STARTED.log)"
import jax, optax, numpy, sys
want = {"jax": "0.11.2", "optax": "0.2.8", "numpy": "2.5.3"}
got = {"jax": jax.__version__, "optax": optax.__version__, "numpy": numpy.__version__}
bad = {k: (got[k], v) for k, v in want.items() if got[k] != v}
devices = jax.devices()
print("python env", got, devices)
if bad:
    sys.exit(f"versions differ from the pins: {bad}")
if devices[0].platform != "gpu":
    sys.exit(f"no GPU: JAX's default device is {devices[0]}")
EOF

    local info=$OUT/run-info/run-info-$STARTED.json
    RI_MODE=$MODE RI_COMMIT=$COMMIT RI_HEAD=$HEAD_COMMIT RI_DIRTY=$DIRTY RI_RUN_ID=${RUN_ID:-dry} \
    RI_WORKERS=$WORKERS RI_AFFINITY=$AFFINITY RI_LADDER=$LADDER_FILE RI_ENV="${RUNTIME_ENV[*]}" RI_IN=$IN \
    RI_SEEDS="collect=$COLLECT_SEED split=$COLLECT_SPLIT_SEED distill=$DISTILL_SEED control=$CONTROL_SEED eval=$EVAL_SEED eval_first_game_id=$EVAL_FIRST_GAME_ID" \
    RI_COMPILER="$(gcc --version | head -1); $(cmake --version | head -1)" \
        "$PY" - "$info" <<'EOF' || die $EX_SETUP "run-info failed"
import json, os, platform, subprocess, sys
import jax, jaxlib, optax, numpy
def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"unavailable: {err}"
sums = {}
with open(os.path.join(os.environ["RI_IN"], "SHA256SUMS")) as f:
    for line in f:
        sha, name = line.split(None, 1)
        sums[name.strip().lstrip("*")] = sha
info = {
    "mode": os.environ["RI_MODE"], "run_id": os.environ["RI_RUN_ID"], "commit": os.environ["RI_COMMIT"],
    "git_head": os.environ["RI_HEAD"], "tracked_changes": os.environ["RI_DIRTY"],
    "workers": int(os.environ["RI_WORKERS"]), "affinity": os.environ["RI_AFFINITY"],
    "ladder_file": os.environ["RI_LADDER"], "seeds": os.environ["RI_SEEDS"],
    "runtime_env": {k: os.environ.get(k) for k in os.environ["RI_ENV"].split()},
    "collector_extra_env": {"JAX_PLATFORMS": "cpu"},
    "versions": {"python": platform.python_version(), "jax": jax.__version__, "jaxlib": jaxlib.__version__,
                 "optax": optax.__version__, "numpy": numpy.__version__,
                 "jax_plugins": run([sys.executable, "-m", "pip", "list", "--format=freeze"]).splitlines()},
    "devices": [str(d) for d in jax.devices()], "compiler": os.environ["RI_COMPILER"],
    "platform": platform.platform(), "nproc": os.cpu_count(),
    "cpu": run(["sh", "-c", "grep -m1 'model name' /proc/cpuinfo"]),
    "gpu": run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
    "inputs_sha256": sums,
}
with open(sys.argv[1], "w") as f:
    json.dump(info, f, indent=1, sort_keys=True)
print("run-info", sys.argv[1])
EOF
}
setup
cd "$WORK_DIR"  # never the repository: no tool default may resolve into it

# ---- running a phase command: pinned affinity, logged, interruptible ----
# launch NAME STDOUT_FILE CMD...: stderr to logs/NAME.log, stdout to STDOUT_FILE (appended); returns the exit code.
launch() {
    local name=$1 stdout=$2; shift 2
    local rc=0 pid
    local shown="$*"
    shown=${shown//"$TEAM_IDS"/<teams.txt>}
    shown=${shown//"$TEAM_WEIGHTS"/<team_weights.txt>}
    log "phase $name: $shown"
    timing "$name" start
    taskset -c "$AFFINITY" "$@" >>"$stdout" 2>>"$OUT/logs/$name.log" &
    pid=$!
    echo "$pid" >"$WORK_DIR/phase.pid"
    wait "$pid" || rc=$?
    rm -f "$WORK_DIR/phase.pid"
    timing "$name" "end-$rc"
    log "phase $name: exit $rc"
    if [[ $rc -ne 0 && -e $WORK_DIR/INTERRUPTED ]]; then
        die $EX_INTERRUPTED "interrupted during $name"
    fi
    return "$rc"
}
# A tool's exit code: 2 is a refusal before work, 3 a signal stop (resume next start), else a crash.
tool_failed() {
    local name=$1 rc=$2
    case $rc in
        2) die $EX_REFUSED "$name refused its inputs (logs/$name.log)" ;;
        3) die $EX_INTERRUPTED "$name stopped by a signal; the next start resumes it" ;;
        *) die $EX_CRASH "$name crashed with exit $rc (logs/$name.log)" ;;
    esac
}
# A fresh start of a tool that wants an empty directory: a directory left without a resumable state is set aside.
set_aside() {
    local dir=$1
    if [[ -d $dir ]] && [[ -n $(ls -A "$dir") ]]; then
        local aside
        aside="$dir.aside-$(date -u +%Y%m%dT%H%M%SZ)"
        log "setting aside $dir (no resumable state) to $aside"
        mv "$dir" "$aside"
    fi
}
last_json() { { grep -E '^\{' "$1" 2>/dev/null || true; } | tail -1; }
json_get() { "$PY" -c 'import json,sys; v=json.loads(sys.argv[1]); [v := v[k] for k in sys.argv[2:]]; print(json.dumps(v) if isinstance(v,(dict,list,bool)) or v is None else v)' "$@"; }

PILOT_LEDGER=$OUT/ledgers/pilot.json
CONTROL_LEDGER=$OUT/ledgers/control.json
EVAL_LEDGER=$OUT/ledgers/eval.json

manifest_write() {  # ROLE ROUNDS FIRST_GAME_ID OUT
    local role=$1 rounds=$2 first=$3 out=$4
    [[ -f $out ]] && { log "manifest $out exists"; return 0; }
    local rc=0
    launch "manifest-$role" "$OUT/logs/manifest-$role.log" env JAX_PLATFORMS=cpu "$PY" "$HERE/p1_manifest.py" write \
        --init "$INIT" --out "$out" --rounds "$rounds" --first-game-id "$first" --workers "$WORKERS" \
        --seed "$COLLECT_SEED" --split-seed "$COLLECT_SPLIT_SEED" --source-commit "$COMMIT" --role "$role" \
        --compiler "$(gcc --version | head -1), Release" --teams "$TEAM_IDS" --team-weights "$TEAM_WEIGHTS" \
        --teams-root "$TEAMS_ROOT" || rc=$?
    [[ $rc -eq 0 ]] || die $EX_REFUSED "p1_manifest write ($role) failed with exit $rc (logs/manifest-$role.log)"
}

collect() {  # NAME DIR MANIFEST
    local name=$1 dir=$2 manifest=$3 rc=0
    mkdir -p "$dir"
    local args=(--init "$INIT" --manifest "$manifest" --out "$dir/data" --workers "$WORKERS" --teams "$TEAM_IDS"
                --team-weights "$TEAM_WEIGHTS" --teams-root "$TEAMS_ROOT" --ledger "$PILOT_LEDGER")
    local last
    last=$(last_json "$dir/result.jsonl")
    if [[ -n $last && $(json_get "$last" complete 2>/dev/null || true) == true ]]; then
        log "$name: complete already"; return 0
    fi
    if [[ -f $dir/data/collect-state.json ]]; then
        args+=(--resume)
    else
        set_aside "$dir/data"
    fi
    launch "$name" "$dir/result.jsonl" env JAX_PLATFORMS=cpu "$PY" -m duoforge_learn.collect_expert "${args[@]}" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed "$name" "$rc"
}

# ======== phase 1: collection ========
SMOKE=$OUT/collect-smoke
PROD=$OUT/collect-production
if ! marked collect-smoke; then
    manifest_write smoke 1 "$SMOKE_FIRST_GAME_ID" "$OUT/manifests/smoke.json"
    collect collect-smoke "$SMOKE" "$OUT/manifests/smoke.json"
    mark collect-smoke
fi
if ! marked freeze; then
    rc=0
    launch freeze "$OUT/manifests/freeze.stdout" "$PY" "$HERE/p1_manifest.py" freeze --smoke-json "$SMOKE/result.jsonl" \
        --ledger "$PILOT_LEDGER" --cpu-budget "$GENERATION_CPU_BUDGET" --out "$OUT/manifests/freeze.json" || rc=$?
    case $rc in
        0) ;;
        20) die $EX_SMOKE_T0 "the smoke gave t = 0 (manifests/freeze.json): STOP, re-plan" ;;
        21|22)
            if [[ $MODE == dry ]]; then
                log "dry run: freeze would STOP with $rc (manifests/freeze.json); continuing the rehearsal"
            elif [[ $rc -eq 21 ]]; then
                die $EX_GEN_BUDGET "the generation forecast exceeds $GENERATION_CPU_BUDGET CPU core-seconds: STOP"
            else
                die $EX_WORK_FALLBACK "primary work fallbacks above 1 % in the smoke: STOP"
            fi ;;
        *) die $EX_CRASH "p1_manifest freeze failed with exit $rc" ;;
    esac
    mark freeze
fi
ROUNDS=$(json_get "$(cat "$OUT/manifests/freeze.json")" rounds)
log "frozen production rounds R=$ROUNDS ($(json_get "$(cat "$OUT/manifests/freeze.json")" t_targets_per_game) targets/game)"

if [[ $MODE == run ]]; then
    if ! marked collect-production; then
        manifest_write production "$ROUNDS" "$PRODUCTION_FIRST_GAME_ID" "$OUT/manifests/production.json"
        collect collect-production "$PROD" "$OUT/manifests/production.json"
        result=$(last_json "$PROD/result.jsonl")
        targets=$(json_get "$result" targets)
        selected=$(json_get "$result" selected)
        exhausted=$(json_get "$result" work_exhausted)
        gen_cpu=$(json_get "$(cat "$PILOT_LEDGER")" phases generate cpu_core_seconds)
        (cd "$PROD/data/shards" && sha256sum -- *.json) >"$PROD/shards.sha256"
        log "production: targets $targets, selected $selected, work_exhausted $exhausted, generation CPU $gen_cpu s"
        "$PY" -c 'import sys; e, s = int(sys.argv[1]), int(sys.argv[2]); sys.exit(1 if s and e / s > 0.01 else 0)' \
            "$exhausted" "$selected" || die $EX_WORK_FALLBACK "primary work fallbacks above 1 % in production: STOP"
        "$PY" -c 'import sys; sys.exit(1 if float(sys.argv[1]) > float(sys.argv[2]) else 0)' "$gen_cpu" "$GENERATION_CPU_BUDGET" \
            || die $EX_GEN_BUDGET "generation CPU $gen_cpu s exceeds $GENERATION_CPU_BUDGET: STOP"
        [[ $targets -ge $LABELS ]] || die $EX_PROD_INCOMPLETE "production gave $targets < $LABELS targets: incomplete, re-plan"
        mark collect-production
    fi
    DISTILL_SHARDS=$PROD/data/shards
    DISTILL_MANIFEST=$OUT/manifests/production.json
else
    log "dry run: no production collection; distill reads the smoke's shards"
    (cd "$SMOKE/data/shards" && sha256sum -- *.json) >"$SMOKE/shards.sha256"
    DISTILL_SHARDS=$SMOKE/data/shards
    DISTILL_MANIFEST=$OUT/manifests/smoke.json
fi

# ======== phase 2: distillation (pilot arm) ========
DISTILL=$OUT/distill
if ! marked distill; then
    mkdir -p "$OUT/distill-meta"
    last=$(last_json "$OUT/distill-meta/result.jsonl")
    stop=$( [[ -n $last ]] && json_get "$last" stop 2>/dev/null || echo none)
    if [[ $stop != none && $stop != signal ]]; then
        log "distill: finished already ($last)"
    else
        args=(--init "$INIT" --reference "$INIT" --shards "$DISTILL_SHARDS" --manifest "$DISTILL_MANIFEST" --out "$DISTILL"
              --seed "$DISTILL_SEED" --ledger "$PILOT_LEDGER")
        if [[ -f $DISTILL/distill-state.npz ]]; then args+=(--resume); else set_aside "$DISTILL"; fi
        rc=0
        distill_env=()
        if [[ $MODE == dry && ${DRY_DISTILL_DEVICE:-gpu} == cpu ]]; then
            # Rehearsal only: distill's 4096-row step does not fit an 8 GB GPU (CUDA out of memory), so a local dry
            # run may put it on the CPU. A run never does.
            log "dry run: distill on the CPU (DRY_DISTILL_DEVICE=cpu)"
            distill_env=(JAX_PLATFORMS=cpu)
        fi
        launch distill "$OUT/distill-meta/result.jsonl" env "${distill_env[@]}" "$PY" -m duoforge_learn.distill "${args[@]}" || rc=$?
        [[ $rc -eq 0 ]] || tool_failed distill "$rc"
    fi
    [[ -f $DISTILL/params-best.npz ]] || die $EX_CRASH "distill finished without params-best.npz"
    sha256sum "$DISTILL/params-best.npz" >"$OUT/distill-meta/params-best.sha256"
    mark distill
fi

# ======== phase 3: continuation control ========
CONTROL=$OUT/control/run
mkdir -p "$OUT/control"
RECIPE=(--envs 256 --workers "$WORKERS" --rollout 32 --epochs 4 --minibatch 2048 --learning-rate 3e-4 --entropy 0.01
        --kl-ref magnet --kl-coef 0.05 --kl-refresh 500 --self-play-share 0.5 --league-slots 4 --slot-refresh 50
        --snapshot-every 200 --eval-every 100000 --eval-budget 1 --max-steps 500 --save-minutes 30
        --teams "$TEAM_IDS" --team-weights "$TEAM_WEIGHTS" --teams-root "$TEAMS_ROOT" --seed "$CONTROL_SEED")
if [[ $MODE == dry ]]; then CAL_A=2 CAL_B=4; else CAL_A=6 CAL_B=12; fi

state_update() {  # the update of the control's saved run state, 0 without one
    [[ -f $CONTROL/state.npz ]] || { echo 0; return; }
    "$PY" -c 'import sys; from duoforge_learn import runstate; print(runstate.load_state(sys.argv[1])["counters"]["update"])' "$CONTROL"
}
train() {  # NAME ARGS...
    local name=$1; shift
    local rc=0
    launch "$name" "$OUT/logs/$name.stdout" "$PY" -m duoforge_learn.train "$@" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed "$name" "$rc"
}

if ! marked control-cal-a; then
    if [[ -f $CONTROL/state.npz ]]; then
        if (( $(state_update) < CAL_A )); then
            train control-cal-a --resume "$CONTROL" --updates "$CAL_A" --update-gpu-share 0 --act-gpu-share 0
        fi
    else
        set_aside "$CONTROL"
        train control-cal-a --out "$CONTROL" --init "$INIT" --keep-init-encoder --ledger "$CONTROL_LEDGER" "${RECIPE[@]}" \
            --updates "$CAL_A" --update-gpu-share 0 --act-gpu-share 0
    fi
    mark control-cal-a
fi
if ! marked control-cal-b; then
    if (( $(state_update) < CAL_B )); then
        train control-cal-b --resume "$CONTROL" --updates "$CAL_B" --update-gpu-share 1 --act-gpu-share 0
    fi
    mark control-cal-b
fi
if ! marked control-match; then
    rc=0
    launch match "$OUT/control/match.stdout" "$PY" "$HERE/p1_match.py" --pilot-ledger "$PILOT_LEDGER" \
        --control-run "$CONTROL" --control-ledger "$CONTROL_LEDGER" --out "$OUT/control/match.json" || rc=$?
    cat "$OUT/control/match.json" 2>/dev/null || true
    case $rc in
        0) ;;
        3) if [[ $MODE == dry ]]; then log "dry run: matching INFEASIBLE (control/match.json); continuing the rehearsal"
           else die $EX_INFEASIBLE "the control cannot match the pilot's compute (control/match.json): STOP"; fi ;;
        *) die $EX_CRASH "p1_match failed with exit $rc" ;;
    esac
    mark control-match
fi

if [[ $MODE == run ]]; then
    if ! marked control-final; then
        mapfile -t FLAGS < <("$PY" -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["resume_flags"]))' "$OUT/control/match.json")
        last=$(grep -E '"update"' "$CONTROL/log.jsonl" | tail -1)
        if [[ $(json_get "$last" stopped 2>/dev/null || true) != budget ]]; then
            train control-final --resume "$CONTROL" "${FLAGS[@]}"
        fi
        last=$(grep -E '"update"' "$CONTROL/log.jsonl" | tail -1)
        [[ $(json_get "$last" stopped 2>/dev/null || true) == budget ]] \
            || die $EX_CONTROL_NO_BUDGET_STOP "the control ended without its ledger budget stop (last record: $last)"
        mark control-final
    fi
fi
if ! marked control-export; then
    rm -f "$OUT/control/params-final.npz"
    rc=0
    launch export "$OUT/control/export.json" "$PY" "$HERE/p1_export.py" "$CONTROL" "$OUT/control/params-final.npz" || rc=$?
    [[ $rc -eq 0 ]] || die $EX_CRASH "p1_export failed with exit $rc"
    mark control-export
fi
CONTROL_FINAL=$OUT/control/params-final.npz

if ! marked compute-check; then
    rc=0
    "$PY" - "$PILOT_LEDGER" "$CONTROL_LEDGER" "$OUT/control/compute-check.json" <<'EOF' || rc=$?
import json, sys
from duoforge_search import expert_eval
pilot, control = (expert_eval.ComputeLedger.from_mapping(json.load(open(p))) for p in sys.argv[1:3])
out = {"pilot": {"cpu_core_seconds": pilot.cpu_core_seconds, "gpu_seconds": pilot.gpu_seconds},
       "control": {"cpu_core_seconds": control.cpu_core_seconds, "gpu_seconds": control.gpu_seconds}}
try:
    expert_eval.validate_compute(pilot, control)
    out["status"] = "MATCH"
except ValueError as err:
    out["status"] = f"MISMATCH: {err}"
json.dump(out, open(sys.argv[3], "w"), indent=1)
print(json.dumps(out))
sys.exit(0 if out["status"] == "MATCH" else 31)
EOF
    if [[ $rc -ne 0 ]]; then
        if [[ $MODE == dry ]]; then log "dry run: compute check $(cat "$OUT/control/compute-check.json" 2>/dev/null) (expected: calibration only)"
        elif [[ $rc -eq 31 ]]; then die $EX_COMPUTE "the arms' compute differs by more than 5 % (control/compute-check.json): STOP"
        else die $EX_CRASH "the compute check failed with exit $rc"; fi
    fi
    [[ $MODE == dry ]] || mark compute-check
fi

# ======== phase 4: evaluation ========
EVAL=$OUT/eval
mkdir -p "$EVAL"
"$PY" -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("duoforge_search.eval_manifest") is None)' \
    || die $EX_NO_M12_TOOL "M12's python -m duoforge_search.eval_manifest is not in this commit"
CHECKPOINTS=(--checkpoint "pilot=$DISTILL/params-best.npz" --checkpoint "control=$CONTROL_FINAL"
             --checkpoint "frozen=$INIT" --checkpoint "BC=$IN/params-0.npz" --checkpoint "3600=$IN/params-3600.npz"
             --checkpoint "11000=$IN/params-11000.npz" --checkpoint "ladder=$IN/$LADDER_FILE")
if [[ ! -f $EVAL/manifest.json ]]; then
    rc=0
    launch eval-manifest "$EVAL/manifest.stdout" "$PY" -m duoforge_search.eval_manifest --teams "$TEAM_IDS" \
        --team-weights "$TEAM_WEIGHTS" --teams-root "$TEAMS_ROOT" --seed "$EVAL_SEED" --first-game-id "$EVAL_FIRST_GAME_ID" \
        "${CHECKPOINTS[@]}" --out "$EVAL/manifest.json" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed eval-manifest "$rc"
fi
EVAL_ARGS=(--manifest "$EVAL/manifest.json" "${CHECKPOINTS[@]}" --teams "$TEAM_IDS" --team-weights "$TEAM_WEIGHTS"
           --teams-root "$TEAMS_ROOT" --workers "$WORKERS" --ledger "$EVAL_LEDGER")
if [[ ! -f $EVAL/smoke.json ]]; then
    rc=0
    launch eval-smoke "$EVAL/smoke.stdout" "$PY" -m duoforge_learn.p1_eval "${EVAL_ARGS[@]}" --smoke --out "$EVAL/smoke.json" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed eval-smoke "$rc"
fi
status=$(json_get "$(cat "$EVAL/smoke.json")" status)
log "evaluation smoke: $status $(json_get "$(cat "$EVAL/smoke.json")" stop_reasons)"
[[ $status == GO ]] || die $EX_EVAL_SMOKE "the evaluation smoke says $status (eval/smoke.json): STOP before the evaluation"
if [[ $MODE == dry ]]; then
    log "dry run complete (the full evaluation and expert_eval are not part of the rehearsal)"
    exit $EX_DONE
fi
if [[ ! -f $EVAL/B.json ]]; then
    rc=0
    launch eval-full "$EVAL/full.stdout" "$PY" -m duoforge_learn.p1_eval "${EVAL_ARGS[@]}" --out "$EVAL/B.json" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed eval-full "$rc"
fi
if [[ ! -f $EVAL/REPORT.json ]]; then
    rc=0
    launch expert-eval "$EVAL/expert_eval.stdout" "$PY" -m duoforge_search.expert_eval --manifest "$EVAL/manifest.json" \
        --pilot "$PILOT_LEDGER" --control "$CONTROL_LEDGER" --baseline "$EVAL/B.json" --out "$EVAL/REPORT.json" || rc=$?
    [[ $rc -eq 0 ]] || die $EX_EXPERT_EVAL "expert_eval refused (exit $rc, logs/expert-eval.log)"
fi
log "report status: $(json_get "$(cat "$EVAL/REPORT.json")" status)"
mark done
exit $EX_DONE
