"""Capture all five contexts of both reference runners via --digest-out.

Usage: python capture_reference.py REPO BUILD OUTSIDE_REPO_OUTPUT
The test-only digest encoding was verified against the step-0 observer on
cc8d3fc7. All original assertions execute; a failed run aborts capture.
Only per-battle counts and hashes are retained, never raw replay/state data.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


VARIANTS = ('', '_pool', '_team_c', '_team_c_pool', '_pool_data')


def records(text):
    rows = []
    for line in text.splitlines():
        fields = line.split('\t')
        if (len(fields) != 4 or re.fullmatch(r'[A-Za-z0-9_]{1,63}', fields[0]) is None or
                re.fullmatch(r'[0-9a-f]{64}', fields[1]) is None or
                any(re.fullmatch(r'[0-9]+', x) is None for x in fields[2:])):
            raise ValueError('invalid reference digest record')
        name, digest, steps, stops = fields
        rows.append(dict(name=name, sha256=digest, steps=int(steps), stops=int(stops)))
    if not rows or len({r['name'] for r in rows}) != len(rows):
        raise ValueError('empty or duplicate reference digest records')
    return sorted(rows, key=lambda r: r['name'])


def main():
    if len(sys.argv) != 4:
        raise SystemExit('usage: capture_reference.py REPO BUILD OUTSIDE_REPO_OUTPUT')
    repo, build, output = (Path(a).resolve() for a in sys.argv[1:])
    if output.is_relative_to(repo):
        raise ValueError('capture output must be outside the repository')
    output.mkdir(parents=True, exist_ok=True)
    summary = {}
    with tempfile.TemporaryDirectory(prefix='reference-digests-', dir=output) as temp:
        for kind in ('conformance', 'tiebreak'):
            for suffix in VARIANTS:
                target = f'duoforge_reference_{kind}{suffix}'
                exe = build / 'tests' / target
                if not exe.exists():
                    exe = exe.with_suffix('.exe')
                digest_file = Path(temp) / f'{target}.tsv'
                run = subprocess.run([str(exe), '--digest-out', str(digest_file)],
                                     cwd=build / 'tests', check=True, capture_output=True, text=True)
                rows = records(digest_file.read_text(encoding='ascii'))
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
