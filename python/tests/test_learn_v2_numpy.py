"""duoforge.python.learn_v2_numpy: the NumPy parts of Learner v2 (decision 0017).

Column groups and the host id check of model v2, the team pool's weighted
pairings, the league state machine, schedules, the evaluation suite and
the per-team ladder fits. The JAX parts are in test_learn_v2.py.
"""
import unittest

import numpy as np

from duoforge import features
from duoforge_learn import columns


class ColumnsTest(unittest.TestCase):
    def test_groups_partition_the_observation(self):
        cols = columns.columns()
        parts = [cols.glob, cols.side, cols.position, cols.occupant, cols.member, cols.species, cols.item,
                 cols.ability, cols.nature, cols.moves, cols.pp, cols.move_count, cols.present]
        every = np.concatenate([p.reshape(-1) for p in parts])
        self.assertEqual(sorted(every.tolist()), list(range(features.OBS_SIZE)))
        names = features.FEATURE_NAMES
        self.assertTrue(all(names[i].startswith("global.") for i in cols.glob))
        self.assertTrue(all(".occupant." in names[i] for i in cols.occupant.reshape(-1)))
        self.assertEqual(names[cols.species[1, 3]], "foe.member3.species")
        self.assertEqual(names[cols.moves[0, 2, 1]], "own.member2.move1")
        self.assertEqual(names[cols.position[1, 0, 0]], "foe.pos0.stage.atk")
        self.assertEqual(cols.position.shape, (2, 2, 17))
        self.assertEqual([features.SLOT_FEATURE_NAMES[i] for i in cols.slot_move], ["move_slot"])
        self.assertEqual([features.SLOT_FEATURE_NAMES[i] for i in cols.slot_reserve], ["reserve"])
        self.assertEqual(cols.slot_scalar.shape, (10,))

    def test_unknown_column_name_is_refused(self):
        with self.assertRaisesRegex(ValueError, "own.member0.weight"):
            columns.columns(features.FEATURE_NAMES + ("own.member0.weight",))

    def test_check_ids_refuses_an_id_at_capacity(self):
        cols = columns.columns()
        obs = np.zeros((2, features.OBS_SIZE), dtype=np.float32)
        caps = {"species": 1024, "move": 1024, "item": 256, "ability": 256, "nature": 25}
        obs[1, cols.species[0, 0]] = np.float32(1023 / 65535)
        columns.check_ids(obs, cols, caps)
        obs[1, cols.species[0, 0]] = np.float32(1024 / 65535)
        with self.assertRaisesRegex(ValueError, "species id 1024 is outside the model's capacity 1024"):
            columns.check_ids(obs, cols, caps)


if __name__ == "__main__":
    unittest.main()
