"""duoforge.python.data: the data API binding (decisions 0015 and 0020) against known rows of the pinned data.

The C test duoforge.data.static compares every row with the generated tables; this checks the binding: that the
wrappers pass their arguments, that every field of a struct reaches the dict under its own name (the dtypes are pinned
to the C layout by duoforge.python.layout), that errors raise with the C status name, and that nothing is computed
in Python (the values are the C library's, so the same row read twice, or through two contexts, is the same dict).
"""
import unittest

import duoforge
from duoforge import _layout, data


def _pool():
    return duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"])


class DataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = _pool()
        cls.closure = duoforge.Context()

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()
        cls.closure.close()

    def test_counts_names_and_find_round_trip(self):
        for table in (data.TABLE_SPECIES, data.TABLE_MOVE, data.TABLE_ITEM, data.TABLE_ABILITY, data.TABLE_NATURE):
            n = data.count(self.pool, table)
            self.assertGreater(n, 0)
            for ident in (0, n // 2, n - 1):
                self.assertEqual(data.find(self.pool, table, data.name(self.pool, table, ident)), ident)
        self.assertEqual(data.count(self.pool, data.TABLE_NATURE), 25)
        self.assertLess(data.count(self.closure, data.TABLE_MOVE), data.count(self.pool, data.TABLE_MOVE))
        self.assertEqual(data.name(self.pool, data.TABLE_MOVE, data.find(self.pool, data.TABLE_MOVE, "closecombat")),
                         "closecombat")

    def test_supported_and_forme_info_and_forme_moves(self):
        staraptor = data.find(self.pool, data.TABLE_SPECIES, "staraptor")
        info = data.forme_info(self.pool, staraptor)
        self.assertEqual(info["is_mega"], 0)
        self.assertEqual(info["setup_legal"], 1)
        self.assertEqual(info["base_species"], staraptor)
        self.assertEqual(info["mega_species"], data.find(self.pool, data.TABLE_SPECIES, "staraptormega"))
        self.assertEqual(len(info["abilities"]), 3)
        moves = data.forme_moves(self.pool, staraptor)
        self.assertEqual(len(moves), info["move_count"])
        self.assertEqual(moves, sorted(moves))
        self.assertIn(data.find(self.pool, data.TABLE_MOVE, "bravebird"), moves)
        self.assertTrue(data.supported(self.pool, data.TABLE_MOVE, data.find(self.pool, data.TABLE_MOVE, "closecombat")))
        self.assertFalse(data.supported(self.pool, data.TABLE_MOVE, data.find(self.pool, data.TABLE_MOVE, "struggle")))

    def test_the_megas_of_a_species_one_per_stone(self):
        """duoforge_data_mega_count and _at: the pairs that the single link of forme_info does not give."""
        find = lambda table, row: data.find(self.pool, table, row)
        charizard = find(data.TABLE_SPECIES, "charizard")
        self.assertEqual(data.mega_count(self.pool, charizard), 2)
        y, x = data.mega_at(self.pool, charizard, 0), data.mega_at(self.pool, charizard, 1)
        self.assertEqual((y["stone"], y["mega_species"]), (find(data.TABLE_ITEM, "charizarditey"),
                                                          find(data.TABLE_SPECIES, "charizardmegay")))
        self.assertEqual((x["stone"], x["mega_species"]), (find(data.TABLE_ITEM, "charizarditex"),
                                                          find(data.TABLE_SPECIES, "charizardmegax")))
        self.assertEqual(x["base_species"], charizard)
        self.assertEqual(data.forme_info(self.pool, charizard)["mega_species"], y["mega_species"])  # the old link: the first
        # one stone, two species: each has its own Mega
        stone = find(data.TABLE_ITEM, "meowsticite")
        self.assertEqual(data.mega_at(self.pool, find(data.TABLE_SPECIES, "meowstic"), 0)["stone"], stone)
        self.assertEqual(data.mega_at(self.pool, find(data.TABLE_SPECIES, "meowsticf"), 0)["mega_species"],
                         find(data.TABLE_SPECIES, "meowsticfmega"))
        # the closure has one Mega of Charizard; a Mega forme and a species without a Mega have none
        self.assertEqual(data.mega_count(self.closure, data.find(self.closure, data.TABLE_SPECIES, "charizard")), 1)
        self.assertEqual(data.mega_count(self.pool, find(data.TABLE_SPECIES, "charizardmegax")), 0)
        with self.assertRaises(duoforge.DuoforgeError):
            data.mega_at(self.pool, charizard, 2)

    def test_forme_static(self):
        rillaboom = data.forme_static(self.pool, data.find(self.pool, data.TABLE_SPECIES, "rillaboom"))
        self.assertEqual(rillaboom, {"types": (_layout.CONSTANTS["DUOFORGE_TYPE_GRASS"], data.NONE),
                                     "base_stats": (100, 125, 90, 60, 70, 85), "weight_hg": 900,
                                     "default_ability": rillaboom["default_ability"], "is_mega": 0})
        self.assertEqual(data.name(self.pool, data.TABLE_ABILITY, rillaboom["default_ability"]), "grassysurge")
        mega = data.forme_static(self.pool, data.find(self.pool, data.TABLE_SPECIES, "staraptormega"))
        self.assertEqual(mega["is_mega"], 1)
        self.assertEqual(data.forme_static(self.pool, 0), data.forme_static(self.closure, 0))  # a pure function of the id

    def test_move_static(self):
        mv = data.move_static(self.pool, data.find(self.pool, data.TABLE_MOVE, "closecombat"))
        c = _layout.CONSTANTS
        self.assertEqual((mv["type"], mv["category"], mv["base_power"], mv["accuracy"], mv["priority"]),
                         (c["DUOFORGE_TYPE_FIGHTING"], c["DUOFORGE_MOVE_CATEGORY_PHYSICAL"], 120, 100, 0))
        self.assertEqual(mv["hits_min"], 1)
        self.assertEqual(mv["hits_max"], 1)
        self.assertTrue(mv["flags"] & c["DUOFORGE_MOVE_STATIC_FLAG_CONTACT"])
        self.assertEqual(data.move_static(self.pool, data.find(self.pool, data.TABLE_MOVE, "trickroom"))["priority"], -7)
        seed = data.move_static(self.pool, data.find(self.pool, data.TABLE_MOVE, "bulletseed"))
        self.assertEqual((seed["hits_min"], seed["hits_max"]), (2, 5))
        self.assertTrue(seed["flags"] & c["DUOFORGE_MOVE_STATIC_FLAG_BULLET"])
        low = data.move_static(self.pool, data.find(self.pool, data.TABLE_MOVE, "lowkick"))
        self.assertTrue(low["flags"] & c["DUOFORGE_MOVE_STATIC_FLAG_POWER_RULE"])
        # lockedmove (step G56): the moves whose use locks the user for 2-3 turns; the live tracker hides a foe's locked
        # slot after one of them like the engine's observation (view audit 2026-10-10), so it reads this flag, not names.
        for name, locked in (("outrage", True), ("thrash", True), ("petaldance", True), ("closecombat", False),
                             ("earthquake", False)):
            flags = data.move_static(self.pool, data.find(self.pool, data.TABLE_MOVE, name))["flags"]
            self.assertEqual(bool(flags & c["DUOFORGE_MOVE_STATIC_FLAG_LOCKED_MOVE"]), locked, name)
        self.assertEqual(data.move_static(self.pool, data.find(self.pool, data.TABLE_MOVE, "earthquake"))["target_class"],
                         11)
        self.assertEqual(tuple(sorted(mv)), tuple(sorted(_layout.MOVE_STATIC.names)))

    def test_item_ability_nature_and_type_effect(self):
        c = _layout.CONSTANTS
        berry = data.item_static(self.pool, data.find(self.pool, data.TABLE_ITEM, "occaberry"))
        self.assertEqual((berry["family"], berry["family_type"]),
                         (c["DUOFORGE_ITEM_FAMILY_RESIST_BERRY"], c["DUOFORGE_TYPE_FIRE"]))
        stone = data.item_static(self.pool, data.find(self.pool, data.TABLE_ITEM, "staraptite"))
        self.assertEqual((stone["is_mega_stone"], stone["mega_species"]),
                         (1, data.find(self.pool, data.TABLE_SPECIES, "staraptormega")))
        plain = data.item_static(self.pool, data.find(self.pool, data.TABLE_ITEM, "leftovers"))
        self.assertEqual((plain["family"], plain["family_type"], plain["mega_species"]), (0, data.NONE, data.NONE))
        rain = data.ability_static(self.pool, data.find(self.pool, data.TABLE_ABILITY, "drizzle"))
        self.assertEqual((rain["family"], rain["family_param"]),
                         (c["DUOFORGE_ABILITY_FAMILY_WEATHER_SETTER"], c["DUOFORGE_WEATHER_RAIN"]))
        self.assertEqual(data.nature_static(self.pool, data.find(self.pool, data.TABLE_NATURE, "adamant")),
                         {"raised_stat": 1, "lowered_stat": 3})
        self.assertEqual(data.nature_static(self.closure, data.find(self.closure, data.TABLE_NATURE, "hardy")),
                         {"raised_stat": data.NONE, "lowered_stat": data.NONE})
        t = c
        self.assertEqual(data.type_effect(self.pool, t["DUOFORGE_TYPE_FIRE"], t["DUOFORGE_TYPE_GRASS"]), (2, 1))
        self.assertEqual(data.type_effect(self.pool, t["DUOFORGE_TYPE_GRASS"], t["DUOFORGE_TYPE_FIRE"]), (1, 2))
        self.assertEqual(data.type_effect(self.closure, t["DUOFORGE_TYPE_NORMAL"], t["DUOFORGE_TYPE_GHOST"]), (0, 1))
        self.assertEqual(data.type_effect(self.pool, t["DUOFORGE_TYPE_NORMAL"], t["DUOFORGE_TYPE_NORMAL"]), (1, 1))

    def test_errors_raise_with_the_c_status_name(self):
        n = data.count(self.pool, data.TABLE_MOVE)
        with self.assertRaises(duoforge.DuoforgeError) as caught:
            data.move_static(self.pool, n)
        self.assertEqual(str(caught.exception), "DUOFORGE_E_INVALID_ARGUMENT")
        with self.assertRaises(duoforge.DuoforgeError):
            data.find(self.pool, data.TABLE_MOVE, "notamove")
        with self.assertRaises(duoforge.DuoforgeError):
            data.type_effect(self.pool, 18, 0)
        with self.assertRaises(duoforge.DuoforgeError):
            data.count(self.pool, 0)
        with self.assertRaises(ValueError):
            data.forme_static(self.pool, -1)
        # a context under the CLOSURE kind has the closure's rows only
        with self.assertRaises(duoforge.DuoforgeError):
            data.move_static(self.closure, n - 1)

    def test_a_closed_context_is_refused(self):
        ctx = duoforge.Context()
        ctx.close()
        with self.assertRaises(ValueError):
            data.count(ctx, data.TABLE_MOVE)

    def test_the_synthetic_kind_has_no_tables(self):
        # the Python Context builds only data kinds with tables; the layout names the constant for the tests of the C side
        self.assertEqual(_layout.CONSTANTS["DUOFORGE_DATA_KIND_SYNTHETIC"], 1)


if __name__ == "__main__":
    unittest.main()
