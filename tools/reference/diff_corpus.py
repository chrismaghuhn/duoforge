"""Differential loop, component 8: the corpus (decision 0015 section 6;
docs/research/expansion/differential-testing.md).

tests/reference/corpus/ holds the fuzz battles that are worth keeping, curated:
only a battle that found a defect or one that covers something no battle had.
Each is two files, <name>.json (its choices spec, as the random mode writes its
cases) and <name>.trace.json.gz (its trace as the pinned Showdown recorded it,
gzipped: the bytes of diff_random.gzipped). The cap is 20 MB; what would go
beyond it moves to a release artifact.

    python tools/reference/diff_driver.py corpus --runner <duoforge_diff_runner>
        [--workers N] [--only GLOB] [--out DIR] [--corpus DIR]
    python tools/reference/diff_driver.py promote --run <run dir> --checkout <pinned checkout>
        --runner <duoforge_diff_runner> [--defects | --coverage] [--cases NAME ...] [--whole]
        [--max-entries N] [--budget-mb M] [--note TEXT] [--dry-run] [--corpus DIR] [--node <node>]

corpus replays every battle without Node: it reads the spec and the trace,
converts them with trace_to_c, writes the records and has the runner say PASS,
DIVERGENCE or UNSUPPORTED, as replay mode does for the committed battles. Every
battle must PASS; a cut of a battle that does not end is no CAP here. CTest runs
it as duoforge.reference.corpus in every local CI job, sanitizers included, and
duoforge.reference.corpus_size (test_corpus_layout.py) holds the layout: every
spec has its trace and the other way round, nothing else is there, the purposes
say why each battle is in, the traces are of this pin and harness, and the whole
is under the cap.

promote chooses what goes in, from a run of the random mode (the cases of its
run directory):

 - A defect: a DIVERGENCE with a failing step or an ORACLE_GAP that the run
   found, in the shortest prefix that shows it (the case's prefix_spec.json: the
   choices up to and including the failing step, or up to the step that the
   converter refuses), one case for each signature unless --cases names them. It
   goes in only once its fix exists: the prefix is recorded again, through the
   same pipeline, and must PASS. Until then it fails, so it is no corpus entry:
   it goes in as a regular fixture together with its fix (tests/reference/specs,
   as d01 to d03 did), and promote says so.
 - Coverage: a PASS battle of a run made with --keep-traces that adds a
   signature (see below) that no committed battle and no corpus battle has.
   Greedily: the battle that adds most first, ties to the lower index, then the
   rest again against what is covered by then, until none adds one. A battle is
   cut after the last step that adds anything (where that is its last step, it is
   whole), or with --whole kept whole; either is recorded again from its spec, as
   a fixture is.

A signature is one of the coverage of tools/reference/gen_real_specs.py (its
`features`: a protocol line kind with its [from] or effect, a draw site with its
context; used as it is, step by step) and the request situations of
`situations`, all computed from the trace: the kind of the request that a side
answered (team preview, turn, replacement, pivot), a slot that passed, Struggle,
a move that was disabled, a locked move (a two-turn move, a Choice item), Mega
Evolution (offered: it was chosen) and a voluntary switch. Whether a Pokemon was
trapped is not in a trace (the recorder does not store the request's trapped
flag), so it is no signature.

The purpose of each entry says why it is there ("Corpus (coverage): ..." with
the signatures it adds, or "Corpus (defect): ..." with the bucket it was found
in and, with --note, what fixed it).
"""
import collections
import gzip
import heapq
import io
import json
import os
import re
import sys
import time
import zlib

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import diff_driver as base  # noqa: E402
import diff_random as rnd  # noqa: E402
import gen_real_specs  # noqa: E402
import trace_to_c  # noqa: E402

CORPUS = os.path.join('tests', 'reference', 'corpus')
SPEC_SUFFIX = '.json'
TRACE_SUFFIX = '.trace.json.gz'
CAP_BYTES = 20 * 1024 * 1024  # decision 0015: what the corpus may grow to; beyond it, a release artifact
DEFAULT_BUDGET_MB = 6.0  # what promote fills by default, well under the cap
NAME = re.compile(r'[A-Za-z0-9_]{1,63}')  # a battle's name in the records
PURPOSES = ('Corpus (coverage): ', 'Corpus (defect): ')
MIN_PURPOSE = 60  # characters: a purpose that says why is longer than that
EXAMPLES = 6  # the signatures that a purpose names


class CorpusError(base.ToolError):
    """The corpus is not what it must be, or a promotion cannot go on."""


# ------------------------------------------------------------ the files

def corpus_dir(root):
    return os.path.join(root, CORPUS)


def spec_path(corpus, name):
    return os.path.join(corpus, name + SPEC_SUFFIX)


def trace_path(corpus, name):
    return os.path.join(corpus, name + TRACE_SUFFIX)


def listing(corpus):
    """(spec names, trace names, other file names) of a corpus directory; empty lists where it does not exist."""
    specs, traces, others = [], [], []
    if os.path.isdir(corpus):
        for fname in sorted(os.listdir(corpus)):
            if fname.endswith(TRACE_SUFFIX):
                traces.append(fname[:-len(TRACE_SUFFIX)])
            elif fname.endswith(SPEC_SUFFIX):
                specs.append(fname[:-len(SPEC_SUFFIX)])
            else:
                others.append(fname)
    return specs, traces, others


def read_json_gz(path):
    with gzip.open(path) as f:
        return json.loads(f.read().decode('utf-8'))


def read_entry(corpus, name):
    """(spec, trace) of corpus battle `name`."""
    with io.open(spec_path(corpus, name), encoding='utf-8') as f:
        spec = json.load(f)
    return spec, read_json_gz(trace_path(corpus, name))


def harness_constants(root):
    """(PIN, HARNESS_VERSION) of tools/reference/ps_trace.js, read from its source: the traces of the corpus are of
    these, or the pin moved and they were not recorded again. No Node."""
    with io.open(os.path.join(root, 'tools', 'reference', 'ps_trace.js'), encoding='utf-8') as f:
        text = f.read()
    pin = re.search(r"^const PIN = '([0-9a-f]{40})';", text, re.M)
    harness = re.search(r'^const HARNESS_VERSION = (\d+);', text, re.M)
    if pin is None or harness is None:
        raise CorpusError('PIN and HARNESS_VERSION are not in tools/reference/ps_trace.js')
    return pin.group(1), int(harness.group(1))


def corpus_bytes(corpus):
    """The size of the corpus in bytes: every file in the directory."""
    if not os.path.isdir(corpus):
        return 0
    return sum(os.path.getsize(os.path.join(corpus, f)) for f in os.listdir(corpus))


def layout_problems(root, corpus=None, cap=CAP_BYTES):
    """What is wrong with the corpus directory, as [(category, message)]; empty when it is as it must be. The
    categories: empty, files (a file that is neither a spec nor a trace, or a name the records cannot hold), orphan (a
    spec without its trace or a trace without its spec), spec (a spec that is not a choices spec of its name), purpose
    (one that does not say why the battle is in), trace (one that is not the recording of its spec at this pin and
    harness) and size."""
    corpus = corpus or corpus_dir(root)
    problems = []
    specs, traces, others = listing(corpus)
    if not specs and not traces:
        problems.append(('empty', '%s holds no battle' % corpus))
    for fname in others:
        problems.append(('files', '%s: neither a <name>.json spec nor a <name>.trace.json.gz trace' % fname))
    for name in sorted(set(specs) | set(traces)):
        if not NAME.fullmatch(name):
            problems.append(('files', '%s: a name is 1 to 63 letters, digits and underscores' % name))
        if name not in traces:
            problems.append(('orphan', '%s has a spec and no trace' % name))
        if name not in specs:
            problems.append(('orphan', '%s has a trace and no spec' % name))
    pin, harness = harness_constants(root)
    for name in sorted(set(specs) & set(traces)):
        try:
            with io.open(spec_path(corpus, name), encoding='utf-8') as f:
                spec = json.load(f)
        except (OSError, ValueError) as e:
            problems.append(('spec', '%s cannot be read: %s' % (name, e)))
            continue
        try:
            trace = read_json_gz(trace_path(corpus, name))
        except (OSError, EOFError, ValueError, zlib.error) as e:
            problems.append(('trace', '%s cannot be read: %s' % (name, e)))
            continue
        problems += entry_problems(name, spec, trace, pin, harness)
    size = corpus_bytes(corpus)
    if size > cap:
        problems.append(('size', 'the corpus is %.2f MB, over the cap of %.0f MB' % (size / 2 ** 20, cap / 2 ** 20)))
    return problems


def entry_problems(name, spec, trace, pin, harness):
    problems = []
    if not isinstance(spec, dict):
        return [('spec', '%s: not a JSON object' % name)]
    if spec.get('name') != name:
        problems.append(('spec', '%s: its name is %r' % (name, spec.get('name'))))
    for key in ('format', 'seed', 'teams', 'choices'):
        if key not in spec:
            problems.append(('spec', '%s: no %s' % (name, key)))
    if 'plan' in spec:
        problems.append(('spec', '%s: a corpus spec has its choices, not a plan' % name))
    if spec.get('data', 'closure') not in ('closure', 'team_c'):
        problems.append(('spec', '%s: data %r' % (name, spec.get('data'))))
    purpose = spec.get('purpose')
    if not isinstance(purpose, str) or not purpose.startswith(PURPOSES) or len(purpose) < MIN_PURPOSE:
        problems.append(('purpose', '%s: the purpose must start with one of %s and say why the battle is in (%d characters '
                         'at least)' % (name, ', '.join('"%s"' % p.strip() for p in PURPOSES), MIN_PURPOSE)))
    if not isinstance(trace, dict) or 'steps' not in trace:
        return problems + [('trace', '%s: not a trace' % name)]
    if trace.get('pin') != pin or trace.get('harness') != harness:
        problems.append(('trace', '%s: recorded at pin %s harness %s, this tree is pin %s harness %s: record it again'
                         % (name, trace.get('pin'), trace.get('harness'), pin, harness)))
    if trace.get('spec') != name + SPEC_SUFFIX:
        problems.append(('trace', '%s: its trace is of the spec %r' % (name, trace.get('spec'))))
    choices = spec.get('choices')
    if isinstance(choices, list) and len(choices) != len(trace['steps']):
        problems.append(('trace', '%s: %d choices and %d steps' % (name, len(choices), len(trace['steps']))))
    elif isinstance(choices, list) and choices != [step['input'] for step in trace['steps']]:
        problems.append(('trace', '%s: the choices of the spec are not what the trace answers' % name))
    for key in ('format', 'seed'):
        if key in spec and trace.get(key) != spec[key]:
            problems.append(('trace', '%s: its %s is not the spec\'s' % (name, key)))
    return problems


# ------------------------------------------------------------ signatures

SENTINEL = {'draws': [], 'log': ['|tie|']}  # a step that ends a battle: features() takes a battle that ended


def step_features(entry, lenient=False):
    """The coverage of one step of a trace as gen_real_specs.features makes it (a protocol line kind with its effect, a
    draw site with its context): a frozenset. features() takes a whole battle that ended, so the step is given to it
    with a step that ends the battle after it, and what that step adds is taken away again. None if a draw has no site
    (UNKNOWN: such a trace is never kept); with `lenient` the draws without a site are left out instead."""
    if lenient and any(d['site'] == 'UNKNOWN' for d in entry['draws']):
        entry = dict(entry, draws=[d for d in entry['draws'] if d['site'] != 'UNKNOWN'])
    found = gen_real_specs.features({'steps': [entry, SENTINEL]})
    if found is None:
        return None
    if not any(line.startswith('|tie|') for line in entry['log']):
        found.discard('tie')
    return frozenset(found)


def situations(trace, k):
    """The request situations of step `k` of a trace: for each side that answered the step, one signature
    'request:<kind>' with the flags that apply to that request after it, sorted and joined with '+'. The kind is that of
    the request the side answered: teampreview, turn, replacement, or pivot (a switch in the middle of the turn: the step
    before it had no upkeep). The flags: pass (a slot passed), and for a turn struggle, disabled-move (a move of the
    request that is disabled), locked-twoturn or locked-choice (an active Pokemon locked into a two-turn move or by a
    Choice item), mega (Mega Evolution was chosen: so it was offered) and switch (a voluntary switch). So
    'request:turn:locked-twoturn+mega' is a turn in which a Pokemon is in the second turn of its move and the other
    Mega Evolves. Trapped is not a flag: a trace does not say."""
    before = trace['start']['state'] if k == 0 else trace['steps'][k - 1]['state']
    entry = trace['steps'][k]
    mid_turn = k > 0 and not any(line.startswith('|upkeep') for line in trace['steps'][k - 1]['log'])
    found = set()
    for side, sid in enumerate(('p1', 'p2')):
        text = entry['input'].get(sid)
        if text is None:
            continue
        state = before['sides'][side]
        kind = {'teampreview': 'teampreview', 'move': 'turn', 'switch': 'pivot' if mid_turn else 'replacement'}.get(
            state['request'], state['request'])
        words = [part.split() for part in text.split(',')]
        flags = set()
        if any(w[:1] == ['pass'] for w in words):
            flags.add('pass')
        if kind == 'turn':
            if any(2 in row for row in state['enabled']):
                flags.add('struggle')
            if any(0 in row for row in state['enabled']):
                flags.add('disabled-move')
            for i in state['active']:
                if i is not None and i >= 0:
                    mon = state['pokemon'][i]
                    if mon.get('locked'):
                        flags.add('locked-twoturn')
                    if mon.get('choice') is not None:
                        flags.add('locked-choice')
            if any('mega' in w for w in words):
                flags.add('mega')
            if any(w[:1] == ['switch'] for w in words):
                flags.add('switch')
        found.add('request:' + kind + (':' + '+'.join(sorted(flags)) if flags else ''))
    return found


def trace_signatures(trace, lenient=False):
    """{signature: the first step it is in} of a trace; None if a draw of it has no site (UNKNOWN), unless `lenient`."""
    first = {}
    for k, entry in enumerate(trace['steps']):
        features = step_features(entry, lenient)
        if features is None:
            return None
        for sig in sorted(features | situations(trace, k)):
            first.setdefault(sig, k)
    return first


def committed_signatures(root):
    """The signatures that the committed battles (tests/reference/specs and traces) have."""
    covered = set()
    for name in base.spec_names(root):
        _, text = base.load_committed(root, name)
        covered.update(trace_signatures(json.loads(text), lenient=True))
    return covered


def corpus_signatures(corpus, skip=()):
    """The signatures that the battles of a corpus directory have (but those named in `skip`)."""
    covered = set()
    for name in listing(corpus)[0]:
        if name not in skip and os.path.exists(trace_path(corpus, name)):
            covered.update(trace_signatures(read_json_gz(trace_path(corpus, name)), lenient=True))
    return covered


def category(signature):
    """What a signature is about, for the report: draw, request, or protocol line."""
    return 'draw' if signature.startswith('draw:') else 'request' if signature.startswith('request:') else 'line'


def cut_step(first, new):
    """The last step that a battle needs for the signatures `new` it adds: the latest of their first steps."""
    return max(first[s] for s in new)


def greedy(candidates, covered, limit=None):
    """Chooses battles by the coverage they add. `candidates` is {key: {signature: first step}} (keys sort: the lower
    key wins a tie), `covered` the signatures that are there already. Repeatedly the battle that adds the most
    signatures is taken, then all are measured again against what is covered by then, until none adds one (or `limit`
    battles are chosen). Returns [(key, new signatures sorted, the step to cut after)] in the order chosen: a battle is
    cut after the last step that adds anything, and only what is before that counts as covered afterwards. (Lazily: a
    gain can only go down as more is covered, so a battle is measured again only when it comes to the top.)"""
    covered = set(covered)
    heap = [(-len([s for s in first if s not in covered]), key) for key, first in candidates.items()]
    heapq.heapify(heap)
    chosen = []
    while heap and (limit is None or len(chosen) < limit):
        stale, key = heapq.heappop(heap)
        new = [s for s in candidates[key] if s not in covered]
        if len(new) != -stale:
            if new:
                heapq.heappush(heap, (-len(new), key))
            continue
        if not new:
            break
        step = cut_step(candidates[key], new)
        chosen.append((key, sorted(new), step))
        covered.update(s for s, k in candidates[key].items() if k <= step)
    return chosen


# ------------------------------------------------------------ replay: the corpus through the converter and the runner

class NoWorker:
    """What run_lanes needs of a worker when nothing is recorded: a version that every lane agrees on."""

    failed = False

    def __init__(self, version):
        self.reported = version

    def version(self):
        return dict(self.reported)

    def close(self):
        return []

    def kill(self):
        pass


def replay(root, runner_path, workers, names=None, corpus=None, out=sys.stdout):
    """Every corpus battle (or `names`) through the converter and the runner: ({name: record}, the summary); the records
    are those of replay mode. No Node: the traces are read."""
    corpus = corpus or corpus_dir(root)
    names = names if names is not None else listing(corpus)[0]
    if not names:
        raise CorpusError('%s holds no battle to replay' % corpus)
    pin, harness = harness_constants(root)
    tables = {team_c: trace_to_c.load_tables(root, team_c) for team_c in (False, True)}
    kinds = conformance_records.data_kinds(root)

    def handle(name, worker, runner):
        try:
            spec, trace = read_entry(corpus, name)
        except (OSError, ValueError, EOFError, zlib.error) as e:
            return base.new_result(name, 'REF_ERROR', detail='cannot read the battle', messages=[str(e)])
        ended = bool(trace['steps'][-1]['state']['ended'])
        # A cut of a battle need not end: a PASS is a PASS here, not a CAP.
        evaluated = rnd.convert_and_run(name, spec, None, trace, ended, runner, tables.__getitem__, kinds,
                                        collections.defaultdict(float), cap=False)
        return evaluated.result

    results, version = base.run_lanes(names, workers, lambda: NoWorker({'node': None, 'pin': pin, 'harness': harness}),
                                      lambda: base.DiffRunner(os.path.abspath(runner_path)), handle)
    return results, base.summarize(results, version, 'corpus', base.git_head(root), base.library_version(root))


# ------------------------------------------------------------ promote

Candidate = collections.namedtuple('Candidate', 'name index record spec trace_text trace first')
Entry = collections.namedtuple('Entry', 'name kind steps total size new')
Refused = collections.namedtuple('Refused', 'name why')


def read_records(run_dir):
    """The records (RECORD_KEYS) of the battles of a run directory that have a result, in index order."""
    records = []
    partial = os.path.join(run_dir, 'partial')
    if not os.path.isdir(partial):
        raise CorpusError('%s has no partial/: not the directory of a run of the random mode' % run_dir)
    for fname in sorted((f for f in os.listdir(partial) if re.fullmatch(r'\d+\.json', f)), key=lambda f: int(f[:-5])):
        with io.open(os.path.join(partial, fname), encoding='ascii') as f:
            records.append(json.load(f)['record'])
    return records


def read_text_json(path):
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def dumps_spec(spec):
    return (json.dumps(spec, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def entry_spec(name, purpose, source, choices):
    """The spec of a corpus entry: the keys in the order of every spec, from the spec of the battle it is made from."""
    spec = {'name': name, 'purpose': purpose}
    if 'data' in source:
        spec['data'] = source['data']
    spec.update({'format': source['format'], 'seed': source['seed'], 'teams': source['teams'], 'choices': choices})
    return spec


def examples(signatures):
    """The signatures that a purpose names: the request situations first, then draws, then protocol lines."""
    order = {'request': 0, 'draw': 1, 'line': 2}
    return sorted(signatures, key=lambda s: (order[category(s)], s))[:EXAMPLES]


def coverage_purpose(record, seed, steps, total, new):
    """Why a coverage battle is in the corpus: the battle it is, whether it is cut, and what it adds."""
    letters = record['pairing']
    shown = ', '.join(examples(new))
    more = '' if len(new) <= EXAMPLES else ' and %d more' % (len(new) - EXAMPLES)
    cut = 'the whole battle' if steps == total else 'cut after step %d of %d, where it stops adding anything' % (steps, total)
    return ('Corpus (coverage): random differential battle %d of run %d (tools/reference/diff_driver.py random), %s against '
            '%s, %s. It adds %d signatures that no committed battle and no earlier corpus battle has: %s%s.'
            % (record['index'], seed, rnd.who(letters[0]), rnd.who(letters[1]), cut, len(new), shown, more))


def defect_purpose(record, seed, steps, total, note):
    """Why a defect battle is in the corpus: what it found, and in how many choices it shows it."""
    bucket, rule, detail = (record['bucket'],) + rnd.signature(record)
    what = '%s%s' % (bucket, ' %s %s' % (rule, base.clip(detail, 120)) if rule or detail else '')
    letters = record['pairing']
    return ('Corpus (defect): case %s of run %d (tools/reference/diff_driver.py random), %s against %s, found as %s. The '
            'shortest prefix that showed it, %d of %d choices; it passes now%s.'
            % (record['name'], seed, rnd.who(letters[0]), rnd.who(letters[1]), what, steps, total,
               ', fixed by %s' % note if note else ''))


def run_seed(run_dir):
    """The seed of a run directory, from its run.json."""
    path = os.path.join(run_dir, 'run.json')
    if not os.path.exists(path):
        raise CorpusError('%s has no run.json: not the directory of a run of the random mode' % run_dir)
    return read_text_json(path)['seed']


def defect_cases(run_dir, records, names):
    """[(record, case directory)] of the defect cases to promote: the cases named in `names`, or the first case of each
    signature among the DIVERGENCE (with a failing step) and ORACLE_GAP battles of the run, that have a shortest prefix."""
    chosen, seen = [], set()
    for record in records:
        if record['bucket'] not in ('DIVERGENCE', 'ORACLE_GAP'):
            continue
        case = os.path.join(run_dir, 'cases', record['name'])
        if names is not None:
            if record['name'] not in names:
                continue
        else:
            if not os.path.exists(os.path.join(case, 'prefix_spec.json')):
                continue
            key = (record['bucket'],) + rnd.signature(record)
            if key in seen:
                continue
            seen.add(key)
        chosen.append((record, case))
    return chosen


def kept_candidates(run_dir, records):
    """The PASS battles of a run directory that were kept (--keep-traces), with the signatures of their traces: [Candidate]
    in index order; a battle whose trace has a draw without a site is left out."""
    out = []
    for record in records:
        kept = os.path.join(run_dir, 'kept', record['name'])
        if record['bucket'] != 'PASS' or not os.path.exists(os.path.join(kept, 'trace.json.gz')):
            continue
        spec = read_text_json(os.path.join(kept, 'spec.json'))
        trace = read_json_gz(os.path.join(kept, 'trace.json.gz'))
        first = trace_signatures(trace)
        if first is not None:
            out.append(Candidate(record['name'], record['index'], record, spec, None, trace, first))
    return out


def recorded(name, spec, worker, runner, tables_for, kinds):
    """The Evaluated of battle `name` recorded again from its spec by the worker and put through the pipeline, a cut that
    does not end being no CAP: what an entry must be before it goes in."""
    return rnd.evaluate(name, spec, worker, runner, tables_for, kinds, None, collections.defaultdict(float), cap=False)


def promote(root, run_dir, worker, runner, tables_for, kinds, corpus=None, defects=True, coverage=True, cases=None,
            max_entries=None, budget_bytes=int(DEFAULT_BUDGET_MB * 2 ** 20), note=None, dry_run=False, base_signatures=None,
            whole=False, out=sys.stdout):
    """Promotes battles of a run directory into the corpus (see the module docstring). `worker` records and `runner`
    runs what is promoted: nothing goes in that does not PASS. `base_signatures` is what the committed battles cover (by
    default computed from the tree). Returns ([Entry] that went in, [Refused]); with `dry_run` the files are not written.
    The budget is for the corpus as a whole, and never above the cap. A coverage battle is cut after the last step that
    adds anything, unless `whole`: then it is kept whole (the choice of battles is the same)."""
    corpus = corpus or corpus_dir(root)
    existing = set(listing(corpus)[0])
    records = read_records(run_dir)
    seed = run_seed(run_dir)
    covered = set(committed_signatures(root) if base_signatures is None else base_signatures) | corpus_signatures(corpus)
    budget = min(budget_bytes, CAP_BYTES)
    size = corpus_bytes(corpus)
    promoted, refused = [], []

    def put(name, spec, trace_text, kind, steps, total, new):
        nonlocal size
        files = {spec_path(corpus, name): dumps_spec(spec), trace_path(corpus, name): rnd.gzipped(trace_text)}
        grown = sum(len(data) for data in files.values())
        if size + grown > budget:
            refused.append(Refused(name, 'the budget of %.1f MB would be passed (%.2f MB now, %.0f KB more)' % (
                budget / 2 ** 20, size / 2 ** 20, grown / 1024)))
            return False
        size += grown
        if not dry_run:
            os.makedirs(corpus, exist_ok=True)
            for path, data in files.items():
                rnd.write_atomically(path, data)
        entry = Entry(name, kind, steps, total, grown, sorted(new))
        promoted.append(entry)
        print('  %s %s: %s, %d of %d steps, %.1f KB, %d new signatures' % (
            'would promote' if dry_run else 'promoted', name, kind, steps, total, grown / 1024, len(new)), file=out, flush=True)
        return True

    if defects:
        for record, case in defect_cases(run_dir, records, cases):
            prefix_file = os.path.join(case, 'prefix_spec.json')
            if not os.path.exists(prefix_file):
                refused.append(Refused(record['name'], 'no shortest prefix in its case (only a DIVERGENCE with a failing step '
                                       'and an ORACLE_GAP that a step refuses have one)'))
                continue
            prefix = read_text_json(prefix_file)
            result = read_text_json(os.path.join(case, 'prefix_result.json'))
            name = prefix['name']
            if not result.get('reproduces'):
                refused.append(Refused(name, 'its prefix did not show the failure again when the run made it: it is not '
                                       'the shortest prefix that shows it'))
            elif name in existing or any(e.name == name for e in promoted):
                refused.append(Refused(name, 'there is a corpus battle of that name already'))
            else:
                evaluated = recorded(name, prefix, worker, runner, tables_for, kinds)
                got = evaluated.result
                if got['bucket'] != 'PASS':
                    refused.append(Refused(name, 'not fixed yet (%s %s): it goes in as a regular fixture with its fix, in '
                                           'tests/reference/specs, as d01 to d03 did' % (got['bucket'], base.clip(
                                               got['detail'] or got['rule'] or '', 100))))
                else:
                    steps = len(prefix['choices'])
                    total = len(read_text_json(os.path.join(case, 'spec.json'))['choices'])
                    spec = entry_spec(name, defect_purpose(record, seed, steps, total, note), prefix, prefix['choices'])
                    put(name, spec, evaluated.trace_text, 'defect', steps, total, [])
    if coverage:
        candidates = kept_candidates(run_dir, records)
        by_index = {c.index: c for c in candidates}
        chosen = greedy({c.index: c.first for c in candidates}, covered, max_entries)
        for index, new, step in chosen:
            c = by_index[index]
            total = len(c.trace['steps'])
            steps = total if whole else step + 1
            name = c.name if steps == total else '%s_cut%d' % (c.name, steps)
            if name in existing or any(e.name == name for e in promoted):
                refused.append(Refused(name, 'there is a corpus battle of that name already'))
                continue
            spec = entry_spec(name, coverage_purpose(c.record, seed, steps, total, new), c.spec, c.spec['choices'][:steps])
            evaluated = recorded(name, spec, worker, runner, tables_for, kinds)
            if evaluated.result['bucket'] != 'PASS':
                refused.append(Refused(name, 'does not PASS when it is recorded again: %s %s' % (
                    evaluated.result['bucket'], base.clip(evaluated.result['detail'] or evaluated.result['rule'] or '', 100))))
                continue
            if json.loads(evaluated.trace_text)['steps'] != c.trace['steps'][:steps]:
                raise CorpusError('%s: the reference did not record again what the run kept (the first %d steps differ): '
                                  'the pin or the harness is not the run\'s' % (name, steps))
            if not put(name, spec, evaluated.trace_text, 'coverage', steps, total, new):
                break  # the budget: what is left adds less than this battle did
            covered.update(s for s, k in c.first.items() if k <= step)
    return promoted, refused


def report(promoted, refused, corpus, out=sys.stdout):
    """The totals of a promotion on `out`."""
    kinds = collections.Counter(e.kind for e in promoted)
    new = sorted({s for e in promoted for s in e.new})
    by_category = collections.Counter(category(s) for s in new)
    print('promote: %d battles (%d coverage, %d defect), %.2f KB; %d new signatures (%d request situations, %d draws, %d '
          'protocol lines)' % (len(promoted), kinds['coverage'], kinds['defect'], sum(e.size for e in promoted) / 1024,
                               len(new), by_category['request'], by_category['draw'], by_category['line']), file=out)
    for r in refused:
        print('  not promoted: %s: %s' % (r.name, r.why), file=out)
    print('promote: the corpus is %.2f MB' % (corpus_bytes(corpus) / 2 ** 20), file=out)


# ------------------------------------------------------------ the command line

def add_arguments(modes):
    p = modes.add_parser('corpus', help='the corpus (tests/reference/corpus) through the converter and the runner, no Node')
    p.add_argument('--runner', required=True, help='the duoforge_diff_runner executable')
    p.add_argument('--workers', type=int, default=4, help='threads, each with a runner (default 4)')
    p.add_argument('--only', metavar='GLOB', help='only the battles whose name matches (fnmatch)')
    p.add_argument('--out', metavar='DIR', help='default build/diff/<UTC yyyymmdd-hhmmss>-corpus')
    p.add_argument('--corpus', metavar='DIR', help='default tests/reference/corpus')
    q = modes.add_parser('promote', help='put battles of a run of the random mode into the corpus')
    q.add_argument('--run', required=True, metavar='DIR', help='the output directory of a run of the random mode')
    q.add_argument('--checkout', required=True, help='the pinned Showdown checkout (built: dist/sim exists)')
    q.add_argument('--runner', required=True, help='the duoforge_diff_runner executable')
    q.add_argument('--node', metavar='EXE', help='default: node on the PATH')
    q.add_argument('--corpus', metavar='DIR', help='default tests/reference/corpus')
    kind = q.add_mutually_exclusive_group()
    kind.add_argument('--defects', action='store_true', help='only the defects of the run')
    kind.add_argument('--coverage', action='store_true', help='only battles that add coverage')
    q.add_argument('--cases', nargs='+', metavar='NAME', help='the defect cases to promote (default: the first of each signature)')
    q.add_argument('--whole', action='store_true',
                   help='keep a coverage battle whole (default: cut after the last step that adds a signature)')
    q.add_argument('--max-entries', type=int, help='at most this many coverage battles')
    q.add_argument('--budget-mb', type=float, default=DEFAULT_BUDGET_MB,
                   help='the corpus as a whole stays under this (default %s; never above the cap of 20)' % DEFAULT_BUDGET_MB)
    q.add_argument('--note', help='what fixed the defects, for their purposes ("A6 (#85)")')
    q.add_argument('--dry-run', action='store_true', help='say what would go in, write nothing')
    return p


def run_corpus(args):
    """The corpus mode; the exit status."""
    import fnmatch
    root = base.ROOT
    if args.workers < 1:
        raise CorpusError('--workers must be at least 1')
    if not os.path.isfile(args.runner):
        raise CorpusError('--runner %s is not a file' % args.runner)
    corpus = os.path.abspath(args.corpus) if args.corpus else corpus_dir(root)
    names = listing(corpus)[0]
    if args.only:
        names = [n for n in names if fnmatch.fnmatchcase(n, args.only)]
        if not names:
            raise CorpusError('no corpus battle matches %r' % args.only)
    results, summary = replay(root, args.runner, args.workers, names, corpus)
    outdir = args.out or os.path.join(root, 'build', 'diff', time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-corpus')
    base.write_outputs(outdir, results, summary)
    counts = summary['buckets']
    print('diff_driver: corpus of %d battles: %s' % (summary['battles'], ', '.join(
        '%s %d' % (b, counts[b]) for b in base.BUCKETS if counts[b] or b == 'PASS')))
    shown = 0
    for name in sorted(results):
        record = results[name]
        if record['bucket'] != 'PASS':
            shown += 1
            if shown <= 40:
                print('  %s %s %s%s' % (name, record['bucket'], record['rule'] or '-',
                                         ' step %d' % record['step'] if record['step'] is not None else ''))
                print('      %s' % base.printable(str(record['detail'])))
    print('diff_driver: results in %s' % outdir)
    return 0 if counts['PASS'] == summary['battles'] else base.EXIT_NOT_ALL_PASS


def run_promote(args):
    """The promote mode; the exit status (0 when something went in or there was nothing to promote, 1 when every
    candidate was refused)."""
    import shutil
    root = base.ROOT
    if not os.path.isfile(args.runner):
        raise CorpusError('--runner %s is not a file' % args.runner)
    if not os.path.isdir(os.path.join(args.checkout, 'dist', 'sim')):
        raise CorpusError('--checkout %s has no dist/sim (npm ci --ignore-scripts --omit=dev; node build)' % args.checkout)
    node = args.node or shutil.which('node')
    if node is None:
        raise CorpusError('node is not on the PATH (--node)')
    if not 0 < args.budget_mb:
        raise CorpusError('--budget-mb is above 0')
    corpus = os.path.abspath(args.corpus) if args.corpus else corpus_dir(root)
    worker = base.NodeWorker(node, args.checkout, rnd.WORKER_TIMEOUT)
    runner = base.DiffRunner(os.path.abspath(args.runner), rnd.RUNNER_TIMEOUT)
    tables = {team_c: trace_to_c.load_tables(root, team_c) for team_c in (False, True)}
    ok = False
    try:
        worker.version()
        promoted, refused = promote(root, os.path.abspath(args.run), worker, runner, tables.__getitem__,
                                    conformance_records.data_kinds(root), corpus=corpus, defects=not args.coverage,
                                    coverage=not args.defects, cases=args.cases, max_entries=args.max_entries,
                                    budget_bytes=int(args.budget_mb * 2 ** 20), note=args.note, dry_run=args.dry_run,
                                    whole=args.whole)
        ok = True
    finally:
        if ok:
            problems = worker.close() + runner.close()
            if problems:
                raise CorpusError('; '.join(problems))
        else:
            worker.kill()
            runner.kill()
    report(promoted, refused, corpus)
    return 0 if promoted or not refused else base.EXIT_NOT_ALL_PASS
