#!/usr/bin/env python3
"""Imports a Showdown paste into the team registry (data/teams, tools/reference/team_registry.py).

usage: python tools/reference/import_paste.py --checkout <pinned checkout> --id ID --name NAME
           [--paste FILE | -] [--url URL] [--event EVENT] [--placing PLACING] [--notes TEXT] [--supersedes ID]
           [--dry-run] [--print] [--node <node>]

Reads the text of a paste (a file, or stdin) and writes data/teams/<ID>.txt in the registry's form, with an entry in
data/teams/index.json, or with --dry-run only says what it would do. It only normalises: the registry's form is the one
trace_to_c.parse_team reads and the learner's loader accepts, and the importer decides no rule of the game. Each thing it
changes it reports, one line, on stdout ("import_paste: ..."):

 - The gender of every Pokemon that has one is stated. One that the paste does not state is added by the owner's standard:
   the species' fixed gender (female only, male only) where it has one, male for a species that can be either (whatever
   its ratio), and none for a genderless one, which stays empty. The pinned pokedex (tools/reference/ps_species.js, of
   the format gen9championsvgc2026regmc) says which. A gender that the paste states is kept; one that the species cannot
   have is an error, not something to fix.
 - A species written as its Mega forme ("Charizard-Mega-Y", "Salamence-Mega") with its stone is the base forme with that
   stone ("Charizard", "Salamence"): the Mega forme is what the battle makes of it. A Mega forme without its stone is an
   error.
 - A nickname ("Sunny (Rillaboom) (M) @ Item") is dropped, and the species name is written as the pokedex spells it.
 - "Level: 50" is added where the paste has no level; another level is an error (the registry is Level 50).
 - The cosmetic lines "Shiny: Yes", "Happiness: N" and "Tera Type: X" are dropped. Every other line that is not an
   ability, level, EVs (the Stat Points), nature or move is an unknown line and an error, and so is a second ability,
   level, EVs or nature line: nothing is dropped silently.
 - The lines are put in the registry's order: the species line, Ability, Level, EVs, the nature, the moves. That, blank space
   and line ends are form, not content, and are not reported.

Only the species are checked against the pokedex. The names of items, abilities, moves and natures are written as they
are: a misspelled one is refused later, by trace_to_c.parse_team and by diff_random.py (which then names it, as one that
no data kind has), and the learner's loader may refuse it as well.

An unknown species, a set without an ability or a nature, a set without a move or with more than four, and a paste that is
not six sets are errors too: nothing is written, and the problems are all listed. An id that is in the registry is an
error (ids are never reused and a file never changes under its id: a correction is a new id, with --supersedes OLD,
which notes the replacement in the entry of OLD and changes nothing else of it).
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import team_registry  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SPECIES_SCRIPT = os.path.join(HERE, 'ps_species.js')
FORMAT = 'gen9championsvgc2026regmc'
COSMETIC = ('Shiny', 'Happiness', 'Tera Type')  # dropped, with a report
LEVEL = 'Level: 50'


class PasteError(Exception):
    """The paste cannot be made a registry team: `problems` lists everything that is wrong with it."""

    def __init__(self, problems):
        super().__init__('\n'.join(problems))
        self.problems = problems


def percent(x):
    return ('%g' % round(x * 100, 1)) + '%'


def parse_set(block, n):
    """The parts of one set of a paste, and what is wrong with it: ({field: value}, [problem]). The fields: written (the
    species as written), nickname, gender, item, ability, level, evs, nature, moves, cosmetic (the lines to drop)."""
    lines = [line.strip() for line in block.split('\n') if line.strip()]
    problems = []
    found = {'nickname': None, 'gender': None, 'item': None, 'ability': None, 'level': None, 'evs': None, 'nature': None,
             'moves': [], 'cosmetic': []}
    head = lines[0]
    who, sep, item = head.partition(' @ ')
    found['item'] = item.strip() if sep and item.strip() else None
    m = re.match(r'^(?P<rest>.+?) \((?P<gender>[MF])\)$', who.strip())
    if m:
        who, found['gender'] = m.group('rest'), m.group('gender')
    m = re.match(r'^(?P<nick>.+?) \((?P<species>[^()]+)\)$', who.strip())
    if m:  # "Nickname (Species)": a gender was taken off above, what is left in parentheses is the species
        found['nickname'], who = m.group('nick'), m.group('species')
    found['written'] = who.strip()
    for line in lines[1:]:
        key, colon, value = line.partition(': ')
        field = None
        if colon and key in COSMETIC:
            found['cosmetic'].append(line)
        elif line.startswith('Ability: '):
            field, value = 'ability', line[len('Ability: '):].strip()
        elif line.startswith('Level: '):
            field, value = 'level', line[len('Level: '):].strip()
        elif line.startswith('EVs: '):
            if not team_registry.EVS.match(line):
                problems.append('set %d (%s): not an EVs line that trace_to_c reads ("2 HP / 32 Atk / 32 Spe"): %r'
                                % (n, who.strip(), line))
            field, value = 'evs', line
        elif team_registry.NATURE.match(line):
            field, value = 'nature', line[:-len(' Nature')]
        elif line.startswith('- ') and len(line) > 2:
            found['moves'].append(line[2:].strip())
        else:
            problems.append('set %d (%s): unknown line %r (the registry has no such line, and nothing is dropped silently)'
                            % (n, who.strip(), line))
        if field is not None:
            if found[field] is not None:  # the later line would replace the earlier one without a word
                problems.append('set %d (%s): a second %s line %r after %r (a set has one, and nothing is dropped silently)'
                                % (n, who.strip(), field, line, found[field]))
            found[field] = value
    return found, problems


def normalize(text, info_of):
    """The sets of the paste `text` in the registry's form and what was changed: ([set text], [report line]). `info_of(name)`
    is the facts of the pokedex about a species (ps_species.js: exists, name, baseSpecies, gender, genderRatio, isMega,
    requiredItem, battleOnly) or None. PasteError, listing every problem, if it cannot be made a registry team."""
    blocks = team_registry.split_sets(text)
    problems, notes, sets = [], [], []
    if len(blocks) != 6:
        raise PasteError(['a team has six sets, the paste has %d' % len(blocks)])
    for n, block in enumerate(blocks, 1):
        parts, set_problems = parse_set(block, n)
        problems += set_problems
        written = parts['written']
        info = info_of(written)
        if info is None or not info.get('exists'):
            problems.append("set %d: unknown species %r (the pinned pokedex of %s does not have it)" % (n, written, FORMAT))
            continue
        species, item = info['name'], parts['item']
        where = 'set %d' % n
        if species != written:
            notes.append('%s: %r is written as the pokedex spells it, %s' % (where, written, species))
        if parts['nickname'] is not None:
            notes.append('%s (%s): the nickname %r is dropped' % (where, species, parts['nickname']))
        if info.get('isMega'):
            stone = info.get('requiredItem')
            base = info.get('battleOnly') or info.get('baseSpecies')
            if not item or not stone or re.sub(r'[^a-z0-9]', '', item.lower()) != re.sub(r'[^a-z0-9]', '', stone.lower()):
                problems.append('%s: %s is a Mega forme, which needs its stone %s (written %r): the team lists the base '
                                'forme with the stone' % (where, species, stone, item))
                continue
            base_info = info_of(base)
            if base_info is None or not base_info.get('exists'):
                problems.append('%s: the base forme %r of %s is not in the pokedex' % (where, base, species))
                continue
            notes.append('%s: %s @ %s is written as %s @ %s: the Mega forme is what the battle makes of the base forme with '
                         'its stone' % (where, species, item, base_info['name'], item))
            info, species = base_info, base_info['name']
        fixed = info.get('gender') or ''
        gender = parts['gender']
        if fixed == 'N':
            if gender:
                problems.append('%s: %s has no gender, the paste states (%s)' % (where, species, gender))
                continue
        elif fixed in ('M', 'F'):
            if gender and gender != fixed:
                problems.append('%s: %s is always %s, the paste states (%s)' % (where, species, fixed, gender))
                continue
            if not gender:
                gender = fixed
                notes.append('%s: gender (%s) added to %s: the species is always %s' % (where, gender, species, fixed))
        elif not gender:
            gender = 'M'
            ratio = info.get('genderRatio') or {}
            notes.append('%s: gender (M) added to %s: the species can be either (M %s, F %s), the owner\'s standard is male'
                         % (where, species, percent(ratio.get('M', 0.5)), percent(ratio.get('F', 0.5))))
        if parts['level'] is None:
            notes.append('%s (%s): "%s" added' % (where, species, LEVEL))
        elif parts['level'] != '50':
            problems.append('%s (%s): Level %s: the registry is Level 50' % (where, species, parts['level']))
            continue
        for line in parts['cosmetic']:
            notes.append('%s (%s): dropped the cosmetic line %r' % (where, species, line))
        if not parts['ability']:
            problems.append('%s (%s): no "Ability: Name" line (trace_to_c needs an ability and a nature)' % (where, species))
        if not parts['nature']:
            problems.append('%s (%s): no nature line ("Adamant Nature")' % (where, species))
        if not 1 <= len(parts['moves']) <= 4:
            problems.append('%s (%s): %d moves, one to four are needed' % (where, species, len(parts['moves'])))
        if set_problems or not parts['ability'] or not parts['nature'] or not 1 <= len(parts['moves']) <= 4:
            continue
        lines = ['%s%s%s' % (species, ' (%s)' % gender if gender else '', ' @ %s' % item if item else ''),
                 'Ability: %s' % parts['ability'], LEVEL]
        if parts['evs']:
            lines.append(parts['evs'])
        lines.append('%s Nature' % parts['nature'])
        lines += ['- %s' % move for move in parts['moves']]
        sets.append('\n'.join(lines))
    if problems:
        raise PasteError(problems)
    return sets, notes


class SpeciesInfo:
    """The facts of the pinned pokedex about species, from ps_species.js (one Node run for each batch of names, asked once
    for each name): get(name) is a dict or None."""

    def __init__(self, checkout, node='node', run=subprocess.run):
        self.checkout, self.node, self.run, self.cache = checkout, node, run, {}

    def prefetch(self, names):
        wanted = sorted({n for n in names if n not in self.cache})
        if not wanted:
            return
        try:
            done = self.run([self.node, SPECIES_SCRIPT, self.checkout, FORMAT], input=json.dumps(wanted).encode('utf-8'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise PasteError(['cannot run node (%s): %s' % (self.node, e)]) from None
        if done.returncode != 0:
            raise PasteError(['ps_species.js failed (status %d): %s' % (done.returncode,
                                                                          done.stderr.decode('utf-8', 'replace').strip())])
        self.cache.update(json.loads(done.stdout.decode('utf-8')))

    def get(self, name):
        self.prefetch([name])
        return self.cache.get(name)


def species_of_paste(text):
    """The species names as a paste writes them and what a Mega forme or a nickname leaves in them, for one query: every
    name that parse_set finds, and the base forme of each (asked for again once the first answers are in)."""
    names = []
    for block in team_registry.split_sets(text):
        names.append(parse_set(block, 0)[0]['written'])
    return names


def report(notes, out=None):
    out = sys.stdout if out is None else out  # looked up when it is called: a caller may have replaced sys.stdout
    for line in notes:
        print('import_paste: %s' % line, file=out)


def main(argv):
    parser = argparse.ArgumentParser(prog='import_paste.py', description=__doc__.split('\n')[0])
    parser.add_argument('--checkout', required=True, help='the pinned Showdown checkout (built: dist/sim exists)')
    parser.add_argument('--id', required=True, help='the id of the team: upper case letters, digits and underscores, starting '
                        'with a letter; never used before, never reused')
    parser.add_argument('--name', required=True, help='the name of the team')
    parser.add_argument('--paste', default='-', metavar='FILE', help='the paste (default: stdin)')
    parser.add_argument('--url', help='where the paste is from')
    parser.add_argument('--event', help='the event the team played')
    parser.add_argument('--placing', help='its placing')
    parser.add_argument('--notes', default='', help='anything a reader of the registry should know')
    parser.add_argument('--supersedes', metavar='ID', help='the team that this one replaces (a correction is a new id)')
    parser.add_argument('--dry-run', action='store_true', help='report what would be written, write nothing')
    parser.add_argument('--print', action='store_true', help='print the paste in the registry form')
    parser.add_argument('--node', default='node', help='default: node on the PATH')
    parser.add_argument('--root', default=ROOT, help=argparse.SUPPRESS)  # the repository: tests use another one
    args = parser.parse_args(argv)
    if not os.path.isdir(os.path.join(args.checkout, 'dist', 'sim')):
        parser.error('--checkout %s has no dist/sim (npm ci --ignore-scripts --omit=dev; node build)' % args.checkout)
    try:
        if args.paste == '-':
            text = sys.stdin.buffer.read().decode('utf-8')
        else:
            with io.open(args.paste, encoding='utf-8') as f:
                text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        parser.error('cannot read the paste: %s' % e)
    infos = SpeciesInfo(args.checkout, args.node)
    try:
        infos.prefetch(species_of_paste(text))
        # The base forme of a Mega forme is another name: asked for now, in one more run, so the species are two runs at most.
        infos.prefetch([i.get('battleOnly') or i.get('baseSpecies') for i in infos.cache.values() if i.get('isMega')])
        sets, notes = normalize(text, infos.get)
        team_registry.check_new(args.root, args.id, args.supersedes)
        import trace_to_c
        tables = {}
        extra = team_registry.team_problems(team_registry.file_text(sets).decode('utf-8'), lambda team_c: tables.setdefault(
            team_c, trace_to_c.load_tables(ROOT, team_c)))  # the tables are the repository's, whatever registry it is
        if extra:
            raise PasteError(['the paste as the registry would have it is not what the registry holds: %s: %s' % x for x in extra])
    except (PasteError, team_registry.RegistryError) as e:
        for problem in getattr(e, 'problems', [str(e)]):
            print('import_paste: error: %s' % problem, file=sys.stderr)
        print('import_paste: nothing written', file=sys.stderr)
        return 1
    report(notes)
    if args.print:
        sys.stdout.write(team_registry.file_text(sets).decode('utf-8'))
    entry = team_registry.new_entry(args.id, args.name, sets, args.url, args.event, args.placing, args.notes)
    if args.dry_run:
        print('import_paste: dry run: would write data/teams/%s.txt (sha256 %s) and its entry, %d changes' % (
            args.id, entry['sha256'], len(notes)))
        return 0
    path = team_registry.add_team(args.root, entry, sets, args.supersedes)
    print('import_paste: wrote %s (sha256 %s), %d changes' % (os.path.relpath(path, args.root), entry['sha256'], len(notes)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
