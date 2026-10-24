#ifndef DUOFORGE_COMBAT_MECHANICS_DAMAGE_MODIFY_DAMAGE_H
#define DUOFORGE_COMBAT_MECHANICS_DAMAGE_MODIFY_DAMAGE_H

/* Private damage implementation (restructure step 4, damage): one phase of dfi_get_damage. Split from
 * src/combat/turn.c@dc9ce14b, lines 1606-1756 of dfi_get_damage; every line of it is unchanged, the phase only loads its inputs
 * from the stack context and stores its outputs. Included by turn.c before dfi_get_damage, so its dependencies and
 * the damage order are unchanged. */
#include "combat/mechanics/damage/context.h"

/* Phase of dfi_get_damage: the burn halving, the ModifyDamage chain with its commutation test, and Piercing Drill's bypass. */
static DFI_ALWAYS_INLINE duoforge_status
dfi_damage_modify(dfi_run *r, uint32_t user, uint32_t target, const dfi_move_data *md, uint32_t move_type,
                  dfi_damage_ctx *c)
{
    const dfi_member *a = c->a;
    const dfi_member *d = c->d;
    const bool crit = c->crit;
    const bool physical = c->physical;
    const uint32_t mod = c->mod;
    uint32_t damage = c->damage;
    bool ok = c->ok;
    /* A burned attacker's physical moves, Struggle included, do half
     * (modifyDamage, sim/battle-actions.ts:1816-1820). */
    if (physical && a->status == DFI_STATUS_BRN) {
        damage = dfi_modify(damage, 2048u);
    }
    /* ModifyDamage, one chained modifier: the attacker's Life Orb 5324/4096;
     * the target's Chople Berry (Team C, data/items.ts:1030-1053), which it
     * eats inside the calculation of a super-effective Fighting hit
     * ([-enditem] [eat], then [weaken]) for 2048/4096; then Reflect
     * (physical) or Light Screen (special) on the target's side, not against
     * a critical hit and not on the user itself, 2732/4096 in doubles.
     * The reference orders the handlers by speed: the held items by their
     * holders' speed, a screen as a side condition at 0 (comparePriority), so
     * last, or first under Trick Room, where speeds are negative. Every order
     * of these modifiers chains to the same value (checked below), so the
     * order and a speed tie between the holders decide nothing (its shuffle
     * draw is dropped, decision 0009 section 10.5). */
    const dfi_side *ds = &r->b->sides[target / 2u];
    uint32_t chain = 4096u;
    uint32_t mods = 0u; /* the ModifyDamage modifiers in the chain */
    uint32_t mlist[DFI_MODIFY_DAMAGE_MAX] = {0u}; /* and their values, for the commutation test below */
    if (dfi_holds(r->b, a, DFI_ITEM_LIFEORB)) {
        ok = dfi_chain_modify(chain, 5324u, &chain);
        if (!dfi_mods_push(mlist, &mods, 5324u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Expert Belt's onModifyDamage (step G28, data/items.ts:1901-1914): 4915/4096 when the hit is super effective
     * (typeMod > 0: the combined type effectiveness above the neutral one). */
    if (dfi_holds(r->b, a, DFI_ITEM_EXPERTBELT) && mod > DFI_BIAS6) {
        ok = ok && dfi_chain_modify(chain, 4915u, &chain);
        if (!dfi_mods_push(mlist, &mods, 4915u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* A resist berry (the RESIST_BERRY family: Chople Berry and the sixteen
     * others, decision 0015; combat/items/families.h) is eaten by a super
     * effective hit of its type, the Normal berry by any Normal hit. */
    const uint32_t berry_item = dfi_item_code(r->b, d);
    if (dfi_resist_berry_applies(berry_item, move_type, mod) && !dfi_unnerved(r->b, target) && !r->sub_hit) {
        const duoforge_status berry_status =
            dfi_resist_berry_hit(r, target, berry_item, &ok, &chain, mlist, &mods, dfi_use_item);
        if (berry_status != DUOFORGE_OK) {
            return berry_status;
        }
    }
    /* Aurora Veil (step G20, data/moves.ts:846-860) weakens both categories by the same 2732/4096 and returns without an
     * effect when the target's side has the screen of the move's category (so the two never multiply): the test is one
     * 2732 for a screen of the category or Aurora Veil. A critical hit and `infiltrates` skip all three: the move's
     * own `infiltrates` field is not modelled (the generator refuses it), and Infiltrator (step G39, data/abilities.ts:
     * 2131-2139, onModifyMove) sets it on every move of its holder. */
    if (!crit && target != user && !dfi_ability(r->b, a, DFI_ABILITY_INFILTRATOR) &&
        ((physical && ds->reflect_turns != 0u) ||
         (md->category == DFI_CATEGORY_SPECIAL && ds->light_screen_turns != 0u) ||
         r->b->tail.sides[target / 2u].aurora_veil_turns != 0u)) {
        /* `this.activePerHalf > 1 ? chainModify([2732, 4096]) : chainModify(0.5)` (data/moves.ts:859-860, 10337-10338 and
         * 14864-14865): 2048/4096 in singles (decision 0083). */
        const uint32_t screen = dfi_context_singles(r->ctx) ? 2048u : 2732u;
        ok = ok && dfi_chain_modify(chain, screen, &chain);
        if (!dfi_mods_push(mlist, &mods, screen)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Glaive Rush's onSourceModifyDamage on the target (data/moves.ts:6647-6678): chainModify(2). With a Life Orb attacker,
     * a resist berry and a screen all in the chain the four modifiers do not commute (3552 or 3551 by their order, the
     * handlers' speeds and a tie draw), a case that this build does not model. */
    if (r->b->tail.sides[target / 2u].positions[target % 2u].glaive_rush != 0u) {
        ok = ok && dfi_chain_modify(chain, 8192u, &chain);
        if (!dfi_mods_push(mlist, &mods, 8192u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Solid Rock and Multiscale (step G34, data/abilities.ts:4414-4425 and 2760-2771, onSourceModifyDamage of the target,
     * both breakable and Mold Breaker is not marked): x0.75 on a super effective hit (typeMod > 0), x0.5 at full HP.
     * Filter (step G63, data/abilities.ts:1283-1294) is the same callback with the same text: x0.75 on typeMod > 0. */
    if ((dfi_ability(r->b, d, DFI_ABILITY_SOLIDROCK) || dfi_ability(r->b, d, DFI_ABILITY_FILTER)) && mod > DFI_BIAS6) {
        ok = ok && dfi_chain_modify(chain, 3072u, &chain);
        if (!dfi_mods_push(mlist, &mods, 3072u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    if (dfi_ability(r->b, d, DFI_ABILITY_MULTISCALE) && d->hp >= d->hp_max) {
        ok = ok && dfi_chain_modify(chain, 2048u, &chain);
        if (!dfi_mods_push(mlist, &mods, 2048u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Aura Guard (Mega batch 2, data/abilities.ts:310-319, onSourceModifyDamage of the target, breakable and Mold Breaker is
     * not marked; the Champions mod has no entry): x0.5 (chainModify(0.5) = 2048/4096) on a move with the contact flag, like
     * the contact half of Fluffy. It is the target's one ability, so with Solid Rock and Multiscale a hit has at most one of
     * the three. */
    if (dfi_ability(r->b, d, DFI_ABILITY_AURAGUARD) && (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u) {
        ok = ok && dfi_chain_modify(chain, 2048u, &chain);
        if (!dfi_mods_push(mlist, &mods, 2048u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Punk Rock's onSourceModifyDamage (step G45, data/abilities.ts:3597-3602, breakable): chainModify(0.5) on a sound move
     * against the holder. It is the target's one ability, so with Solid Rock, Multiscale and Aura Guard a hit has at most one. */
    if (dfi_ability(r->b, d, DFI_ABILITY_PUNKROCK) && md->special != DFI_SPECIAL_STRUGGLE &&
        (dfi_pool_move_flags2[(uint32_t)(md - dfi_pool_moves)] & DFI_MOVE_FLAG2_SOUND) != 0u) { /* wide-operands-reviewed: a pointer into the move table */
        ok = ok && dfi_chain_modify(chain, 2048u, &chain);
        if (!dfi_mods_push(mlist, &mods, 2048u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Fluffy (batch A1b, data/abilities.ts:1458-1469, onSourceModifyDamage of the target, breakable and Mold Breaker is not marked):
     * one chainModify of mod, where mod starts at 1, doubles for a Fire move (move_type) and halves for a move with the contact
     * flag: x2 (8192/4096) for a Fire move without contact, x0.5 (2048/4096) for a contact move that is not Fire, and for a Fire
     * contact move chainModify(1), which leaves the modifier as it is (((m * 4096) + 2048) >> 12 is m), so no factor. It is the
     * target's one ability, so with Solid Rock, Multiscale, Aura Guard and Punk Rock a hit has at most one. */
    if (dfi_ability(r->b, d, DFI_ABILITY_FLUFFY)) {
        const bool fluffy_fire = move_type == DFI_TYPE_FIRE;
        const bool fluffy_contact = (md->flags & DFI_MOVE_FLAG_CONTACT) != 0u;
        if (fluffy_fire != fluffy_contact) {
            const uint32_t fluffy = fluffy_fire ? 8192u : 2048u;
            ok = ok && dfi_chain_modify(chain, fluffy, &chain);
            if (!dfi_mods_push(mlist, &mods, fluffy)) {
                return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
            }
        }
    }
    /* Friend Guard (step G35, data/abilities.ts:1533-1540, onAnyModifyDamage, breakable and Mold Breaker is not marked): the
     * target's partner, when it stands and holds the ability, weakens every hit on the target by x0.75 (3072/4096). The handler
     * is any Pokemon's, so the attacker's own partner is a holder too when it is the one hit (a spread move on an ally), and the
     * holder itself is not weakened (target !== holder). A fainted holder does not run (runEvent skips the fainted). */
    const dfi_member *partner = dfi_at(r->b, target ^ 1u);
    if (partner != NULL && partner->hp != 0u && dfi_ability(r->b, partner, DFI_ABILITY_FRIENDGUARD)) {
        ok = ok && dfi_chain_modify(chain, 3072u, &chain);
        if (!dfi_mods_push(mlist, &mods, 3072u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* Sniper (step G77, data/abilities.ts:4358-4369, onModifyDamage of the attacker, not breakable): chainModify(1.5) = 6144/4096
     * on a critical hit. The Champions modifyDamage runs its ModifyDamage event once, at its end (scripts.ts:296; the base game
     * at sim/battle-actions.ts:1826), so Sniper is one more factor of the same chain as Life Orb and the rest, applied once. */
    if (crit && dfi_ability(r->b, a, DFI_ABILITY_SNIPER)) {
        ok = ok && dfi_chain_modify(chain, 6144u, &chain);
        if (!dfi_mods_push(mlist, &mods, 6144u)) {
            return DUOFORGE_E_UNSUPPORTED; /* more modifiers than the list holds: refused, never written past it */
        }
    }
    /* The handlers have no order and priority 0, so runEvent sorts them by their holders' speed, then by subOrder (a screen, a
     * side condition, has no speed and is last); this build does not compute that order (a follow-up, combat/damage_chain.h), so
     * the modifiers must chain to one value in every order. Pairs and triples of Life Orb, Expert Belt, a resist berry, a screen,
     * Solid Rock, Multiscale and Friend Guard do (checked by dfi_mods_commute at its own test, tests/interactions/test_modify_damage_chain_order.c, and here for
     * every hit); the combinations that do not (Glaive Rush's x2 with three others, an Expert Belt with a berry and Glaive Rush, a
     * Solid Rock with them) are E_UNSUPPORTED. */
    if (mods >= 3u && !dfi_mods_commute(mlist, mods)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    if (!ok) {
        return DUOFORGE_E_INVARIANT;
    }
    if (chain != 4096u) {
        damage = dfi_modify(damage, chain);
    }
    /* Step K2 (Piercing Drill, data/mods/champions/scripts.ts, the bypassProtect block after ModifyDamage): x0.25 of the hit that
     * passed a protection, then the holder's [-ability] (the attacker, Piercing Drill is an Ability effect) and [-zbroken] on the
     * target. Both lines print in this getDamage, after the critical and effectiveness lines above. */
    if (((r->protect_bypass >> target) & 1u) != 0u) {
        damage = dfi_modify(damage, DFI_PIERCING_DRILL_BYPASS_MOD);
        const duoforge_event ab =
            dfi_ev(DUOFORGE_EVENT_ABILITY, user, DUOFORGE_CAUSE_NONE, 1u + DFI_ABILITY_PIERCINGDRILL, DUOFORGE_NO_POSITION);
        dfi_emit(r, &ab); /* [-ability] attacker|Piercing Drill */
        dfi_emit_plain(r, DUOFORGE_EVENT_PROTECT_BROKEN, target); /* [-zbroken] target (decision 0015 5dd, kind 51 from the HS register, chrismaghuhn/duoforge#478) */
    }
    c->damage = damage;
    return DUOFORGE_OK;
}

#endif
