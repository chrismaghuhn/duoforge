"""duoforge.python.cts_luck_check: the luck meter's comparison with luck.py (#494, tools/research/cts_luck_check.py).

A point whose public record the open-sheet tracker refused (record.assemble: the zero record, E_UNSUPPORTED and a named
reason) has no true world. The tool skips it by that reason, true-record-unsupported:<reason>, and never hands the zero
record to the engine, which would refuse it as a schema mismatch (the comparison of 2026-10-15 named 34 such turns
DUOFORGE_E_SCHEMA_MISMATCH before this check).
"""
import importlib.util
import unittest

import numpy as np

from duoforge import _layout
from duoforge_live import data, record

_SPEC = importlib.util.spec_from_file_location("cts_luck_check", data.ROOT / "tools" / "research" / "cts_luck_check.py")
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)


class RefusedRecordTest(unittest.TestCase):
    def point(self, reason):
        return {"k": 2, "record": np.zeros((), dtype=_layout.PUBLIC_STATE), "status": record.E_UNSUPPORTED,
                "reason": reason}

    def test_a_refused_record_is_skipped_by_its_reason(self):
        for reason in ("engine-refuses-record", "pivot-switch-reason-unknown"):
            with self.subTest(reason=reason):
                # no context: the check comes before any engine call, so reaching the engine would fail otherwise
                with self.assertRaises(check.Skip) as caught:
                    check.world(None, self.point(reason), None)
                self.assertEqual(str(caught.exception), f"true-record-unsupported:{reason}")
                self.assertNotIn("SCHEMA_MISMATCH", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
