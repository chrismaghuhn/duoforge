#!/usr/bin/env python3
"""The generated names of the data query API (duoforge_data_find, _name)
against the macros of the generated headers.

gen_closure.py --pool writes, next to the pool tables, the Showdown id (toID)
of every forme, move, item, ability and nature as a designated initializer
([DFI_MOVE_CLOSECOMBAT] = "closecombat"). This test reads the committed
src/data/{closure,extended,pool}_tables.h and pool_tables.c and checks, for
every table:
  - every macro has exactly one name, and every name one macro (the ids 0 to
    count-1 are all there);
  - a name is a Showdown id: lower-case letters and digits, never empty;
  - the macro is the key of its name, trace_to_c.key(name), which is how the
    converter of the reference traces maps a Showdown name to an id, so that a
    name and its id cannot drift apart;
  - the names of a table are unique.
The same names are checked against the pinned dex (ids that Showdown knows) by
tools/datagen/pool_families.js. No checkout is needed here.

usage: python3 tools/datagen/test_pool_names.py
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'reference'))
import trace_to_c  # noqa: E402

# table prefix of the macros -> (array in pool_tables.c, count macro)
TABLES = {
    'FORME': ('dfi_pool_forme_names', 'DFI_POOL_FORME_COUNT'),
    'MOVE': ('dfi_pool_move_names', 'DFI_POOL_MOVE_COUNT'),
    'ITEM': ('dfi_pool_item_names', 'DFI_POOL_ITEM_COUNT'),
    'ABILITY': ('dfi_pool_ability_names', 'DFI_POOL_ABILITY_COUNT'),
    'NATURE': ('dfi_pool_nature_names', 'DFI_NATURE_COUNT'),
}


def read(rel):
    with open(os.path.join(ROOT, 'src', 'data', rel), 'rb') as fh:
        return fh.read().decode('ascii').replace('\r\n', '\n')


HEADER = ''.join(read(f) for f in ('closure_tables.h', 'extended_tables.h', 'pool_tables.h'))
SOURCE = read('pool_tables.c')


def count_of(macro):
    return int(re.search(r'^#define %s (\d+)u$' % macro, HEADER, re.M).group(1))


def names_of(array):
    """{macro suffix: name} of one generated array."""
    start = SOURCE.index('const char *const %s[' % array)
    end = SOURCE.index('\n};', start)
    return re.findall(r'^\s*\[DFI_[A-Z]+_([A-Z0-9]+)\] = "([^"]*)",$', SOURCE[start:end], re.M)


class PoolNames(unittest.TestCase):
    def test_every_table(self):
        for prefix, (array, count_macro) in TABLES.items():
            with self.subTest(table=prefix):
                ids = {k: v for k, v in trace_to_c.ids(HEADER, prefix).items() if k != 'COUNT'}
                count = count_of(count_macro)
                rows = names_of(array)
                keys = [k for k, _n in rows]
                # One name per macro, none twice, none missing.
                self.assertEqual(len(rows), count)
                self.assertEqual(len(set(keys)), len(keys))
                self.assertEqual(set(keys), set(ids))
                self.assertEqual(sorted(ids.values()), list(range(count)))
                names = [n for _k, n in rows]
                self.assertEqual(len(set(names)), len(names), 'two ids share a name')
                for key, name in rows:
                    self.assertRegex(name, r'^[a-z0-9]+$')
                    self.assertEqual(trace_to_c.key(name), key, 'the macro is not the key of the name')

    def test_the_prefix_keeps_its_names(self):
        # A closure or Team C id has the same name in the pool tables: the macro of the closure
        # and extended headers is the one the pool array indexes by.
        for prefix, (array, _count) in TABLES.items():
            names = dict(names_of(array))
            for macro, value in trace_to_c.ids(read('closure_tables.h') + read('extended_tables.h'), prefix).items():
                if macro != 'COUNT':
                    self.assertIn(macro, names, '%s %d' % (prefix, value))


if __name__ == '__main__':
    unittest.main()
