#ifndef DUOFORGE_COMBAT_FIELD_MAGIC_ROOM_REFUSAL_H
#define DUOFORGE_COMBAT_FIELD_MAGIC_ROOM_REFUSAL_H

/* Private field-family implementation (step K5, #475, decision 0015 5dm): the one refusal of Magic Room's setter. It stands apart from
 * magic_room.h, which needs the turn's run state, so that the white-box test can ask it on a battle. */
#include "state/battle_internal.h"

/* An Illusion holder whose disguise is up that uses Magic Room is refused (E_UNSUPPORTED) before any line: Showdown keeps the disguise
 * when the setter is switched out (data/abilities.ts:2075-2079), so the end line of a benched disguised setter would print the
 * disguise, while the digest's benched branch (observation_digest.c) hashes the real member. Not measured, not modelled. `user` is the
 * flat position of the user. (No pool species has Illusion and Magic Room together: only a decoded state or a copied move reaches this.) */
static inline bool dfi_magic_room_refused(const struct duoforge_battle *b, uint32_t user)
{
    const uint32_t side = user / DUOFORGE_ACTIVE_PER_SIDE;
    return dfi_illusion_disguise_up(&b->sides[side], &b->tail.sides[side], user % DUOFORGE_ACTIVE_PER_SIDE) != 0;
}

#endif
