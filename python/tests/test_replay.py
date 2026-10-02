"""duoforge.python.replay: the M11 replay pipeline against the pinned Showdown
and DuoForge (spec docs/superpowers/specs/2026-10-02-m11-replay-data-design.md
section 14).

Needs Node and the pinned checkout (DUOFORGE_NODE, DUOFORGE_PS_REFERENCE_DIR)
and the runner (DUOFORGE_DIFF_RUNNER); CTest registers it only with all of
them and reports it skipped otherwise. Every input is our own: the committed
reference battles, replayed by the pinned Showdown as spectator logs.
"""
import json
import os
import subprocess
import unittest

from duoforge_live import data, lines


def node_stats(*args, stdin=None):
    script = data.ROOT / "tools" / "reference" / "ps_stats.js"
    out = subprocess.run([os.environ["DUOFORGE_NODE"], str(script), os.environ["DUOFORGE_PS_REFERENCE_DIR"]] +
                         list(args), input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=300)
    if out.returncode != 0:
        raise AssertionError(f"ps_stats.js {' '.join(args)}: {out.stderr}")
    return json.loads(out.stdout)


class ShowdownFactsTest(unittest.TestCase):
    """Facts of the pinned Showdown the pipeline relies on (Task 4)."""

    def test_choice_items_equal_showdown(self):
        self.assertEqual(list(lines.CHOICE_ITEMS), node_stats("--choice-items"))

    def test_stat_source_serves_showdown_stats(self):
        from duoforge_replay.stats import StatSource
        query = {"species": "Rillaboom", "nature": "Adamant", "sp": [32, 32, 0, 0, 0, 2]}
        want = node_stats(stdin=json.dumps([query]))[0]
        source = StatSource(os.environ["DUOFORGE_NODE"], os.environ["DUOFORGE_PS_REFERENCE_DIR"])
        try:
            self.assertEqual(source.stats("Rillaboom", "Adamant", [32, 32, 0, 0, 0, 2]), want)
            self.assertEqual(source.stats("rillaboom", "adamant", [32, 32, 0, 0, 0, 2]), want)  # ids too
            with self.assertRaisesRegex(ValueError, "unknown species"):
                source.stats("Nope", "Adamant", [0] * 6)
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
