#!/usr/bin/env python3
"""Differential loop, replay mode (docs/research/expansion/differential-testing.md,
component 4): every committed battle goes worker -> converter -> runner and is
put in exactly one bucket.

usage: python tools/reference/diff_driver.py replay --checkout <pinned checkout>
           --runner <duoforge_diff_runner> [--workers N] [--only <glob>] [--out DIR] [--node <node>]

For each committed spec (tests/reference/specs, in name order):

 1. The persistent worker (ps_worker.js) records the spec; its trace must be
    the committed trace (line ends as LF), else REF_ERROR ("trace differs from
    the committed trace"). A worker that answers ok:false is REF_ERROR with its
    error.
 2. trace_to_c converts the battle. A ConversionError is ORACLE_GAP with its
    rule and detail; a KeyError, IndexError, ValueError or TypeError out of
    convert_battle is ORACLE_GAP with the rule "untyped:<ExceptionType>" and
    as detail the message and where it was raised. Nothing else is caught.
 3. conformance_records writes the records and the runner (tools/difftest)
    answers PASS, DIVERGENCE or UNSUPPORTED, with its messages.

N threads (default 4) each own one worker and one runner process. A process
that dies, does not answer in time or answers out of protocol is a failure of
the tool, not a bucket: the replay stops with status 3 and writes nothing.

--out (default build/diff/<UTC yyyymmdd-hhmmss>-replay) gets battles.jsonl,
one line per battle in name order (name, bucket, rule, detail, step, steps,
context, messages; null where there is nothing), and summary.json: the counts
per bucket and per rule and the versions the run used. Neither depends on
thread timing. Exit status: 0 when every battle is PASS, 1 when one is not,
2 for a bad command line, 3 for a failure of the tool.

This file only orchestrates: the rules of the game are the converter's and
the engine's.
"""
import argparse
import datetime
import fnmatch
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import namedtuple

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import conformance_records  # noqa: E402
import trace_to_c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
WORKER_SCRIPT = os.path.join(HERE, 'ps_worker.js')

BUCKETS = ('PASS', 'DIVERGENCE', 'UNSUPPORTED', 'ORACLE_GAP', 'REF_ERROR')
VERDICTS = ('PASS', 'DIVERGENCE', 'UNSUPPORTED')  # what the runner says
UNTYPED = (KeyError, IndexError, ValueError, TypeError)  # the errors of convert_battle that are an ORACLE_GAP
REQUEST_TIMEOUT = 300  # seconds a child may take for one answer
EXIT_NOT_ALL_PASS, EXIT_TOOL = 1, 3  # a bad command line is argparse's 2


class ToolError(Exception):
    """The driver's own machinery failed: a child died, hung or answered out of protocol. Never a bucket."""


class WorkerError(Exception):
    """The worker answered ok:false: its message and the first lines of its stack."""

    def __init__(self, error, stack):
        super().__init__(error)
        self.error = error
        self.stack = stack


RunnerResult = namedtuple('RunnerResult', 'verdict context step steps detail messages')


# ------------------------------------------------------------ child processes

class Child:
    """A child process spoken to in lines over binary pipes. Its stderr goes to
    a temporary file, which is read when something went wrong."""

    def __init__(self, argv, label, timeout):
        self.label = label
        self.timeout = timeout
        self.timed_out = False
        self.stderr = tempfile.TemporaryFile()
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr)
        except OSError as e:
            self.stderr.close()
            raise ToolError('cannot start %s (%s): %s' % (label, argv[0], e)) from None

    def _expire(self):
        self.timed_out = True
        self.proc.kill()

    def _stderr_tail(self):
        self.stderr.seek(0)
        text = self.stderr.read()[-1500:].decode('utf-8', 'replace').strip()
        return ': ' + text if text else ''

    def _death(self):
        """What became of the process, for the message of a ToolError."""
        try:
            code = self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            code = self.proc.wait()
        if self.timed_out:
            return 'no answer in %d s, killed%s' % (self.timeout, self._stderr_tail())
        return 'exited with status %s%s' % (code, self._stderr_tail())

    def send(self, data):
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except OSError:
            raise ToolError('%s closed its input: %s' % (self.label, self._death())) from None

    def readline(self):
        """The next line from the child, without its line end."""
        timer = threading.Timer(self.timeout, self._expire)
        timer.start()
        try:
            line = self.proc.stdout.readline()
        finally:
            timer.cancel()
        if not line.endswith(b'\n'):
            raise ToolError('%s gave no answer: %s' % (self.label, self._death()))
        return line

    def _release(self):
        for pipe in (self.proc.stdin, self.proc.stdout, self.stderr):
            try:
                pipe.close()
            except OSError:
                pass

    def close(self):
        """The end of a job well done: EOF on stdin, and the child must leave
        with status 0. Returns the problems found (none if it did)."""
        problems = []
        try:
            self.proc.stdin.close()
        except OSError:
            pass  # it is gone; its status says why
        try:
            code = self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            problems.append('%s did not leave at EOF' % self.label)
        else:
            if code != 0:
                problems.append('%s left with status %s%s' % (self.label, code, self._stderr_tail()))
        self._release()
        return problems

    def kill(self):
        """The end of an abandoned job."""
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self._release()


class NodeWorker(Child):
    """The client of ps_worker.js (its protocol is in that file)."""

    def __init__(self, node, checkout, timeout=REQUEST_TIMEOUT):
        super().__init__([node, WORKER_SCRIPT, checkout], 'the reference worker', timeout)
        self.next_id = 1

    def request(self, cmd, **fields):
        rid = self.next_id
        self.next_id += 1
        self.send(json.dumps({'id': rid, 'cmd': cmd, **fields}).encode('ascii') + b'\n')
        raw = self.readline()
        try:
            reply = json.loads(raw.decode('utf-8'))
        except ValueError:
            raise ToolError('%s answered something that is not JSON: %r' % (self.label, raw[:200])) from None
        if not isinstance(reply, dict) or reply.get('id') != rid or not isinstance(reply.get('ok'), bool):
            raise ToolError('%s answered out of protocol to request %d: %r' % (self.label, rid, raw[:200]))
        if not reply['ok']:
            raise WorkerError(str(reply.get('error')), str(reply.get('stack', '')))
        return reply

    def version(self):
        reply = self.request('version')
        try:
            return {key: reply[key] for key in ('node', 'pin', 'harness')}
        except KeyError as e:
            raise ToolError('%s: the version answer lacks %s' % (self.label, e)) from None

    def record(self, spec, spec_file):
        """The trace text of `spec`, exactly what ps_trace.js prints."""
        trace = self.request('record', spec=spec, spec_file=spec_file).get('trace')
        if not isinstance(trace, str):
            raise ToolError('%s answered a record without a trace' % self.label)
        return trace


class DiffRunner(Child):
    """The client of duoforge_diff_runner (its output format is in diff_runner.c)."""

    def __init__(self, exe, timeout=REQUEST_TIMEOUT):
        super().__init__([exe], 'the runner', timeout)

    def run(self, name, records):
        """Feeds one battle (`records` text) and returns its RunnerResult."""
        self.send(records.encode('ascii'))
        messages = []
        while True:
            line = self.readline().decode('ascii', 'replace').rstrip('\r\n')  # Windows may add the CR
            if line.startswith('R '):
                break
            messages.append(line)
        parts = line.split(' ', 6)
        if len(parts) != 7 or parts[1] != name or parts[2] not in VERDICTS:
            raise ToolError('%s: the answer for %s is not a result line: %r' % (self.label, name, line))
        try:
            step = None if parts[4] == '-' else int(parts[4])
            steps = int(parts[5])
        except ValueError:
            raise ToolError('%s: the answer for %s has no step numbers: %r' % (self.label, name, line)) from None
        return RunnerResult(parts[2], parts[3], step, steps, parts[6], messages)


# ------------------------------------------------------------ one battle

def new_result(name, bucket, rule=None, detail=None, step=None, steps=None, context=None, messages=()):
    """The record of a battle: one schema, null where there is nothing."""
    assert bucket in BUCKETS, bucket
    return {'name': name, 'bucket': bucket, 'rule': rule, 'detail': detail, 'step': step, 'steps': steps,
            'context': context, 'messages': list(messages)}


def clip(text, n=200):
    return text if len(text) <= n else text[:n] + '...'


def printable(text, n=160):
    """`text` clipped for the console, in ASCII whatever the console is: the error of a worker may hold anything."""
    return clip(text, n).encode('ascii', 'backslashreplace').decode('ascii')


def first_difference(have, want):
    """Where two texts first differ, for the messages of a REF_ERROR."""
    a, b = have.split('\n'), want.split('\n')
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return 'line %d: %s against %s' % (i + 1, clip(a[i]) if i < len(a) else '<end>', clip(b[i]) if i < len(b) else '<end>')


def raised_at(e):
    """The function and the line where `e` was raised (the innermost frame of its traceback)."""
    tb = e.__traceback__
    while tb.tb_next is not None:
        tb = tb.tb_next
    return tb.tb_frame.f_code.co_name, tb.tb_lineno


def oracle_gap(name, e):
    """The ORACLE_GAP of an error of the converter: a ConversionError by its
    rule and detail, an untyped one by its type, its message and where it was raised."""
    if isinstance(e, trace_to_c.ConversionError):
        return new_result(name, 'ORACLE_GAP', rule=e.rule, detail=e.detail, messages=[e.code])
    function, line = raised_at(e)
    return new_result(name, 'ORACLE_GAP', rule='untyped:' + type(e).__name__, detail='%s (%s:%d)' % (e, function, line),
                      messages=['%s: %s' % (type(e).__name__, e)])


def process_battle(name, spec, committed, worker, runner, tables_for):
    """One battle through the three steps; the record of its bucket. `committed`
    is the text of its committed trace (LF), `tables_for(team_c)` the name
    tables of trace_to_c."""
    try:
        text = worker.record(spec, name + '.json')
    except WorkerError as e:
        return new_result(name, 'REF_ERROR', detail=e.error, messages=e.stack.split('\n') if e.stack else [])
    if text != committed:
        return new_result(name, 'REF_ERROR', detail='trace differs from the committed trace',
                          messages=[first_difference(text, committed)])
    trace = json.loads(text)
    try:
        team_c = trace_to_c.spec_is_team_c(name, spec)
    except trace_to_c.ConversionError as e:
        return oracle_gap(name, e)
    tables = tables_for(team_c)
    try:
        data = trace_to_c.convert_battle(name, spec, trace, tables)
    except trace_to_c.ConversionError as e:
        return oracle_gap(name, e)
    except UNTYPED as e:
        return oracle_gap(name, e)
    records = io.StringIO()
    conformance_records.write_battle(data, team_c, records)
    run = runner.run(name, records.getvalue())
    return new_result(name, run.verdict, detail=None if run.verdict == 'PASS' else run.detail, step=run.step,
                      steps=run.steps, context=run.context, messages=run.messages)


# ------------------------------------------------------------ the replay

def spec_names(root):
    """The committed specs, by name."""
    return sorted(f[:-5] for f in os.listdir(os.path.join(root, 'tests', 'reference', 'specs')) if f.endswith('.json'))


def load_committed(root, name):
    """The parsed spec and the text of the committed trace of battle `name`, with LF line ends."""
    spec = trace_to_c.load_json(root, 'specs', name)
    with io.open(os.path.join(root, 'tests', 'reference', 'traces', name + '.json'), 'rb') as f:
        return spec, f.read().decode('utf-8').replace('\r\n', '\n')


def run_lanes(names, workers, make_worker, make_runner, handle):
    """Serves `names` with `workers` lanes: each lane makes its own worker and
    runner, asks the worker for its version, and takes the next name until none
    is left; handle(name, worker, runner) returns the record of a battle.
    Returns ({name: record}, version). The first failure of a lane stops the
    others and is raised once all are done; a lane closes its children (and
    reports one that does not leave cleanly), or kills them after a failure."""
    if not names:
        raise ToolError('there are no battles to replay')
    jobs = queue.Queue()
    for name in names:
        jobs.put(name)
    results, versions, errors = {}, [], []
    lock = threading.Lock()
    abort = threading.Event()

    def lane():
        children = []
        failed = False
        try:
            for make in (make_worker, make_runner):
                children.append(make())
            worker, runner = children
            version = worker.version()
            with lock:
                versions.append(version)
            while not abort.is_set():
                try:
                    name = jobs.get_nowait()
                except queue.Empty:
                    break
                record = handle(name, worker, runner)
                with lock:
                    results[name] = record
        except BaseException as e:  # a failure of any kind ends the whole replay
            failed = True
            with lock:
                errors.append(e)
            abort.set()
        finally:
            for child in reversed(children):
                if failed:
                    child.kill()
                else:
                    for problem in child.close():
                        with lock:
                            errors.append(ToolError(problem))
                        abort.set()

    lanes = [threading.Thread(target=lane, name='lane-%d' % i) for i in range(min(workers, len(names)))]
    for t in lanes:
        t.start()
    for t in lanes:
        t.join()
    if errors:
        raise errors[0]
    if sorted(results) != sorted(names):
        raise ToolError('%d battles have no result' % (len(names) - len(results)))
    if any(v != versions[0] for v in versions):
        raise ToolError('the workers disagree about their versions: %r' % versions)
    return results, versions[0]


def library_version(root):
    """MAJOR.MINOR.PATCH from include/duoforge/duoforge.h."""
    with io.open(os.path.join(root, 'include', 'duoforge', 'duoforge.h'), encoding='utf-8') as f:
        text = f.read()
    parts = []
    for part in ('MAJOR', 'MINOR', 'PATCH'):
        m = re.search(r'^#define DUOFORGE_VERSION_%s (\d+)$' % part, text, re.M)
        if m is None:
            raise ToolError('DUOFORGE_VERSION_%s is not in include/duoforge/duoforge.h' % part)
        parts.append(m.group(1))
    return '.'.join(parts)


def git_head(root):
    try:
        p = subprocess.run(['git', '-C', root, 'rev-parse', 'HEAD'], capture_output=True, text=True)
    except OSError as e:
        raise ToolError('cannot run git for the HEAD of %s: %s' % (root, e)) from None
    if p.returncode != 0:
        raise ToolError('cannot read the git HEAD of %s: %s' % (root, p.stderr.strip() or p.returncode))
    return p.stdout.strip()


def summarize(results, version, mode, head, library):
    counts = {bucket: 0 for bucket in BUCKETS}
    rules = {}
    for record in results.values():
        counts[record['bucket']] += 1
        if record['rule'] is not None:
            rules[record['rule']] = rules.get(record['rule'], 0) + 1
    return {'mode': mode, 'battles': len(results), 'buckets': counts, 'rules': dict(sorted(rules.items())),
            'node': version['node'], 'pin': version['pin'], 'harness': version['harness'], 'git_head': head,
            'library_version': library}


def write_outputs(outdir, results, summary):
    """battles.jsonl (in name order) and summary.json (sorted keys) into outdir."""
    os.makedirs(outdir, exist_ok=True)
    with io.open(os.path.join(outdir, 'battles.jsonl'), 'w', encoding='ascii', newline='\n') as f:
        for name in sorted(results):
            f.write(json.dumps(results[name]) + '\n')
    with io.open(os.path.join(outdir, 'summary.json'), 'w', encoding='ascii', newline='\n') as f:
        f.write(json.dumps(summary, indent=1, sort_keys=True) + '\n')


def report(summary, results, outdir):
    counts = summary['buckets']
    print('diff_driver: replay of %d battles: %s' % (summary['battles'], ', '.join(
        '%s %d' % (b, counts[b]) for b in BUCKETS if counts[b] or b == 'PASS')))
    shown = 0
    for name in sorted(results):
        record = results[name]
        if record['bucket'] != 'PASS':
            shown += 1
            if shown <= 40:
                print('  %s %s %s%s' % (name, record['bucket'], record['rule'] or '-',
                                         ' step %d' % record['step'] if record['step'] is not None else ''))
                print('      %s' % printable(str(record['detail'])))
    if shown > 40:
        print('  ... and %d more (battles.jsonl)' % (shown - 40))
    print('diff_driver: results in %s' % outdir)


def select_names(names, pattern):
    """The names that match the fnmatch pattern (all of them without one); ValueError when none does."""
    if pattern is None:
        return names
    chosen = [n for n in names if fnmatch.fnmatchcase(n, pattern)]
    if not chosen:
        raise ValueError('no committed spec matches %r' % pattern)
    return chosen


def battle_handler(root, tables):
    """handle(name, worker, runner) for run_lanes: the battle `name` of the
    committed data under `root`, put in its bucket. `tables` maps team_c to the
    name tables."""

    def handle(name, worker, runner):
        spec, committed = load_committed(root, name)
        return process_battle(name, spec, committed, worker, runner, tables.__getitem__)

    return handle


def replay(root, names, node, args):
    """The replay of the committed battles `names`; the exit status."""
    tables = {team_c: trace_to_c.load_tables(root, team_c) for team_c in (False, True)}
    runner = os.path.abspath(args.runner)  # a bare name would be looked up on the PATH
    results, version = run_lanes(names, args.workers, lambda: NodeWorker(node, args.checkout),
                                 lambda: DiffRunner(runner), battle_handler(root, tables))
    summary = summarize(results, version, 'replay', git_head(root), library_version(root))
    outdir = args.out or os.path.join(root, 'build', 'diff', datetime.datetime.now(datetime.timezone.utc).strftime(
        '%Y%m%d-%H%M%S') + '-replay')
    write_outputs(outdir, results, summary)
    report(summary, results, outdir)
    return 0 if summary['buckets']['PASS'] == summary['battles'] else EXIT_NOT_ALL_PASS


def main(argv):
    parser = argparse.ArgumentParser(prog='diff_driver.py', description=__doc__.split('\n')[0])
    modes = parser.add_subparsers(dest='mode', required=True)
    p = modes.add_parser('replay', help='put every committed battle in a bucket')
    p.add_argument('--checkout', required=True, help='the pinned Showdown checkout (built: dist/sim exists)')
    p.add_argument('--runner', required=True, help='the duoforge_diff_runner executable')
    p.add_argument('--workers', type=int, default=4, help='threads, each with a worker and a runner (default 4)')
    p.add_argument('--only', metavar='GLOB', help='only the specs whose name matches (fnmatch)')
    p.add_argument('--out', metavar='DIR', help='default build/diff/<UTC yyyymmdd-hhmmss>-replay')
    p.add_argument('--node', metavar='EXE', help='default: node on the PATH')
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error('--workers must be at least 1')
    if not os.path.isfile(args.runner):
        parser.error('--runner %s is not a file' % args.runner)
    if not os.path.isdir(os.path.join(args.checkout, 'dist', 'sim')):
        parser.error('--checkout %s has no dist/sim (npm ci --ignore-scripts --omit=dev; node build)' % args.checkout)
    node = args.node or shutil.which('node')
    if node is None:
        parser.error('node is not on the PATH (--node)')
    try:
        names = select_names(spec_names(ROOT), args.only)
    except ValueError as e:
        parser.error(str(e))
    try:
        return replay(ROOT, names, node, args)
    except ToolError as e:
        sys.stderr.write('diff_driver: %s\n' % e)
        return EXIT_TOOL


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
