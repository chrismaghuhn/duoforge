# 0080 - Attract's source is public (step G87, lane B)

Status: accepted by HauptSession and the lead (2026-10-11). Part of decision 0015 (the content expansion, lane B), entry 5bv. Builds
on decision 0034 (Cute Charm and Attract, entry 5bn), decision 0050 (encoder 6, the reserve columns) and decision 0023 (the public view).

## The problem

Attract's presence has been public since step G71 (the presence bit `DUOFORGE_POSITION_EXT_ATTRACT`, bit 27). The source of the
infatuation is public too: the `-start` line names it (`[of] Y`, Cute Charm's `[from] ability: Cute Charm|[of] Y`), and every
`-activate|X|move: Attract|[of] Y` line repeats it. But the view did not carry the source's flat position, and a from-view world
with an infatuated occupant was refused outright (E_UNSUPPORTED, decision 0034's lead's option B), which refused 42 decision points of
the committed pool corpus.

## The values (`include/duoforge/duoforge.h`)

- `DUOFORGE_POSITION_EXT2_ATTRACT_SOURCE_LO` = `0x00001000u` and `DUOFORGE_POSITION_EXT2_ATTRACT_SOURCE_HI` = `0x00002000u`: bits 12 and
  13 of `duoforge_observation_ext.volatiles2[side][position]`. Bit 12 is the low bit. Together they hold the flat position (0 to 3) of
  the infatuated occupant's source: `flat = side * DUOFORGE_ACTIVE_PER_SIDE + position`, the same numbering as the state.
- Valid **only with `DUOFORGE_POSITION_EXT_ATTRACT`** on the same position. Otherwise both bits are 0.
- Feature **53**: `DUOFORGE_VIEWEXT_FEATURE_ATTRACT_SOURCE`, the feature of this field. It sits in the lane block of HauptSession's
  numbering (53 to 58). `DUOFORGE_VIEWEXT_RESERVE_OWN` lists `X(VOLATILES2, 12u, ATTRACT_SOURCE)` and `X(VOLATILES2, 13u, ATTRACT_SOURCE)`:
  one entry per bit, because the C macro compares the bit number exactly (a combined `12u|13u` would gate bit 13 only). Encoders 1 to 5
  refuse the bits (as every reserve bit); encoder 6 shows them under the feature, and `support_manifest.c` marks the feature supported.
- Visibility: **both players**. The Attract line is public, so its source is public too.

## The derivation

The observation computes the bits from the engine's state, not from the protocol: `tail.attract_source[flat]` holds the source member's
code (`1 + side * 6 + roster index`, decision 0034), and `dfi_attract_source_flat` (`src/combat/turn.c`) finds the source's position among
its side's occupants. The state check (`dfi_attract_byte_ok`, `src/state/invariants.c`) guarantees that the source stands on the field, so
the lookup always succeeds; a failure is `DUOFORGE_E_INVARIANT`.

The protocol gives the same position, so a live record builds the same bits: the `-start|X|Attract|[from] ability: Cute Charm|[of] Y` line
gives the flat position of Y; the `-activate|X|move: Attract|[of] Y` line repeats it; a `-end|X|Attract` line (visible or `[silent]`) or the
holder's switch-out ends it, and the bits go with the presence bit. Only Cute Charm starts Attract in the pool (decision 0034), so the
`[of]` form is the only one reachable; a future Attract move whose `-start` has no `[of]` needs its own rule before it is marked.

## The from-view world (replaces the refusal)

The view already carries the source's member code: the rev 5 reserve bytes are public state (a source is always active, so its roster
index is the occupant the view shows). `duoforge_battle_from_view` therefore needs **no mapping**: the roster index of the foe's members is
the view's own index (the open team sheet makes it public, decision 0023), and the world copies the byte. Each nonzero byte is checked
(`dfi_view_attract_ok`, `src/state/view.c`) and an inconsistent view is `DUOFORGE_E_MALFORMED`:

- the code is 1 to 12;
- the infatuated occupant is present and below its side's member count;
- the source is below its side's member count;
- the source is an active occupant of the view (on either side);
- the source is not the holder itself.

The world's own checks (the state check, and the round trip `public(world) == view`) stay as they were. The refusal of an infatuated
world is gone; the explicit refusals of inconsistent views are the new ones.

## Ally Switch (lane A's G80, open)

The byte is indexed by the holder's flat position (`tail.attract_source[flat]`), while the member code names the source. When Ally Switch lands
(lane A), the swap of two positions must swap the two holder bytes too, with a test ("whoever lands last", agreed with HauptSession). Until
then Ally Switch is unmarked, so the swap cannot occur, and the bits follow the source automatically: they are computed from the member's
current position at every observation.

## Python (the encoder and the tracker)

- `python/duoforge/features.py` names the two bits under the feature `ATTRACT_SOURCE` (the family's exceptions, as `_VOLATILE_FEATURE`
  for the volatile bits).
- `python/duoforge_live` (HauptSession, #393) folds the source per infatuated position from the Attract lines above. Whether its record
  sets volatiles2 bits 12-13 from that fold is for HauptSession to confirm; it is not changed by this step.

## The evidence

- `tests/test_pool_g87.c` (white-box): the bits per position for both players (both infatuated occupants of the recorded battle; the
  positions without infatuation carry no bits); the pair invariant (a benched source is refused by the check and by the observation); the
  from-view world copies the byte; the tampered views (the holder itself, a benched member, a code past the roster, an empty holder) are
  E_MALFORMED.
- The corpus test replays every committed pool battle step by step (as `test_conformance.c`). At every decision point with an infatuated
  occupant, both players' views are built into worlds, and the test checks `public(world) == view`, the world's source bytes equal the
  engine's, and the observation's Attract bits of the world equal the engine's. Measured: 849 battles replayed to the end, 22 decision points
  with an infatuated occupant, 21 worlds per player (42 in all), 0 mismatches. One view per player is refused at the same point for the
  older PIVOT rule (no public move volatile, E_UNSUPPORTED, no cause bit); that is not Attract.
- `tests/test_pool_g71.c` now expects the consistent infatuated world to build (it was the refusal's test).
- Python: `test_encoder6` (the own feature of the two bits, the feature's bit in the version-6 mask, the header list).

## Triggers (the trigger rule)

The differential driver (`tools/reference/diff_driver.py`) does not call `duoforge_battle_from_view`, so it cannot count these builds.
The engine-only check (python API, no Showdown, script not committed) measures the rule: seed 9720000, the G71 Cute Charm teams,
36 environments, 275 battles to the end. At 151 decision points with an infatuated occupant, both players' views were taken: 111
worlds per player were built, all with the engine's attract_source bytes and public(world) == view (0 deviations); 40 per player were
refused by public() for the older PIVOT rule. Two engine step refusals (E_INVARIANT, the pre-state valid) are reported separately:
one with an Attract source on flat 0, one without any Attract.
