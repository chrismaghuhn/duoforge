"""duoforge.python.live: the Showdown live adapter against the pinned Showdown.

Needs Node and the pinned checkout (DUOFORGE_NODE, DUOFORGE_PS_REFERENCE_DIR)
and the runner (DUOFORGE_DIFF_RUNNER); CTest registers it only with all of
them and reports it skipped otherwise. Spec section 8, test 5 (packing).
"""
import os
import subprocess
import unittest

from duoforge_live import data, teams


def node_tool(*args):
    """stdout of tools/reference/ps_client.js with the pinned checkout."""
    script = data.ROOT / "tools" / "reference" / "ps_client.js"
    out = subprocess.run([os.environ["DUOFORGE_NODE"], str(script), os.environ["DUOFORGE_PS_REFERENCE_DIR"]] +
                         list(args), capture_output=True, text=True, encoding="utf-8", timeout=600)
    if out.returncode != 0:
        raise AssertionError(f"ps_client.js {' '.join(args)}: {out.stderr}")
    return out.stdout


class PackTest(unittest.TestCase):
    def test_pack_equals_showdown(self):
        for name, file in teams.FILES.items():
            path = data.ROOT / "tests" / "reference" / "teams" / file
            self.assertEqual(teams.pack(teams.text(name)), node_tool("--pack", str(path)).rstrip("\n"), name)


if __name__ == "__main__":
    unittest.main()
