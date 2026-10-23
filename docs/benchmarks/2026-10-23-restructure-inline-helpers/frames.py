"""Stack frames (-fstack-usage) and code sizes of one commit, IPO on and off (restructure: helper inlining).

Usage: PHASE=before|after OUT=<dir outside the repo> REPO=<worktree> python3 frames.py
Configures build/su-ipo and build/su-noipo (Release, -fstack-usage, same paths in both phases), builds the shared library
and the bench, and records every function's frame (IPO off: the .su files of the compile; IPO on: the *.ltrans*.su of the
LTO links, which -fstack-usage writes next to the outputs) and the .text sizes of libduoforge_shared.so and duoforge_bench.
"""
from pathlib import Path
import json, os, re, subprocess

root = Path(os.environ['REPO'])
out = Path(os.environ['OUT']) / os.environ['PHASE']
out.mkdir(parents=True, exist_ok=True)
jobs = os.environ.get('DUOFORGE_JOBS', '4')
result = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()}
for mode, ipo in (('ipo', 'ON'), ('noipo', 'OFF')):
    build = root / 'build' / f'su-{mode}'
    subprocess.run(['cmake', '-S', str(root), '-B', str(build), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                    f'-DDUOFORGE_ENABLE_IPO={ipo}', '-DBUILD_TESTING=OFF', '-DCMAKE_C_FLAGS=-fstack-usage'],
                   check=True, stdout=subprocess.DEVNULL)
    for su in build.rglob('*.su'):
        su.unlink()  # every frame below comes from this build
    subprocess.run(['cmake', '--build', str(build), '--parallel', jobs, '--target', 'duoforge_shared', 'duoforge_bench'],
                   check=True, stdout=subprocess.DEVNULL)
    frames = {}
    for su in sorted(build.rglob('*.su')):
        target = 'bench' if 'bench' in str(su.relative_to(build)) else 'library'
        for line in su.read_text().splitlines():
            loc, size, kind = line.rsplit('\t', 2)
            name = loc.rsplit(':', 1)[-1]
            key = f'{target}:{name}'
            frames[key] = max(frames.get(key, 0), int(size))
    sizes = {}
    for name, path in (('library', build / 'libduoforge_shared.so'), ('bench', build / 'bench' / 'duoforge_bench')):
        text = subprocess.check_output(['size', '-A', str(path)], text=True)
        sizes[name] = int(re.search(r'^\.text\s+(\d+)', text, re.M).group(1))
    result[mode] = {'frames': frames, 'text': sizes}
(out / 'frames.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
print(os.environ['PHASE'], {m: result[m]['text'] for m in ('ipo', 'noipo')}, {m: len(result[m]['frames']) for m in ('ipo', 'noipo')})
