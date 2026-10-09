"""The bulk import of the VGCPastes Repository sheet (Champions Reg M-A, M-B, M-C) into the team registry.

    python tools/reference/import_vgcpastes.py --sheet-dir DIR --pastes DIR --checkout PINNED [--report FILE] [--write]

The sheet is the owner's HTML export of the repository (one file per tab, "Champions M-C.html" and so on, kept outside
the repository with the fetched pastes). Every row whose "EVs" column says Yes and whose paste is cached
(--pastes/<pokepast.es id>.txt) is made a registry team with import_paste.normalize (the same normalisation as
import_paste.py, every change reported) and is then decided by the engine: the setup of the POOL data kind, the team
against itself (duoforge.teams.check). What it accepts goes into the registry as PP_<upper case paste id>; what is legal
but needs a mechanic the library does not support yet is pending, with its blockers; anything else is left out with its
status. Nothing decides a rule here.

A team the registry or an earlier row already has (the same species, items, abilities, natures and moves; EVs and genders
aside) is a duplicate: the first one is kept, in the order Reg M-C, M-B, M-B featured, M-A, M-A featured, and within a tab
the sheet's. A paste whose id the registry has is skipped. Without --write nothing is written; --report writes every
decision (outside the repository).
"""
import argparse
import html.parser
import json
import os
import re
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'python'))

import import_paste  # noqa: E402
import team_registry  # noqa: E402

TABS = ('Champions M-C', 'Champions M-B', 'Champions M-B Featured Teams', 'Champions M-A',
        'Champions M-A Featured Teams')
_TEAM_ID = re.compile(r'[A-Z]{1,3}\d+$')
_PASTE = re.compile(r'pokepast\.es/([0-9a-f]{16})')


class _Table(html.parser.HTMLParser):
    """The rows of an exported sheet: each cell as (text, links)."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.links = [], None, None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell, self.links = [], []
        elif tag == 'a' and self.cell is not None and dict(attrs).get('href'):
            self.links.append(dict(attrs)['href'])

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.row is not None and self.cell is not None:
            self.row.append((''.join(self.cell).strip(), list(self.links)))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def sheet_rows(text, tab):
    """The team rows of one exported tab: team_id, description, creator, paste_id (lower case, or None), evs, event,
    rank, date, tab."""
    table = _Table()
    table.feed(text)
    header = next((r for r in table.rows if any(t == 'Team ID' for t, _ in r)), None)
    if header is None:
        raise ValueError('%s: no header row with "Team ID"' % tab)
    col = {t: i for i, (t, _) in enumerate(header) if t}

    def cell(row, name):
        i = col.get(name)
        return row[i] if i is not None and i < len(row) else ('', [])

    out = []
    for row in table.rows[table.rows.index(header) + 1:]:
        team_id = cell(row, 'Team ID')[0]
        if not _TEAM_ID.match(team_id):
            continue
        text, links = cell(row, 'Pokepaste')
        m = next((m for m in (_PASTE.search(s) for s in links + [text]) if m), None)
        out.append({'team_id': team_id, 'description': cell(row, 'Team Description')[0],
                    'creator': cell(row, 'Full Name')[0], 'paste_id': m.group(1) if m else None,
                    'evs': cell(row, 'EVs')[0], 'event': cell(row, 'Tournament / Event')[0],
                    'rank': cell(row, 'Rank')[0], 'date': cell(row, 'Date Shared')[0], 'tab': tab})
    return out


def normalized(text, info_of):
    """(sets, change notes) of a paste in the registry's form (import_paste.normalize)."""
    return import_paste.normalize(text, info_of)


def content_key(sets):
    """What makes two teams the same here: per set the species, item, ability, nature and moves (EVs, gender and the
    order of moves and sets aside)."""
    out = []
    for block in sets:
        lines = block.split('\n')
        head = re.sub(r' \([MF]\)', '', lines[0])
        species, _, item = head.partition(' @ ')
        ability = next((l[len('Ability: '):] for l in lines if l.startswith('Ability: ')), '')
        nature = next((l[:-len(' Nature')] for l in lines if l.endswith(' Nature')), '')
        moves = tuple(sorted(l[2:] for l in lines if l.startswith('- ')))
        out.append((species.strip(), item.strip(), ability, nature, moves))
    return tuple(sorted(out))


def _has_all_evs(sets):
    return all(any(line.startswith('EVs: ') for line in block.split('\n')) for block in sets)


def decide(rows, pastes, known, info_of, check, registry_ids=()):
    """The decision for every row with EVs = Yes and a paste link, in the import order: a dict with row, status (pool,
    pending, illegal, name, evs-missing, paste-error, duplicate, in-registry, not-fetched), id, sets, notes, blockers,
    detail and duplicate_of. `known` maps content_key -> id of the registry's teams; `check(text)` is the engine's
    verdict on a registry paste: (status, blockers or detail)."""
    order = {t: n for n, t in enumerate(TABS)}
    wanted = [r for r in rows if r['evs'] == 'Yes' and r['paste_id']]
    wanted = sorted(enumerate(wanted), key=lambda x: (order.get(x[1]['tab'], len(TABS)), x[0]))
    keys, ids, out = dict(known), {}, []
    for _, row in wanted:
        pid = row['paste_id']
        d = {'row': row, 'id': 'PP_' + pid.upper(), 'status': None, 'sets': None, 'notes': [], 'blockers': None,
             'detail': None, 'duplicate_of': None}
        out.append(d)
        if d['id'] in registry_ids:
            d['status'] = 'in-registry'
            continue
        if pid in ids:
            d['status'], d['duplicate_of'] = 'duplicate', ids[pid]
            continue
        ids[pid] = d['id']
        text = pastes.get(pid)
        if text is None:
            d['status'] = 'not-fetched'
            continue
        try:
            d['sets'], d['notes'] = normalized(text, info_of)
        except import_paste.PasteError as e:
            d['status'], d['detail'] = 'paste-error', '; '.join(e.problems if hasattr(e, 'problems') else e.args)
            continue
        if not _has_all_evs(d['sets']):
            d['status'] = 'evs-missing'
            continue
        key = content_key(d['sets'])
        if key in keys:
            d['status'], d['duplicate_of'] = 'duplicate', keys[key]
            continue
        verdict, info = check(team_registry.file_text(d['sets']).decode('utf-8'))
        d['status'] = verdict
        if verdict == 'pending':
            d['blockers'] = info
        elif verdict != 'pool':
            d['detail'] = info
        if verdict in ('pool', 'pending'):
            keys[key] = d['id']
    return out


def entry_for(d, today):
    """The registry entry of a pool decision, crediting the repository and the paste's author."""
    r = d['row']
    changes = d['notes']
    said = ('%d changes by import_paste.py: %s.' % (len(changes), '; '.join(changes)) if changes
            else 'No change by import_paste.py.')
    event = r['event'] if r['event'] not in ('', '-') else None
    placing = r['rank'] if r['rank'] not in ('', '-') else None
    notes = ('A team of the VGCPastes Repository (@VGCPastes), tab %s, row %s, by %s, shared %s%s. The paste is read '
             'from pokepast.es (one request a second) and imported on %s from the owner\'s export of the sheet; the '
             'engine\'s setup under the POOL data kind accepts it. %s'
             % (r['tab'], r['team_id'], r['creator'] or 'an unnamed author', r['date'] or 'on an unknown date',
                (', %s%s' % (event, ', %s' % placing if placing else '')) if event else '', today, said))
    name = '%s (%s)' % (r['description'] or 'VGCPastes team', r['team_id'])
    return team_registry.new_entry(d['id'], name, d['sets'], 'https://pokepast.es/' + r['paste_id'], event, placing,
                                   notes)


def pending_list(decisions, today):
    """The teams that are legal but need a mechanic the library does not support yet, with their blockers (no paste
    text: the paste is at its URL), and how often each blocker keeps a team out."""
    teams, counts = [], {}
    for d in decisions:
        if d['status'] != 'pending':
            continue
        r = d['row']
        teams.append({'id': d['id'], 'url': 'https://pokepast.es/' + r['paste_id'], 'tab': r['tab'],
                      'team_id': r['team_id'], 'creator': r['creator'], 'blockers': d['blockers']})
        for b in {re.sub(r'^set \d+: ', '', b) for b in d['blockers']}:
            counts[b] = counts.get(b, 0) + 1
    return {'source': 'VGCPastes Repository (@VGCPastes), Champions Reg M-A, M-B and M-C (tools/reference/'
                      'import_vgcpastes.py)', 'date': today, 'teams': teams,
            'blocker_counts': dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))}


def write(root, decisions, today):
    """Adds every pool decision to the registry at `root`; returns the ids written."""
    written = []
    for d in decisions:
        if d['status'] == 'pool':
            team_registry.add_team(root, entry_for(d, today), d['sets'])
            written.append(d['id'])
    return written


def engine_check(context):
    """check(text) for decide: the setup of the team against itself under the context (duoforge.teams.check)."""
    from duoforge import _layout, data, teams
    from duoforge._lib import status_name
    header = open(os.path.join(ROOT, 'include', 'duoforge', 'duoforge.h'), encoding='ascii').read()
    limits = {m.group(1): int(m.group(2)) for m in re.finditer(r'#define (DUOFORGE_STAT_POINTS_\w+) +(\d+)u', header)}
    unsupported = _layout.CONSTANTS['DUOFORGE_E_UNSUPPORTED']

    def blockers(members):
        out = []
        for k, m in enumerate(members):
            for table, name in [(data.TABLE_ITEM, m['item']), (data.TABLE_ABILITY, m['ability'])] + \
                    [(data.TABLE_MOVE, mv) for mv in m['moves']]:
                if name is None:
                    continue
                ident = data.find(context, table, data.to_id(name))
                if not data.supported(context, table, ident):
                    out.append('set %d: %s %s' % (k + 1, {data.TABLE_ITEM: 'item', data.TABLE_ABILITY: 'ability',
                                                          data.TABLE_MOVE: 'move'}[table], name))
            species = data.find(context, data.TABLE_SPECIES, data.to_id(m['species']))
            info = data.forme_info(context, species)
            if m['item'] is not None and info['mega_stone'] != data.NONE and \
                    data.find(context, data.TABLE_ITEM, data.to_id(m['item'])) == info['mega_stone'] and \
                    not info['mega_supported']:
                out.append('set %d: Mega Evolution of %s' % (k + 1, m['species']))
        return out

    def check(text):
        try:
            members = teams.parse(text, 'vgcpastes')
            side = teams.side_setup(context, members, 'vgcpastes')
        except teams.TeamError as e:
            return ('name', str(e))
        status = teams.check(context, side)
        if status == 0:
            return ('pool', None)
        if status == unsupported:
            return ('pending', blockers(members))
        return ('illegal', '%s: %s' % (status_name(status), '; '.join(why_illegal(members)) or 'no member rule'))

    def why_illegal(members):
        """The data API's legality rules a refused team breaks, set by set (what the setup validated)."""
        out, dex = [], set()
        for k, m in enumerate(members):
            f = data.find(context, data.TABLE_SPECIES, data.to_id(m['species']))
            info = data.forme_info(context, f)
            if not info['setup_legal']:
                out.append('set %d: %s cannot be a member' % (k + 1, m['species']))
                continue
            if info['dex_num'] in dex:
                out.append('set %d: a second %s (Species Clause)' % (k + 1, m['species']))
            dex.add(info['dex_num'])
            a = data.find(context, data.TABLE_ABILITY, data.to_id(m['ability']))
            if a not in info['abilities'][:info['ability_count']]:
                out.append('set %d: %s cannot have %s' % (k + 1, m['species'], m['ability']))
            learnable = set(data.forme_moves(context, f))
            out += ['set %d: %s cannot learn %s' % (k + 1, m['species'], mv) for mv in m['moves']
                    if data.find(context, data.TABLE_MOVE, data.to_id(mv)) not in learnable]
            if sum(m['stat_points']) > limits['DUOFORGE_STAT_POINTS_TOTAL_MAX'] or \
                    max(m['stat_points']) > limits['DUOFORGE_STAT_POINTS_MAX']:
                out.append('set %d: stat points %s over the limits' % (k + 1, m['stat_points']))
        items = [m['item'] for m in members if m['item'] is not None]
        out += ['a second %s (Item Clause)' % i for i in sorted({i for i in items if items.count(i) > 1})]
        return out
    return check


def main(argv=None):
    p = argparse.ArgumentParser(prog='import_vgcpastes.py', description=__doc__.split('\n')[0])
    p.add_argument('--sheet-dir', required=True, help='the HTML export of the sheet, one file per tab')
    p.add_argument('--pastes', required=True, help='the fetched pastes, <pokepast.es id>.txt')
    p.add_argument('--checkout', required=True, help='the pinned Showdown checkout (ps_species.js)')
    p.add_argument('--node', default='node')
    p.add_argument('--report', default=None, help='a JSON file of every decision (outside the repository)')
    p.add_argument('--write', action='store_true', help='add the pool teams to the registry')
    p.add_argument('--pending', default=None, help='write the pending list (ids, URLs, blockers; no paste text) here')
    p.add_argument('--today', default=None, help='the import date of the notes (default: today)')
    p.add_argument('--root', default=ROOT, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    import datetime
    import duoforge
    from duoforge import _layout
    from duoforge_replay.dataset import refuse_repository
    if args.report:
        refuse_repository(args.report)
    today = args.today or datetime.date.today().isoformat()
    rows = []
    for tab in TABS:
        path = os.path.join(args.sheet_dir, tab + '.html')
        if os.path.exists(path):
            rows += sheet_rows(open(path, encoding='utf-8', errors='replace').read(), tab)
    pastes = {}
    for r in rows:
        pid = r['paste_id']
        path = os.path.join(args.pastes, '%s.txt' % pid) if pid else None
        if path and pid not in pastes and os.path.exists(path):
            pastes[pid] = open(path, encoding='utf-8').read()
    entries = team_registry.entries(args.root)
    known = {}
    for e in entries:
        sets, _ = team_registry.read_team(args.root, e['id'])
        known.setdefault(content_key(sets), e['id'])
    species = import_paste.SpeciesInfo(args.checkout, args.node)
    species.prefetch(n for text in pastes.values() for n in import_paste.species_of_paste(text))
    with duoforge.Context(data_kind=_layout.CONSTANTS['DUOFORGE_DATA_KIND_POOL']) as context:
        decisions = decide(rows, pastes, known, species.get, engine_check(context), {e['id'] for e in entries})
    counts = {}
    for d in decisions:
        counts[d['status']] = counts.get(d['status'], 0) + 1
    print(json.dumps(counts, sort_keys=True))
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as f:
            json.dump([{k: v for k, v in d.items() if k != 'sets'} for d in decisions], f, indent=1)
    if args.pending:
        with open(args.pending, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(pending_list(decisions, today), indent=1, ensure_ascii=False) + '\n')
    if args.write:
        written = write(args.root, decisions, today)
        print('import_vgcpastes: %d teams written' % len(written))
    return 0


if __name__ == '__main__':
    sys.exit(main())
