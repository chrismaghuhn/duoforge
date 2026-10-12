#!/usr/bin/env python3
"""The corpus of kept fuzz battles (tests/reference/corpus, decision 0015 section 6) as it must be on disk.

usage: python3 tools/reference/test_corpus_layout.py

CTest runs it as duoforge.reference.corpus_size. Python only, no Node. The corpus is held to:

 - it holds battles, and nothing but <name>.json specs and <name>.trace.json.gz traces;
 - every spec has its trace and every trace its spec: no orphans;
 - a spec is a choices spec of its name (format, seed, teams, choices, the data kind Team C or none), and its trace is the
   recording of it: of the spec's file name, with its choices, its seed and its format, at the pin and with the harness
   of tools/reference/ps_trace.js (a pin that moved leaves the traces of the corpus to be recorded again);
 - the purposes say why each battle is there: "Corpus (coverage): ..." with what it adds, or "Corpus (defect): ..." with
   what it found;
 - the whole stays under 20 MB (decision 0015: what grows beyond it moves to a release artifact).

The checks are diff_corpus.layout_problems, which test_diff_corpus.py tests against made-up corpora.
"""
import os
import sys
import unittest

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

import diff_corpus  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))


class CorpusLayout(unittest.TestCase):
    problems = None

    @classmethod
    def setUpClass(cls):
        cls.problems = diff_corpus.layout_problems(ROOT)
        corpus = diff_corpus.corpus_dir(ROOT)
        specs = diff_corpus.listing(corpus)[0]
        sys.stderr.write('  the corpus: %d battles, %.2f MB of %d MB\n' % (
            len(specs), diff_corpus.corpus_bytes(corpus) / 2 ** 20, diff_corpus.CAP_BYTES // 2 ** 20))

    def nothing_in(self, *categories):
        found = ['%s: %s' % (c, m) for c, m in self.problems if c in categories]
        self.assertEqual(found, [], '\n' + '\n'.join(found))

    def test_the_corpus_holds_battles_and_nothing_else(self):
        self.nothing_in('empty', 'files')

    def test_every_spec_has_its_trace_and_every_trace_its_spec(self):
        self.nothing_in('orphan')

    def test_the_specs_are_choices_specs_of_their_names(self):
        self.nothing_in('spec')

    def test_the_traces_are_the_recordings_of_the_specs_at_this_pin(self):
        self.nothing_in('trace')

    def test_the_purposes_say_why_each_battle_is_there(self):
        self.nothing_in('purpose')

    def test_the_corpus_stays_under_the_cap(self):
        self.nothing_in('size')
        self.assertEqual(diff_corpus.CAP_BYTES, 20 * 1024 * 1024)

    def test_nothing_is_missing_from_the_checks(self):
        """The categories of layout_problems are the ones tested here: a new one must not slip through."""
        categories = {c for c, _ in self.problems}
        self.assertLessEqual(categories, {'empty', 'files', 'orphan', 'spec', 'trace', 'purpose', 'size'})


if __name__ == '__main__':
    unittest.main()
