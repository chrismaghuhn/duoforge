"""A private team corpus from the open team sheets of the replays (owner, 2026-10-11), accepted by the engine.

    python tools/reference/replay_teams.py --source PATH... --format-prefix PREFIX --prior PRIOR.json --out DIR
                                           [--ps-dir PINNED]

The sources are the replay files of duoforge_replay (parquet or JSON lines); a game counts when its format id starts
with PREFIX (one regulation per corpus: gen9championsvgc2026regmc, gen9championsvgc2026regmb; Reg M-A is refused,
another mechanics era). Each |showteam| sheet of such a game is one team. Teams are deduplicated by a canonical form:
the members sorted, each member's moves sorted, names as ids, the nickname dropped (what an open sheet shows, as
duoforge_live.teams compares sheets). The number of sheets of each team is its frequency; its paste is written from the
canonical form alone, so one team has one paste and one id whatever sheet or source order it came from. A sheet with
a field a paste cannot carry (IVs, shiny, the misc field) is refused, not stripped.

An open sheet shows no stat points. The paste of a team gets each member's stat points from the M11 prior (the
VGCPastes spreads, duoforge_replay.prior), and the manifest names that source, the prior's sha256 and how many members
the prior knows no spread for (stat points 0): a stated source, not the players' spreads.

The engine then decides every distinct team as import_vgcpastes does (the POOL data kind, the team against itself):
only what it accepts is written, a refusal is counted with its reason (a pending team once per feature that blocks it,
whatever its member). Nothing is changed to make a team pass.

The output directory (outside the repository; it must not exist) is the corpus format of tools/reference/
random_teams.py that duoforge.teams.load_corpus reads: RP_<sha256 of the paste, 16 digits>.txt per kept team,
index.json (id, sha256), teams.txt and manifest.json (pin, seed null, the sources with their sha256, the filter, the
counts, the refusal reasons, frequency per kept team, teams_sha256). The replays have no licence: the corpus is
derived data, never committed, never a CI artifact, never published.
"""
import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'python'))
sys.path.insert(0, HERE)


def team_id(text):
    """The id of a kept team: the first 16 hex digits of its paste's sha256, so an id always names the same team."""
    return 'RP_' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:16].upper()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def pin_commit(checkout):
    if not checkout:
        return None
    out = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                         check=False)
    return out.stdout.strip() if out.returncode == 0 else None


def _dirty():
    out = subprocess.run(['git', '-C', ROOT, 'status', '--porcelain', '--untracked-files=no'], capture_output=True,
                         text=True, check=False)
    return bool(out.stdout.strip())


def sheets_of(log):
    """The packed sheets of a game's |showteam| lines (none for a game without sheets)."""
    return [line.rstrip('\r').split('|', 3)[3] for line in log.split('\n') if line.startswith('|showteam|')]


# The packed fields an open sheet may fill that a registry paste cannot carry (IVs, shiny, the misc field: happiness,
# Poke Ball, Hidden Power type, Gigantamax, Dynamax level, Tera type); duoforge_live.teams.unpack drops them.
_UNCARRIED = {8: 'IVs', 9: 'shiny', 11: 'misc'}


def uncarried(packed):
    """The fields of a packed sheet a registry paste cannot carry, by name (none: [])."""
    out = set()
    for chunk in packed.split(']'):
        f = chunk.split('|')
        if len(f) == 12:
            out |= {name for k, name in _UNCARRIED.items() if f[k]}
    return sorted(out)


def canonical(sets, live):
    """A sheet's canonical form: per member (species, item, ability, nature, gender, level, sorted moves), names as
    ids and the species canonical, the members sorted. ValueError for a species the POOL tables do not have."""
    from duoforge import data
    return tuple(sorted((data.to_id(live.canonical(s['species'])), data.to_id(s['item']), data.to_id(s['ability']),
                         data.to_id(s['nature']), s['gender'], s['level'],
                         tuple(sorted(data.to_id(m) for m in s['moves']))) for s in sets))


def to_paste(key, live, prior):
    """The registry paste of a canonical team, written from the key alone (names as ids, the nature capitalised as the
    paste's Nature line needs), so one team has one paste and one id whatever sheet it came from; the stat points from
    the prior. (paste, members the prior knows no spread for)."""
    from duoforge_live import teams as live_teams
    from duoforge_replay.prior import LEVELS
    out, unknown = [], 0
    for species, item, ability, nature, gender, level, moves in key:
        s = {'species': live.canonical(species), 'item': item, 'ability': ability, 'nature': nature.capitalize(),
             'gender': gender, 'level': level, 'moves': list(moves)}
        points, prior_level = prior.lookup(s)
        unknown += prior_level == LEVELS
        out.append(dict(s, evs=list(points)))
    return live_teams.to_text(out), unknown


def build(paths, format_prefix, prior_path, out, ps_dir=None):
    """Writes the corpus of the sources' games under format_prefix to out (module docstring); returns the manifest."""
    import duoforge
    from duoforge import _layout
    from duoforge_live import data as live_data
    from duoforge_live import teams as live_teams
    from duoforge_replay import dataset, source
    from duoforge_replay.funnel import REG_MA
    from duoforge_replay.prior import Prior
    import import_vgcpastes

    out = Path(out)
    if REG_MA.startswith(format_prefix) or format_prefix.startswith(REG_MA):
        raise ValueError(f'Reg M-A is excluded (another mechanics era, owner 2026-10-10): {format_prefix!r}')
    dataset.refuse_repository(out)
    if out.exists():
        raise ValueError(f'{out} exists: a run writes a new directory')
    live = live_data.load(kind='pool')
    prior = Prior.load(prior_path)
    counts, frequency = collections.Counter(), collections.Counter()
    verdicts, reasons = collections.Counter(), collections.Counter()
    read = collections.Counter()
    for unit in source.units(paths):
        for _, format_id, log in source.read_unit(unit, (format_prefix,), read):
            if not format_id.startswith(format_prefix):
                continue
            counts['games'] += 1
            packed = sheets_of(log)
            if not packed:
                counts['games_without_sheets'] += 1
                continue
            for sheet in packed:
                counts['sheets'] += 1
                fields = uncarried(sheet)
                if fields:
                    counts['sheets_refused'] += 1
                    reasons['sheet: a field the paste cannot carry: ' + ', '.join(fields)] += 1
                    continue
                try:
                    key = canonical(live_teams.unpack(sheet), live)
                except ValueError as e:
                    counts['sheets_refused'] += 1
                    reasons['sheet: ' + str(e).split(':')[0][:80]] += 1
                    continue
                frequency[key] += 1
    counts['distinct'] = len(frequency)
    counts['sheets_refused'] += 0
    # the gender a sheet shows may be the battle's roll (a paste without one gets a random gender): the teams apart
    # from it, so the owner can see how much gender splits them
    counts['distinct_without_gender'] = len({tuple(m[:4] + m[5:] for m in key) for key in frequency})
    kept, unknown_members = [], 0
    with duoforge.Context(data_kind=_layout.CONSTANTS['DUOFORGE_DATA_KIND_POOL']) as context:
        check = import_vgcpastes.engine_check(context)
        for key in sorted(frequency):
            text, unknown = to_paste(key, live, prior)
            status, info = check(text)
            verdicts[status] += 1
            if status == 'pool':
                kept.append((team_id(text), text, frequency[key]))
                unknown_members += unknown
            elif status == 'pending':  # each blocker once per team, without its set's number: one count per feature
                for blocker in sorted({b.split(': ', 1)[1] for b in info}):
                    reasons['pending: ' + blocker] += 1
            else:
                reasons['%s: %s' % (status, info)] += 1
    kept.sort()
    counts['kept'] = len(kept)
    out.mkdir(parents=True)
    entries = []
    for tid, text, _ in kept:
        raw = text.encode('utf-8')
        (out / f'{tid}.txt').write_bytes(raw)
        entries.append({'id': tid, 'sha256': duoforge.teams.text_sha256(raw)})
    (out / 'index.json').write_text(json.dumps({'teams': entries}, indent=1) + '\n', encoding='utf-8')
    (out / 'teams.txt').write_text(''.join(t + '\n' for t, _, _ in kept), encoding='utf-8')
    manifest = {
        'source': 'replay open sheets', 'pin': pin_commit(ps_dir), 'seed': None, 'format_prefix': format_prefix,
        'code': {'commit': pin_commit(ROOT), 'dirty': _dirty()},
        'sources': [{'file': Path(p).name, 'bytes': Path(p).stat().st_size, 'sha256': _sha256_file(p)}
                    for p in source.files(paths)],
        'stat_points': {'source': 'prior', 'prior_sha256': _sha256_file(prior_path),
                        'members_without_prior': unknown_members},
        'counts': dict(sorted(counts.items())), 'verdicts': dict(sorted(verdicts.items())),
        'reasons': dict(sorted(reasons.most_common(40))),
        'frequency': {tid: n for tid, _, n in kept},
        'python': '%d.%d.%d' % sys.version_info[:3],
        'teams_sha256': hashlib.sha256(''.join(e['sha256'] for e in entries).encode()).hexdigest(),
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    return manifest


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--source', required=True, nargs='+', help='replay files (parquet or JSON lines) or directories')
    p.add_argument('--format-prefix', required=True, help='one regulation, e.g. gen9championsvgc2026regmc')
    p.add_argument('--prior', required=True, help='the M11 prior (the stat points of the pastes)')
    p.add_argument('--out', required=True, help='the output directory (outside the repository, must not exist)')
    p.add_argument('--ps-dir', default=os.environ.get('DUOFORGE_PS_REFERENCE_DIR'), help='the pinned Showdown')
    args = p.parse_args(argv)
    try:
        manifest = build(args.source, args.format_prefix, args.prior, args.out, args.ps_dir)
    except ValueError as e:
        p.error(str(e))
    print(json.dumps({k: manifest[k] for k in ('counts', 'verdicts', 'stat_points')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
