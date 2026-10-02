"""The team registry: data/teams/, one Showdown paste for each team and an index, shared by the differential loop
(diff_random.py takes a team by its id) and the learner (it reads the same files).

    data/teams/<id>.txt     the paste of the team: six sets, in the importer's form (below)
    data/teams/index.json   {"registry": 1, "teams": [entry, ...]}, an entry for each team in the order they were added

An entry is {"id", "name", "source": {"url", "event", "placing"}, "notes", "sha256"} and, once a correction has
replaced the team, "superseded_by": the id of the team that replaced it. The id is upper case ([A-Z][A-Z0-9_]*, 32
characters at most; a dash is how a pairing joins two ids, so an id has none); `source` has the three keys, each a string
or null; `sha256` is the SHA-256 of the bytes of the paste.

Ids are stable and never reused, and a team file never changes under its id: the learner records the SHA-256 of each file
and refuses a file that changed. A correction of a team is a new team, with a new id and its own entry; the old entry
stays, with `superseded_by`, and so does its file. `problems()` checks all of that that a tree can show.

A paste is exactly the form tools/reference/import_paste.py writes, which trace_to_c.parse_team reads: LF line ends, the
sets separated by one blank line, one newline at the end, and for each set

    Species (G) @ Item          (G is M or F: stated for every Pokemon that has a gender; none for a genderless one;
                                 "@ Item" is left out for no item)
    Ability: Name
    Level: 50
    EVs: 2 HP / 32 Atk / 32 Spe (Stat Points, as in the specs; the line is left out for none)
    Adamant Nature
    - Move                      (one to four lines)

Nothing else is allowed: a line that is not one of these is an unknown line (a cosmetic one such as "Shiny: Yes" is dropped
by the importer, with a report, and never written). The species is the base forme with its Mega Stone, never the Mega
forme. The registry states every rule of its own and no rule of the game: whether a team is legal is the converter's,
the engine's and Showdown's to say.
"""
import hashlib
import io
import json
import os
import re
import sys

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

REGISTRY = os.path.join('data', 'teams')
INDEX = 'index.json'
FORMAT = 1
ID = re.compile(r'[A-Z][A-Z0-9_]{0,31}')
ENTRY_KEYS = ('id', 'name', 'source', 'notes', 'sha256')
OPTIONAL_KEYS = ('superseded_by',)
SOURCE_KEYS = ('url', 'event', 'placing')
STATS = r'(?:HP|Atk|Def|SpA|SpD|Spe)'
HEAD = re.compile(r'^(?P<species>[^()@]+?)(?: \((?P<gender>[MF])\))?(?: @ (?P<item>[^@]+))?$')
EVS = re.compile(r'^EVs: \d+ %s(?: / \d+ %s)*$' % (STATS, STATS))
NATURE = re.compile(r'^[A-Z][a-z]+ Nature$')
FILE_NAME = re.compile(r'^([A-Z][A-Z0-9_]{0,31})\.txt$')
OTHER_FILES = ('README.md',)


class RegistryError(Exception):
    """The registry cannot be read or written as asked."""


# ------------------------------------------------------------ files and hashes

def registry_dir(root):
    return os.path.join(root, REGISTRY)


def index_path(root):
    return os.path.join(registry_dir(root), INDEX)


def team_path(root, team_id):
    return os.path.join(registry_dir(root), team_id + '.txt')


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def split_sets(text):
    """The sets of a Showdown paste: the blocks between blank lines, each without the blank space around it."""
    return [s.strip() for s in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n').strip()) if s.strip()]


def file_text(sets):
    """The bytes of the paste of `sets` as the registry has them: one blank line between the sets, one newline at the end."""
    return ('\n\n'.join(sets) + '\n').encode('utf-8')


def team_sha256(sets):
    """The SHA-256 of a team as a run uses it: its sets as paste text in the order of the file (a blank line more or
    less, or a line end of another system, is no difference)."""
    return hashlib.sha256('\n\n'.join(sets).encode('utf-8')).hexdigest()


def read_team_file(path):
    """The sets of the paste in `path`, which must be six; RegistryError if it cannot be read or is not six sets."""
    try:
        with io.open(path, encoding='utf-8') as f:
            sets = split_sets(f.read())
    except (OSError, UnicodeDecodeError) as e:
        raise RegistryError('cannot read the team file %s: %s' % (path, e)) from None
    if len(sets) != 6:
        raise RegistryError('%s has %d sets, not 6' % (path, len(sets)))
    return sets


# ------------------------------------------------------------ the index

def read_index(root):
    """The parsed index.json of the registry of `root`; RegistryError if it is missing or not JSON of the shape."""
    path = index_path(root)
    try:
        with io.open(path, encoding='utf-8') as f:
            index = json.load(f)
    except (OSError, ValueError) as e:
        raise RegistryError('cannot read the team index %s: %s' % (path, e)) from None
    if not isinstance(index, dict) or not isinstance(index.get('teams'), list):
        raise RegistryError('%s is not {"registry": %d, "teams": [...]}' % (path, FORMAT))
    return index


def entries(root):
    """The entries of the registry, in the order they were added."""
    return read_index(root)['teams']


def get_entry(root, team_id):
    """The entry of team `team_id`; RegistryError, naming the ids there are, if there is none."""
    for entry in entries(root):
        if isinstance(entry, dict) and entry.get('id') == team_id:
            return entry
    raise RegistryError('no team %s in the registry (%s): ids are %s' % (
        team_id, registry_dir(root), ', '.join(str(e.get('id')) for e in entries(root) if isinstance(e, dict)) or 'none'))


def read_team(root, team_id):
    """(sets, path) of registry team `team_id`."""
    get_entry(root, team_id)
    path = team_path(root, team_id)
    return read_team_file(path), path


def dumps_index(index):
    """index.json as it is written: two spaces, the keys in the order of the entries, a newline at the end."""
    return (json.dumps(index, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def new_entry(team_id, name, sets, url=None, event=None, placing=None, notes=''):
    """The entry of a team that is about to be added, with the hash of the paste it will have."""
    return {'id': team_id, 'name': name, 'source': {'url': url, 'event': event, 'placing': placing}, 'notes': notes,
            'sha256': sha256_of(file_text(sets))}


def check_new(root, team_id, supersedes=None):
    """RegistryError unless `team_id` can be the id of a new team of the registry of `root`: an id of the right form that
    is in no entry and has no file (ids are never reused), and a `supersedes` that names a team that nothing replaced."""
    if not ID.fullmatch(team_id):
        raise RegistryError('%r is no team id: an upper case letter, then upper case letters, digits and underscores (32 '
                            'at most)' % team_id)
    index = read_index(root) if os.path.exists(index_path(root)) else {'registry': FORMAT, 'teams': []}
    if any(isinstance(e, dict) and e.get('id') == team_id for e in index['teams']) or os.path.exists(team_path(root, team_id)):
        raise RegistryError('team %s is in the registry already: ids are never reused and a file never changes under its id '
                            '(a correction is a new id, with --supersedes)' % team_id)
    if supersedes is not None:
        old = [e for e in index['teams'] if isinstance(e, dict) and e.get('id') == supersedes]
        if not old:
            raise RegistryError('--supersedes %s: no such team' % supersedes)
        if 'superseded_by' in old[0]:
            raise RegistryError('team %s is superseded by %s already' % (supersedes, old[0]['superseded_by']))
    return index


def add_team(root, entry, sets, supersedes=None):
    """Adds team `entry` (new_entry) with `sets` to the registry: its file and its entry at the end of the index (the
    registry is created if there is none). Ids are never reused: RegistryError for one that is there, or whose file is.
    `supersedes` names the team that this one replaces: that entry gets `superseded_by`, and nothing else of it changes.
    Returns the path of the new file."""
    team_id = entry['id']
    if len(sets) != 6:
        raise RegistryError('a team has six sets, not %d' % len(sets))
    index = check_new(root, team_id, supersedes)
    if supersedes is not None:
        next(e for e in index['teams'] if e.get('id') == supersedes)['superseded_by'] = team_id
    index['teams'].append(entry)
    os.makedirs(registry_dir(root), exist_ok=True)
    path = team_path(root, team_id)
    with io.open(path, 'wb') as f:
        f.write(file_text(sets))
    with io.open(index_path(root), 'wb') as f:
        f.write(dumps_index(index))
    return path


# ------------------------------------------------------------ what the registry must be

def set_problems(block):
    """What is wrong with the text of one set as the registry has it: the form (the lines, their order, Level 50, one to
    four moves), as [message]. The names, and whether a gender may be left out, are the converter's to say."""
    lines = block.split('\n')
    found = []
    head = HEAD.match(lines[0])
    if head is None:
        return ['the first line is not "Species (G) @ Item": %r' % lines[0]]
    rest = lines[1:]
    if not rest or not rest[0].startswith('Ability: ') or len(rest[0]) <= len('Ability: '):
        found.append('the second line is "Ability: Name"')
    else:
        rest = rest[1:]
    if not rest or rest[0] != 'Level: 50':
        found.append('"Level: 50" must follow the ability: the registry is Level 50')
    else:
        rest = rest[1:]
    if rest and rest[0].startswith('EVs: '):
        if not EVS.match(rest[0]):
            found.append('not an EVs line (Stat Points: "2 HP / 32 Atk / 32 Spe"): %r' % rest[0])
        rest = rest[1:]
    if not rest or not NATURE.match(rest[0]):
        found.append('a nature line ("Adamant Nature") must follow')
    else:
        rest = rest[1:]
    moves = [line for line in rest if line.startswith('- ') and len(line) > 2]
    if rest != moves or not 1 <= len(moves) <= 4:
        found.append('then one to four "- Move" lines and nothing else: %r' % rest)
    return found


def team_problems(text, tables_for=None):
    """[(category, message)] of the paste `text` of a team: its form, the form of each set (category 'form'), the gender
    of each Pokemon as the converter reads it (category 'gender': it is stated unless the species has none, and it is one
    the species can have) when `tables_for` (trace_to_c tables by the team_c flag) knows every name of the team; a team that
    names something the tables do not have is only checked for its form."""
    problems = []
    if '\r' in text:
        problems.append(('form', 'carriage returns: the registry has LF line ends'))
    if not text.endswith('\n') or text.endswith('\n\n'):
        problems.append(('form', 'the file ends with exactly one newline'))
    sets = text.replace('\r\n', '\n').strip('\n').split('\n\n')
    if len(sets) != 6 or any(not s.strip() or '\n\n' in s for s in sets):
        problems.append(('form', 'six sets separated by one blank line, not %d' % len(sets)))
        return problems
    for i, block in enumerate(sets, 1):
        if block != block.strip() or any(line != line.rstrip() for line in block.split('\n')):
            problems.append(('form', 'set %d has blank space around a line' % i))
        for message in set_problems(block):
            problems.append(('form', 'set %d: %s' % (i, message)))
    if problems or tables_for is None:
        return problems
    import trace_to_c  # here: the registry is read by tools that have no use for the converter
    for team_c in (False, True):
        try:
            trace_to_c.parse_team('\n\n'.join(sets), tables_for(team_c))
        except trace_to_c.ConversionError as e:
            problems.append(('gender' if e.rule.startswith('gender') else 'form', e.code))
            break
        except KeyError:
            continue  # a name that these tables do not have: the next, and then no check
        except (AttributeError, IndexError, ValueError) as e:
            problems.append(('form', 'a paste that the converter cannot read (%s: %s)' % (type(e).__name__, e)))
            break
        break
    return problems


def problems(root, tables_for=None):
    """What is wrong with the registry of `root`, as [(category, message)]; empty when it is as it must be. Categories: index
    (index.json, its entries and their keys), files (a file that is no team of the index, or a team without its file, or a
    name that is no id), sha256 (a file that is not what the index says: a team never changes under its id), form (a
    paste that is not in the importer's form) and gender."""
    found = []
    registry = registry_dir(root)
    try:
        index = read_index(root)
    except RegistryError as e:
        return [('index', str(e))]
    if index.get('registry') != FORMAT or sorted(index) != ['registry', 'teams']:
        found.append(('index', 'the keys of index.json are "registry" (%d) and "teams"' % FORMAT))
    ids = []
    for n, entry in enumerate(index['teams'], 1):
        where = 'entry %d' % n
        if not isinstance(entry, dict):
            found.append(('index', '%s is not an object' % where))
            continue
        expected = [k for k in ENTRY_KEYS + OPTIONAL_KEYS if k in entry]
        if list(entry) != expected or any(k not in entry for k in ENTRY_KEYS):
            found.append(('index', '%s has the keys %s, not %s (and optionally %s) in that order' % (
                where, list(entry), list(ENTRY_KEYS), list(OPTIONAL_KEYS))))
            continue
        team_id = entry['id']
        where = 'team %s' % team_id
        if not isinstance(team_id, str) or not ID.fullmatch(team_id):
            found.append(('index', '%s: the id is an upper case letter, then upper case letters, digits and underscores'
                          % where))
            continue
        if team_id in ids:
            found.append(('index', '%s is in the index twice' % where))
        ids.append(team_id)
        if not isinstance(entry['name'], str) or not entry['name'].strip():
            found.append(('index', '%s: the name is a string that says something' % where))
        if not isinstance(entry['notes'], str):
            found.append(('index', '%s: the notes are a string' % where))
        source = entry['source']
        if not isinstance(source, dict) or sorted(source) != sorted(SOURCE_KEYS) \
                or any(v is not None and not isinstance(v, str) for v in source.values()):
            found.append(('index', '%s: the source is {"url", "event", "placing"}, each a string or null' % where))
        if not isinstance(entry['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
            found.append(('index', '%s: the sha256 is 64 hex digits' % where))
    for entry in index['teams']:
        if isinstance(entry, dict) and 'superseded_by' in entry:
            other = entry['superseded_by']
            if other not in ids or other == entry.get('id'):
                found.append(('index', 'team %s is superseded by %r, which is no other team of the index' % (entry.get('id'), other)))
    present = sorted(os.listdir(registry)) if os.path.isdir(registry) else []
    for fname in present:
        m = FILE_NAME.match(fname)
        if fname == INDEX or fname in OTHER_FILES:
            continue
        if m is None:
            found.append(('files', '%s: no team file (<id>.txt) and no index' % fname))
        elif m.group(1) not in ids:
            found.append(('files', '%s is in no entry of the index (a team file is never taken out: ids are never reused)' % fname))
    for entry in index['teams']:
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not ID.fullmatch(entry['id']):
            continue
        team_id = entry['id']
        path = team_path(root, team_id)
        if not os.path.exists(path):
            found.append(('files', 'team %s has no file %s' % (team_id, team_id + '.txt')))
            continue
        with io.open(path, 'rb') as f:
            data = f.read()
        if isinstance(entry.get('sha256'), str) and sha256_of(data) != entry['sha256']:
            found.append(('sha256', 'team %s: the file is not what the index says (sha256 %s, the file has %s): a team never '
                          'changes under its id, a correction is a new id' % (team_id, entry['sha256'][:12], sha256_of(data)[:12])))
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            found.append(('form', 'team %s: not UTF-8' % team_id))
            continue
        for category, message in team_problems(text, tables_for):
            found.append((category, 'team %s: %s' % (team_id, message)))
    return found


def main(argv):
    """python tools/reference/team_registry.py <repo root>: the problems of the registry, status 1 if there are any."""
    if len(argv) != 1:
        sys.stderr.write('usage: team_registry.py <repo root>\n')
        return 2
    import trace_to_c
    tables = {}
    found = problems(argv[0], lambda team_c: tables.setdefault(team_c, trace_to_c.load_tables(argv[0], team_c)))
    for category, message in found:
        print('%s: %s' % (category, message))
    print('team_registry: %d problems' % len(found))
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
