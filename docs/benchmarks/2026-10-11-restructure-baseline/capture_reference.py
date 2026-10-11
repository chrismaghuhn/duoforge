"""Observe all five variants of both reference drivers without editing them.

Linux/GCC, Release+IPO Ninja build, CMAKE_EXPORT_COMPILE_COMMANDS=ON.
Usage: python capture_reference.py REPO BUILD OUTSIDE_REPO_OUTPUT
Only per-battle hashes/counts and aggregate results are saved; no replay data.
The original assertions still execute; any failed compile/run aborts capture.
"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one insertion point: {old!r}")
    return source.replace(old, new)


def instrument(source, kind, header):
    source = replace_once(source, 'static void build_setup(',
                          f'#include "{header.as_posix()}"\n\nstatic void build_setup(')
    source = replace_once(source, '        unsigned bad = 0;',
                          '        printf("BEGIN %s\\n", cb->name);\n'
                          '        baseline_state(ctx, b);\n        unsigned bad = 0;')
    source = replace_once(source, '        duoforge_battle_destroy(b);',
                          '        printf("END %s\\n", cb->name);\n        duoforge_battle_destroy(b);')
    if kind == 'conformance':
        source = replace_once(source, '            bad += df_conf_compare_state(',
                              '            baseline_step(ctx, b, used, &res);\n'
                              '            baseline_events(buffers);\n            bad += df_conf_compare_state(')
    else:
        source = replace_once(source, '    counts->stops += 1u;',
                              '    baseline_tiebreak(st, &r, rs, ps, out);\n    counts->stops += 1u;')
        source = replace_once(source, '            }\n            while (stop < tb->stop_count',
                              '                baseline_step(ctx, b, used, &res);\n'
                              '            }\n            while (stop < tb->stop_count')
    return source


def records(stdout):
    result, current, lines = [], None, []
    for line in stdout.splitlines(keepends=True):
        if line.startswith('BEGIN '):
            if current is not None:
                raise RuntimeError('nested battle')
            current, lines = line[6:].strip(), []
        elif line.startswith('END '):
            if current != line[4:].strip():
                raise RuntimeError('incomplete battle')
            if not lines or not lines[0].startswith('state '):
                raise RuntimeError('missing initial state observation')
            result.append(dict(name=current, sha256=hashlib.sha256(''.join(lines).encode('ascii')).hexdigest(),
                               steps=sum(s.startswith('step ') for s in lines),
                               stops=sum(s.startswith('tiebreak ') for s in lines)))
            current = None
        elif current is not None:
            lines.append(line)
    if current is not None or not result or len({r['name'] for r in result}) != len(result):
        raise RuntimeError('incomplete or duplicate battle records')
    return sorted(result, key=lambda r: r['name'])


def main():
    repo, build, output = (Path(a).resolve() for a in sys.argv[1:])
    if output.is_relative_to(repo):
        raise RuntimeError('capture output must be outside the repository')
    output.mkdir(parents=True, exist_ok=True)
    database = json.loads((build / 'compile_commands.json').read_text())
    header = Path(__file__).with_name('observe.h').resolve()
    summary = {}
    with tempfile.TemporaryDirectory(prefix='reference-observer-', dir=output) as temp:
        temp = Path(temp)
        for kind in ('conformance', 'tiebreak'):
            source = repo / 'tests' / f'test_{kind}.c'
            entries = [e for e in database if Path(e['file']).resolve() == source]
            if len(entries) != 5:
                raise RuntimeError(f'expected five {kind} variants, got {len(entries)}')
            observed = temp / source.name
            observed.write_text(instrument(source.read_text(), kind, header))
            for entry in entries:
                args = shlex.split(entry['command'])
                target = re.search(r'CMakeFiles/([^/]+)\.dir/', entry['command']).group(1)
                obj, exe = temp / f'{target}.o', temp / target
                args[args.index('-o') + 1] = str(obj)
                args[args.index('-c') + 1] = str(observed)
                if kind == 'conformance':
                    args.insert(1, '-DBASELINE_CONFORMANCE')
                subprocess.run(args, cwd=entry['directory'], check=True)
                subprocess.run([args[0], '-flto=auto', str(obj), str(build / 'tests/libduoforge_test_support.a'),
                                str(build / 'libduoforge.a'), '-pthread', '-o', str(exe)], check=True)
                run = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
                rows = records(run.stdout)
                canonical = ''.join(f"{r['name']}\t{r['sha256']}\n" for r in rows).encode('ascii')
                summary[target] = dict(battles=len(rows), steps=sum(r['steps'] for r in rows),
                                       stops=sum(r['stops'] for r in rows),
                                       sha256=hashlib.sha256(canonical).hexdigest(),
                                       checks=run.stdout.splitlines()[-1], details=run.stderr.strip(),
                                       per_battle=rows)
                print(target, len(rows), summary[target]['sha256'], flush=True)
    (output / 'reference-results.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
