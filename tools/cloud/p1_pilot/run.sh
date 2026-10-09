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
EX_INFEASIBLE=30 EX_COMPUTE=31 EX_CONTROL_NO_BUDGET_STOP=32 EX_CALIBRATION_CAP=33
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

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO=$(cd "$HERE/../../.." && pwd -P)

MODE=run
LOCAL_INPUTS=
case "${1:-}" in
    "") ;;
    --check-env)
        MODE=check
        [[ $# -eq 1 ]] || { echo "run.sh --check-env takes no argument" >&2; exit $EX_USAGE; }
        ;;
    --dry-run)
        MODE=dry
        LOCAL_INPUTS=${2:-}
        [[ -n $LOCAL_INPUTS && -d $LOCAL_INPUTS ]] || { echo "usage: run.sh --dry-run LOCAL_INPUTS_DIR" >&2; exit $EX_USAGE; }
        LOCAL_INPUTS=$(cd "$LOCAL_INPUTS" && pwd -P)
        [[ $# -eq 2 ]] || { echo "run.sh --dry-run takes one directory" >&2; exit $EX_USAGE; }
        ;;
    --on-interrupt)
        MODE=interrupt
        [[ $# -eq 1 ]] || { echo "run.sh --on-interrupt takes no argument" >&2; exit $EX_USAGE; }
        ;;
    *) echo "usage: run.sh [--dry-run LOCAL_INPUTS_DIR | --on-interrupt | --check-env]" >&2; exit $EX_USAGE ;;
esac

log() { printf '%s run.sh: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { local code=$1; shift; log "EXIT $code: $*"; exit "$code"; }

# BUCKET, RUN_PREFIX and RUN_ID of a run (and of --on-interrupt): RUN_ID is one path segment that cannot be read as
# another prefix (no leading '.', not "inputs"), and RUN_PREFIX is exactly p1/<RUN_ID>/.
require_cloud_env() {
    [[ -n ${BUCKET:-} && -n ${RUN_PREFIX:-} && -n ${RUN_ID:-} ]] || die $EX_USAGE "BUCKET, RUN_PREFIX and RUN_ID are required"
    [[ $RUN_ID =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]] \
        || die $EX_USAGE "RUN_ID must start with a letter, digit, _ or - and hold only letters, digits, . _ - (got '$RUN_ID')"
    [[ $RUN_ID != inputs ]] || die $EX_USAGE "RUN_ID 'inputs' is the inputs prefix"
    [[ $RUN_PREFIX == "p1/$RUN_ID/" ]] || die $EX_USAGE "RUN_PREFIX must be p1/<RUN_ID>/ (got '$RUN_PREFIX', RUN_ID '$RUN_ID')"
}
# The earlier starts recorded in OUT/run-info must be this run: the same WORK_DIR (the tools' states hold absolute
# paths), RUN_ID and mode, so a new RUN_ID, or a run after a dry run in the same WORK_DIR, never inherits markers or
# outputs. Exit 11 otherwise.
check_earlier_starts() {  # OUT WORK_DIR RUN_ID MODE
    local out=$1 work=$2 run_id=$3 mode=$4 info key want got
    for info in "$out"/run-info/run-info-*.json; do
        [[ -f $info ]] || continue
        for key in work_dir run_id mode; do
            case $key in work_dir) want=$work ;; run_id) want=$run_id ;; mode) want=$mode ;; esac
            got=$(sed -n "s/^ *\"$key\": \"\(.*\)\",\{0,1\}\$/\1/p" "$info")
            [[ -z $got || $got == "$want" ]] \
                || die $EX_SETUP "$(basename "$info") of an earlier start has $key '$got', this start '$want': use a fresh WORK_DIR (or the earlier run's settings)"
        done
    done
}
if [[ $MODE == check ]]; then  # the environment checks alone: no aws call; with WORK_DIR set, also its earlier starts
    require_cloud_env
    if [[ -n ${WORK_DIR:-} && -d $WORK_DIR ]]; then
        check_earlier_starts "$(cd "$WORK_DIR" && pwd -P)/out" "$(cd "$WORK_DIR" && pwd -P)" "$RUN_ID" run
    fi
    echo "run.sh: BUCKET, RUN_PREFIX and RUN_ID are valid"
    exit 0
fi

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
WORK_DIR=$(cd "$WORK_DIR" && pwd -P)
OUT=$WORK_DIR/out
case "$WORK_DIR/" in "$REPO"/*) echo "WORK_DIR $WORK_DIR lies inside the repository $REPO" >&2; exit $EX_USAGE ;; esac

# The only AWS calls this script makes: aws s3 cp / sync / ls, never in a dry run.
s3() {
    [[ $MODE != dry ]] || { log "internal error: an aws call in a dry run: s3 $*"; exit $EX_CRASH; }
    case "${1:-}" in cp|sync|ls) ;; *) log "internal error: aws s3 $1 is not allowed"; exit $EX_CRASH ;; esac
    aws s3 "$@" --only-show-errors
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
rm -f "$WORK_DIR/INTERRUPTED" "$WORK_DIR/phase.pid" "$WORK_DIR/.restored"
mkdir -p "$OUT"/{logs,markers,manifests,ledgers,run-info,status}
STARTED=$(date -u +%Y%m%dT%H%M%SZ)
# One log per start: the restore below may replace files of out/logs with their uploaded copies. fds 3/4 keep the
# console, so on_exit can close the tee (and wait for it) before the final upload.
exec 3>&1 4>&2
exec > >(tee -a "$OUT/logs/run-$STARTED.log") 2>&1
TEE_PID=$!
log "start mode=$MODE work=$WORK_DIR repo=$REPO"

# Waits up to INTERRUPT_WAIT seconds for the phase process (if any) to exit.
wait_phase() {
    local child
    [[ -f $WORK_DIR/phase.pid ]] || return 0
    child=$(cat "$WORK_DIR/phase.pid")
    kill -0 "$child" 2>/dev/null || return 0
    kill -TERM "$child" 2>/dev/null || true
    for _ in $(seq "$INTERRUPT_WAIT"); do kill -0 "$child" 2>/dev/null || return 0; sleep 1; done
    log "phase process $child still running after ${INTERRUPT_WAIT}s"
}

on_exit() {
    local code=$?
    trap '' TERM INT
    trap - EXIT
    local meaning
    case $code in
        0) meaning=done ;; 1) meaning=crash ;; 2) meaning=usage ;; 10) meaning=input-sha-mismatch-or-missing ;;
        11) meaning=setup-failed ;; 13) meaning=phase-cli-refusal ;; 20) meaning=smoke-t0 ;;
        21) meaning=generation-cpu-budget ;; 22) meaning=work-fallback-above-1pct ;; 23) meaning=production-incomplete ;;
        30) meaning=matching-infeasible ;; 31) meaning=compute-mismatch ;; 32) meaning=control-no-budget-stop ;;
        33) meaning=calibration-over-cap ;; 40) meaning=eval-smoke-stop ;; 41) meaning=expert-eval-refusal ;;
        50) meaning=missing-m12-tool ;; 60) meaning=interrupted ;; *) meaning=unknown ;;
    esac
    if [[ -n ${UPLOADER:-} ]]; then  # with its children: its sleep would hold the log pipe open
        pkill -TERM -P "$UPLOADER" 2>/dev/null || true
        kill "$UPLOADER" 2>/dev/null || true
    fi
    wait_phase  # the phase saves its state on SIGTERM; upload only after it has
    printf '{"exit": %d, "meaning": "%s", "mode": "%s", "started": "%s", "ended": "%s"}\n' \
        "$code" "$meaning" "$MODE" "$STARTED" "$(date -u +%Y%m%dT%H%M%SZ)" | tee "$OUT/status/exit-$STARTED.json" >"$OUT/STATUS.json"
    log "exit $code ($meaning)"
    exec 1>&3 2>&4  # close the tee, so the run log is complete before it is uploaded
    for _ in $(seq 10); do kill -0 "$TEE_PID" 2>/dev/null || break; sleep 1; done
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
check_earlier_starts "$OUT" "$WORK_DIR" "${RUN_ID:-dry}" "$MODE"
touch "$WORK_DIR/.restored"
if [[ $MODE == run ]]; then  # long phases (production collection, the control) upload their progress meanwhile
    ( trap - EXIT TERM INT; while true; do sleep "$UPLOAD_EVERY" & wait $!; upload_state || log "periodic upload failed"; done ) &
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

# ---- per-phase runtime environment (added to setup's shared base) ----
# collector: JAX on the CPU, as its manifest pins device cpu.
# training phases of both arms (distill; the control's calibration and matched run): the platform allocator
#   (cudaMalloc/cudaFree, no pool). With the default pool and PREALLOCATE=false, distill's held-out evaluation leaves
#   its pool reserved and loading jit__step fails with a CUBIN-load CUDA out of memory on an 8 GB card. Both arms'
#   training phases share it, so their GPU-seconds compare fairly.
# evaluation (eval_manifest, p1_eval smoke and full): a shared phase charged half to each arm, so its allocator does
#   not bias the comparison: JAX's default pool allocator (about 5x the games/s of the platform one in the dry run).
PHASE_ENV_COLLECT=(JAX_PLATFORMS=cpu)
PHASE_ENV_TRAIN=(XLA_PYTHON_CLIENT_ALLOCATOR=platform)
PHASE_ENV_EVAL=()

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

    # The runtime environment: one shared base for every phase, plus a per-phase addition (PHASE_ENV_*, above).
    # Written to the log and to run-info.
    unset JAX_PLATFORMS JAX_ENABLE_X64 XLA_PYTHON_CLIENT_MEM_FRACTION XLA_PYTHON_CLIENT_ALLOCATOR CUDA_VISIBLE_DEVICES
    export DUOFORGE_LIBRARY=$LIB
    export PYTHONPATH=$REPO/python
    export PYTHONDONTWRITEBYTECODE=1
    export XLA_FLAGS=--xla_gpu_deterministic_ops=true
    export XLA_PYTHON_CLIENT_PREALLOCATE=false
    export OMP_NUM_THREADS=4
    export OPENBLAS_NUM_THREADS=4
    RUNTIME_ENV=(DUOFORGE_LIBRARY PYTHONPATH PYTHONDONTWRITEBYTECODE XLA_FLAGS XLA_PYTHON_CLIENT_PREALLOCATE
                 OMP_NUM_THREADS OPENBLAS_NUM_THREADS)
    local name
    for name in "${RUNTIME_ENV[@]}"; do log "env $name=${!name}"; done
    log "env collector: ${PHASE_ENV_COLLECT[*]}"
    log "env training (distill, control calibration and matched run): ${PHASE_ENV_TRAIN[*]}"
    log "env evaluation (eval_manifest, p1_eval smoke and full): ${PHASE_ENV_EVAL[*]:-nothing added (the default BFC allocator of JAX)}"
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
    # Every tool of every phase must come from this one commit: M12's evaluation manifest CLI is checked before any
    # phase runs, never after hours of training.
    "$PY" -c 'import duoforge_search.eval_manifest' \
        || die $EX_NO_M12_TOOL "M12's duoforge_search.eval_manifest is not importable from this commit: no phase is run"

    local info=$OUT/run-info/run-info-$STARTED.json
    RI_MODE=$MODE RI_COMMIT=$COMMIT RI_HEAD=$HEAD_COMMIT RI_DIRTY=$DIRTY RI_RUN_ID=${RUN_ID:-dry} RI_WORK=$WORK_DIR \
    RI_WORKERS=$WORKERS RI_AFFINITY=$AFFINITY RI_LADDER=$LADDER_FILE RI_ENV="${RUNTIME_ENV[*]}" RI_IN=$IN \
    RI_PHASE_COLLECT="${PHASE_ENV_COLLECT[*]}" RI_PHASE_TRAIN="${PHASE_ENV_TRAIN[*]}" RI_PHASE_EVAL="${PHASE_ENV_EVAL[*]}" \
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
    "git_head": os.environ["RI_HEAD"], "tracked_changes": os.environ["RI_DIRTY"], "work_dir": os.environ["RI_WORK"],
    "workers": int(os.environ["RI_WORKERS"]), "affinity": os.environ["RI_AFFINITY"],
    "ladder_file": os.environ["RI_LADDER"], "seeds": os.environ["RI_SEEDS"],
    "runtime_env": {k: os.environ.get(k) for k in os.environ["RI_ENV"].split()},
    "phase_env": {phase: dict(kv.split("=", 1) for kv in os.environ[f"RI_PHASE_{phase.upper()}"].split())
                  for phase in ("collect", "train", "eval")},
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
    [[ ! -e $WORK_DIR/INTERRUPTED ]] || die $EX_INTERRUPTED "interrupted: $name is not started"
    log "phase $name: $shown"
    timing "$name" start
    taskset -c "$AFFINITY" "$@" >>"$stdout" 2>>"$OUT/logs/$name.log" &
    pid=$!
    echo "$pid" >"$WORK_DIR/phase.pid"
    wait "$pid" || rc=$?
    rm -f "$WORK_DIR/phase.pid"
    timing "$name" "end-$rc"
    log "phase $name: exit $rc"
    # An interrupt decides, whatever the exit code: train answers SIGTERM by saving and exiting 0, which must not
    # count as a finished phase.
    [[ ! -e $WORK_DIR/INTERRUPTED ]] || die $EX_INTERRUPTED "interrupted during $name (exit $rc); the next start resumes"
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
    launch "manifest-$role" "$OUT/logs/manifest-$role.log" env "${PHASE_ENV_COLLECT[@]}" "$PY" "$HERE/p1_manifest.py" write \
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
    launch "$name" "$dir/result.jsonl" env "${PHASE_ENV_COLLECT[@]}" "$PY" -m duoforge_learn.collect_expert "${args[@]}" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed "$name" "$rc"
}

# ---- evaluation manifest + p1_eval smoke (used twice: before training with stand-ins, after it for real) ----
# eval_smoke NAME DIR PILOT CONTROL: writes DIR/manifest.json (eval_manifest, once) and DIR/smoke.json (p1_eval
# --smoke, once; its compute goes to the shared evaluation ledger), STOPs (exit 40) unless the smoke says GO, and
# leaves the --checkpoint arguments in EVAL_CHECKPOINTS.
eval_smoke() {
    local name=$1 dir=$2 pilot=$3 control=$4 rc=0
    mkdir -p "$dir"
    EVAL_CHECKPOINTS=(--checkpoint "pilot=$pilot" --checkpoint "control=$control" --checkpoint "frozen=$INIT"
                      --checkpoint "BC=$IN/params-0.npz" --checkpoint "3600=$IN/params-3600.npz"
                      --checkpoint "11000=$IN/params-11000.npz" --checkpoint "ladder=$IN/$LADDER_FILE")
    if [[ ! -f $dir/manifest.json ]]; then
        launch "$name-manifest" "$dir/manifest.stdout" env "${PHASE_ENV_EVAL[@]}" "$PY" -m duoforge_search.eval_manifest \
            --teams "$TEAM_IDS" --team-weights "$TEAM_WEIGHTS" --teams-root "$TEAMS_ROOT" --seed "$EVAL_SEED" \
            --first-game-id "$EVAL_FIRST_GAME_ID" "${EVAL_CHECKPOINTS[@]}" --out "$dir/manifest.json" || rc=$?
        [[ $rc -eq 0 ]] || tool_failed "$name-manifest" "$rc"
    fi
    if [[ ! -f $dir/smoke.json ]]; then
        launch "$name-smoke" "$dir/smoke.stdout" env "${PHASE_ENV_EVAL[@]}" "$PY" -m duoforge_learn.p1_eval \
            --manifest "$dir/manifest.json" "${EVAL_CHECKPOINTS[@]}" --teams "$TEAM_IDS" --team-weights "$TEAM_WEIGHTS" \
            --teams-root "$TEAMS_ROOT" --workers "$WORKERS" --ledger "$EVAL_LEDGER" --smoke --out "$dir/smoke.json" || rc=$?
        [[ $rc -eq 0 ]] || tool_failed "$name-smoke" "$rc"
    fi
    local status
    status=$(json_get "$(cat "$dir/smoke.json")" status)
    log "$name smoke: $status $(json_get "$(cat "$dir/smoke.json")" stop_reasons)"
    [[ $status == GO ]] || die $EX_EVAL_SMOKE "the $name smoke says $status ($dir/smoke.json): STOP"
}

# ======== phase 0: pre-training evaluation smoke ========
# Throughput, JIT and cut-offs of the evaluation before any training spend (plan C5: "STOP/re-plan before training").
# params-49333 stands in for pilot and control; its manifest (eval-pretrain/manifest.json) is never used for the gate.
# The post-training smoke (phase 4) checks the real students again.
if ! marked eval-pretrain; then
    eval_smoke eval-pretrain "$OUT/eval-pretrain" "$INIT" "$INIT"
    mark eval-pretrain
fi

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
        distill_env=("${PHASE_ENV_TRAIN[@]}")
        if [[ $MODE == dry && ${DRY_DISTILL_DEVICE:-gpu} == cpu ]]; then
            # Rehearsal only: distill's 4096-row step does not fit an 8 GB GPU (CUDA out of memory), so a local dry
            # run may put it on the CPU. A run never does.
            log "dry run: distill on the CPU (DRY_DISTILL_DEVICE=cpu)"
            distill_env+=(JAX_PLATFORMS=cpu)
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
# p1_match skips the first update of every process (its JIT): a block keeps a warm update through one interrupt.
if [[ $MODE == dry ]]; then CAL_A=3 CAL_B=6; else CAL_A=6 CAL_B=12; fi

state_update() {  # the update of the control's saved run state, 0 without one
    [[ -f $CONTROL/state.npz ]] || { echo 0; return; }
    "$PY" -c 'import sys; from duoforge_learn import runstate; print(runstate.load_state(sys.argv[1])["counters"]["update"])' "$CONTROL"
}
train() {  # NAME ARGS...
    local name=$1; shift
    local rc=0
    launch "$name" "$OUT/logs/$name.stdout" env "${PHASE_ENV_TRAIN[@]}" "$PY" -m duoforge_learn.train "$@" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed "$name" "$rc"
}

reached() {  # NAME UPDATES: the saved run state must hold exactly that many updates (a signal or --minutes cut fails)
    local got
    got=$(state_update)
    [[ $got -eq $2 ]] || die $EX_CRASH "$1: the control's saved state is at update $got, not $2 (cut short; the next start resumes)"
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
    reached control-cal-a "$CAL_A"
    mark control-cal-a
fi
if ! marked control-cal-b; then
    if (( $(state_update) < CAL_B )); then
        train control-cal-b --resume "$CONTROL" --updates "$CAL_B" --update-gpu-share 1 --act-gpu-share 0
    fi
    reached control-cal-b "$CAL_B"
    mark control-cal-b
fi
# The matching, with extra calibration blocks while a device has no warm update (p1_match exit 5): each extra block
# is its own train process of p1_match.EXTRA_UPDATES updates on that device, at most p1_match.MAX_EXTRA per device,
# all charged to the control ledger and counted against the 10 % cap. The blocks played are in
# control/extra-calibration.json, so a restart neither repeats nor forgets one.
# Dry run only: a STOP here (INFEASIBLE, over the cap, extras exhausted; expected without a production phase) is
# reported, and the rehearsal goes on without the matched run: the export takes the calibrated state.
EXTRAS=$OUT/control/extra-calibration.json
match_stop() {  # CODE MESSAGE
    if [[ $MODE == dry ]]; then log "dry run: $2 (control/match.json); continuing without the matched run"
    else die "$1" "$2 (control/match.json): STOP"; fi
}
if ! marked control-match; then
    while true; do
        rc=0
        launch match "$OUT/control/match.stdout" "$PY" "$HERE/p1_match.py" --pilot-ledger "$PILOT_LEDGER" \
            --control-run "$CONTROL" --control-ledger "$CONTROL_LEDGER" --extras "$EXTRAS" \
            --out "$OUT/control/match.json" || rc=$?
        case $rc in
            0) break ;;
            3) match_stop $EX_INFEASIBLE "the control cannot match the pilot's compute"; break ;;
            4) match_stop $EX_CALIBRATION_CAP "the calibration spent more than 10 % of a pilot axis"; break ;;
            5) next=$(json_get "$(cat "$OUT/control/match.json")" next_extra)
               device=$(json_get "$next" device 2>/dev/null || true)
               if [[ -z $device ]]; then
                   match_stop $EX_INFEASIBLE "no warm calibration update on $(json_get "$next" exhausted) after the extra blocks"
                   break
               fi
               share=$(json_get "$next" update_gpu_share)
               target=$(( $(state_update) + $(json_get "$next" updates) ))
               log "calibrate more: $device has no warm update; extra block to update $target"
               [[ ! -e $WORK_DIR/INTERRUPTED ]] || die $EX_INTERRUPTED "interrupted before an extra calibration block"
               # The count first: a crash inside the block then counts it too (the bound holds across restarts).
               "$PY" -c 'import json, sys, pathlib; p = pathlib.Path(sys.argv[1]); d = json.loads(p.read_text()) if p.exists() else {}; d[sys.argv[2]] = d.get(sys.argv[2], 0) + 1; p.write_text(json.dumps(d))' \
                   "$EXTRAS" "$device"
               train "control-cal-extra-$device" --resume "$CONTROL" --updates "$target" --update-gpu-share "$share" \
                   --act-gpu-share 0
               reached "control-cal-extra-$device" "$target"
               ;;
            *) die $EX_CRASH "p1_match failed with exit $rc" ;;
        esac
    done
    cat "$OUT/control/match.json"
    mark control-match
fi

# "Budget reached" from the saved run: the control's ledger file (saved together with its state) against the stops
# p1_match set. Exit 0 yes, 1 no.
budget_reached() {
    "$PY" - "$CONTROL_LEDGER" "$OUT/control/match.json" <<'EOF'
import json, sys
ledger, match = (json.load(open(p)) for p in sys.argv[1:3])
stop_c, stop_g = match["pilot"]["cpu_core_seconds"], match["pilot"]["gpu_seconds"]
hit = ledger["cpu_core_seconds"] >= stop_c or (stop_g > 0 and ledger["gpu_seconds"] >= stop_g)
print(f"control ledger cpu {ledger['cpu_core_seconds']:.1f} / stop {stop_c:.1f}, gpu {ledger['gpu_seconds']:.1f} / "
      f"stop {stop_g:.1f}: {'reached' if hit else 'not reached'}")
sys.exit(0 if hit else 1)
EOF
}
if [[ $MODE == run ]]; then
    if ! marked control-final; then
        mapfile -t FLAGS < <("$PY" -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["resume_flags"]))' "$OUT/control/match.json")
        (( ${#FLAGS[@]} > 0 )) && [[ -n ${FLAGS[0]} ]] || die $EX_CRASH "control/match.json gives no resume flags"
        if ! budget_reached; then
            train control-final --resume "$CONTROL" "${FLAGS[@]}"
        fi
        budget_reached || die $EX_CONTROL_NO_BUDGET_STOP "the control ended without reaching its ledger budget (logs/control-final.log)"
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
eval_smoke eval "$EVAL" "$DISTILL/params-best.npz" "$CONTROL_FINAL"  # the real students: the gate's manifest
EVAL_ARGS=(--manifest "$EVAL/manifest.json" "${EVAL_CHECKPOINTS[@]}" --teams "$TEAM_IDS" --team-weights "$TEAM_WEIGHTS"
           --teams-root "$TEAMS_ROOT" --workers "$WORKERS" --ledger "$EVAL_LEDGER")
if [[ $MODE == dry ]]; then
    log "dry run complete (the full evaluation and expert_eval are not part of the rehearsal)"
    exit $EX_DONE
fi
if [[ ! -f $EVAL/B.json ]]; then
    rc=0
    launch eval-full "$EVAL/full.stdout" env "${PHASE_ENV_EVAL[@]}" "$PY" -m duoforge_learn.p1_eval "${EVAL_ARGS[@]}" --out "$EVAL/B.json" || rc=$?
    [[ $rc -eq 0 ]] || tool_failed eval-full "$rc"
fi
if [[ ! -f $EVAL/REPORT.json ]]; then
    rc=0
    launch expert-eval "$EVAL/expert_eval.stdout" "$PY" -m duoforge_search.expert_eval --manifest "$EVAL/manifest.json" \
        --pilot "$PILOT_LEDGER" --control "$CONTROL_LEDGER" --baseline "$EVAL/B.json" --out "$EVAL/REPORT.json" || rc=$?
    case $rc in
        0) ;;
        2) die $EX_EXPERT_EVAL "expert_eval refused (exit 2, logs/expert-eval.log)" ;;
        *) die $EX_CRASH "expert_eval crashed with exit $rc (logs/expert-eval.log)" ;;
    esac
fi
log "report status: $(json_get "$(cat "$EVAL/REPORT.json")" status)"
mark done
exit $EX_DONE
