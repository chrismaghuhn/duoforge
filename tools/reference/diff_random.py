"""Differential loop, random mode (docs/research/expansion/differential-testing.md,
component 4): random battles, played by the pinned Showdown's own judgment of
legal choices, go worker -> converter -> runner and are put in one bucket each.
The command line is diff_driver.py's:

    python tools/reference/diff_driver.py random --checkout <pinned checkout>
        --runner <duoforge_diff_runner> --battles N --seed S
        [--pairings AB,BA,AA,BB] [--workers W] [--out DIR] [--start K]
        [--chunk-minutes M] [--no-lock] [--node <node>]
        [--max-steps 300] [--switch-weight 0.1] [--mega-weight 0.5] [--domain-rate 0.1]

Battle i of run S is derived from (S, i) alone: the pairing is pairings[i %
len(pairings)] (A and B are tests/reference/teams/team_a.txt and team_b.txt, C
is docs/research/third-team/team-c.txt; a pairing with C is Team C data and
opt-in), the team orders and the reference seed come from gen_real_specs's
splitmix64 and shuffle, the policy seed from the same stream. Its name is
fz_<S>_<i>. The pipeline, and the bucket of the first step that ends it:

 1. play      the worker plays the battle with random choices that Showdown
              accepts (ps_play.js); failing, or a worker that dies or hangs:
              REF_ERROR;
 2. record    the worker records the resulting choices spec (ps_trace.run);
              failing, or a battle that ends otherwise than play said: REF_ERROR
              "the choices spec does not replay";
 3. convert   trace_to_c; a ConversionError, or one of the untyped errors of
              diff_driver: ORACLE_GAP;
 4. run       the runner creates the battle under CLOSURE (Team C: TEAM_C) with
              no DEV fallback: a real team that is rejected is a finding.
              UNSUPPORTED or DIVERGENCE as it says; a runner that dies or hangs
              is a DIVERGENCE "runner died (exit X)" / "runner timed out";
 5. CAP       the runner PASSed but the battle did not end within max_steps;
 6. PASS.

The domain check (--domain-rate, the share of requests; 0.1 by default): the
worker also returns, for the requests that a hash of (policy seed, step, side)
picks, every choice that Showdown accepts for the side (judged option by
option, ps_play.js). The driver makes each text the choice that trace_to_c.
convert_choice makes of it, as the converter does for what was played, and the
set goes to the runner with the battle (D and C records): before the step is
applied the runner compares the engine's candidates for the side with it, and a
difference is a DIVERGENCE "domain: engine-only N, reference-only M (step K
side S)". What was played must be in its set, or the reference contradicts
itself (REF_ERROR "a domain sample disagrees with the recording").

Every battle that is not PASS gets a directory in cases/ with its spec (as a
committed spec could be), its trace gzipped, the messages, and for a
DIVERGENCE with a failing step that step's protocol lines and draws, each draw
with the verdict of trace_to_c.drop_reason, and for a domain difference the
accepted texts, each with its choice. For a DIVERGENCE with a step and
for a CAP the driver also runs the prefix (the choices up to and including the
failing step, or all of them) through the same pipeline and records whether it
comes to the same bucket at the same step ("reproduces").

Output (--out, default build/diff/<UTC yyyymmdd-hhmmss>-random-s<S>/):
battles.jsonl (one line per battle, in index order) and summary.json (counts
per bucket and per (rule, detail) signature, the parameters, the versions) are
the same for the same run however it was cut into chunks and however fast it
ran; timings are in timing.json. run.json is the identity of the run (a chunk
refuses a directory that belongs to another one), partial/ holds the result of
each finished battle, cases/ the cases.

Chunks. Without --no-lock the run is a loop of chunk subprocesses, each
started as `bash tools/ci/machine_lock.sh fuzz <python> diff_driver.py random
... --start K --chunk-minutes M --no-lock` (M defaults to 10): the chunk holds
the machine lock, stops starting battles after M minutes, finishes the running
ones and exits; between chunks the lock is free and the loop sleeps 30 s, so a
waiting CI or benchmark gets it. --no-lock runs all battles from --start in
this process with no lock (CTest does: local_ci.sh holds the lock already); an
explicit --chunk-minutes with it makes this process one chunk, which writes the
results of its battles and no summary: the files of the whole run are written by
the process that owns it (the loop above, or a run without --chunk-minutes once
every battle has a result). Children run below normal priority.

Exit status: 0 when the run is complete (the buckets are in the files), 2 for a
bad command line, 3 for a failure of the tool. This file only orchestrates.
"""
import collections
import copy
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import diff_driver as base  # noqa: E402
import gen_real_specs  # noqa: E402
import trace_to_c  # noqa: E402

PAIRINGS = ('AB', 'BA', 'AA', 'BB', 'CA', 'AC', 'CB', 'BC', 'CC')
DEFAULT_PAIRINGS = PAIRINGS[:4]
DEFAULT_MAX_STEPS = 300
DEFAULT_SWITCH_WEIGHT = 0.1
DEFAULT_MEGA_WEIGHT = 0.5
DEFAULT_DOMAIN_RATE = 0.1
DEFAULT_CHUNK_MINUTES = 10
CHUNK_PAUSE = 30  # seconds between chunks, the lock released
WORKER_TIMEOUT = 300  # seconds for one answer of the worker (a play of 300 steps is a few seconds)
RUNNER_TIMEOUT = 60  # seconds for one battle in the engine
PHASES = ('play', 'record', 'convert', 'run', 'prefix')
BUCKET_ORDER = {bucket: i for i, bucket in enumerate(base.RANDOM_BUCKETS)}
RECORD_KEYS = ['index', 'name', 'pairing', 'bucket', 'rule', 'detail', 'step', 'steps', 'context', 'ended', 'reproduces',
               'domain', 'messages']
WHO = {'A': 'team A', 'B': 'team B', 'C': 'Team C'}

Params = collections.namedtuple('Params', 'seed battles pairings max_steps switch_weight mega_weight domain_rate',
                                defaults=(0.0,))


# ------------------------------------------------------------ what battle i is

def battle_seed(seed, index):
    """The 64-bit seed of battle `index` of run `seed`: two splitmix64 steps (the generator hashes its state), so any
    (seed, index) is reached at once and nothing depends on the other battles or on how many there are."""
    first = gen_real_specs.SplitMix64(seed).next()
    return gen_real_specs.SplitMix64(first ^ ((index * 0x9E3779B97F4A7C15) & gen_real_specs.MASK)).next()


def read_teams(root):
    """{'A': [six sets], 'B': [...], 'C': [...]}: the paste text of each set of the committed teams."""
    teams = {'A': gen_real_specs.read_team('team_a.txt'), 'B': gen_real_specs.read_team('team_b.txt')}
    with io.open(os.path.join(root, 'docs', 'research', 'third-team', 'team-c.txt'), encoding='utf-8') as f:
        teams['C'] = [s.strip() for s in f.read().split('\n\n') if s.strip()]
    if len(teams['C']) != 6:
        raise base.ToolError('team-c.txt has %d sets, not 6' % len(teams['C']))
    return teams


def derive(params, index, teams):
    """(spec without choices, policy seed, pairing) of battle `index`. The team order of each side and the reference
    seed are drawn as gen_real_specs does for its candidates, the policy seed follows from the same stream."""
    rng = gen_real_specs.SplitMix64(battle_seed(params.seed, index))
    pairing = params.pairings[index % len(params.pairings)]
    sides = ['\n\n'.join(gen_real_specs.shuffled(rng, teams[letter])) for letter in pairing]
    ps_seed = 'sodium,' + ''.join('%016x' % rng.next() for _ in range(4))
    policy_seed = rng.next() & 0xFFFFFFFF
    name = 'fz_%d_%d' % (params.seed, index)
    spec = {
        'name': name,
        'purpose': ('Random differential battle %d of run %d (tools/reference/diff_driver.py random): %s against %s, '
                    'the sets in a seeded random order, team preview to the end or to the cap, both sides answering '
                    'every request with random choices (policy seed %d, tools/reference/ps_play.js) that the pinned '
                    'Showdown accepted.' % (index, params.seed, WHO[pairing[0]], WHO[pairing[1]], policy_seed)),
    }
    if 'C' in pairing:
        spec['data'] = 'team_c'
    spec.update({'format': gen_real_specs.FORMAT, 'seed': ps_seed, 'teams': sides})
    return spec, policy_seed, pairing


def prefix_spec(spec, step=None):
    """A copy of the choices spec cut after the choices of `step` (None: all of them), named <name>_prefix."""
    cut = copy.deepcopy(spec)
    cut['name'] = spec['name'] + '_prefix'
    if step is not None:
        cut['choices'] = cut['choices'][:step + 1]
    return cut


# ------------------------------------------------------------ the domain of a request

class DomainError(Exception):
    """A domain sample that disagrees with the recording of the battle it was taken in: the reference is not
    consistent with itself, a bug of the harness, not a finding about the engine."""


def roster_tables(trace):
    """roster_of as trace_to_c.convert_battle builds it (inline, so it is made again here): the roster index of each
    member of each side by the name of its set's species, and by the name that the protocol uses for the formes that
    have another one."""
    state = trace['start']['state']
    roster_of = []
    for s in range(2):
        names = [trace_to_c.name_of(p) for p in state['sides'][s]['pokemon']]
        roster_of.append({n: i for i, n in enumerate(names)})
        for species, protocol in trace_to_c.BASE_SPECIES_NAME.items():
            if species in roster_of[s]:
                roster_of[s][protocol] = roster_of[s][species]
    return roster_of


def state_before(trace, step):
    """The state the choices of `step` are made in."""
    return trace['start']['state'] if step == 0 else trace['steps'][step - 1]['state']


def mid_turn_before(trace, step):
    """The request of `step` was made during the turn (a pivot), not at its end: the step before it has no upkeep."""
    return step > 0 and not any(line.startswith('|upkeep') for line in trace['steps'][step - 1]['log'])


def canonical_choice(text, side, state, roster_of, mid_turn):
    """The choice that trace_to_c.convert_choice makes of a Showdown text, as a value that goes in a set: ('team',
    picks) or ('slots', (command, command)), a command being (kind, move_slot, target, mega, reserve), the leaves of
    the engine's duoforge_slot_command."""
    kind, value = trace_to_c.convert_choice(text, side, state, roster_of, mid_turn)
    if kind == 'team':
        return ('team', tuple(value))
    return ('slots', tuple(tuple(command) for command in value))


def format_command(command):
    """A slot command as the runner prints it (tools/difftest/domain.c, dfd_format)."""
    kind, move_slot, target, mega, reserve = command
    if kind == 1:
        return 'move %d -> %s%s' % (move_slot, 'none' if target == 255 else target, ' mega' if mega else '')
    if kind == 2:
        return 'switch %d' % reserve
    return 'pass' if kind == 3 else 'none'


def format_choice(choice):
    """A canonical choice as the runner prints it: 'team 2 4 0 1' or 'slots move 1 -> 2 mega, switch 3'."""
    kind, value = choice
    if kind == 'team':
        return 'team ' + ' '.join(str(pick) for pick in value)
    return 'slots ' + ', '.join(format_command(command) for command in value)


def choice_shape(text):
    """What kind of choice a printed one is, for the signature: 'team', or the kind of each command of 'slots ...'
    joined by '/': move, move+mega, move+target, move+mega+target, switch, pass or none."""
    if not text.startswith('slots '):
        return text.split(' ')[0]
    shape = []
    for part in text[len('slots '):].split(', '):
        word = part.split(' ')[0]
        if word == 'move':
            word += ('+mega' if part.endswith(' mega') else '') + ('' if ' -> none' in part else '+target')
        shape.append(word)
    return '/'.join(shape)


def domain_choices(trace, samples):
    """The domain samples of a play (dicts with 'step', 'side' and the Showdown texts 'accepted') as the sets of the
    records: dicts with 'step', 'side', 'accepted' (the texts), 'choices' (the canonical choices, in the ascending
    order of the record) and 'rendered' ({text: the choice as the runner prints it}), by step and side. What was
    played at that step is accepted, so it must be in its set: else DomainError. A ConversionError or an untyped
    error of the converter passes."""
    if not samples:
        return []
    roster_of = roster_tables(trace)
    out = []
    for sample in sorted(samples, key=lambda x: (x['step'], x['side'])):
        step, side = sample['step'], sample['side']
        where = 'step %d side %d' % (step, side)
        sid = ('p1', 'p2')[side]
        if step >= len(trace['steps']) or sid not in trace['steps'][step]['input']:
            raise DomainError('%s: the side did not answer a step of the recording' % where)
        state, mid_turn = state_before(trace, step), mid_turn_before(trace, step)
        by_text = {text: canonical_choice(text, side, state, roster_of, mid_turn) for text in sample['accepted']}
        played_text = trace['steps'][step]['input'][sid]
        played = canonical_choice(played_text, side, state, roster_of, mid_turn)
        choices = set(by_text.values())
        if played not in choices:
            raise DomainError('%s: what was played (%r) is not among the %d choices that Showdown accepted'
                              % (where, played_text, len(choices)))
        out.append({'step': step, 'side': side, 'accepted': sample['accepted'],
                    'choices': sorted(choices, key=conformance_records.flat_choice),
                    'rendered': {text: format_choice(choice) for text, choice in by_text.items()}})
    return out


# ------------------------------------------------------------ one battle through the pipeline

Evaluated = collections.namedtuple('Evaluated', 'result trace_text trace ended domain', defaults=((),))


def runner_bucket(verdict, ended):
    """The bucket after the runner's verdict: UNSUPPORTED and DIVERGENCE stand; a PASS of a battle that did not end is
    CAP, not PASS."""
    if verdict != 'PASS':
        return verdict
    return 'PASS' if ended else 'CAP'


def evaluate(name, spec, worker, runner, tables_for, kinds, play_ended, seconds, clock=time.monotonic, domain=()):
    """record -> convert -> runner for a choices spec. `play_ended` is what the play said about the end (None for a
    prefix); `seconds` collects the time of each phase; `domain` the samples of the play for the steps of the spec.
    Returns an Evaluated: the record of a bucket (the schema of diff_driver.new_result), the trace, whether the battle
    ended and its domain samples as the records have them, as far as the pipeline got."""
    t0 = clock()
    try:
        text = worker.record(spec, name + '.json')
    except base.WorkerError as e:
        seconds['record'] += clock() - t0
        return Evaluated(base.new_result(name, 'REF_ERROR', detail='the choices spec does not replay',
                                         messages=[e.error] + (e.stack.split('\n') if e.stack else [])), None, None, None)
    except base.ChildFailure as e:
        seconds['record'] += clock() - t0
        return Evaluated(base.child_failure_result(name, e), None, None, None)
    seconds['record'] += clock() - t0
    trace = json.loads(text)
    ended = bool(trace['steps'][-1]['state']['ended'])
    if play_ended is not None and ended != play_ended:
        return Evaluated(base.new_result(name, 'REF_ERROR', detail='the choices spec does not replay',
                                         messages=['the play said ended %s, the recording of its choices ended %s'
                                                   % (play_ended, ended)]), text, trace, ended)
    t0 = clock()
    try:
        team_c = trace_to_c.spec_is_team_c(name, spec)
        data = trace_to_c.convert_battle(name, spec, trace, tables_for(team_c))
        sets = domain_choices(trace, domain)
    except trace_to_c.ConversionError as e:
        seconds['convert'] += clock() - t0
        return Evaluated(base.oracle_gap(name, e), text, trace, ended)
    except base.UNTYPED as e:
        seconds['convert'] += clock() - t0
        return Evaluated(base.oracle_gap(name, e), text, trace, ended)
    except DomainError as e:
        seconds['convert'] += clock() - t0
        return Evaluated(base.new_result(name, 'REF_ERROR', detail='a domain sample disagrees with the recording',
                                         messages=[str(e)]), text, trace, ended)
    records = io.StringIO()
    conformance_records.write_battle(data, team_c, records, kind=kinds['TEAM_C' if team_c else 'CLOSURE'], domain=sets)
    seconds['convert'] += clock() - t0
    t0 = clock()
    try:
        run = runner.run(name, records.getvalue())
    except base.ChildFailure as e:
        seconds['run'] += clock() - t0
        return Evaluated(base.child_failure_result(name, e), text, trace, ended)
    seconds['run'] += clock() - t0
    bucket = runner_bucket(run.verdict, ended)
    if bucket == 'CAP':
        result = base.new_result(name, 'CAP', detail='the battle did not end within %d steps' % run.steps,
                                 steps=run.steps, context=run.context)
    else:
        result = base.new_result(name, bucket, detail=None if bucket == 'PASS' else run.detail, step=run.step,
                                 steps=run.steps, context=run.context, messages=run.messages)
    return Evaluated(result, text, trace, ended, sets)


Outcome = collections.namedtuple('Outcome', 'record spec trace_text trace play_request domain', defaults=((),))


def process_random(index, params, worker, runner, tables_for, kinds, spec_for, seconds, clock=time.monotonic):
    """Battle `index` through play, record, convert and run, and for a DIVERGENCE with a step or a CAP through the
    prefix again. Returns an Outcome: the record (RECORD_KEYS), the spec (with its choices when it got that far), the
    trace text and trace (or None), the play request (when the play failed) and the domain samples as the records
    have them (what the case of a domain difference shows)."""
    spec, policy_seed, pairing = spec_for(index)
    name = spec['name']
    battle = {'format': spec['format'], 'seed': spec['seed'], 'teams': spec['teams']}
    policy = {'seed': policy_seed, 'max_steps': params.max_steps, 'switch_weight': params.switch_weight,
              'mega_weight': params.mega_weight, 'domain_rate': params.domain_rate}

    def record_of(result, ended, reproduces=None, played=None):
        # How many requests were sampled (they are all in the records, or the battle never got there) and how many
        # samples were dropped because the request changed while Showdown judged it; None when there was no play.
        domain = None if played is None else {'samples': len(played['domain']['samples']),
                                              'request_changed': played['domain']['request_changed']}
        return {'index': index, 'name': name, 'pairing': pairing, 'bucket': result['bucket'], 'rule': result['rule'],
                'detail': result['detail'], 'step': result['step'], 'steps': result['steps'],
                'context': result['context'], 'ended': ended, 'reproduces': reproduces, 'domain': domain,
                'messages': result['messages']}

    t0 = clock()
    try:
        played = worker.play(battle, policy)
    except base.WorkerError as e:
        seconds['play'] += clock() - t0
        result = base.new_result(name, 'REF_ERROR', detail=e.error, messages=e.stack.split('\n') if e.stack else [])
        return Outcome(record_of(result, None), spec, None, None, {'battle': battle, 'policy': policy})
    except base.ChildFailure as e:
        seconds['play'] += clock() - t0
        return Outcome(record_of(base.child_failure_result(name, e), None), spec, None, None,
                       {'battle': battle, 'policy': policy})
    seconds['play'] += clock() - t0
    spec['choices'] = played['choices']
    samples = played['domain']['samples']
    first = evaluate(name, spec, worker, runner, tables_for, kinds, played['ended'], seconds, clock, domain=samples)
    result = first.result
    reproduces = None
    if (result['bucket'] == 'DIVERGENCE' and result['step'] is not None) or result['bucket'] == 'CAP':
        t0 = clock()
        cut = prefix_spec(spec, result['step'])
        cut_samples = [x for x in samples if x['step'] < len(cut['choices'])]
        again = evaluate(cut['name'], cut, worker, runner, tables_for, kinds, None, collections.defaultdict(float), clock,
                         domain=cut_samples)
        reproduces = again.result['bucket'] == result['bucket'] and again.result['step'] == result['step']
        seconds['prefix'] += clock() - t0
    return Outcome(record_of(result, first.ended, reproduces, played), spec, first.trace_text, first.trace, None,
                   first.domain)


# ------------------------------------------------------------ what to say about a battle that is not a PASS

def step_report(trace, step):
    """The protocol lines and draws of step `step` of a trace, each draw with what trace_to_c does with it: kept
    (a tape entry), dropped with the rule's reason, or the error it raises."""
    before = trace['start']['state'] if step == 0 else trace['steps'][step - 1]['state']
    entry = trace['steps'][step]
    draws = []
    for d in entry['draws']:
        try:
            if trace_to_c.side_end_tie(d, before) is not None:
                verdict = 'kept: the order of two side conditions ending'
            else:
                reason = trace_to_c.drop_reason(d, before)
                verdict = 'kept' if reason is None else 'dropped: ' + reason
        except trace_to_c.ConversionError as e:
            verdict = 'error: %s: %s' % (e.rule, e.code)
        except base.UNTYPED as e:
            verdict = 'error: %s: %s' % (type(e).__name__, e)
        draws.append({'draw': d, 'verdict': verdict})
    return {'step': step, 'input': entry['input'], 'log': entry['log'], 'draws': draws}


def dumps(value):
    return json.dumps(value, indent=1, ensure_ascii=False) + '\n'


def gzipped(text):
    """The gzip of `text`, the same bytes every time (no name, no time)."""
    buf = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buf, mtime=0) as f:
        f.write(text.encode('utf-8'))
    return buf.getvalue()


def case_files(outcome, prefix_result=None):
    """{file name: bytes} of the case of a battle that is not a PASS."""
    record = outcome.record
    files = {'spec.json': dumps(outcome.spec).encode('utf-8')}
    if outcome.trace_text is not None:
        files['trace.json.gz'] = gzipped(outcome.trace_text)
    if outcome.play_request is not None:
        files['play_request.json'] = dumps(outcome.play_request).encode('utf-8')
    head = '%s | %s | %s' % (record['bucket'], record['rule'] or '-', record['detail'] or '-')
    files['messages.txt'] = ('\n'.join([head] + record['messages']) + '\n').encode('utf-8')
    if record['bucket'] == 'DIVERGENCE' and record['step'] is not None and outcome.trace is not None:
        files['step.json'] = dumps(step_report(outcome.trace, record['step'])).encode('utf-8')
    at = re.search(r'^domain: .* \(step (\d+) side (\d+)\)$', record['detail'] or '')
    if at is not None:  # a difference of the domain: what Showdown accepted there, each text with its choice
        sample = next((x for x in outcome.domain if (x['step'], x['side']) == (int(at.group(1)), int(at.group(2)))), None)
        if sample is not None:
            files['domain.json'] = dumps({'step': sample['step'], 'side': sample['side'],
                                          'accepted': [{'text': t, 'choice': sample['rendered'][t]}
                                                       for t in sample['accepted']]}).encode('utf-8')
    if record['reproduces'] is not None:
        cut = prefix_spec(outcome.spec, record['step'])
        files['prefix_spec.json'] = dumps(cut).encode('utf-8')
        files['prefix_result.json'] = dumps({'bucket': record['bucket'], 'step': record['step'],
                                             'choices': len(cut['choices']), 'reproduces': record['reproduces']}).encode('utf-8')
    return files


def write_atomically(path, data):
    """Writes `data` (bytes) to `path` whole or not at all."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = '%s.%d.%d.tmp' % (path, os.getpid(), threading.get_ident())
    with io.open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def write_case(outdir, name, files):
    for fname, data in files.items():
        write_atomically(os.path.join(outdir, 'cases', name, fname), data)


# ------------------------------------------------------------ the signature of a battle that is not a PASS

def numbers_away(text):
    """A message without its numbers (decimal ones become #, hexadecimal ones 0x#): what is the same about differences
    in other places, with other values."""
    return re.sub(r'0x[0-9a-fA-F]+|\d+', lambda m: '0x#' if m.group().startswith('0x') else '#', text)


def event_signature(lines):
    """The two lines the events comparator prints after "event # differs" ("reference kind 7 pos ..." and "engine
    kind 5 ..."): the reference's event kind and the fields in which the two differ; None if they are not that."""
    parsed = {}
    for line in lines:
        m = re.match(r'^\s+(reference|engine)\s+(kind .*)$', line)
        if m:
            tokens = m.group(2).split()
            if len(tokens) % 2:
                return None
            seen = collections.Counter()
            fields = []
            for name, value in zip(tokens[::2], tokens[1::2]):
                seen[name] += 1
                fields.append((name if seen[name] == 1 else '%s%d' % (name, seen[name]), value))
            parsed[m.group(1)] = fields
    if 'reference' in parsed and 'engine' in parsed and len(parsed['reference']) == len(parsed['engine']):
        differ = [a[0] for a, b in zip(parsed['reference'], parsed['engine']) if a[1] != b[1]]
        return 'reference kind %s differs in %s' % (parsed['reference'][0][1], ', '.join(differ))
    if 'reference' in parsed:
        return 'reference kind %s, engine has no event' % parsed['reference'][0][1]
    if 'engine' in parsed:
        return 'engine kind %s, reference has no event' % parsed['engine'][0][1]
    return None


def runner_signature(detail, messages):
    """(rule, detail) of a DIVERGENCE or UNSUPPORTED of the runner, stable for the same kind of difference: the
    numbers of a message (the member, the HP) are not part of it."""
    m = re.match(r'^create: (.*)$', detail)
    if m:
        return 'create', m.group(1)
    m = re.match(r'^step: (DUOFORGE_E_\w+), tape ', detail)
    if m:
        return 'step', m.group(1)
    if detail.startswith('step: the tape is not consumed exactly'):
        return 'tape', 'not consumed exactly'
    m = re.match(r'^domain: candidates: (\w+) \(step \d+ side \d+\)$', detail)
    if m:
        return 'domain', 'candidates: ' + m.group(1)
    if re.match(r'^domain: engine-only \d+, reference-only \d+ \(step \d+ side \d+\)$', detail):
        # The kind of the choices that differ, from the examples that the runner prints.
        kinds = {}
        for which in ('engine-only', 'reference-only'):
            found = {choice_shape(m.group(1)) for line in messages
                     for m in [re.match(r'^  \S+ step \d+: domain side \d+ %s: (.*)$' % which, line)] if m}
            kinds[which] = ', '.join(sorted(found)) or '-'
        return 'domain', 'engine-only %s, reference-only %s' % (kinds['engine-only'], kinds['reference-only'])
    m = re.match(r'^differences: state (\d+), observation (\d+), events (\d+), battle_check (\w+)$', detail)
    if m:
        state, observation, events, check = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        rule = ('state' if state else 'observation' if observation else 'events' if events else 'battle_check')
        if rule == 'battle_check':
            return rule, check
        shown = [i for i, line in enumerate(messages) if re.match(r'^  \S+ step \d+: ', line)]
        if not shown:
            return rule, detail
        first = shown[0]
        text = re.sub(r'^  \S+ step \d+: ', '', messages[first])
        if rule == 'events':
            rest = messages[first + 1:first + 3]
            return rule, event_signature(rest) or numbers_away(text)
        return rule, numbers_away(text)
    return 'runner', numbers_away(detail)


def signature(record):
    """(rule, detail) of a battle that is not a PASS, as strings (empty where there is none): what the summary counts."""
    bucket = record['bucket']
    if bucket in ('DIVERGENCE', 'UNSUPPORTED') and record['detail']:
        if record['detail'].startswith('runner '):  # died or timed out: the exit code is the signature
            return 'runner-failed', record['detail'][len('runner '):]
        return runner_signature(record['detail'], record['messages'])
    return record['rule'] or '', record['detail'] or ''


def summarize(records, identity):
    """summary.json of a complete run: its parameters and versions, the count per bucket, and per (bucket, rule,
    detail) signature the count and the first battle of it."""
    counts = {bucket: 0 for bucket in base.RANDOM_BUCKETS}
    signatures = {}
    reproduction = {'reproduced': 0, 'not reproduced': 0}
    domain = {'rate': identity['domain_rate'], 'samples': 0, 'request_changed': 0}
    for record in sorted(records, key=lambda r: r['index']):
        counts[record['bucket']] += 1
        for key in ('samples', 'request_changed'):
            domain[key] += (record['domain'] or {}).get(key, 0)
        if record['reproduces'] is not None:
            reproduction['reproduced' if record['reproduces'] else 'not reproduced'] += 1
        if record['bucket'] == 'PASS':
            continue
        key = (record['bucket'],) + signature(record)
        if key not in signatures:
            signatures[key] = {'count': 0, 'first': record['index'], 'case': record['name']}
        signatures[key]['count'] += 1
    listed = [dict(bucket=k[0], rule=k[1] or None, detail=k[2] or None, **v)
              for k, v in sorted(signatures.items(), key=lambda kv: (BUCKET_ORDER[kv[0][0]], kv[0][1], kv[0][2]))]
    summary = {'mode': 'random', 'battles': len(records), 'buckets': counts, 'signatures': listed,
               'reproduction': reproduction, 'domain': domain}
    summary.update({k: identity[k] for k in ('seed', 'pairings', 'policy', 'node', 'pin', 'harness', 'git_head',
                                             'library_version')})
    return summary


# ------------------------------------------------------------ the output directory

def partial_path(outdir, index):
    return os.path.join(outdir, 'partial', '%d.json' % index)


def write_partial(outdir, index, record, seconds):
    write_atomically(partial_path(outdir, index),
                     json.dumps({'record': record, 'seconds': {k: round(seconds[k], 3) for k in PHASES}},
                                indent=1).encode('ascii') + b'\n')


def first_missing(outdir, battles, start=0):
    """The first battle from `start` on that has no result; `battles` when all of them have one. Chunks start their
    battles in order and finish what they start, so the results of a run are a prefix and this is where to go on."""
    k = start
    while k < battles and os.path.exists(partial_path(outdir, k)):
        k += 1
    return k


def read_partial(outdir, index):
    with io.open(partial_path(outdir, index), encoding='ascii') as f:
        return json.load(f)


def run_parameters(params):
    """What the battles of a run follow from, apart from the code that plays them."""
    return {'seed': params.seed, 'battles': params.battles, 'pairings': list(params.pairings),
            'policy': {'max_steps': params.max_steps, 'switch_weight': params.switch_weight,
                       'mega_weight': params.mega_weight},
            'domain_rate': params.domain_rate}


def identity_of(params, version, head, library, runner_sha256):
    """run.json: the parameters and the code that plays the battles (Node, the pin, the harness, the git HEAD, the
    library and the runner), all of which the results depend on."""
    identity = run_parameters(params)
    identity.update({'node': version['node'], 'pin': version['pin'], 'harness': version['harness'], 'git_head': head,
                     'library_version': library, 'runner_sha256': runner_sha256})
    return identity


def read_identity(outdir):
    """run.json of the directory, or None."""
    path = os.path.join(outdir, 'run.json')
    if not os.path.exists(path):
        return None
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def other_run(outdir, differ):
    return base.ToolError('%s belongs to another run (it differs in %s): use another --out' % (outdir, ', '.join(differ)))


def check_identity(outdir, identity):
    """run.json of the directory is this run, or it is written: a chunk never mixes into another run's results."""
    have = read_identity(outdir)
    if have is None:
        write_atomically(os.path.join(outdir, 'run.json'), dumps(identity).encode('utf-8'))
    elif have != identity:
        raise other_run(outdir, sorted(k for k in set(have) | set(identity) if have.get(k) != identity.get(k)))


def check_parameters(outdir, params):
    """The loop that starts the chunks has no versions to compare (the chunks have), but a directory that holds the
    results of another run is refused at once, also when there is nothing left to run and a report would be made."""
    have = read_identity(outdir)
    want = run_parameters(params)
    if have is not None and any(have.get(k) != v for k, v in want.items()):
        raise other_run(outdir, sorted(k for k, v in want.items() if have.get(k) != v))


def finalize(outdir, battles):
    """battles.jsonl, summary.json and timing.json from the results of all battles; ToolError if one is missing."""
    missing = [i for i in range(battles) if not os.path.exists(partial_path(outdir, i))]
    if missing:
        raise base.ToolError('battle %d and %d more have no result yet' % (missing[0], len(missing) - 1))
    parts = [read_partial(outdir, i) for i in range(battles)]
    records = [p['record'] for p in parts]
    with io.open(os.path.join(outdir, 'run.json'), encoding='utf-8') as f:
        identity = json.load(f)
    lines = []
    for record in records:
        assert list(record) == RECORD_KEYS, list(record)
        lines.append(json.dumps(record) + '\n')
    write_atomically(os.path.join(outdir, 'battles.jsonl'), ''.join(lines).encode('ascii'))
    write_atomically(os.path.join(outdir, 'summary.json'),
                     (json.dumps(summarize(records, identity), indent=1, sort_keys=True) + '\n').encode('ascii'))
    totals = {k: round(sum(p['seconds'][k] for p in parts), 3) for k in PHASES}
    chunks = []
    chunk_dir = os.path.join(outdir, 'chunks')
    if os.path.isdir(chunk_dir):  # a chunk that was killed may have left a temporary file: it is not a result
        names = [f for f in os.listdir(chunk_dir) if re.fullmatch(r'\d+\.json', f)]
        for fname in sorted(names, key=lambda f: int(f.split('.')[0])):
            with io.open(os.path.join(chunk_dir, fname), encoding='ascii') as f:
                chunks.append(json.load(f))
    slowest = sorted(({'name': r['name'], 'seconds': round(sum(p['seconds'].values()), 3)} for r, p in zip(records, parts)),
                     key=lambda x: (-x['seconds'], x['name']))[:10]
    write_atomically(os.path.join(outdir, 'timing.json'),
                     (json.dumps({'battles': battles, 'seconds': totals, 'chunks': chunks, 'slowest': slowest},
                                 indent=1) + '\n').encode('ascii'))


# ------------------------------------------------------------ a chunk: the battles of this process

def run_chunk(params, outdir, start, minutes, make_worker, make_runner, tables_for, kinds, spec_for, workers,
              clock=time.monotonic, out=sys.stdout):
    """Runs the battles from `start` that have no result yet, until all are done or `minutes` have passed (None: no
    limit): no battle is started after that and the running ones are finished. Every result is written to partial/
    when it is done, and a case to cases/. Returns how many battles this call ran. The caller checks the identity of
    the directory first."""
    indices = [i for i in range(start, params.battles) if not os.path.exists(partial_path(outdir, i))]
    if not indices:
        return 0
    deadline = None if minutes is None else clock() + minutes * 60
    t_start = clock()
    lock = threading.Lock()
    tally = [0]

    def handle(index, worker, runner):
        seconds = collections.defaultdict(float)
        outcome = process_random(index, params, worker, runner, tables_for, kinds, spec_for, seconds, clock)
        record = outcome.record
        if record['bucket'] != 'PASS':
            write_case(outdir, record['name'], case_files(outcome))
        return record, seconds

    def on_result(index, result):
        record, seconds = result
        write_partial(outdir, index, record, seconds)
        with lock:
            tally[0] += 1
            print('  [%d/%d] %s %s %s%s' % (index + 1, params.battles, record['name'], record['pairing'], record['bucket'],
                                          '' if record['rule'] is None and record['detail'] is None else
                                          ' ' + base.printable('%s %s' % (record['rule'] or '', record['detail'] or ''), 90)),
                  file=out, flush=True)

    base.run_lanes(indices, workers, make_worker, make_runner, handle,
                   should_stop=None if deadline is None else (lambda: clock() >= deadline), on_result=on_result)
    write_atomically(os.path.join(outdir, 'chunks', '%d.json' % indices[0]),
                     json.dumps({'start': indices[0], 'battles': tally[0], 'wall_seconds': round(clock() - t_start, 3)}).encode('ascii') + b'\n')
    return tally[0]


# ------------------------------------------------------------ the loop of chunks under the machine lock

def find_bash(windows=os.name == 'nt', which=shutil.which, environ=os.environ):
    """The bash that runs tools/ci/machine_lock.sh: the first on the PATH, but on Windows Git's, not the launcher
    of WSL in System32 (it would run the script in another system, where the paths mean nothing). None if there is
    none."""
    found = which('bash')
    if not windows:
        return found
    if found is not None and 'system32' not in found.lower().replace('/', '\\'):
        return found
    for var, tail in (('ProgramFiles', 'Git'), ('ProgramFiles(x86)', 'Git'), ('LocalAppData', os.path.join('Programs', 'Git'))):
        if environ.get(var):
            candidate = os.path.join(environ[var], tail, 'bin', 'bash.exe')
            if os.path.isfile(candidate):
                return candidate
    return None


def chunk_command(args_forward, start, minutes, python=None, driver_script=None, bash=None, lock_script=None):
    """The command of one chunk: the driver, held by tools/ci/machine_lock.sh, from battle `start`, for `minutes`."""
    bash = bash or find_bash()
    if bash is None:
        raise base.ToolError('bash is not on the PATH: the chunks run under tools/ci/machine_lock.sh (--no-lock to run without)')
    python = (python or sys.executable).replace('\\', '/')
    driver_script = (driver_script or os.path.join(base.HERE, 'diff_driver.py')).replace('\\', '/')
    lock_script = (lock_script or os.path.join(base.ROOT, 'tools', 'ci', 'machine_lock.sh')).replace('\\', '/')
    return [bash, lock_script, 'fuzz', python, driver_script, 'random'] + list(args_forward) + [
        '--start', str(start), '--chunk-minutes', str(minutes), '--no-lock']


def run_process(command):
    """Runs a chunk below normal priority (what it starts inherits that); its exit status."""
    argv, kwargs = base.low_priority(command)
    return subprocess.run(argv, **kwargs).returncode


def orchestrate(params, outdir, args_forward, minutes, start=0, run=run_process, sleep=time.sleep, python=None,
                driver_script=None, bash=None, lock_script=None, out=sys.stdout):
    """The chunks one after the other, from the first battle from `start` that has no result, until every battle
    from there has one; each is a process that holds the machine lock, and between two the lock is free for
    CHUNK_PAUSE seconds. Returns when the last chunk is done."""
    done = first_missing(outdir, params.battles, start)
    while done < params.battles:
        command = chunk_command(args_forward, done, minutes, python, driver_script, bash, lock_script)
        print('diff_random: chunk from battle %d of %d' % (done, params.battles), file=out, flush=True)
        status = run(command)
        if status != 0:
            raise base.ToolError('a chunk (from battle %d) exited with status %d' % (done, status))
        progress = first_missing(outdir, params.battles, done)
        if progress <= done:
            raise base.ToolError('a chunk from battle %d made no progress' % done)
        done = progress
        if done < params.battles:
            sleep(CHUNK_PAUSE)  # the lock is free: a waiting CI or benchmark takes it


# ------------------------------------------------------------ the command line

def parse_pairings(text):
    """'AB,ba,CC' -> ('AB', 'BA', 'CC'); ValueError for one that is not a pairing of A, B and C."""
    out = tuple(p.strip().upper() for p in text.split(',') if p.strip())
    bad = [p for p in out if p not in PAIRINGS]
    if not out or bad:
        raise ValueError('pairings are some of %s, not %r' % (','.join(PAIRINGS), bad or text))
    return out


def add_arguments(modes):
    p = modes.add_parser('random', help='random Showdown-judged battles through worker, converter and runner')
    p.add_argument('--checkout', required=True, help='the pinned Showdown checkout (built: dist/sim exists)')
    p.add_argument('--runner', required=True, help='the duoforge_diff_runner executable')
    p.add_argument('--battles', type=int, required=True, help='how many battles (index 0 to N - 1)')
    p.add_argument('--seed', type=int, required=True, help='the seed of the run (0 or more)')
    p.add_argument('--pairings', default=','.join(DEFAULT_PAIRINGS),
                   help='which teams meet, battle i takes the pairing at i mod the number of pairings: some of %s '
                   '(C is opt-in; default %s)' % (','.join(PAIRINGS), ','.join(DEFAULT_PAIRINGS)))
    p.add_argument('--workers', type=int, default=4, help='threads, each with a worker and a runner (default 4)')
    p.add_argument('--out', metavar='DIR', help='default build/diff/<UTC yyyymmdd-hhmmss>-random-s<S>')
    p.add_argument('--start', type=int, default=0, help='the first battle to run in this process (default 0)')
    p.add_argument('--chunk-minutes', type=int, default=None,
                   help='stop starting battles after M minutes (default 10 without --no-lock, none with it)')
    p.add_argument('--no-lock', action='store_true', help='run in this process, with no machine lock and no chunks')
    p.add_argument('--node', metavar='EXE', help='default: node on the PATH')
    p.add_argument('--max-steps', type=int, default=DEFAULT_MAX_STEPS,
                   help='a battle that has not ended after this many steps is a CAP (default %d)' % DEFAULT_MAX_STEPS)
    p.add_argument('--switch-weight', type=float, default=DEFAULT_SWITCH_WEIGHT,
                   help='the chance that a slot switches (default %s)' % DEFAULT_SWITCH_WEIGHT)
    p.add_argument('--mega-weight', type=float, default=DEFAULT_MEGA_WEIGHT,
                   help='the chance that a Pokemon that can Mega Evolve does (default %s)' % DEFAULT_MEGA_WEIGHT)
    p.add_argument('--domain-rate', type=float, default=DEFAULT_DOMAIN_RATE,
                   help='the share of requests whose whole domain (every choice Showdown accepts) is compared with the '
                   "engine's candidates; 0 for none (default %s)" % DEFAULT_DOMAIN_RATE)
    return p


def validate(parser, args):
    """The Params of a parsed command line, or parser.error."""
    try:
        pairings = parse_pairings(args.pairings)
    except ValueError as e:
        parser.error(str(e))
    if args.battles < 1 or args.seed < 0 or args.workers < 1 or args.start < 0 or args.max_steps < 1:
        parser.error('--battles, --workers and --max-steps are at least 1; --seed and --start at least 0')
    if args.chunk_minutes is not None and args.chunk_minutes < 1:
        parser.error('--chunk-minutes is at least 1')
    if not (0 <= args.switch_weight <= 1 and 0 <= args.mega_weight <= 1 and 0 <= args.domain_rate <= 1):
        parser.error('--switch-weight, --mega-weight and --domain-rate are from 0 to 1')
    if args.start >= args.battles:
        parser.error('--start %d is not before --battles %d' % (args.start, args.battles))
    if not os.path.isfile(args.runner):
        parser.error('--runner %s is not a file' % args.runner)
    if not os.path.isdir(os.path.join(args.checkout, 'dist', 'sim')):
        parser.error('--checkout %s has no dist/sim (npm ci --ignore-scripts --omit=dev; node build)' % args.checkout)
    if (args.node or shutil.which('node')) is None:
        parser.error('node is not on the PATH (--node)')
    return Params(args.seed, args.battles, pairings, args.max_steps, args.switch_weight, args.mega_weight,
                  args.domain_rate)


def forwarded(args, outdir):
    """The arguments a chunk gets: the run's, with the output directory fixed."""
    out = ['--checkout', args.checkout, '--runner', os.path.abspath(args.runner), '--battles', str(args.battles),
           '--seed', str(args.seed), '--pairings', args.pairings, '--workers', str(args.workers), '--out', outdir,
           '--max-steps', str(args.max_steps), '--switch-weight', repr(args.switch_weight), '--mega-weight',
           repr(args.mega_weight), '--domain-rate', repr(args.domain_rate)]
    if args.node:
        out += ['--node', args.node]
    return out


def file_sha256(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def run(args, params):
    """The random mode with parsed arguments; the exit status."""
    root = base.ROOT
    outdir = os.path.abspath(args.out or os.path.join(root, 'build', 'diff', '%s-random-s%d' % (
        datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S'), params.seed)))
    start = args.start
    if not args.no_lock:
        minutes = args.chunk_minutes if args.chunk_minutes is not None else DEFAULT_CHUNK_MINUTES
        check_parameters(outdir, params)
        orchestrate(params, outdir, forwarded(args, outdir), minutes, start=start, run=run_process)
    else:
        node = args.node or shutil.which('node')
        runner_path = os.path.abspath(args.runner)
        make_worker = lambda: base.NodeWorker(node, args.checkout, WORKER_TIMEOUT)
        make_runner = lambda: base.DiffRunner(runner_path, RUNNER_TIMEOUT)
        probe = make_worker()
        try:
            version = probe.version()
        except BaseException:
            probe.kill()
            raise
        for problem in probe.close():
            raise base.ToolError(problem)
        identity = identity_of(params, version, base.git_head(root), base.library_version(root), file_sha256(runner_path))
        os.makedirs(outdir, exist_ok=True)
        check_identity(outdir, identity)
        teams = read_teams(root)
        tables = {team_c: trace_to_c.load_tables(root, team_c) for team_c in (False, True)}
        kinds = conformance_records.data_kinds(root)
        ran = run_chunk(params, outdir, start, args.chunk_minutes, make_worker, make_runner, tables.__getitem__, kinds,
                        lambda index: derive(params, index, teams), args.workers)
        print('diff_random: %d battles run in this process' % ran, flush=True)
        if args.chunk_minutes is not None:
            # One chunk of a run: its results are in partial/. The files of the whole run are written by whoever owns
            # the run: the loop that started the chunk, or a run of this mode without --chunk-minutes.
            print('diff_random: the first %d of %d battles have a result in %s' % (
                first_missing(outdir, params.battles), params.battles, outdir), flush=True)
            return 0
    finalize(outdir, params.battles)
    with io.open(os.path.join(outdir, 'summary.json'), encoding='ascii') as f:
        summary = json.load(f)
    report(summary, outdir)
    return 0


def report(summary, outdir):
    counts = summary['buckets']
    print('diff_random: %d battles, seed %d: %s' % (summary['battles'], summary['seed'], ', '.join(
        '%s %d' % (b, counts[b]) for b in base.RANDOM_BUCKETS if counts[b] or b == 'PASS')))
    for entry in summary['signatures']:
        print('  %s %s %s: %d (first %s)' % (entry['bucket'], entry['rule'] or '-', base.printable(entry['detail'] or '-', 100),
                                           entry['count'], entry['case']))
    domain = summary['domain']
    if domain['rate'] > 0:
        print('diff_random: domain rate %s: %d requests compared, %d dropped because the request changed' % (
            domain['rate'], domain['samples'], domain['request_changed']))
    print('diff_random: results in %s' % outdir)
