"""Build a K5 spec: python mk.py <name> -> reads battles.py (dict BATTLES), writes the spec, records the trace, prints the log."""
import json, subprocess, sys, os
sys.path.insert(0, os.path.dirname(__file__))
ROOT = os.environ['DUOFORGE_ROOT']
NODE = os.environ['DUOFORGE_NODE']
PS = os.environ['DUOFORGE_PS_REFERENCE_DIR']

def mon(name, item, ability, evs, nature, moves, gender=None):
    head = name + (' (%s)' % gender if gender else '') + (' @ ' + item if item else '')
    return '%s\nAbility: %s\nLevel: 50\nEVs: %s\n%s Nature\n%s' % (head, ability, evs, nature, '\n'.join('- ' + m for m in moves))

def team(*mons):
    return '\n\n'.join(mons)

def write_spec(name, purpose, teams, p1, p2, seed):
    spec = {'name': name, 'purpose': purpose, 'data': 'pool', 'format': 'gen9championsvgc2026regmc',
            'seed': 'sodium,%064x' % seed, 'teams': teams, 'plan': {'p1': p1, 'p2': p2, 'max_steps': max(len(p1), len(p2)) + 1}}
    path = '%s/tests/reference/specs/%s.json' % (ROOT, name)
    open(path, 'w', encoding='utf-8', newline='\n').write(json.dumps(spec, indent=2) + '\n')
    return path

def record(name):
    spec = '%s/tests/reference/specs/%s.json' % (ROOT, name)
    out = subprocess.run([NODE, '%s/tools/reference/ps_trace.js' % ROOT, PS, spec], capture_output=True, cwd=ROOT)
    if out.returncode != 0:
        print(out.stderr[-3000:].decode('utf-8', 'replace')); sys.exit(1)
    open('%s/tests/reference/traces/%s.json' % (ROOT, name), 'wb').write(out.stdout)
    return json.loads(out.stdout.decode('utf-8'))

def show(trace, skip=('|t:|', '|upkeep', '|j|', '|player|', '|teamsize', '|gametype', '|gen|', '|tier|', '|rule|', '|clearpoke', '|poke|', '|start', '|-heal|', '|split|', '|raw')):
    for k, step in enumerate(trace['steps']):
        print('--- step', k)
        for l in step['log']:
            if any(l.startswith(s) for s in skip): continue
            print(l)

if __name__ == '__main__':
    import battles
    name = sys.argv[1]
    b = battles.BATTLES[name]
    write_spec(name, b['purpose'], b['teams'], b['p1'], b['p2'], b['seed'])
    v = subprocess.run([NODE, os.path.dirname(__file__) + '/validate.js', '%s/tests/reference/specs/%s.json' % (ROOT, name)], capture_output=True, text=True)
    print(v.stdout, v.stderr[-500:])
    if v.returncode != 0: sys.exit(1)
    show(record(name))
