"""Random training teams from the pinned Showdown's Champions random doubles generator, accepted by the engine.

    python tools/reference/random_teams.py --checkout PINNED --seed HEX16 --count N --out DIR [--node node]
                                          [--max-candidates M]

The generator (tools/reference/ps_random_teams.js) gives team i of a seed deterministically. Each candidate becomes a
registry paste with two stated, generator-wide translations, never per team:
- the level is 50: battles are at level 50 (the generator levels each species for balance, 50 to about 60);
- the nature is Serious: the generator gives none, and Showdown battles such a set with a neutral nature.
The stat points (11 per stat, at most 66), species, item, ability and moves are the generator's. Candidates with a
shiny line or IVs other than 31 are refused (the registry format has neither). The engine then decides each paste as
import_vgcpastes does (the POOL data kind, the team against itself): only what it accepts is written. A candidate it
refuses (Item Clause, an illegal member, a mechanic not supported yet) is counted with its reason and skipped; nothing
is changed to make it pass, so the kept teams are a filtered sample of the generator, not a repaired one.

The output directory (outside the repository) gets RT_<seed>_<index>.txt per kept team, an index.json in the
registry's form (id, sha256) for duoforge.teams.load, teams.txt (one id per line) and manifest.json (pin commit, seed,
counts by verdict, the most frequent refusal reasons).
"""
import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'python'))

_STAT_NAMES = (('hp', 'HP'), ('atk', 'Atk'), ('def', 'Def'), ('spa', 'SpA'), ('spd', 'SpD'), ('spe', 'Spe'))
LEVEL = 50
NATURE = 'Serious'
BATCH = 500


class RandomTeamError(Exception):
    pass


def to_paste(team):
    """The registry paste of a generator team (the list of sets of ps_random_teams.js). Raises RandomTeamError for a
    set the registry format cannot carry (shiny, an IV other than 31)."""
    blocks = []
    for k, s in enumerate(team):
        if s['shiny']:
            raise RandomTeamError('set %d: shiny' % (k + 1))
        if any(v != 31 for v in s['ivs'].values()):
            raise RandomTeamError('set %d: IVs other than 31' % (k + 1))
        head = s['species'] + (' (%s)' % s['gender'] if s['gender'] in ('M', 'F') else '')
        if s['item']:
            head += ' @ ' + s['item']
        lines = [head, 'Ability: ' + s['ability'], 'Level: %d' % LEVEL]
        evs = ' / '.join('%d %s' % (s['evs'][key], label) for key, label in _STAT_NAMES if s['evs'][key])
        if evs:
            lines.append('EVs: ' + evs)
        lines.append('%s Nature' % (s['nature'] or NATURE))
        lines += ['- ' + m for m in s['moves']]
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks) + '\n'


def team_id(seed, index):
    return 'RT_%s_%06d' % (seed.upper(), index)


def refuse_repository(path):
    real = os.path.realpath(path)
    root = os.path.realpath(ROOT)
    if real == root or real.startswith(root + os.sep):
        raise RandomTeamError('%s is inside the repository: generated teams stay outside it' % path)


def generate(node, checkout, seed, first, count):
    out = subprocess.run([node, os.path.join(HERE, 'ps_random_teams.js'), checkout, seed, str(first), str(count)],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RandomTeamError('ps_random_teams.js failed: %s' % out.stderr.strip())
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]


def pin_commit(checkout):
    out = subprocess.run(['git', '-C', checkout, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def member_ok(context, s):
    """A pre-filter for one generator set, so that composed teams rarely fail (diagnostics only: the engine decides
    each composed team): every name is in the POOL tables and supported (a Mega stone with a supported Mega), the
    species can be a member, it may have the ability and learn the moves. Returns None or the reason."""
    from duoforge import data, teams
    try:
        [m] = teams.parse(to_paste([s]), 'set')
        teams.side_setup(context, [m], 'set')
    except RandomTeamError as e:
        return 'format: ' + str(e).split(': ', 1)[1]
    except teams.TeamError as e:
        return 'name: ' + str(e).split(': ', 2)[-1]
    species = data.find(context, data.TABLE_SPECIES, data.to_id(m['species']))
    for table, label, name in [(data.TABLE_ITEM, 'item', m['item']), (data.TABLE_ABILITY, 'ability', m['ability'])] + \
            [(data.TABLE_MOVE, 'move', mv) for mv in m['moves']]:
        if name is not None and not data.supported(context, table, data.find(context, table, data.to_id(name))):
            return 'pending: %s %s' % (label, name)
    if m['item'] is not None:
        item = data.find(context, data.TABLE_ITEM, data.to_id(m['item']))
        for i in range(data.mega_count(context, species)):
            mega = data.mega_at(context, species, i)
            if mega['stone'] == item and not mega['supported']:
                return 'pending: Mega Evolution of %s' % m['species']
    info = data.forme_info(context, species)
    if not info['setup_legal']:
        return 'illegal: %s cannot be a member' % m['species']
    if data.find(context, data.TABLE_ABILITY, data.to_id(m['ability'])) not in info['abilities'][:info['ability_count']]:
        return 'illegal: %s cannot have %s' % (m['species'], m['ability'])
    learnable = set(data.forme_moves(context, species))
    for mv in m['moves']:
        if data.find(context, data.TABLE_MOVE, data.to_id(mv)) not in learnable:
            return 'illegal: %s cannot learn %s' % (m['species'], mv)
    return None


def compose(sets, rng, dex_of, size=6):
    """Teams of `size` sets in the order of a seeded shuffle: each set is used once, a team takes the next set whose
    species (dex number) and item are not in it yet (Species and Item Clause). Sets left over at the end are unused."""
    pool = list(sets)
    rng.shuffle(pool)
    teams = []
    while pool:
        team, rest = [], []
        for s in pool:
            if len(team) < size and dex_of(s['species']) not in {dex_of(t['species']) for t in team} and \
                    (not s['item'] or s['item'] not in {t['item'] for t in team}):
                team.append(s)
            else:
                rest.append(s)
        if len(team) < size:
            break
        teams.append(team)
        pool = rest
    return teams


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--checkout', required=True, help='the pinned Showdown checkout (built: dist/sim exists)')
    p.add_argument('--node', default='node')
    p.add_argument('--seed', required=True, help='16 hex digits')
    p.add_argument('--count', type=int, required=True, help='teams to keep')
    p.add_argument('--generator-teams', type=int, default=None,
                   help='generator teams to draw sets from (default 3 x count)')
    p.add_argument('--out', required=True, help='the output directory (outside the repository, must not exist)')
    args = p.parse_args(argv)
    seed = args.seed.lower()
    if len(seed) != 16 or any(c not in '0123456789abcdef' for c in seed):
        p.error('--seed must be 16 hex digits')
    refuse_repository(args.out)
    if os.path.exists(args.out):
        p.error('--out %s exists: a run writes a new directory' % args.out)
    if not os.path.isdir(os.path.join(args.checkout, 'dist', 'sim')):
        p.error('--checkout %s has no dist/sim (npm ci --ignore-scripts --omit=dev; node build)' % args.checkout)

    import random
    import duoforge
    from duoforge import _layout, data
    import import_vgcpastes
    n_gen = args.generator_teams or 3 * args.count
    set_verdicts, team_verdicts, reasons, kept = collections.Counter(), collections.Counter(), collections.Counter(), []
    with duoforge.Context(data_kind=_layout.CONSTANTS['DUOFORGE_DATA_KIND_POOL']) as context:
        check = import_vgcpastes.engine_check(context)
        sets, seen = [], set()
        for first in range(0, n_gen, BATCH):
            for cand in generate(args.node, args.checkout, seed, first, min(BATCH, n_gen - first)):
                for s in cand['team']:
                    key = json.dumps(s, sort_keys=True)
                    if key in seen:
                        set_verdicts['duplicate'] += 1
                        continue
                    seen.add(key)
                    why = member_ok(context, s)
                    if why is None:
                        set_verdicts['ok'] += 1
                        sets.append(s)
                    else:
                        set_verdicts[why.split(':', 1)[0]] += 1
                        reasons['set ' + why] += 1

        def dex_of(species):
            return data.forme_info(context, data.find(context, data.TABLE_SPECIES, data.to_id(species)))['dex_num']

        rng = random.Random(int(seed, 16))
        for k, team in enumerate(compose(sets, rng, dex_of)):
            if len(kept) == args.count:
                break
            text = to_paste(team)
            status, info = check(text)
            team_verdicts[status] += 1
            if status == 'pool':
                kept.append((team_id(seed, k), text))
            else:
                reasons['team %s: %s' % (status, info if isinstance(info, str) else '; '.join(info))] += 1
    os.makedirs(args.out)
    entries = []
    for tid, text in kept:
        raw = text.encode('utf-8')
        with open(os.path.join(args.out, tid + '.txt'), 'wb') as f:
            f.write(raw)
        entries.append({'id': tid, 'sha256': duoforge.teams.text_sha256(raw)})
    with open(os.path.join(args.out, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump({'teams': entries}, f, indent=1)
    with open(os.path.join(args.out, 'teams.txt'), 'w', encoding='utf-8') as f:
        f.write(''.join(t + '\n' for t, _ in kept))
    manifest = {'generator': 'gen9championsrandomdoublesbattle', 'pin': pin_commit(args.checkout), 'seed': seed,
                'level': LEVEL, 'nature_when_missing': NATURE, 'generator_teams': n_gen, 'sets': dict(set_verdicts),
                'teams': dict(team_verdicts), 'kept': len(kept), 'reasons': dict(reasons.most_common(40)),
                'teams_sha256': hashlib.sha256(''.join(e['sha256'] for e in entries).encode()).hexdigest()}
    with open(os.path.join(args.out, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1)
    print(json.dumps({k: manifest[k] for k in ('generator_teams', 'sets', 'teams', 'kept')}))
    if len(kept) < args.count:
        print('only %d of %d teams from %d generator teams' % (len(kept), args.count, n_gen), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
