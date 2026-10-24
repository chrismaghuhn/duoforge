<a id="5bn"></a>

# 5bn. G71, Cute Charm and Attract

- Area: abilities
- Step: G71
- Tests: -

5bn. **G71, Cute Charm and Attract** (lane B batch 5; decision 0034, owner-approved 2026-10-10). Pins: Cute Charm `data/abilities.ts:798-810`, the attract condition `data/moves.ts:706-761` (onStart with the opposite-gender test at line 719, onUpdate at 737-740, onBeforeMove at 743-749, onEnd at 750-751). Marked: the ability Cute Charm and the volatile Attract (the move Attract and Destiny Knot stay unmarked). Public: volatile 11 (VOLATILE_START and VOLATILE_END), cause 36 (CANT of the stopped move), the presence bit `DUOFORGE_POSITION_EXT_ATTRACT` = 0x08000000 (bit 27, an encoder 6 reserve bit, decision 0050). Internal: the source member's code in the rev 5 reserve bytes 0 to 3 (`1 + side * 6 + roster index`, the state check in `dfi_attract_byte_ok`), draw sites 24 (Cute Charm's 3/10) and 25 (Attract's 1/2 at BeforeMove priority 2). The Oblivious immunity and cure and the Mental Herb cure are extensions of the G47 rows. Evidence and triggers: 13 recorded battles and a 600-battle campaign (seed 9720000, kept traces): PASS 600, DIVERGENCE 0 after the shown-faint fix of commit 824a9aa7. Triggers: Cute Charm draws 2698, infatuations 453, Attract checks 383 (cant 189), silent ends 241, Mental Herb cures 62. Mutants: 11 of 12 valid caught, M12 equivalent. Full text: docs/decisions/0034-cute-charm-attract.md.

## Support

**Cute Charm and Attract (step G71, decision 0034, entry 5bn; the source is public, step G87, decision 0080, entry 5bv)**: Cute Charm infatuates an attacker of the opposite gender on a contact hit (3/10); Attract stops the move half the time (1/2), ends silently when its source leaves, and is cured by Oblivious (immunity and cure) and Mental Herb. The view shows the presence and the source position for both players (volatiles2 bits 12-13, feature 53); a from-view world copies the source and is checked (E_MALFORMED otherwise). Only Cute Charm starts it in the pool; the move Attract and Destiny Knot are unmarked. Recorded POOL battles (`g71_*`) and the corpus of all committed pool battles (`duoforge.moves.attract_source_view`).
