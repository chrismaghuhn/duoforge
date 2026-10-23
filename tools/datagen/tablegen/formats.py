"""The table set of a format (restructure step 5): what gen_closure.py builds for the format that --format names.

The format definition data/formats/<id>.json (checked by tools/datagen/gen_format.py: its keys, the shape of its
tables section, its pool source's sha256 and that the pool was made by the pinned validator for the definition's
Showdown format id at the definition's commit) names the rule set, the writer's symbol prefix, include guard and file
stem, the learnset bytes, the id bounds of the set and the formes it excludes from the pool, each with its reason.
Every value is required; a definition without a tables section builds no tables and is refused by name.
"""
import os

import gen_format

from .source import fail, PIN, rule_set


class TableSet:
    """One format's table set, read from its definition and checked."""

    def __init__(self, fmt, rel):
        t = fmt['tables']
        self.format_id = fmt['id']
        self.definition = rel.replace(os.sep, '/')
        self.showdown_format_id = fmt['showdown_format_id']
        self.legal_pool = os.path.join(*fmt['pool']['source'].split('/'))
        self.rule_set_name = t['rule_set']
        self.rule_set = rule_set(t['rule_set'])
        self.pp_cap = self.rule_set['pp_cap']
        self.symbol_prefix = t['symbol_prefix']
        self.include_guard = t['include_guard']
        self.stem = t['stem']
        self.learnset_bytes = t['learnset_bytes']
        self.bounds = dict(t['bounds'])
        self.excluded = {e['id']: e['reason'] for e in t['excluded_formes']}

    def file(self, role):
        """The rule set's file of that role (moves, items, abilities, formats_data, learnsets, scripts)."""
        return self.rule_set['files'][role]


def load_table_set(repo, format_id):
    rel = gen_format.format_file(format_id)
    fmt = gen_format.load_format(repo, format_id)
    if fmt['showdown_commit'] != PIN:
        fail('%s is not at the pin %s' % (rel, PIN))
    if 'tables' not in fmt:
        fail('%s builds no tables: the definition has no tables section' % rel.replace(os.sep, '/'))
    return TableSet(fmt, rel)
