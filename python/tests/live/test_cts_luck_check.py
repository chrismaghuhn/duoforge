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


class TargetAdditionsTest(unittest.TestCase):
    """The third comparison's additions (README): (a) a set with more than 5% of its compared foe slots lost as
    target-not-reproduced is not evaluable and does not pass; (b) the #406 rule, a Serious member with 0 SP."""

    def test_a_set_over_the_lost_limit_is_not_evaluable_and_does_not_pass(self):
        self.assertEqual(check.verdict(0.001, 0.002, {"slots-compared": 100, "slots-lost": 5}),
                         (True, 0.05, True, True))
        self.assertEqual(check.verdict(0.001, 0.002, {"slots-compared": 100, "slots-lost": 6}),
                         (True, 0.06, False, False))
        self.assertEqual(check.verdict(0.05, 0.01, {"slots-compared": 100, "slots-lost": 0}), (False, 0.0, True, False))
        self.assertEqual(check.verdict(0.05, 0.01, {}), (False, 0.0, True, False))  # nothing compared: nothing lost
        self.assertEqual(check.verdict(None, None, {}), (None, 0.0, True, None))

    def test_the_406_rule_counts_serious_members_with_zero_stat_points(self):
        head = "Pikachu @ Light Ball\nAbility: Static\nLevel: 50\n"
        serious = head + "Serious Nature\n- Thunderbolt\n"
        no_nature = head + "EVs: 0 HP / 0 Atk\n- Thunderbolt\n"
        trained = head + "EVs: 2 HP\nSerious Nature\n- Thunderbolt\n"
        timid = head + "Timid Nature\n- Thunderbolt\n"
        self.assertEqual(check.zero_sp_serious("\n".join([serious, no_nature, trained, timid])), 2)
        self.assertEqual(check.zero_sp_serious(trained + "\n" + timid), 0)


if __name__ == "__main__":
    unittest.main()
