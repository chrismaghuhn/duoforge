"""The pinned Showdown inputs and the shared parsing helpers: the pin and the input hashes, Source (a pinned
file read with its hash checked), the entry parsers, the id and name helpers and the pattern matchers.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area from
gen_closure.py@8800b625).
"""
import hashlib
import io
import os
import re
import sys

PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc'

# More files of the pin, read only by the whole-pool rows of --pool (decision 0015 section 4.2) to find where an item or
# an ability is read by its id; they are not part of the provenance of any table header.
READER_INPUTS = {
    'data/conditions.ts': '03ec1b90913f864a0baab0574a70abb856d5e84f722acf96ab11a7601a72fc35',
    'sim/battle-actions.ts': 'a30408e2f9a53a43333bf4a865366d6adbe26d3d91a836ba51042accce4d9437',
    'sim/battle-queue.ts': '3d9dd71dfb7abc788f961d6123b1b9f7308ccab947af6527f1752dd1d94b95ed',
    'sim/battle.ts': '852dc6eed2876100787090cf049e27d2b061fdb6e808a1edd261468390afaa1f',
    'sim/field.ts': '3c46a9923736a9a0aaa35791e99d491308c255934553c9d104a0cc2ea453aa79',
    'sim/pokemon.ts': 'f40260351baf649b15ad3beacfa4269c3418b2da27947af8f5c1097c888ab122',
    'sim/side.ts': 'a18946aefe31018162956b1c708a9cce27bb33fe0f098cb58c44d8521d53b1f1',
    'data/mods/champions/conditions.ts': '851507309dde0b58807e33b17d8ce7e607dad70893546f67bad294ad70249005',
}

# sha256 of the input files at the pin, after CRLF -> LF normalisation: the base data every rule set reads.
BASE_INPUTS = {
    'data/pokedex.ts': '73048386b864be5aff093e9393acf32e8016299e9d7b76078bf5120b769e2fe0',
    'data/moves.ts': '6b44af2a393739e00fc444dc574eaa79659b68867777012b0f7ce4727a9b7734',
    'data/abilities.ts': '818edd100c8eb5bdf4d4ded8dd1b1ce9d394f87f40f7d9d53a5414276e84f82b',
    'data/items.ts': '75da206e2cb09868bb549360f38a144c2f50b24e1d189e03b485d550a4f6357a',
    'data/typechart.ts': '7b0eae126bdcf98edfd71cbe75af00b763f5f0d5db36024b6f3e7c5e4aea95ac',
    'data/natures.ts': '5cfefee4c23dd19f629deb9a67f75361226bd24fe34cefe9a13d30d985428416',
}

# The rule sets (restructure step 5, the "rule set" of the Gen 9 design): what a format reads on top of the base data.
# A format definition names one (data/formats/<id>.json, tables.rule_set). Each names its override files by role, their
# pinned sha256 and the PP cap of its moves (None: no cap). champions is the Champions mod: its own move, item and
# ability entries over the base ones, its formats data and learnsets, and init()'s PP cap of 20
# (data/mods/champions/scripts.ts:3-9). A rule set without overrides (gen9, step O8 of the Gen 9 design) needs the code
# that reads the base data alone; until then RULE_SETS_REFUSED names it with its reason and any other name is refused.
RULE_SETS = {
    'champions': {
        'files': {
            'moves': 'data/mods/champions/moves.ts',
            'items': 'data/mods/champions/items.ts',
            'abilities': 'data/mods/champions/abilities.ts',
            'formats_data': 'data/mods/champions/formats-data.ts',
            'learnsets': 'data/mods/champions/learnsets.ts',
            'scripts': 'data/mods/champions/scripts.ts',
        },
        'inputs': {
            'data/mods/champions/moves.ts': '1d317da33d3e36d430a9cbe195c2ef9bb9a6fc2f3e0516ba2200da8a394080bc',
            'data/mods/champions/items.ts': 'b39dafa66d136ebb1a8576367ced2c9f4519aa1c17d5d65c59b368ac15d7de77',
            'data/mods/champions/abilities.ts': '86c3843d402f1ff7be276d8f2da08d6744b8a8822349560b300ddcfa9c1fbc52',
            'data/mods/champions/formats-data.ts': 'a512b537a84574a324c250c6ff99ad60f0cf1e82420fdae60d4635eec8661e13',
            'data/mods/champions/learnsets.ts': '826d302703358260a1c4967e2bf8edd15f1fe7e0f664c8ab14aff734906cc9d0',
            'data/mods/champions/scripts.ts': 'a6cc11eeb525ad58dee9010dd0d42274a5b4dacb39ce8653f4888cbd2f4f459d',
        },
        'pp_cap': 20,
    },
}
RULE_SET_ROLES = ('moves', 'items', 'abilities', 'formats_data', 'learnsets', 'scripts')
# Rule sets that a definition may name but no table set builds yet, each with its reason (HS decision 2026-10-23, O8):
# gen9 is the base data alone (no override files, no PP cap), but the pool build of the tables is an extension of the
# Reg M-C tables (the closure, Team C and G2 rows as the prefix, the flat "9M" Champions learnsets, the Champions fact
# checks), so a Gen 9 table set needs a standalone build of its own.
RULE_SETS_REFUSED = {
    'gen9': 'standalone table sets come with the Gen 9 design (the base data alone, without the Reg M-C prefix)',
}


def rule_set(name):
    """The rule set of that name, checked: every role has a file, every file its pinned hash; an unknown name fails."""
    if name in RULE_SETS_REFUSED:
        fail('rule set %s is refused: %s' % (name, RULE_SETS_REFUSED[name]))
    if name not in RULE_SETS:
        fail('rule set %r is not defined (known: %s)' % (name, ', '.join(sorted(RULE_SETS))))
    rs = RULE_SETS[name]
    if set(rs) != {'files', 'inputs', 'pp_cap'} or set(rs['files']) != set(RULE_SET_ROLES):
        fail('rule set %s: it needs exactly the files %s, its inputs and its pp_cap' % (name, ', '.join(RULE_SET_ROLES)))
    if set(rs['files'].values()) != set(rs['inputs']):
        fail('rule set %s: every file needs its pinned sha256, and only those' % name)
    if rs['pp_cap'] is not None and (type(rs['pp_cap']) is not int or rs['pp_cap'] < 1):
        fail('rule set %s: pp_cap must be a positive int or None' % name)
    return rs


# Every pinned input by path, the base first (Source checks a file against it).
INPUTS = dict(BASE_INPUTS)
for _rs in RULE_SETS.values():
    INPUTS.update(_rs['inputs'])
del _rs

TYPES = ['Bug', 'Dark', 'Dragon', 'Electric', 'Fairy', 'Fighting', 'Fire', 'Flying', 'Ghost', 'Grass', 'Ground',
         'Ice', 'Normal', 'Poison', 'Psychic', 'Rock', 'Steel', 'Water']
STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
CATEGORIES = {'Physical': 0, 'Special': 1, 'Status': 2}


def fail(msg):
    sys.exit('gen_closure: ' + msg)


class Source:
    def __init__(self, root, rel, pins=None):
        pins = INPUTS if pins is None else pins
        raw = io.open(os.path.join(root, rel), 'rb').read().replace(b'\r\n', b'\n')
        got = hashlib.sha256(raw).hexdigest()
        if got != pins[rel]:
            fail('%s: sha256 %s differs from the pin %s' % (rel, got, pins[rel]))
        self.rel = rel
        self.lines = raw.decode('utf-8').split('\n')

    def first_lines(self):
        """key -> index of the first line of its top-level entry (the first one of a repeated key), built once."""
        if getattr(self, '_first', None) is None or self._first_of is not self.lines:
            self._first, self._first_of = {}, self.lines
            for i, line in enumerate(self.lines):
                m = re.match(r'^\t(\w+): \{', line)
                if m is not None and m.group(1) not in self._first:
                    self._first[m.group(1)] = i
        return self._first

    def entry(self, key):
        """Returns (first line, last line, body lines) of the top-level entry or None."""
        i = self.first_lines().get(key)
        if i is None:
            return None
        line = self.lines[i]
        if line.rstrip().endswith('},'):  # one-line entry
            return i + 1, i + 1, [line]
        depth = 0
        for j in range(i, len(self.lines)):
            depth += self.lines[j].count('{') - self.lines[j].count('}')
            if depth <= 0:
                if self.lines[j] != '\t},':
                    fail('%s: the entry %s does not end at a line "\\t},"' % (self.rel, key))
                return i + 1, j + 1, self.lines[i:j + 1]
        fail('%s: the entry %s is not closed' % (self.rel, key))

    def ref(self, key):
        e = self.entry(key)
        if e is None:
            fail('%s: entry %s not found' % (self.rel, key))
        return '%s:%d-%d' % (self.rel, e[0], e[1])


def fields(body):
    """Top-level fields of an entry body: name -> (is_function, text)."""
    out = {}
    name = None
    for line in body[1:-1]:
        m = re.match(r'^\t\t([A-Za-z]+)([:(])', line)
        if m:
            name = m.group(1)
            out[name] = [m.group(2) == '(', line]
        elif name is not None:
            out[name][1] += '\n' + line
    return out


def scalar(text):
    v = text.split(':', 1)[1].strip().rstrip(',')
    if v == 'true':
        return True
    if v == 'false':
        return False
    if re.match(r'^-?\d+$', v):
        return int(v)
    return v.strip('"\'')


def toid(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


class NoMatch(Exception):
    """An entry does not follow the pattern of a family."""


def norm(text):
    return ' '.join(text.split())


def shape(f, keys):
    """The entry has exactly these top-level fields: nothing that the pattern does not account for."""
    if set(f) != keys:
        raise NoMatch('fields %s, not %s' % (sorted(f), sorted(keys)))


def field_is(f, key, want):
    if norm(f[key][1]) != want:
        raise NoMatch('%s is "%s", not "%s"' % (key, norm(f[key][1]), want))


def field_match(f, key, pattern):
    m = re.fullmatch(pattern, norm(f[key][1]))
    if m is None:
        raise NoMatch('%s deviates from the pattern: %s' % (key, norm(f[key][1])))
    return m


def wrap_names(head, names, width=100):
    """Comment lines that hold `head` and then the names, wrapped between names, never inside one."""
    lines, line = [], head
    for i, name in enumerate(names):
        piece = name + (',' if i + 1 < len(names) else '')
        if len(line) + 1 + len(piece) > width and line != head:
            lines.append(line)
            line = '   ' + piece
        else:
            line += ' ' + piece
    lines.append(line)
    return lines


class ReaderIndex:
    """Where the quoted id of an item or ability appears in the pinned code: the data files that hold handlers (moves,
    abilities, items, conditions and the Champions mod) and the sim files that run them. An item or ability with no
    callback of its own can still be read by its id elsewhere (Damp Rock by Rain Dance, Levitate by isGrounded, Binding
    Band by the trapping condition): its effect is then code in the reader, not data in its row."""

    QUOTED = re.compile(r"""['"]([a-z][a-z0-9]*)['"]""")

    def __init__(self, root, loaded):
        self.lines = {rel: Source(root, rel, READER_INPUTS).lines for rel in READER_INPUTS}
        for rel, src in loaded.items():  # the base data files and the rule set's overrides and scripts
            self.lines[rel] = src.lines
        self.index = {}
        for rel, lines in self.lines.items():
            for n, line in enumerate(lines, 1):
                for tok in self.QUOTED.findall(line):
                    self.index.setdefault(tok, []).append((rel, n))

    def files(self, rid, own):
        """The files that read the id outside the id's own entries (own: (file, first line, last line) triples)."""
        return sorted({rel for rel, n in self.index.get(rid, []) if not any(r == rel and a <= n <= b for r, a, b in own)})
