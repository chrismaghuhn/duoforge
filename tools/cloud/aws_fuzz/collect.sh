#!/usr/bin/env bash
# Downloads the results of a fuzz campaign and reproduces every kept case on this machine
# (tools/cloud/aws_fuzz/README.md): a finding of the cloud counts only once the local engine and the local converter
# say the same about the same spec and trace.
#
# usage: collect.sh --campaign ID --run RUN_ID --bucket B --runner <duoforge_diff_runner> [--out DIR] [--allow-other-commit]
#   --campaign  the campaign id
#   --run       the run (printed by launch.sh; without it the runs of the campaign are listed)
#   --bucket    the results bucket (default $DUOFORGE_FUZZ_BUCKET)
#   --runner    the local build of the differential runner (default $DUOFORGE_DIFF_RUNNER)
#   --out       where the results go (default build/fuzz/<campaign> under the repository)
#   --allow-other-commit  replay even if this checkout is not the commit that the campaign ran
# Reads s3://<bucket>/fuzz/<campaign>/<run>/ (s3:ListBucket and s3:GetObject; nothing is written there) and runs
# `diff_driver.py corpus` over the kept cases (every cases/<name>/spec.json with its trace.json.gz). Exit status: 0 when
# no case was kept or every kept case reproduced, 1 when a kept case did not reproduce (it does not count), 2 for a
# refusal or a failure. Needs the pinned Showdown nowhere: the corpus mode works without Node.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"
# Python and git may be native Windows programs under Git Bash: they get paths in the form they understand.
native() { if command -v cygpath > /dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
ROOT=$(native "$(cd "$HERE/../../.." && pwd)")

campaign=''
run=''
bucket=${DUOFORGE_FUZZ_BUCKET:-}
runner=${DUOFORGE_DIFF_RUNNER:-}
out=''
other_commit=no
while [ $# -gt 0 ]; do
    case $1 in
        --campaign) [ $# -ge 2 ] || df_die '--campaign needs a value'; campaign=$2; shift 2 ;;
        --run) [ $# -ge 2 ] || df_die '--run needs a value'; run=$2; shift 2 ;;
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --runner) [ $# -ge 2 ] || df_die '--runner needs a value'; runner=$2; shift 2 ;;
        --out) [ $# -ge 2 ] || df_die '--out needs a value'; out=$2; shift 2 ;;
        --allow-other-commit) other_commit=yes; shift ;;
        -h | --help) sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) df_die "unknown argument '$1' (see --help)" ;;
    esac
done

df_init
df_identity_guard # the first AWS action

df_valid_campaign "$campaign" || df_die "bad or missing --campaign '$campaign'"
df_valid_bucket "$bucket" || df_die "bad or missing --bucket '$bucket'"
if [ -z "$run" ]; then
    df_log "no --run given; the runs of campaign $campaign:"
    df_aws s3 ls "s3://$bucket/fuzz/$campaign/" >&2 || true
    df_die 'give one with --run'
fi
df_valid_run_id "$run" || df_die "--run '$run' is not a run id (<commit12>-<chunk_battles>-<base_seed>-<time>)"
[ -n "$runner" ] && [ -x "$runner" ] || df_die "--runner (or DUOFORGE_DIFF_RUNNER) must be an executable duoforge_diff_runner"
out=${out:-$ROOT/build/fuzz/$campaign}
mkdir -p "$out/results"
out=$(native "$out")
runner=$(native "$runner")

PY=${PYTHON:-}
if [ -z "$PY" ]; then
    if command -v python3 > /dev/null 2>&1; then PY=python3; else PY=python; fi
fi

df_log "downloading s3://$bucket/fuzz/$campaign/$run/ to $out/results (not the partial/ folders of interrupted boxes)"
df_aws s3 sync "s3://$bucket/fuzz/$campaign/$run/" "$out/results" --exclude 'partial/*' --only-show-errors ||
    df_die 'the download failed'

# --- the totals of the finished chunks
shopt -s nullglob
summaries=("$out"/results/chunk-*/summary.json)
[ ${#summaries[@]} -gt 0 ] || df_die "no finished chunk under s3://$bucket/fuzz/$campaign/$run/"
"$PY" - "${summaries[@]}" << 'EOF' || df_die 'a summary.json could not be read'
import collections, json, sys
total = collections.Counter()
heads, nodes = set(), set()
signatures = collections.Counter()
for path in sys.argv[1:]:
    with open(path, encoding='utf-8') as f:
        s = json.load(f)
    total.update(s['buckets'])
    heads.add(s.get('git_head'))
    nodes.add(s.get('node'))
    for e in s.get('signatures', []):
        signatures[(e.get('bucket'), e.get('rule'), e.get('detail'))] += e.get('count', 1)
print('chunks: %d, battles: %d' % (len(sys.argv) - 1, sum(total.values())))
print('buckets: ' + ', '.join('%s %d' % (k, v) for k, v in sorted(total.items())))
print('commit(s): ' + ', '.join(sorted(str(h) for h in heads)) + '; node: ' + ', '.join(sorted(str(n) for n in nodes)))
for (b, r, d), n in sorted(signatures.items(), key=lambda kv: -kv[1]):
    print('  %-12s %-28s %s  x%d' % (b, r, d, n))
EOF

# --- the commit that the campaign ran is the commit that replays it
head_ran=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("git_head") or "")' "${summaries[0]}")
head_here=$(git -C "$ROOT" rev-parse HEAD 2> /dev/null || true)
if [ -n "$head_ran" ] && [ "$head_ran" != "$head_here" ]; then
    if [ "$other_commit" = yes ]; then
        df_log "warning: the campaign ran $head_ran, this checkout is ${head_here:-unknown}: a case may not reproduce for that reason"
    else
        df_die "the campaign ran commit $head_ran but this checkout is ${head_here:-unknown}: check it out, or --allow-other-commit"
    fi
fi

# --- the kept cases, as a corpus (name.json + name.trace.json.gz), replayed locally
corpus="$out/corpus"
rm -rf "$corpus"
mkdir -p "$corpus"
kept=0
for spec in "$out"/results/chunk-*/cases/*/spec.json; do
    dir=$(dirname "$spec")
    name=$(basename "$dir")
    [ -f "$dir/trace.json.gz" ] || { df_log "case $name has no trace.json.gz: not replayable"; continue; }
    cp "$spec" "$corpus/$name.json"
    cp "$dir/trace.json.gz" "$corpus/$name.trace.json.gz"
    kept=$((kept + 1))
done
if [ "$kept" -eq 0 ]; then
    echo 'no kept case: nothing to reproduce (every battle of the finished chunks passed).'
    exit 0
fi
echo "replaying $kept kept case(s) locally (diff_driver.py corpus)"
"$PY" "$ROOT/tools/reference/diff_driver.py" corpus --runner "$runner" --corpus "$corpus" --out "$out/replay" --workers 4
status=$?
if [ "$status" -ge 2 ]; then
    df_die "the replay itself failed (status $status)"
fi
"$PY" - "$out/replay/battles.jsonl" "$out/results" << 'EOF'
import glob, json, os, sys
local = {}
with open(sys.argv[1], encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        local[r['name']] = r
cloud = {}
for path in glob.glob(os.path.join(sys.argv[2], 'chunk-*', 'battles.jsonl')):
    with open(path, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            cloud[r['name']] = r
reproduced = 0
for name in sorted(local):
    c, l = cloud.get(name, {}), local[name]
    same_bucket = c.get('bucket') is not None and c.get('bucket') == l['bucket'] and l['bucket'] != 'PASS'
    detail = '' if (c.get('rule'), c.get('detail')) == (l.get('rule'), l.get('detail')) else         ' (cloud: %s %s; here: %s %s)' % (c.get('rule'), c.get('detail'), l.get('rule'), l.get('detail'))
    if same_bucket:
        verdict = 'REPRODUCED'
        reproduced += 1
    elif c.get('rule') == 'domain' or str(c.get('detail') or '').startswith('domain'):
        verdict = 'NOT REPLAYABLE HERE (a domain finding needs Showdown: rerun the random mode with the same seed and battle index)'
        detail = ''
    else:
        verdict = 'NOT REPRODUCED (cloud %s, here %s)' % (c.get('bucket'), l['bucket'])
    print('%-18s %s  %s%s' % (name, verdict, l['bucket'], detail))
print('%d of %d kept case(s) reproduced here; only these count as findings' % (reproduced, len(local)))
sys.exit(0 if reproduced == len(local) else 1)
EOF
