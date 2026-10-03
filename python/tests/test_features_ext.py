"""duoforge.python.features_ext: encoder 3, the block of decision 0018
section 10.

The first 607 columns are encoder 2's, byte for byte; the 235 columns of the
block follow the 0018 templates, each column belongs to one feature bit, and
each of the 40 bits has columns. A clear bit of ext_supported zeros its
columns. A new base value (Sand, Snow, Electric, Misty, Tox) needs its bit
and then shows in its own column with an all-zero old group; a record
feature needs the extension records; a bit the library does not support,
records of another boundary and record values outside their documented
ranges raise. as_encoder gives encoders 1 and 2 their 607 columns and
refuses the new values; slots_as_encoder refuses Recharge (move slot 5,
encoded 5/4) for them. A POOL battle's records come from Batch.observe_ext
and encode with the library's mask at every step.
"""
import os
import unittest

import numpy as np

import duoforge
from duoforge import _layout, features, teams

C = _layout.CONSTANTS
SEED = 0x2026100300000003
ENVS = 4
COL = {name: i for i, name in enumerate(features.FEATURE_NAMES)}
ALL = (1 << C["DUOFORGE_VIEWEXT_FEATURE_COUNT"]) - 1
BIT = {name[len("DUOFORGE_VIEWEXT_FEATURE_"):]: v for name, v in C.items()
       if name.startswith("DUOFORGE_VIEWEXT_FEATURE_") and name != "DUOFORGE_VIEWEXT_FEATURE_COUNT"}
BASE_BITS = ("WEATHER_SAND", "WEATHER_SNOW", "TERRAIN_ELECTRIC", "TERRAIN_MISTY", "AILMENT_TOX")
CAMPAIGN = os.path.join("tools", "cloud", "aws_fuzz", "campaigns", "weather-sand-snow")
_STATUS = ("NONE", "BURN", "FREEZE", "PARALYSIS", "SLEEP", "POISON")
VOLATILES = ("substitute", "taunt", "imprison", "leech_seed", "yawn", "focus_energy", "dragon_cheer", "must_recharge",
             "partial_trap", "glaive_rush", "destiny_bond", "curse", "no_retreat", "salt_cure", "charge", "heal_block",
             "throat_chop", "rage_powder", "type_changed", "illusion_up")


def _mask(*names):
    return sum(1 << BIT[n] for n in names)


def _turn_scene(ctx):
    """(observations (2E,), domains (2E,)) of the reference battles at their first turn."""
    with duoforge.Batch(ctx, duoforge.reference_setups(list(range(ENVS))), 1, SEED) as batch:
        policy = duoforge.RandomPolicy(SEED, ENVS)
        policy.start_episodes(np.arange(ENVS), np.zeros(ENVS, dtype=np.uint64))
        batch.query_factored()
        batch.step_factored(policy.choose_factored(batch))
        batch.query_factored()
        return batch.observations.reshape(-1).copy(), batch.domains.reshape(-1).copy()


def _records(observations, supported=ALL):
    """Extension records of revision 1 for the observations, every field set:
    gravity 3; side s: Aurora Veil 5 - s, Stealth Rock, Spikes 2, Toxic Spikes
    1, Sticky Web, both guards; position k of side s: volatiles bit s * 2 + k
    and MUST_RECHARGE, ability_now 17 + k, type_now (6, 0), encore slot 2,
    disable slot 4, stockpile 2, perish 3; member r: forme 0x1234 + r, item_now
    10 (r even) or ITEM_NOW_NONE (r odd)."""
    ext = np.zeros(observations.shape, dtype=_layout.OBSERVATION_EXT)
    ext["revision"] = C["DUOFORGE_OBSERVATION_EXT_REVISION"]
    ext["player"] = observations["player"]
    ext["epoch"] = observations["epoch"]
    ext["supported"] = supported
    ext["field"]["gravity_turns"] = 3
    sides = ext["sides"]
    for s in range(2):
        sides["aurora_veil_turns"][:, s] = 5 - s
        sides["stealth_rock"][:, s] = 1
        sides["spikes"][:, s] = 2
        sides["toxic_spikes"][:, s] = 1
        sides["sticky_web"][:, s] = 1
        sides["guard_flags"][:, s] = C["DUOFORGE_SIDE_GUARD_WIDE_GUARD"] | C["DUOFORGE_SIDE_GUARD_QUICK_GUARD"]
        for k in range(2):
            pos = sides["positions"]
            pos["volatiles"][:, s, k] = (1 << (s * 2 + k)) | C["DUOFORGE_POSITION_EXT_MUST_RECHARGE"]
            pos["ability_now"][:, s, k] = 17 + k
            pos["type_now"][:, s, k] = (6, 0)
            pos["encore_slot"][:, s, k] = 2
            pos["disable_slot"][:, s, k] = 4
            pos["stockpile"][:, s, k] = 2
            pos["perish"][:, s, k] = 3
        for r in range(_layout.MAX_ROSTER):
            sides["members"]["forme"][:, s, r] = 0x1234 + r
            sides["members"]["item_now"][:, s, r] = 10 if r % 2 == 0 else C["DUOFORGE_ITEM_NOW_NONE"]
    ext["sides"] = sides
    return ext


def _with_all_volatiles(sides):
    """sides with every volatiles bit set at every position."""
    sides = sides.copy()
    sides["positions"]["volatiles"] = (1 << len(VOLATILES)) - 1
    return sides


def _side_name(observation, side):
    """"own" or "foe": the absolute side from the observation's viewer."""
    return "own" if side == int(observation["player"]) else "foe"


class FeaturesExtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context()
        cls.obs, cls.domains = _turn_scene(cls.ctx)

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def test_layout_appends_the_block(self):
        self.assertEqual((features.ENCODER, features.ENCODERS), (3, (1, 2, 3)))
        self.assertEqual((features.BASE_OBS_SIZE, features.EXT_SIZE, features.OBS_SIZE), (607, 235, 842))
        self.assertEqual(len(set(features.FEATURE_NAMES)), 842)
        self.assertEqual([features.obs_size(v) for v in (1, 2, 3)], [607, 607, 842])
        self.assertEqual(features.feature_names(3), features.FEATURE_NAMES)
        self.assertEqual(features.feature_names(2), features.FEATURE_NAMES[:607])
        self.assertEqual(features.feature_names(1), features.FEATURE_NAMES[:607])
        ext = features.FEATURE_NAMES[607:]
        self.assertEqual(ext[:5], ("ext.global.weather_sand", "ext.global.weather_snow", "ext.global.terrain_electric",
                                   "ext.global.terrain_misty", "ext.global.gravity_turns"))
        side = ("aurora_veil_turns", "stealth_rock", "spikes", "toxic_spikes", "sticky_web", "wide_guard", "quick_guard")
        self.assertEqual(ext[5:12], tuple(f"ext.own.{n}" for n in side))
        self.assertEqual(ext[5 + 115:12 + 115], tuple(f"ext.foe.{n}" for n in side))
        position = ([f"volatile.{n}" for n in VOLATILES] + ["encore.none"] + [f"encore.slot{k}" for k in range(4)]
                    + ["disable.none"] + [f"disable.slot{k}" for k in range(4)]
                    + ["stockpile", "perish", "ability_changed", "ability_now", "type_now0", "type_now1"])
        self.assertEqual(ext[12:48], tuple(f"ext.own.pos0.{n}" for n in position))
        self.assertEqual(ext[48:84], tuple(f"ext.own.pos1.{n}" for n in position))
        member = ("tox", "forme_changed", "forme", "item_changed", "item_removed", "item_now")
        self.assertEqual(ext[84:90], tuple(f"ext.own.mem0.{n}" for n in member))
        self.assertEqual(ext[-6:], tuple(f"ext.foe.mem5.{n}" for n in member))

    def test_every_column_has_one_feature_bit(self):
        bits = features.EXT_COLUMN_FEATURES
        self.assertEqual(bits.shape, (features.EXT_SIZE,))
        self.assertEqual(set(bits.tolist()), set(range(C["DUOFORGE_VIEWEXT_FEATURE_COUNT"])))
        want = {"ext.global.weather_sand": "WEATHER_SAND", "ext.global.terrain_misty": "TERRAIN_MISTY",
                "ext.global.gravity_turns": "GRAVITY", "ext.foe.aurora_veil_turns": "AURORA_VEIL",
                "ext.own.quick_guard": "QUICK_GUARD", "ext.own.pos1.volatile.must_recharge": "MUST_RECHARGE",
                "ext.foe.pos0.volatile.type_changed": "TYPE_CHANGE", "ext.own.pos0.volatile.illusion_up": "ILLUSION",
                "ext.own.pos0.encore.none": "ENCORE", "ext.foe.pos1.disable.slot3": "DISABLE",
                "ext.own.pos0.ability_now": "ABILITY_CHANGE", "ext.own.pos0.type_now1": "TYPE_CHANGE",
                "ext.own.pos0.perish": "PERISH", "ext.foe.mem3.tox": "AILMENT_TOX", "ext.own.mem0.forme": "FORME_CHANGE",
                "ext.own.mem5.item_removed": "ITEM_CHANGE"}
        for name, feature in want.items():
            self.assertEqual(int(bits[COL[name] - features.BASE_OBS_SIZE]), BIT[feature], name)
        self.assertEqual(features.BASE_VALUE_FEATURES, _mask(*BASE_BITS))

    def test_closure_battles_keep_encoder_2_and_a_zero_block(self):
        from python.tests import _reference_features as reference
        policy = duoforge.RandomPolicy(SEED, ENVS)
        policy.start_episodes(np.arange(ENVS), np.zeros(ENVS, dtype=np.uint64))
        compared = 0
        with duoforge.Batch(self.ctx, duoforge.reference_setups(list(range(ENVS))), 1, SEED) as batch:
            for _ in range(40):
                batch.query_factored()
                ext = batch.observe_ext()
                self.assertEqual(ext.shape, (ENVS, 2))
                self.assertFalse(ext.view(np.uint8).any())  # not a POOL kind: all zero
                ob, d = batch.observations.reshape(-1), batch.domains.reshape(-1)
                for mask in (0, ALL):
                    obs, slots, pairs = features.encode_batch(ob, d, ext.reshape(-1), mask)
                    self.assertEqual(obs.shape, (2 * ENVS, 842))
                    self.assertFalse(obs[:, 607:].any())
                    for n in range(ob.shape[0]):
                        want = reference.encode(ob[n], d[n])
                        self.assertTrue(np.array_equal(obs[n, :607], want[0]))
                        self.assertTrue(np.array_equal(slots[n], want[1]))
                        self.assertTrue(np.array_equal(pairs[n], want[2]))
                        compared += 1
                if not (batch.requests["requested"] != 0).any():
                    break
                batch.step_factored(policy.choose_factored(batch))
        self.assertGreater(compared, 200)

    def test_record_columns_hold_the_fields(self):
        ob, d = self.obs, self.domains
        part = features.encode_batch(ob, d, _records(ob), ALL)[0]
        for n in range(ob.shape[0]):
            row = part[n]
            self.assertEqual(row[COL["ext.global.gravity_turns"]], np.float32(3 / 5))
            for s in range(2):
                o = _side_name(ob[n], s)
                self.assertEqual(row[COL[f"ext.{o}.aurora_veil_turns"]], np.float32((5 - s) / 8))
                self.assertEqual(row[COL[f"ext.{o}.stealth_rock"]], 1.0)
                self.assertEqual(row[COL[f"ext.{o}.spikes"]], np.float32(2 / 3))
                self.assertEqual(row[COL[f"ext.{o}.toxic_spikes"]], 0.5)
                self.assertEqual(row[COL[f"ext.{o}.sticky_web"]], 1.0)
                self.assertEqual(row[COL[f"ext.{o}.wide_guard"]], 1.0)
                self.assertEqual(row[COL[f"ext.{o}.quick_guard"]], 1.0)
                for k in range(2):
                    p = f"ext.{o}.pos{k}."
                    on = {name for name in COL if name.startswith(p + "volatile.") and row[COL[name]] != 0}
                    self.assertEqual(on, {p + "volatile." + VOLATILES[s * 2 + k], p + "volatile.must_recharge"})
                    slots = ("none", "slot0", "slot1", "slot2", "slot3")
                    self.assertEqual([row[COL[p + f"encore.{x}"]] for x in slots], [0, 0, 1, 0, 0])  # slot 2 - 1
                    self.assertEqual([row[COL[p + f"disable.{x}"]] for x in slots], [0, 0, 0, 0, 1])
                    self.assertEqual(row[COL[p + "stockpile"]], np.float32(2 / 3))
                    self.assertEqual(row[COL[p + "perish"]], 1.0)
                    self.assertEqual(row[COL[p + "ability_changed"]], 1.0)
                    self.assertEqual(row[COL[p + "ability_now"]], np.float32((17 + k) / 255))
                    self.assertEqual((row[COL[p + "type_now0"]], row[COL[p + "type_now1"]]), (np.float32(6 / 18), 0.0))
                for r in range(6):
                    m = f"ext.{o}.mem{r}."
                    self.assertEqual(row[COL[m + "forme_changed"]], 1.0)
                    self.assertEqual(row[COL[m + "forme"]], np.float32((0x1234 + r) / 65535))
                    self.assertEqual(row[COL[m + "item_changed"]], 1.0)
                    self.assertEqual(row[COL[m + "item_removed"]], float(r % 2))
                    self.assertEqual(row[COL[m + "item_now"]], np.float32(10 / 255) if r % 2 == 0 else 1.0)
                    self.assertEqual(row[COL[m + "tox"]], 0.0)
        # An empty record of revision 1: no encore and no disable (their none columns), nothing else.
        empty = np.zeros(ob.shape, dtype=_layout.OBSERVATION_EXT)
        empty["revision"], empty["player"], empty["epoch"], empty["supported"] = 1, ob["player"], ob["epoch"], ALL
        part = features.encode_batch(ob, d, empty, ALL)[0]
        on = {features.FEATURE_NAMES[i] for i in np.flatnonzero(part[0, 607:]) + 607}
        self.assertEqual(on, {f"ext.{o}.pos{k}.{g}.none" for o in ("own", "foe") for k in range(2)
                              for g in ("encore", "disable")})

    def test_a_clear_bit_zeros_its_columns(self):
        ob, d = self.obs, self.domains
        ext = _records(ob)
        ext["sides"] = _with_all_volatiles(ext["sides"])
        full = features.encode_batch(ob, d, ext, ALL)[0][:, 607:]
        bits = features.EXT_COLUMN_FEATURES
        self.assertFalse(features.encode_batch(ob, d, ext, 0)[0][:, 607:].any())
        for name, bit in BIT.items():
            if name in BASE_BITS:
                continue  # no base value in this scene: those columns are zero either way
            one = features.encode_batch(ob, d, ext, 1 << bit)[0][:, 607:]
            self.assertTrue(np.array_equal(one[:, bits == bit], full[:, bits == bit]), name)
            self.assertFalse(one[:, bits != bit].any(), name)
            self.assertTrue(full[:, bits == bit].any(), name)

    def test_new_base_values_need_their_bit(self):
        ob, d = self.obs, self.domains
        cases = (("weather", "DUOFORGE_WEATHER_SAND", "WEATHER_SAND", "ext.global.weather_sand", "global.weather."),
                 ("weather", "DUOFORGE_WEATHER_SNOW", "WEATHER_SNOW", "ext.global.weather_snow", "global.weather."),
                 ("terrain", "DUOFORGE_TERRAIN_ELECTRIC", "TERRAIN_ELECTRIC", "ext.global.terrain_electric",
                  "global.terrain."),
                 ("terrain", "DUOFORGE_TERRAIN_MISTY", "TERRAIN_MISTY", "ext.global.terrain_misty", "global.terrain."))
        for field, value, bit, column, group in cases:
            with self.subTest(value=value):
                odd = ob.copy()
                odd[field] = C[value]
                part = features.encode_batch(odd, d, None, _mask(bit))[0]
                self.assertTrue((part[:, COL[column]] == 1.0).all())
                old = [i for name, i in COL.items() if name.startswith(group) and not name.endswith("_turns")]
                self.assertEqual(len(old), 3)
                self.assertFalse(part[:, old].any())
                with self.assertRaisesRegex(ValueError, field):
                    features.encode_batch(odd, d, None, features.BASE_VALUE_FEATURES & ~_mask(bit))
        odd = ob.copy()
        odd["sides"]["members"]["status"][:, 1, 2] = C["DUOFORGE_AILMENT_TOX"]
        part = features.encode_batch(odd, d, None, _mask("AILMENT_TOX"))[0]
        for n in range(odd.shape[0]):
            o = _side_name(odd[n], 1)
            self.assertEqual(part[n, COL[f"ext.{o}.mem2.tox"]], 1.0)
            self.assertFalse(part[n, [COL[f"{o}.member2.status.{a}"] for a in _STATUS]].any())
        with self.assertRaisesRegex(ValueError, "ailment"):
            features.encode_batch(odd, d, None, 0)
        for field in ("weather", "terrain"):
            odd = ob.copy()
            odd[field] = 5
            with self.assertRaisesRegex(ValueError, field):
                features.encode_batch(odd, d, None, ALL & features.BASE_VALUE_FEATURES)

    def test_record_features_need_the_records(self):
        ob, d = self.obs, self.domains
        features.encode_batch(ob, d, None, features.BASE_VALUE_FEATURES)  # computed from the observation alone
        for name in ("AURORA_VEIL", "GRAVITY", "ENCORE", "ITEM_CHANGE"):
            with self.assertRaisesRegex(ValueError, "extension"):
                features.encode_batch(ob, d, None, _mask(name))

    def test_a_bit_the_library_does_not_support_raises(self):
        ob, d = self.obs, self.domains
        ext = _records(ob, supported=ALL & ~_mask("AURORA_VEIL"))
        features.encode_batch(ob, d, ext, ALL & ~_mask("AURORA_VEIL"))
        with self.assertRaisesRegex(ValueError, "AURORA_VEIL"):
            features.encode_batch(ob, d, ext, ALL)

    def test_masks_outside_the_feature_bits_raise(self):
        ob, d = self.obs, self.domains
        for bad in (1 << 40, -1, 1.0, True, "1", None):
            with self.assertRaisesRegex(ValueError, "ext_supported"):
                features.encode_batch(ob, d, None, bad)

    def test_records_of_another_boundary_raise(self):
        ob, d = self.obs, self.domains
        ext = _records(ob)
        with self.assertRaises(TypeError):
            features.encode_batch(ob, d, ext[:-1], ALL)
        with self.assertRaises(TypeError):
            features.encode_batch(ob, d, ext.view(np.uint8), ALL)
        for field in ("player", "epoch", "revision"):
            odd = ext.copy()
            odd[field][0] = {"player": 1 - int(ob[0]["player"]), "epoch": int(ob[0]["epoch"]) + 1, "revision": 2}[field]
            with self.assertRaises(ValueError):
                features.encode_batch(ob, d, odd, ALL)

    def test_record_values_outside_their_ranges_raise(self):
        ob, d = self.obs, self.domains
        cases = (("gravity_turns", lambda e: e["field"].__setitem__("gravity_turns", 6)),
                 ("aurora_veil_turns", lambda e: e["sides"]["aurora_veil_turns"].__setitem__((0, 1), 9)),
                 ("stealth_rock", lambda e: e["sides"]["stealth_rock"].__setitem__((0, 1), 2)),
                 ("spikes", lambda e: e["sides"]["spikes"].__setitem__((0, 1), 4)),
                 ("toxic_spikes", lambda e: e["sides"]["toxic_spikes"].__setitem__((0, 1), 3)),
                 ("sticky_web", lambda e: e["sides"]["sticky_web"].__setitem__((0, 1), 2)),
                 ("guard_flags", lambda e: e["sides"]["guard_flags"].__setitem__((0, 1), 4)),
                 ("volatiles", lambda e: e["sides"]["positions"]["volatiles"].__setitem__((0, 1, 1), 1 << 20)),
                 ("encore_slot", lambda e: e["sides"]["positions"]["encore_slot"].__setitem__((0, 1, 1), 5)),
                 ("disable_slot", lambda e: e["sides"]["positions"]["disable_slot"].__setitem__((0, 1, 1), 5)),
                 ("stockpile", lambda e: e["sides"]["positions"]["stockpile"].__setitem__((0, 1, 1), 4)),
                 ("perish", lambda e: e["sides"]["positions"]["perish"].__setitem__((0, 1, 1), 4)),
                 ("type_now", lambda e: e["sides"]["positions"]["type_now"].__setitem__((0, 1, 1, 0), 19)))
        for field, edit in cases:
            with self.subTest(field=field):
                ext = _records(ob)
                sides = ext["sides"]
                field_ext = ext["field"]
                view = {"field": field_ext, "sides": sides}
                edit(view)
                ext["field"], ext["sides"] = field_ext, sides
                with self.assertRaisesRegex(ValueError, field):
                    features.encode_batch(ob, d, ext, ALL)

    def test_as_encoder_serves_the_old_versions(self):
        from python.tests import _reference_features as reference
        ob, d = self.obs, self.domains
        part = features.encode_batch(ob, d, _records(ob), ALL)[0]
        self.assertIs(features.as_encoder(part, ob, 3), part)
        self.assertTrue(np.array_equal(features.as_encoder(part, ob, 2), part[:, :607]))
        old = features.as_encoder(part, ob, 1)
        for n in range(ob.shape[0]):
            self.assertTrue(np.array_equal(old[n], reference.encode(ob[n], d[n], encoder=1)[0]))
        for field, value, bit in (("weather", "DUOFORGE_WEATHER_SAND", "WEATHER_SAND"),
                                  ("terrain", "DUOFORGE_TERRAIN_MISTY", "TERRAIN_MISTY")):
            odd = ob.copy()
            odd[field] = C[value]
            new = features.encode_batch(odd, d, None, _mask(bit))[0]
            for version in (1, 2):
                with self.assertRaisesRegex(ValueError, field):
                    features.as_encoder(new, odd, version)
        odd = ob.copy()
        odd["sides"]["members"]["status"][:, 0, 5] = C["DUOFORGE_AILMENT_TOX"]
        new = features.encode_batch(odd, d, None, _mask("AILMENT_TOX"))[0]
        with self.assertRaisesRegex(ValueError, "ailment"):
            features.as_encoder(new, odd, 2)
        with self.assertRaises(TypeError):
            features.as_encoder(part[:, :607], ob, 2)  # only an obs_part of this encoder

    def test_recharge_is_move_slot_five(self):
        ob, d = self.obs, self.domains
        n, s, i = next((n, s, i) for n in range(d.shape[0]) for s in range(2) for i in range(int(d[n]["slot_count"][s]))
                       if int(d[n]["slots"][s, i]["kind"]) == C["DUOFORGE_SLOT_MOVE"])
        recharge = d.copy()
        recharge["slots"]["move_slot"][n, s, i] = C["DUOFORGE_MOVE_SLOT_RECHARGE"]
        recharge["slots"]["target"][n, s, i] = C["DUOFORGE_TARGET_NONE"]
        slots = features.encode_batch(ob, recharge)[1]
        self.assertEqual(slots[n, s, i, features.SLOT_FEATURE_NAMES.index("move_slot")], 1.25)
        self.assertIs(features.slots_as_encoder(slots, 3), slots)
        for version in (1, 2):
            with self.assertRaisesRegex(ValueError, "Recharge"):
                features.slots_as_encoder(slots, version)
        plain = features.encode_batch(ob, d)[1]
        self.assertIs(features.slots_as_encoder(plain, 2), plain)
        bad = d.copy()
        bad["slots"]["move_slot"][n, s, i] = C["DUOFORGE_MOVE_SLOT_RECHARGE"] + 1
        with self.assertRaisesRegex(ValueError, "move slot"):
            features.encode_batch(ob, bad)

    def test_pool_battles_encode_their_records(self):
        pool = duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"])
        try:
            sides = []
            for name in ("sand.txt", "snow.txt"):
                with open(os.path.join(CAMPAIGN, name), encoding="utf-8") as f:
                    sides.append(teams.side_setup(pool, teams.parse(f.read(), name), name))
            team_pool = teams.TeamPool.from_setups(("sand", "snow"), sides)
            setups = team_pool.setups(np.array([0, 1, 0, 1]), np.array([1, 0, 0, 1]))
            policy = duoforge.RandomPolicy(SEED, 4)
            policy.start_episodes(np.arange(4), np.zeros(4, dtype=np.uint64))
            seen = set()
            with duoforge.Batch(pool, setups, 1, SEED) as batch:
                for _ in range(60):
                    batch.query_factored()
                    ext = batch.observe_ext()
                    self.assertTrue((ext["revision"] == C["DUOFORGE_OBSERVATION_EXT_REVISION"]).all())
                    self.assertTrue((ext["player"] == batch.observations["player"]).all())
                    self.assertTrue((ext["epoch"] == batch.observations["epoch"]).all())
                    supported = int(ext["supported"][0, 0])
                    self.assertTrue((ext["supported"] == supported).all())
                    self.assertEqual(supported & _mask("WEATHER_SAND", "WEATHER_SNOW"), _mask("WEATHER_SAND", "WEATHER_SNOW"))
                    ob = batch.observations.reshape(-1)
                    part = features.encode_batch(ob, batch.domains.reshape(-1), ext.reshape(-1), supported)[0]
                    for name in ("ext.global.weather_sand", "ext.global.weather_snow"):
                        weathered = part[:, COL[name]] == 1.0
                        if weathered.any():
                            seen.add(name)
                            with self.assertRaisesRegex(ValueError, "weather"):
                                features.as_encoder(part[weathered], ob[weathered], 2)
                    if not (batch.requests["requested"] != 0).any():
                        break
                    batch.step_factored(policy.choose_factored(batch))
            self.assertEqual(seen, {"ext.global.weather_sand", "ext.global.weather_snow"})
        finally:
            pool.close()


if __name__ == "__main__":
    unittest.main()
