<a id="5cx"></a>

# 5cx. G94a, Baneful Bunker (lane A batch 6, builder H29).

- Area: moves
- Step: G94a
- Tests: -

5cx. **G94a, Baneful Bunker (lane A batch 6, builder H29).** Protect variant with `protect_kind` 3 (`DFI_PROTECT_BANEFUL_BUNKER`; `DFI_TAIL_PROTECT_KIND_MAX` 2 -> 3, approved like King's Shield). Pin: `data/moves.ts:985-1037`, the Protect condition of Spiky Shield with a poison punishment on a contact attacker: `source.trySetStatus('psn', target)` in onTryHit, through `dfi_try_status` with origin OTHER, so an immune or an already poisoned attacker gets no line (the Poison and Steel type immunity and the existing status are checked by that path). The special is `BANEFUL_BUNKER` from the generator (`G94_HANDLERS`, after G78, before UNMODELED); the generator checks the whole condition text with the punishment filled in. Manifest: `banefulbunker` marked, with Toxapex (Limber or Regenerator) as its learner. The Baneful Bunker note is 0061 on main (`docs/decisions/0061-baneful-bunker.md`); its Last Resort part is on the paused branch `chris/expansion-g94-protect-misc`. Recorded battles: `g94_bunker_poison` (Garchomp's contact Dragon Claw poisoned), `g94_bunker_noncontact` (Earthquake stopped with no poison), `g94_bunker_already_poisoned` (a second contact hit on a poisoned foe: no line). User status immunity for the turn as in the pin. **Triggers** (campaign seeds 94001 and 94002, 700 battles): uses 3266, blocks 1084 (contact 520), contact poisonings 134, immune 329, already statused 57. **Evidence:** 700 of 700 PASS; mutants 6 of 6 caught.
