#!/bin/bash
# Learner v2 measurement night (plan Task 20), run in WSL. Steps:
#   ab           the PPO update A/B: night configuration (v1, Teams A and B, self-play), host vs scan, 3 x 300 updates
#   ingredients  act on GPU vs CPU per model (double-buffering)
#   runs         v2-S (stopped by SIGTERM at update 2300 and resumed), v1, v2-M, v2-L on A/B/C, 4600 updates each
#   ladder       cross ladder over the four runs
# usage: night.sh <run root> <step...>
set -u
SRC=/mnt/c/Dev/src/duoforge/.claude/worktrees/cranky-aryabhata-d5b498
W=$SRC/.superpowers/sdd/2026-10-02-learner-v2
R=$1; shift
mkdir -p "$R"
# A frozen copy of the code: edits to the worktree during the night change nothing.
if [ ! -d "$R/src" ]; then
  mkdir -p "$R/src/data" "$R/src/w"
  cp -r "$SRC/python" "$R/src/python" && cp -r "$SRC/data/teams" "$R/src/data/teams"
  cp "$W"/ab_train.py "$W"/ingredients.py "$R/src/w/"
  cp "$HOME/df-build/learnv2/libduoforge_shared.so" "$R/src/"
  echo "${COMMIT:-unknown}" > "$R/src/COMMIT"
fi
W=$R/src/w
cd "$R/src"
export DUOFORGE_LIBRARY=$R/src/libduoforge_shared.so
export PYTHONPATH=python PYTHONDONTWRITEBYTECODE=1
PY=$HOME/df-learn/bin/python
mkdir -p "$R"
log() { echo "$(date '+%F %T') $*" | tee -a "$R/night.log"; }
UPDATES=${UPDATES:-4600} STOP_AT=${STOP_AT:-2300} AB_UPDATES=${AB_UPDATES:-300} EVERY=${EVERY:-200}
COMMON=(--teams A,B,C --data-kind team_c --envs 256 --workers 8 --rollout 32 --minibatch 2048 --updates $UPDATES
        --minutes 0 --eval-every $EVERY --snapshot-every $EVERY --entropy 0:0.02,50M:0.005)

for step in "$@"; do
  case $step in
  ab)
    mkdir -p "$R/ab"
    for rep in 1 2 3; do for arm in host scan; do
      log "ab $arm $rep start"
      $PY "$W/ab_train.py" $arm --envs 256 --workers 8 --rollout 32 --updates $AB_UPDATES --minutes 0 --eval-every 100000 \
          --self-play-share 1.0 --snapshot-every 100000 --out "$R/ab/$arm-$rep" > "$R/ab/$arm-$rep.out" 2>&1
      log "ab $arm $rep exit $?"
    done; done ;;
  ingredients)
    log "ingredients start"
    $PY "$W/ingredients.py" > "$R/ingredients.jsonl" 2> "$R/ingredients.err"
    log "ingredients exit $?" ;;
  runs)
    log "v2-S start"
    $PY -m duoforge_learn.train --model v2 --preset S "${COMMON[@]}" --out "$R/v2-S" > "$R/v2-S.out" 2>&1 &
    pid=$!
    until grep -q "\"update\": $STOP_AT," "$R/v2-S/log.jsonl" 2>/dev/null || ! kill -0 $pid 2>/dev/null; do sleep 5; done
    kill -TERM $pid; wait $pid; log "v2-S stopped by SIGTERM, exit $?"
    $PY -m duoforge_learn.train --resume "$R/v2-S" >> "$R/v2-S.out" 2>&1
    log "v2-S resumed, exit $?"
    for m in "v1:--model v1" "v2-M:--model v2 --preset M" "v2-L:--model v2 --preset L"; do
      name=${m%%:*}; args=${m#*:}
      log "$name start"
      $PY -m duoforge_learn.train $args "${COMMON[@]}" --out "$R/$name" > "$R/$name.out" 2>&1
      log "$name exit $?"
    done ;;
  ladder)
    log "ladder start"
    $PY -m duoforge_learn.ladder "$R/v1" "$R/v2-S" "$R/v2-M" "$R/v2-L" --pick 4 --games 2 --workers 8 \
        --out "$R/ladder" > "$R/ladder.out" 2>&1
    log "ladder exit $?" ;;
  *) log "unknown step $step"; exit 2 ;;
  esac
done
log "done"
