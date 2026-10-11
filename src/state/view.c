/*
 * Views and worlds (decision 0023): a player's public state of a battle, the
 * world built from a public state and a hypothesis, and the privileged
 * hypothesis of a battle. All three work on the canonical encoding
 * (src/codec/state_codec.h): the public state is the encoding with the
 * hidden values replaced, and a world is decoded strictly, so it passes the
 * full state check. The mapping of the hypothesis's words is integer
 * arithmetic only.
 */
#include <duoforge/duoforge_view.h>

#include <string.h>

#include "codec/state_codec.h"
#include "core/bytes.h"
#include "data/closure_tables.h"
#include "data/pool_tables.h"
#include "rng/pcg32.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/invariants.h"
#include "state/knowledge.h"

_Static_assert(sizeof(duoforge_public_state) == 1396u, "public state layout (the state array is DUOFORGE_VIEW_STATE_MAX, 1357, since tail rev 5)");
_Static_assert(sizeof(duoforge_hypothesis) == 280u, "hypothesis layout");
_Static_assert(sizeof(((duoforge_hypothesis *)0)->queue_order) == DFI_QUEUE_CAPACITY, "queue permutation capacity");

/* The weights of a running hidden counter's value v = 1, 2, ... (a draw seen at a random point of its run). */
static const uint32_t dfi_sleep_weights[3] = {3u, 3u, 2u};           /* sample([2, 3, 3]) */
static const uint32_t dfi_confusion_weights[5] = {4u, 4u, 3u, 2u, 1u}; /* random(2, 6): 2..5 */

/* ---- integer uniforms ---- */

/* floor(u * n / 2^64) for n < 2^32, exactly. */
static uint32_t dfi_pick(uint64_t u, uint32_t n)
{
    const uint64_t lo = (u & 0xFFFFFFFFu) * (uint64_t)n;
    const uint64_t hi = (u >> 32) * (uint64_t)n;
    return (uint32_t)((hi + (lo >> 32)) >> 32); /* wide-operands-reviewed: < n < 2^32, no overflow (hi < 2^64 - 2^33) */
}

/* The middle word of those that pick index i of n: floor((2i + 1) * 2^63 / n), exactly (n < 2^16). */
static uint64_t dfi_word_of(uint32_t i, uint32_t n)
{
    const uint64_t half = (uint64_t)1u << 63;
    const uint64_t k = 2u * (uint64_t)i + 1u;
    return k * (half / n) + (k * (half % n)) / n;
}

/* The index of the value picked by u under integer weights w[0..n). */
static uint32_t dfi_pick_weighted(uint64_t u, const uint32_t *w, uint32_t n)
{
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        total += w[i];
    }
    uint32_t t = dfi_pick(u, total);
    for (uint32_t i = 0u; i < n; ++i) {
        if (t < w[i]) {
            return i;
        }
        t -= w[i];
    }
    return n - 1u;
}

static uint64_t dfi_word_of_weighted(uint32_t index, const uint32_t *w, uint32_t n)
{
    uint32_t start = 0u;
    uint32_t total = 0u;
    for (uint32_t i = 0u; i < n; ++i) {
        if (i < index) {
            start += w[i];
        }
        total += w[i];
    }
    return dfi_word_of(start + w[index] / 2u, total);
}

/* ---- bytes ---- */

static uint32_t rd16(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8);
}

static void wr16(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFFu);        /* wide-operands-reviewed: masked */
    p[1] = (uint8_t)((v >> 8) & 0xFFu); /* wide-operands-reviewed: masked */
}

static void wr64(uint8_t *p, uint64_t v)
{
    for (uint32_t i = 0u; i < 8u; ++i) {
        p[i] = (uint8_t)((v >> (8u * i)) & 0xFFu); /* wide-operands-reviewed: masked */
    }
}

static uint8_t *side_at(uint8_t *s, uint32_t side)
{
    return s + DFI_ENC_SIDE_OFF + side * DFI_ENC_SIDE_SIZE;
}

static uint8_t *member_at(uint8_t *s, uint32_t side, uint32_t m)
{
    return side_at(s, side) + DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
}

static uint8_t *position_at(uint8_t *s, uint32_t side, uint32_t p)
{
    return side_at(s, side) + DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
}

static uint8_t *knowledge_at(uint8_t *s, uint32_t side, uint32_t m)
{
    return side_at(s, side) + DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
}

/* A private queue order must never disclose a remaining move's priority or
 * an actor's hidden speed. Canonical public order: kind, side, slot. The
 * hypothesis carries the permutation solely for privileged byte round trips.
 * A resumed pivot processes its new switch-ins and sorts moves again. */
static uint32_t queue_key(const uint8_t *q)
{
    return (uint32_t)q[0] * 4u + (uint32_t)q[1] * 2u + q[2];
}

static void queue_canonical(uint8_t *s, uint8_t *order)
{
    const uint32_t n = s[DFI_ENC_QUEUE_LEN_OFF];
    for (uint32_t i = 0u; i < n; ++i) {
        order[i] = (uint8_t)i;
    }
    for (uint32_t i = 1u; i < n; ++i) {
        uint32_t j = i;
        while (j > 0u) {
            uint8_t *a = s + DFI_ENC_QUEUE_OFF + (j - 1u) * DFI_ENC_QUEUE_RECORD_SIZE;
            uint8_t *b = a + DFI_ENC_QUEUE_RECORD_SIZE;
            if (queue_key(a) <= queue_key(b)) {
                break;
            }
            uint8_t tmp[DFI_ENC_QUEUE_RECORD_SIZE];
            memcpy(tmp, a, sizeof tmp);
            memcpy(a, b, sizeof tmp);
            memcpy(b, tmp, sizeof tmp);
            const uint8_t idx = order[j];
            order[j] = order[j - 1u];
            order[j - 1u] = idx;
            --j;
        }
    }
}

/* ---- the candidates of a hidden value ---- */

/* The exact HP values whose display is (percent, flag) under hp_max, in ascending order: their count, and the
 * index-th of them in *out_hp (when index < count). */
static uint32_t dfi_hp_candidates(uint32_t percent, uint32_t flag, uint32_t hp_max, uint32_t index, uint32_t *out_hp)
{
    if (percent == 0u) {
        *out_hp = 0u;
        return 1u;
    }
    uint32_t n = 0u;
    for (uint32_t hp = 1u; hp <= hp_max; ++hp) {
        uint8_t pc = 0u;
        uint8_t fl = 0u;
        dfi_hp_display(hp, hp_max, &pc, &fl);
        if (pc == percent && fl == flag) {
            if (n == index) {
                *out_hp = hp;
            }
            ++n;
        }
    }
    return n;
}

/* The targets a move of the given target class could have chosen from flat position `user`, in ascending order. */
static uint32_t dfi_target_candidates(uint32_t target_class, uint32_t user, uint8_t *out)
{
    uint32_t n = 0u;
    const uint32_t ally = user ^ 1u;
    for (uint32_t f = 0u; f < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE; ++f) {
        const bool foe = f / 2u != user / 2u;
        bool ok = false;
        switch (target_class) {
        case DUOFORGE_TARGET_CLASS_NORMAL:
        case DUOFORGE_TARGET_CLASS_ANY:
            ok = f != user;
            break;
        case DUOFORGE_TARGET_CLASS_ADJACENT_FOE:
            ok = foe;
            break;
        case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY:
            ok = f == ally;
            break;
        case DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF:
            ok = f == ally || f == user;
            break;
        default:
            break;
        }
        if (ok) {
            out[n++] = (uint8_t)f;
        }
    }
    if (n == 0u) {
        out[n++] = (uint8_t)DUOFORGE_TARGET_NONE;
    }
    return n;
}

/* ---- the public state ---- */

/* The causes of a public refusal that the player's view decides (decision 0023; the bits are DUOFORGE_PUBLIC_CAUSE_*). This
 * is the ONE predicate of both the public record (duoforge_battle_public refuses while it is nonzero) and the causes call
 * (duoforge_battle_public_causes writes it), so the two can never disagree. It reads only the player's observation, never a
 * hidden counter. Elapsed status attempts are not stored in schema 3. Never invent their posterior: a visible sleep or
 * confusion is a cause, nothing else is. ILLUSION_POSSIBLE stays 0 until Illusion (decision 0026, section 4). */
/* Any byte of a side's Illusion state is set (point (d) of I2: a public view is refused while the foe side's ill_* is nonzero). */
static bool dfi_view_ill_nonzero(const dfi_tail_illusion *il)
{
    const uint8_t *p = (const uint8_t *)il;
    for (size_t i = 0u; i < sizeof *il; ++i) {
        if (p[i] != 0u) {
            return true;
        }
    }
    return false;
}

/* Step G72b (decision 0015 5ce; cause DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN): at any PIVOT boundary (public: b->boundary_kind, the
 * view's boundary), an active Pokemon of either side that knows Alluring Voice (its move ids are open, the OTS sheet; the position
 * is public through occupant[]) may have had its stats raised this turn, which the view does not carry (stats_raised_this_turn).
 * Pool data only (the move id is a pool row). Nothing here reads the engine's queue: the queue holds the foe's chosen moves, which
 * no player knows (an information leak if read). A turn boundary is not affected (the bit is zero there), and a replacement at the
 * end of a turn is the REPLACEMENT boundary, not a PIVOT. */
static bool dfi_view_raised_risk(const duoforge_context *ctx, const duoforge_observation *ob)
{
    if (ob->boundary_kind != DUOFORGE_BOUNDARY_PIVOT || !dfi_context_is_pool(ctx)) {
        return false;
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occ = ob->sides[side].occupant[p];
            if (occ >= DUOFORGE_MAX_ROSTER) {
                continue;
            }
            const duoforge_member_view *v = &ob->sides[side].members[occ];
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS && k < v->move_count; ++k) {
                if (v->move_ids[k] == DFI_MOVE_ALLURINGVOICE) {
                    return true;
                }
            }
        }
    }
    return false;
}

/* Step G88 (decision 0046, cause DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY = 64): at a PIVOT boundary, an active Pokemon of either side
 * that knows Lash Out or Assurance (its move ids are open, the OTS sheet; the position is public through occupant[]). Lash Out's
 * LOWERED_THIS_TURN and Assurance's HURT_THIS_TURN (position_flags bits 5 and 6) are live mid-turn and are not in the view, so the
 * record and the rebuild refuse. The same predicate as the Alluring Voice one: it reads only the observation (its boundary kind,
 * its turn, the move ids of the own team and of the foe's open sheet) and the context, never the battle or the queue, so the
 * battle path and duoforge_observation_causes (the live record assembler's path) share it. The bits are zero at a turn
 * boundary (endTurn clears them). */
static bool dfi_view_turn_history_risk(const duoforge_context *ctx, const duoforge_observation *ob)
{
    if (!dfi_context_is_pool(ctx)) {
        return false;
    }
    const bool pivot = ob->boundary_kind == DUOFORGE_BOUNDARY_PIVOT;
    /* The first decision (turn 1, after team selection, and any boundary of turn 1 before its endTurn): the entries of the battle
     * start can have set LOWERED (Intimidate, sim/battle.ts:2086), and endTurn keeps it at turn 1 (the gate turn !== 1,
     * sim/battle.ts:1677-1683). The view does not carry LOWERED, so the rebuilt world would be wrong there (decision 0046,
     * section 3). HURT cannot be set before the first move: no spread damage happens at the start (entries set stages, weather
     * and terrain; hazards are set by moves), so only Lash Out refuses at the first decision. A negative boost is not the
     * criterion: the rule refuses whenever Lash Out is known. */
    if (!pivot && ob->turn != 1u) {
        return false;
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occ = ob->sides[side].occupant[p];
            if (occ >= DUOFORGE_MAX_ROSTER) {
                continue;
            }
            const duoforge_member_view *v = &ob->sides[side].members[occ];
            for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS && k < v->move_count; ++k) {
                if (v->move_ids[k] == DFI_MOVE_LASHOUT || (pivot && v->move_ids[k] == DFI_MOVE_ASSURANCE)) {
                    return true;
                }
            }
        }
    }
    return false;
}

/* The part of the one predicate that the player's observation alone decides: a visible sleep, a visible confusion, a foe
 * Illusion member that may be disguised, a PIVOT with Alluring Voice on the field, the turn history of Lash Out and Assurance
 * (step G88). The battle path adds what the observation does
 * not carry (the foe's disguise state, a Substitute, a temporary forme). duoforge_observation_causes serves this part to the live
 * record assembler, so that no copy of it lives outside C. */
static uint32_t dfi_view_observation_causes(const duoforge_context *ctx, const duoforge_observation *observation)
{
    uint32_t mask = 0u;
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            if (observation->sides[side].members[m].status == DUOFORGE_AILMENT_SLEEP) {
                mask |= DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP;
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            if (observation->sides[side].positions[p].confused != 0u) {
                mask |= DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION;
            }
        }
    }
    /* Illusion (decision 0026 section 4, amended by I2, point (a)): the foe's sheet has an Illusion member that the viewer has not
     * seen fainted under its own name and that is not shown on the field under its own name. Facts of the viewer only. */
    const uint32_t foe = 1u - (observation->player & 1u);
    for (uint32_t m = 0u; m < observation->sides[foe].member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        const duoforge_member_view *v = &observation->sides[foe].members[m];
        if (v->ability != DFI_ABILITY_ILLUSION + 1u) {
            continue;
        }
        const bool fainted_seen = v->hp_kind == DUOFORGE_HP_PERCENT && v->hp == 0u;
        const bool shown_own = observation->sides[foe].occupant[0] == m || observation->sides[foe].occupant[1] == m;
        if (!fainted_seen && !shown_own) {
            mask |= DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE;
        }
    }
    if (dfi_view_raised_risk(ctx, observation)) {
        mask |= DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN; /* step G72b: a PIVOT with Alluring Voice known on the field */
    }
    if (dfi_view_turn_history_risk(ctx, observation)) {
        mask |= DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY; /* step G88: Lash Out or Assurance known on the field (PIVOT, turn 1) */
    }
    return mask;
}

static duoforge_status dfi_view_visible_causes(const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                                               uint32_t *out_mask)
{
    duoforge_observation observation;
    const duoforge_status st = duoforge_battle_observe(ctx, b, player, &observation);
    if (st != DUOFORGE_OK) {
        return st;
    }
    uint32_t mask = dfi_view_observation_causes(ctx, &observation);
    /* The foe side's disguise state (ill_*) being nonzero counts for Illusion as well (decision 0026, I2 point (d)). */
    if (dfi_view_ill_nonzero(&b->tail.sides[1u - player].illusion)) {
        mask |= DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE;
    }
    /* Step G60 (decision 0032): a Substitute on either side is public presence (the position's volatile, VOLATILE_SUBSTITUTE); its
     * HP never is, so the presence is a function of the public record only. */
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            if (b->tail.sides[side].positions[p].substitute_hp != 0u) {
                mask |= DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE;
            }
        }
    }
    /* Step G66 (decision 0040; the cause approved by HauptSession): a position whose occupant is in a temporary forme (Stance
     * Change's Aegislash-Blade), on either side. The view does not show that forme yet (member_ext.forme stays unfilled), so
     * the record and the rebuild refuse it with this cause. forme_now ends with the switch-out. */
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const uint32_t occupant = b->sides[side].positions[p].occupant;
            if (occupant < DUOFORGE_MAX_ROSTER && b->tail.sides[side].forme_now[occupant] != 0u) {
                mask |= DUOFORGE_PUBLIC_CAUSE_TEMP_FORME;
            }
        }
    }
    *out_mask = mask;
    return DUOFORGE_OK;
}

/* The counter refusal of duoforge_battle_public: E_UNSUPPORTED while the one predicate names a cause. */
/* decision 0023 (HauptSession, the PP proxy): the record keeps no revive history, so a foe that may have revived is seen
 * through its Revival Blessing slot: Revival Blessing has PP 1 and a foe's PP is derived from the moves it used, so a
 * derived PP of 0 means the move was used once, revive or not. While any foe member shows that, the record refuses (the
 * generic cause: no cause bit, the causes mask stays 0). It depends only on the observation. Own slots never count. */
static bool dfi_view_foe_revive_proxy(const duoforge_observation *ob, uint32_t foe)
{
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const duoforge_member_view *v = &ob->sides[foe].members[m];
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS && k < v->move_count; ++k) {
            if (v->move_ids[k] == DFI_MOVE_REVIVALBLESSING && v->pp[k] == 0u) {
                return true;
            }
        }
    }
    return false;
}

static duoforge_status dfi_view_counter_support(const duoforge_context *ctx, const duoforge_battle *b, uint32_t player)
{
    uint32_t causes = 0u;
    const duoforge_status st = dfi_view_visible_causes(ctx, b, player, &causes);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (causes != 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    duoforge_observation observation;
    const duoforge_status so = duoforge_battle_observe(ctx, b, player, &observation);
    if (so != DUOFORGE_OK) {
        return so;
    }
    return dfi_view_foe_revive_proxy(&observation, 1u - (player & 1u)) ? DUOFORGE_E_UNSUPPORTED : DUOFORGE_OK;
}

/* party_order in a public view (step G46; decision 0023): the foe's bench entries (positions 2 and up) are the order of the
 * foe's hidden pick and switch history, so the view hides them as DFI_PARTY_HIDDEN, exactly as it hides the pick order past
 * the leads. The foe's two actives stay (they are public: the switches show them). The own side is exact. */
static void dfi_view_hide_foe_party(uint8_t *s, uint32_t foe)
{
    dfi_pool_tail t;
    memset(&t, 0, sizeof t);
    uint8_t *pb = s + DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_FIELD_PARTY_OFF + foe * DFI_PARTY_BYTES_PER_SIDE;
    memcpy(t.party_order[foe], pb, DFI_PARTY_BYTES_PER_SIDE);
    for (uint32_t k = DUOFORGE_ACTIVE_PER_SIDE; k < DUOFORGE_MAX_ROSTER; ++k) {
        dfi_party_put(&t, foe, k, DFI_PARTY_HIDDEN);
    }
    memcpy(pb, t.party_order[foe], DFI_PARTY_BYTES_PER_SIDE);
}

/* Illusion (decision 0026 section 4): the foe's record hides what the foe was never shown. The disguise flag of each foe position
 * (ability_state: the holder's disguise is up) and the snapshot and pending counts of the foe's side are the engine's truth; the
 * shown name and the override stay (the foe saw them). */
static void dfi_view_hide_foe_illusion(uint8_t *s, uint32_t foe, const duoforge_battle *b)
{
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (dfi_illusion_disguise_up(&b->sides[foe], &b->tail.sides[foe], p) != 0) {
            s[DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_SIDES_OFF + foe * DFI_ENC_TAIL_SIDE_SIZE + DFI_ENC_TAIL_POS_OFF + p * DFI_ENC_TAIL_POS_SIZE +
              DFI_ENC_TAIL_POS_ABILITY_STATE_OFF] = 0u;
        }
    }
    uint8_t *il = s + DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_REV4_SIZE + DFI_ENC_TAIL5_SIDES_OFF + foe * DFI_ENC_TAIL5_SIDE_SIZE;
    memset(il + DFI_ENC_TAIL5_ILL_SNAPSHOT_OFF, 0, 7u); /* bytes 7..8 (the holder's status and location as the foe knew them) stay */
    memset(il + DFI_ENC_TAIL5_ILL_PENDING_OFF, 0, 4u);
}

/* The foe's party_order of a world built from a public view (from_view): the two actives from the view (public), then the
 * hypothesis's brought order (its first `count` picks, the brought members in pick order) minus the two actives. The bench
 * is hypothesis-supplied (decision 0023): the true foe order never reaches a world. Nothing is brought: the order is zero. */
static duoforge_status dfi_view_world_foe_party(uint8_t *s, uint32_t foe, uint32_t brought_mask, const uint8_t *pick_order)
{
    uint32_t count = 0u;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        count += ((uint32_t)brought_mask >> m) & 1u;
    }
    dfi_pool_tail t;
    memset(&t, 0, sizeof t);
    uint8_t *pb = s + DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_FIELD_PARTY_OFF + foe * DFI_PARTY_BYTES_PER_SIDE;
    memcpy(t.party_order[foe], pb, DFI_PARTY_BYTES_PER_SIDE);
    if (count == 0u) {
        memset(t.party_order[foe], 0, DFI_PARTY_BYTES_PER_SIDE);
    } else {
        const uint32_t a = dfi_party_entry(&t, foe, 0u);
        const uint32_t c = dfi_party_entry(&t, foe, 1u);
        if ((a == 0u) != (c == 0u) || a > DUOFORGE_MAX_ROSTER || c > DUOFORGE_MAX_ROSTER) {
            return DUOFORGE_E_MALFORMED;
        }
        /* No active is placed yet (team selection): the party is the hypothesis's pick order, the leads first. */
        const bool placed = a != 0u;
        for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
            dfi_party_put(&t, foe, k, 0u);
        }
        uint32_t k = placed ? DUOFORGE_ACTIVE_PER_SIDE : 0u;
        if (!placed) {
            for (uint32_t i = 0u; i < count && i < DUOFORGE_MAX_ROSTER; ++i) {
                if (pick_order[i] >= DUOFORGE_MAX_ROSTER) {
                    return DUOFORGE_E_MALFORMED;
                }
                dfi_party_put(&t, foe, i, (uint32_t)pick_order[i] + 1u);
            }
            memcpy(pb, t.party_order[foe], DFI_PARTY_BYTES_PER_SIDE);
            return DUOFORGE_OK;
        }
        dfi_party_put(&t, foe, 0u, a);
        dfi_party_put(&t, foe, 1u, c);
        for (uint32_t i = 0u; i < count && i < DUOFORGE_MAX_ROSTER; ++i) {
            if (pick_order[i] >= DUOFORGE_MAX_ROSTER) {
                return DUOFORGE_E_MALFORMED;
            }
            const uint32_t r = (uint32_t)pick_order[i] + 1u;
            if (r == a || r == c) {
                continue;
            }
            if (k >= DUOFORGE_MAX_ROSTER) {
                return DUOFORGE_E_MALFORMED;
            }
            dfi_party_put(&t, foe, k, r);
            k += 1u;
        }
    }
    memcpy(pb, t.party_order[foe], DFI_PARTY_BYTES_PER_SIDE);
    return DUOFORGE_OK;
}

/* The argument checks of the public calls, in their order (shared by the record and the causes call). */
static duoforge_status dfi_view_check_args(const duoforge_context *ctx, const duoforge_battle *b, uint32_t player)
{
    if (ctx == NULL || b == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (!dfi_context_fingerprint_matches(ctx, b->context_fingerprint)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (player >= DUOFORGE_SIDE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (dfi_state_check(ctx, b, NULL) != DUOFORGE_OK) {
        return DUOFORGE_E_INVARIANT;
    }
    return DUOFORGE_OK;
}

static duoforge_status dfi_view_encode(const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                                       uint8_t *s, size_t *out_size)
{
    const duoforge_status args = dfi_view_check_args(ctx, b, player);
    if (args != DUOFORGE_OK) {
        return args;
    }
    const duoforge_status counter_support = dfi_view_counter_support(ctx, b, player);
    if (counter_support != DUOFORGE_OK) {
        return counter_support;
    }
    const uint32_t foe = player ^ 1u;
    /* the refusals, each decided by public facts */
    if (b->boundary_kind == DUOFORGE_BOUNDARY_PIVOT) {
        bool moves_started = false;
        for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                /* These publicly shown volatiles end in every residual.
                 * move_actions, in contrast, is cumulative since entry. */
                const uint32_t public_turn_flags = DFI_VOL_PROTECT | DFI_VOL_HELPING_HAND | DFI_VOL_FOLLOW_ME;
                moves_started = moves_started || (b->sides[side].positions[p].flags & public_turn_flags) != 0u;
            }
        }
        if (!moves_started) {
            /* A hazard/entry pivot can precede the Mega phase. A refusal
             * based on the private queue then reveals an unannounced Mega
             * declaration. Refuse the entire public pre-move phase. */
            return DUOFORGE_E_UNSUPPORTED;
        }
        /* The silent flinch (view audit 2026-10-10): a secondary's flinch is set without a line and shows only when the
         * flinched Pokemon tries to move ([cant] flinch), hidden from both players (0007). No public fact tells whether one is
         * outstanding on a position still to move, so a PIVOT with a queued move left is refused; with none left a flinch has
         * no effect before the residual ends it, and the record drops the bit (below). */
        for (uint32_t q = 0u; q < b->queue_len && q < DFI_QUEUE_CAPACITY; ++q) {
            if (b->queue[q].kind == DFI_Q_MOVE) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
    }
    if (b->sides[foe].sealed != 0u) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    for (uint32_t q = 0u; q < b->queue_len && q < DFI_QUEUE_CAPACITY; ++q) {
        const dfi_queue_record *r = &b->queue[q];
        if (r->kind != DFI_Q_MOVE && r->kind != DFI_Q_RESIDUAL) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_tail_pos *tp = &b->tail.sides[side].positions[p];
            /* A Substitute on either side is refused (decision 0032): its HP follows hidden damage and the owner's request does not show
             * it, so no honest world can rebuild it. The cause (DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE) is named by the causes call. */
            /* A lockedmove is refused while one may run, decided from the public last move (dfi_maybe_lockedmove), not from
             * the drawn count, whose silent end would show (view audit 2026-10-10). A running lock outside that is a broken
             * state. */
            const bool maybe_locked = dfi_maybe_lockedmove(b, side * 2u + p);
            if (tp->lock_turns != 0u && !maybe_locked) {
                return DUOFORGE_E_INVARIANT;
            }
            /* Step G66: a temporary forme (Stance Change) is refused too: its forme is not in the view (the TEMP_FORME cause). */
            const uint32_t occupant = b->sides[side].positions[p].occupant;
            const bool temp_forme = occupant < DUOFORGE_MAX_ROSTER && b->tail.sides[side].forme_now[occupant] != 0u;
            if (tp->trap_turns != 0u || maybe_locked || tp->substitute_hp != 0u || temp_forme) {
                return DUOFORGE_E_UNSUPPORTED;
            }
        }
    }
    const size_t n = dfi_encode_unchecked(ctx, b, s);
    if (dfi_kind_limits_of(ctx->data_kind).pool_rules) {
        dfi_view_hide_foe_party(s, foe); /* step G46: the foe's party_order past the leads is hidden (decision 0023) */
        dfi_view_hide_foe_illusion(s, foe, b); /* Illusion (decision 0026 section 4): the foe's record hides the disguise's truth */
    }
    uint8_t order[DFI_QUEUE_CAPACITY] = {0};
    queue_canonical(s, order);
    for (uint32_t q = 0u; q < b->queue_len; ++q) {
        uint8_t *r = s + DFI_ENC_QUEUE_OFF + q * DFI_ENC_QUEUE_RECORD_SIZE;
        if (r[0] == DFI_Q_MOVE && r[1] == foe) {
            r[3] = (uint8_t)DUOFORGE_VIEW_HIDDEN;
            r[4] = (uint8_t)DUOFORGE_VIEW_HIDDEN_TARGET;
        }
    }
    memset(s + DFI_ENC_RNG_STATE_OFF, 0, 24u);
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            uint8_t *mb = member_at(s, side, m);
            if (mb[DFI_ENC_MEMBER_STATUS_OFF] == DFI_STATUS_SLP && mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] != 0u) {
                mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN;
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            uint8_t *pb = position_at(s, side, p);
            /* The silent flinch (above): no move is left that it could stop. Its residual end is one more entry of the
             * residual's speed order, so a world without it may draw a different number of speed ties there; the
             * distribution of the outcomes is the same. */
            pb[DFI_ENC_POS_FLAGS_OFF] = (uint8_t)(pb[DFI_ENC_POS_FLAGS_OFF] & ~DFI_VOL_FLINCH); /* wide-operands-reviewed: flags are 8 bits */
            if (pb[DFI_ENC_POS_CONFUSION_OFF] != 0u) {
                pb[DFI_ENC_POS_CONFUSION_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN;
            }
            if (side == foe && pb[DFI_ENC_POS_CHARGE_OFF] != 0u) {
                pb[DFI_ENC_POS_LOCKED_TARGET_OFF] = (uint8_t)DUOFORGE_VIEW_HIDDEN_TARGET;
            }
        }
    }
    uint8_t *fs = side_at(s, foe);
    fs[DFI_ENC_SIDE_BROUGHT_OFF] = 0u;
    for (uint32_t k = 2u; k < DUOFORGE_MAX_ROSTER; ++k) {
        fs[DFI_ENC_SIDE_ORDER_OFF + k] = (uint8_t)DUOFORGE_VIEW_PICK_NONE;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        uint8_t *mb = member_at(s, foe, m);
        memset(mb + DFI_ENC_MEMBER_HP_OFF, 0, 2u + 2u + 2u * DFI_MEMBER_STAT_COUNT);
        memset(mb + DFI_ENC_MEMBER_STAT_POINTS_OFF, 0, DFI_STAT_POINT_COUNT);
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            mb[DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE + 2u] = 0u; /* pp */
        }
    }
    *out_size = n;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_public(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                       duoforge_public_state *out)
{
    if (out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    memset(s, 0, sizeof s);
    size_t n = 0u;
    const duoforge_status st = dfi_view_encode(ctx, battle, player, s, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t foe = player ^ 1u;
    memset(out, 0, sizeof *out);
    out->revision = DUOFORGE_VIEW_REVISION;
    out->player = player;
    out->state_size = (uint32_t)n;
    out->boundary = battle->boundary_kind;
    out->turn = battle->turn;
    out->request_mask = battle->request_mask;
    out->epoch = battle->request_epoch;
    out->foe_seen_mask = battle->sides[player].seen_mask;
    out->foe_leads[0] = battle->sides[foe].brought_order[0];
    out->foe_leads[1] = battle->sides[foe].brought_order[1];
    out->queue_count = battle->queue_len;
    for (uint32_t q = 0u; q < battle->queue_len; ++q) {
        const dfi_queue_record *r = &battle->queue[q];
        if (r->side == foe && r->kind == DFI_Q_MOVE) {
            out->foe_pending_mask = (uint8_t)(out->foe_pending_mask | (1u << r->slot)); /* wide-operands-reviewed: slots < 2 */
        }
    }
    memcpy(out->state, s, n);
    return DUOFORGE_OK;
}

/* The causes of the public refusal (decision 0023, decision 0026 section 4): a pure call. Its checks are those of
 * duoforge_battle_public, in the same order. It writes the mask of the causes that the view decides, the same predicate
 * that duoforge_battle_public refuses on. A mask of 0 with a refusing duoforge_battle_public means another refusal (a
 * PIVOT, sealed commands, a Substitute, a partial trap, a locked move). Depends on the player's view only. */
duoforge_status duoforge_battle_public_causes(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t player,
                                              uint32_t *out_mask)
{
    if (out_mask == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status args = dfi_view_check_args(ctx, battle, player);
    if (args != DUOFORGE_OK) {
        return args;
    }
    uint32_t causes = 0u;
    const duoforge_status st = dfi_view_visible_causes(ctx, battle, player, &causes);
    if (st != DUOFORGE_OK) {
        return st;
    }
    *out_mask = causes;
    return DUOFORGE_OK;
}

duoforge_status duoforge_observation_causes(const duoforge_context *ctx, const duoforge_observation *observation,
                                            uint32_t *out_mask)
{
    if (ctx == NULL || observation == NULL || out_mask == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (observation->player >= DUOFORGE_SIDE_COUNT) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out_mask = dfi_view_observation_causes(ctx, observation);
    return DUOFORGE_OK;
}

duoforge_status duoforge_hp_display(uint32_t hp, uint32_t hp_max, uint8_t *out_percent, uint8_t *out_flag)
{
    if (out_percent == NULL || out_flag == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (hp_max == 0u || hp_max > 0xFFFFu || hp > hp_max) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    dfi_hp_display(hp, hp_max, out_percent, out_flag);
    return DUOFORGE_OK;
}

#define DFI_POSITIONS_MR (DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE)

/* ---- the result of a move action from its events (POOL tail rev 4 move_result; the live record assembler) ---- */

/* The classes of the move body (src/combat/turn.c, DFI_MRES_* there): a hit or a change true, a literal false, a
 * NOT_FAIL null. */
#define MR_TRUE 1u
#define MR_FALSE 2u
#define MR_NULL 4u

/* The first event of a move action of `user`: its [cant], its confusion line, its own [move] or a [move] Magic Bounce
 * reflected (cause ABILITY, the holder's run). */
static bool mr_start(const duoforge_event *e, uint32_t user)
{
    if (e->position != user) {
        return false;
    }
    return e->kind == DUOFORGE_EVENT_CANT || e->kind == DUOFORGE_EVENT_CONFUSED ||
           (e->kind == DUOFORGE_EVENT_MOVE && (e->cause == DUOFORGE_CAUSE_NONE || e->cause == DUOFORGE_CAUSE_ABILITY));
}

/* The abilities that take a move at their holder's TryHit and stop it there (the move's result false: the hit steps
 * normalise their null). The line names the ability: -ability (Lightning Rod, Sap Sipper, Motor Drive, Storm Drain),
 * -heal [from] ability (Water Absorb, Volt Absorb, Dry Skin, Earth Eater). */
static bool mr_absorbs(uint32_t ability)
{
    return ability == DFI_ABILITY_LIGHTNINGROD || ability == DFI_ABILITY_SAPSIPPER || ability == DFI_ABILITY_MOTORDRIVE ||
           ability == DFI_ABILITY_WATERABSORB || ability == DFI_ABILITY_VOLTABSORB || ability == DFI_ABILITY_DRYSKIN ||
           ability == DFI_ABILITY_EARTHEATER;
}

/* A target class whose move acts on its user or its side: what happens to the user is the move's own effect. */
static bool mr_selfish(uint32_t target_class)
{
    return target_class == DUOFORGE_TARGET_CLASS_SELF || target_class == DUOFORGE_TARGET_CLASS_ADJACENT_ALLY_OR_SELF ||
           target_class == DUOFORGE_TARGET_CLASS_ALLY_SIDE || target_class == DUOFORGE_TARGET_CLASS_ALL ||
           target_class == DUOFORGE_TARGET_CLASS_ALLY_TEAM || target_class == DUOFORGE_TARGET_CLASS_ALLIES ||
           target_class == DUOFORGE_TARGET_CLASS_FOE_SIDE;
}

/* The status-move families of the engine's move body, by special (and the move ids whose special is the generic one). */
typedef enum mr_family {
    MR_EFFECT,       /* true when something changed (a stage, a status that stayed, a volatile, a condition...), else false */
    MR_RUNS,         /* true once it runs: Wide Guard (a second one prints nothing), Rage Powder, Follow Me, Perish Song,
                        Revival Blessing, Baton Pass (dfi_status_hit_end) */
    MR_REACHES,      /* true for a target it reaches: Parting Shot's onHit always counts, Helping Hand, a forced switch's
                        hit (Roar, Whirlwind: the reserve's) */
    MR_UNCLASSIFIED, /* its success sets no class: Quick Guard, Haze, After You, Quash */
    MR_HEAL_PULSE,   /* a target at full HP is NOT_FAIL: true */
    MR_REFUSED       /* a handler this classifier does not map: refused */
} mr_family;

static mr_family mr_family_of(uint32_t move_id, const dfi_move_data *md)
{
    if ((dfi_pool_move_flags2[move_id] & DFI_MOVE_FLAG2_FORCE_SWITCH) != 0u && md->primary_status == DFI_STATUS_NONE) {
        return MR_REACHES;
    }
    switch (md->special) {
    case DFI_SPECIAL_NONE:
    case DFI_SPECIAL_PROTECT:
    case DFI_SPECIAL_SPIKY_SHIELD:
    case DFI_SPECIAL_KINGS_SHIELD:
    /* G94a: Baneful Bunker runs dfi_run_protect as every Protect: the stall fail FALSE, the -singleturn Protect TRUE */
    case DFI_SPECIAL_BANEFUL_BUNKER:
    case DFI_SPECIAL_ENCORE:
    case DFI_SPECIAL_SOAK:
    case DFI_SPECIAL_DISABLE:
    case DFI_SPECIAL_TRICK:
    case DFI_SPECIAL_SWITCHEROO:
    case DFI_SPECIAL_TAUNT:
    case DFI_SPECIAL_YAWN:
    case DFI_SPECIAL_DRAGON_CHEER:
    case DFI_SPECIAL_SKILL_SWAP:
    case DFI_SPECIAL_THUNDER_WAVE:
    case DFI_SPECIAL_SHELL_SMASH:
    case DFI_SPECIAL_CLANGOROUS_SOUL:
    case DFI_SPECIAL_RECOVER:
    case DFI_SPECIAL_ROOST:
    case DFI_SPECIAL_STRENGTH_SAP:
    case DFI_SPECIAL_SANDSTORM:
    case DFI_SPECIAL_SNOWSCAPE:
    case DFI_SPECIAL_RAIN_DANCE:
    case DFI_SPECIAL_SUNNY_DAY:
    case DFI_SPECIAL_ELECTRIC_TERRAIN:
    case DFI_SPECIAL_MISTY_TERRAIN:
    case DFI_SPECIAL_PSYCHIC_TERRAIN: /* G96: the same setter as Electric and Misty Terrain, true when set, -fail false */
    case DFI_SPECIAL_AURORA_VEIL:
    case DFI_SPECIAL_IMPRISON:
        return MR_EFFECT;
    case DFI_SPECIAL_WIDE_GUARD:
    case DFI_SPECIAL_RAGE_POWDER:
    case DFI_SPECIAL_FOLLOW_ME:
    case DFI_SPECIAL_PERISH_SONG:
    case DFI_SPECIAL_REVIVAL_BLESSING:
    case DFI_SPECIAL_BATON_PASS:
        return MR_RUNS;
    case DFI_SPECIAL_PARTING_SHOT:
    case DFI_SPECIAL_HELPING_HAND:
        return MR_REACHES;
    case DFI_SPECIAL_QUICK_GUARD:
    case DFI_SPECIAL_HAZE:
    case DFI_SPECIAL_AFTER_YOU:
    case DFI_SPECIAL_QUASH:
        return MR_UNCLASSIFIED;
    case DFI_SPECIAL_HEAL_PULSE:
        return MR_HEAL_PULSE;
    default:
        return MR_REFUSED; /* Substitute, Destiny Bond and every handler not mapped here */
    }
}

/* A status move changed something at a position it reached (not `stopped`; the user only for a move of its own side): a
 * stage, a status that stayed (one a berry cured in the same action did not), a volatile, a type, an item, an ability, a
 * heal, a Protect, a side or field condition that started, a weather that started, Trick Room's own end.
 * The last action of a turn reaches the caller with the residual's events after it (no line marks where the residual
 * begins), so the events that only the residual makes never count as the move's: a side condition's end (no status move
 * of the engine ends one; Psychic Fangs is a damaging move), a field's end other than Trick Room's toggle by the Trick Room
 * move (the durations, Steel Roller's damaging hit), the weather's end (-weather|none, the duration), a Perish count
 * (Perish Song's own start is silent) and a sleep without [from] move (Yawn's; a move's sleep names the move). */
static bool mr_changed(const duoforge_event *body, uint32_t count, uint32_t user, uint32_t stopped, bool selfish,
                       bool trick_room)
{
    uint32_t statused = 0u;
    for (uint32_t i = 0u; i < count; ++i) {
        const duoforge_event *e = &body[i];
        const uint32_t pos = e->position;
        const bool at = pos < DFI_POSITIONS_MR;
        if (at && (((stopped >> pos) & 1u) != 0u || (pos == user && !selfish))) {
            continue;
        }
        const bool own_cause = e->cause == DUOFORGE_CAUSE_NONE || e->cause == DUOFORGE_CAUSE_MOVE;
        switch (e->kind) {
        case DUOFORGE_EVENT_BOOST:
        case DUOFORGE_EVENT_UNBOOST:
            if (e->cause == DUOFORGE_CAUSE_NONE && e->amount > 0u) {
                return true;
            }
            break;
        case DUOFORGE_EVENT_STATUS:
            if (own_cause && at && !(e->detail == DFI_STATUS_SLP && e->cause == DUOFORGE_CAUSE_NONE)) {
                statused |= 1u << pos;
            }
            break;
        case DUOFORGE_EVENT_CURE_STATUS:
            if (at) {
                statused &= ~(1u << pos);
            }
            break;
        case DUOFORGE_EVENT_VOLATILE_START:
            if (own_cause && e->detail != DUOFORGE_VOLATILE_PERISH) {
                return true;
            }
            break;
        case DUOFORGE_EVENT_CONFUSION_START:
        case DUOFORGE_EVENT_TYPE_CHANGE:
        case DUOFORGE_EVENT_SINGLE_TURN:
        case DUOFORGE_EVENT_PROTECT:
        case DUOFORGE_EVENT_ITEM_START:
            if (own_cause) {
                return true;
            }
            break;
        case DUOFORGE_EVENT_HEAL:
            if (e->cause == DUOFORGE_CAUSE_NONE) {
                return true;
            }
            break;
        case DUOFORGE_EVENT_ABILITY:
            if (e->cause == DUOFORGE_CAUSE_MOVE) {
                return true;
            }
            break;
        case DUOFORGE_EVENT_ITEM_END:
            if (e->cause == DUOFORGE_CAUSE_ITEM_TAKEN) {
                return true; /* Trick, Switcheroo: the target's item went */
            }
            break;
        case DUOFORGE_EVENT_SIDE_START:
        case DUOFORGE_EVENT_FIELD_START:
            if (e->cause == DUOFORGE_CAUSE_NONE) {
                return true;
            }
            break;
        case DUOFORGE_EVENT_FIELD_END:
            if (e->cause == DUOFORGE_CAUSE_NONE && trick_room && e->detail == DUOFORGE_FIELD_TRICK_ROOM) {
                return true; /* Trick Room again ends it (onFieldRestart) */
            }
            break;
        case DUOFORGE_EVENT_WEATHER:
            if (e->cause == DUOFORGE_CAUSE_NONE && (e->flags & DUOFORGE_EVENT_FLAG_UPKEEP) == 0u &&
                e->detail != DUOFORGE_WEATHER_NONE) {
                return true;
            }
            break;
        default:
            break;
        }
    }
    return statused != 0u;
}

static duoforge_status mr_value(uint32_t classes, uint8_t *out)
{
    if ((classes & MR_TRUE) != 0u) {
        *out = (uint8_t)DFI_MOVE_RESULT_TRUE;
    } else if ((classes & MR_FALSE) != 0u) {
        *out = (uint8_t)DFI_MOVE_RESULT_FALSE;
    } else if ((classes & MR_NULL) != 0u) {
        *out = (uint8_t)DFI_MOVE_RESULT_NULL;
    } else {
        return DUOFORGE_E_UNSUPPORTED;
    }
    return DUOFORGE_OK;
}

/* A [cant] that stops the action at BeforeMove: false; mustrecharge's is null. */
static uint32_t mr_cant_result(const duoforge_event *e)
{
    return e->cause == DUOFORGE_CAUSE_RECHARGE ? DFI_MOVE_RESULT_NULL : DFI_MOVE_RESULT_FALSE;
}

duoforge_status duoforge_move_result(const duoforge_context *ctx, uint32_t user, const duoforge_event *events,
                                     uint32_t count, uint8_t *out_result)
{
    if (ctx == NULL || out_result == NULL || (events == NULL && count != 0u)) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (user >= DFI_POSITIONS_MR) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (!dfi_context_is_pool(ctx)) {
        return DUOFORGE_E_UNSUPPORTED; /* only the POOL kinds carry the tail */
    }
    uint32_t i = 0u;
    while (i < count && !mr_start(&events[i], user)) {
        ++i; /* the lines of other positions before the action (the previous action's last ones) */
    }
    if (i == count) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    const duoforge_event *e0 = &events[i];
    /* BeforeMove stops the action (sleep, freeze, paralysis, flinch, Taunt, Disable, ...): false; mustrecharge's null */
    if (e0->kind == DUOFORGE_EVENT_CANT) {
        *out_result = (uint8_t)mr_cant_result(e0);
        return DUOFORGE_OK;
    }
    if (e0->kind == DUOFORGE_EVENT_CONFUSED) {
        for (uint32_t j = i + 1u; j < count; ++j) {
            if (events[j].kind == DUOFORGE_EVENT_DAMAGE && events[j].cause == DUOFORGE_CAUSE_CONFUSION) {
                *out_result = (uint8_t)DFI_MOVE_RESULT_FALSE; /* it hit itself: BeforeMove false */
                return DUOFORGE_OK;
            }
        }
        i += 1u;
        if (i == count) {
            return DUOFORGE_E_UNSUPPORTED;
        }
        e0 = &events[i];
        if (e0->kind == DUOFORGE_EVENT_CANT) {
            *out_result = (uint8_t)mr_cant_result(e0);
            return DUOFORGE_OK;
        }
    }
    if (e0->kind != DUOFORGE_EVENT_MOVE || e0->id >= DFI_POOL_MOVE_COUNT) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    const bool reflected = e0->cause == DUOFORGE_CAUSE_ABILITY;
    const uint32_t move_id = e0->id;
    const dfi_move_data *md = &dfi_pool_moves[move_id];
    const duoforge_event *body = &events[i + 1u];
    const uint32_t n = count - i - 1u;
    uint32_t inner = 0u;
    bool inner_reflected = true;
    for (uint32_t j = 0u; j < n; ++j) {
        if (body[j].kind == DUOFORGE_EVENT_MOVE) {
            inner += 1u;
            inner_reflected = inner_reflected && body[j].cause == DUOFORGE_CAUSE_ABILITY;
        }
    }
    if (inner != 0u) {
        if (inner != 1u || !inner_reflected || reflected) {
            return DUOFORGE_E_UNSUPPORTED; /* a move another one calls is not modelled here */
        }
        *out_result = (uint8_t)DFI_MOVE_RESULT_FALSE; /* Magic Bounce took it: its TryHit's null, normalised to false */
        return DUOFORGE_OK;
    }
    if ((e0->flags & DUOFORGE_EVENT_FLAG_NOTARGET) != 0u) {
        *out_result = (uint8_t)DFI_MOVE_RESULT_FALSE; /* no target: false */
        return DUOFORGE_OK;
    }
    bool prepared = false;
    bool fired = false;
    for (uint32_t j = 0u; j < n; ++j) {
        prepared = prepared || (body[j].kind == DUOFORGE_EVENT_PREPARE && body[j].position == user);
        fired = fired || body[j].kind == DUOFORGE_EVENT_ANIMATION;
    }
    if (prepared && !fired) {
        *out_result = (uint8_t)DFI_MOVE_RESULT_NULL; /* the charge turn's onTryMove: null */
        return DUOFORGE_OK;
    }
    /* the hit steps of the targets */
    uint32_t classes = 0u;
    uint32_t stopped = 0u;
    bool hit = false;
    bool user_fail = false;
    for (uint32_t j = 0u; j < n; ++j) {
        const duoforge_event *e = &body[j];
        const uint32_t pos = e->position;
        const bool other = pos < DFI_POSITIONS_MR && pos != user;
        switch (e->kind) {
        case DUOFORGE_EVENT_MISS:
            classes |= MR_FALSE;
            stopped |= e->other < DFI_POSITIONS_MR ? 1u << e->other : 0u;
            break;
        case DUOFORGE_EVENT_IMMUNE:
            if (other) {
                classes |= MR_FALSE;
                stopped |= 1u << pos;
            }
            break;
        case DUOFORGE_EVENT_BLOCKED:
            classes |= e->detail == DUOFORGE_FIELD_PSYCHIC_TERRAIN ? MR_FALSE : MR_NULL; /* Protect, Wide Guard: NOT_FAIL */
            stopped |= pos < DFI_POSITIONS_MR ? 1u << pos : 0u;
            break;
        case DUOFORGE_EVENT_CANT:
            if (e->cause == DUOFORGE_CAUSE_ABILITY) {
                classes |= MR_FALSE; /* Armor Tail, Queenly Majesty: onFoeTryMove false */
            }
            break;
        case DUOFORGE_EVENT_ABILITY:
            if (other && e->cause == DUOFORGE_CAUSE_NONE && e->id2 != 0u && mr_absorbs((uint32_t)e->id2 - 1u)) {
                classes |= MR_FALSE;
                stopped |= 1u << pos;
            }
            break;
        case DUOFORGE_EVENT_HEAL:
            if (other && e->cause == DUOFORGE_CAUSE_ABILITY && e->id2 != 0u && mr_absorbs((uint32_t)e->id2 - 1u)) {
                classes |= MR_FALSE;
                stopped |= 1u << pos;
            }
            break;
        case DUOFORGE_EVENT_FLASH_FIRE:
            if (other) {
                classes |= MR_FALSE; /* Flash Fire took the Fire move */
                stopped |= 1u << pos;
            }
            break;
        case DUOFORGE_EVENT_DAMAGE:
            hit = hit || (other && e->cause == DUOFORGE_CAUSE_NONE);
            break;
        case DUOFORGE_EVENT_FAIL:
            if (e->cause == DUOFORGE_CAUSE_NONE) {
                user_fail = user_fail || pos == user; /* a target's -fail is an effect's, not the hit's (Synchronize) */
            }
            break;
        default:
            break;
        }
    }
    if ((e0->flags & DUOFORGE_EVENT_FLAG_MISS) != 0u) {
        classes |= MR_FALSE;
    }
    if (md->category != DFI_CATEGORY_STATUS) {
        /* a damaging move: true for a hit target (spreadDamage returns a number), else the classes of its hit steps */
        if (hit) {
            classes |= MR_TRUE;
        }
        for (uint32_t j = 0u; j < n; ++j) {
            if (body[j].kind == DUOFORGE_EVENT_FAIL && body[j].cause == DUOFORGE_CAUSE_NONE) {
                classes |= MR_FALSE;
            }
        }
        return mr_value(classes, out_result);
    }
    const mr_family family = mr_family_of(move_id, md);
    const bool selfish = mr_selfish(md->target_class);
    uint8_t value = 0u;
    switch (family) {
    case MR_REFUSED:
        return DUOFORGE_E_UNSUPPORTED;
    case MR_UNCLASSIFIED:
        if (user_fail || (classes & MR_FALSE) != 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_FALSE;
        } else if ((classes & MR_NULL) != 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_NULL;
        } else {
            value = (uint8_t)DFI_MOVE_RESULT_UNCLASSIFIED_NOW; /* the handler set no class */
        }
        break;
    case MR_RUNS: {
        const uint32_t runs = user_fail ? DFI_MOVE_RESULT_FALSE : DFI_MOVE_RESULT_TRUE;
        value = (uint8_t)runs;
        break;
    }
    case MR_REACHES: {
        if (user_fail) {
            value = (uint8_t)DFI_MOVE_RESULT_FALSE;
            break;
        }
        const uint32_t target = e0->other;
        const bool reached = target >= DFI_POSITIONS_MR || ((stopped >> target) & 1u) == 0u;
        if (reached && (classes & (MR_FALSE | MR_NULL)) == 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_TRUE;
        } else if (reached) {
            return DUOFORGE_E_UNSUPPORTED; /* reached with a failure beside it: a spread case not mapped */
        } else {
            const uint32_t missed = (classes & MR_FALSE) != 0u ? DFI_MOVE_RESULT_FALSE : DFI_MOVE_RESULT_NULL;
            value = (uint8_t)missed;
        }
        break;
    }
    case MR_HEAL_PULSE:
        if ((classes & MR_FALSE) != 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_FALSE;
        } else if ((classes & MR_NULL) != 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_NULL;
        } else {
            value = (uint8_t)DFI_MOVE_RESULT_TRUE; /* a heal, or full HP: NOT_FAIL, the hit is true */
        }
        break;
    case MR_EFFECT:
    default:
        if (mr_changed(body, n, user, stopped, selfish, md->pseudo_weather == DFI_PSEUDO_WEATHER_TRICK_ROOM)) {
            value = (uint8_t)DFI_MOVE_RESULT_TRUE;
        } else if (user_fail || (classes & MR_FALSE) != 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_FALSE;
        } else if ((classes & MR_NULL) != 0u) {
            value = (uint8_t)DFI_MOVE_RESULT_NULL;
        } else {
            value = (uint8_t)DFI_MOVE_RESULT_FALSE; /* a hit target that nothing changed: false (runMoveEffects) */
        }
        break;
    }
    if (reflected && (value & DFI_MOVE_RESULT_UNCLASSIFIED_NOW) != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* a reflected run the engine does not classify is refused by the engine itself */
    }
    *out_result = value;
    return DUOFORGE_OK;
}

/* ---- the world ---- */

static bool dfi_all_zero(const uint8_t *p, size_t n)
{
    for (size_t i = 0u; i < n; ++i) {
        if (p[i] != 0u) {
            return false;
        }
    }
    return true;
}

/* A member of the encoding, as far as its stats need it. */
static void dfi_member_of(const uint8_t *mb, dfi_member *m)
{
    memset(m, 0, sizeof *m);
    m->species_id = (uint16_t)rd16(mb + DFI_ENC_MEMBER_SPECIES_OFF);
    m->is_mega = mb[DFI_ENC_MEMBER_IS_MEGA_OFF];
    m->nature = mb[DFI_ENC_MEMBER_NATURE_OFF];
    m->item = mb[DFI_ENC_MEMBER_ITEM_OFF];
    memcpy(m->stat_points, mb + DFI_ENC_MEMBER_STAT_POINTS_OFF, DFI_STAT_POINT_COUNT);
}

static duoforge_status dfi_check_picks(const duoforge_context *ctx, const duoforge_public_state *v,
                                       const duoforge_hypothesis *h, uint32_t member_count, uint8_t *out_mask)
{
    uint32_t mask = 0u;
    uint32_t count = 0u;
    for (uint32_t k = 0u; k < DUOFORGE_MAX_ROSTER; ++k) {
        const uint32_t m = h->pick_order[k];
        if (m == DUOFORGE_VIEW_PICK_NONE) {
            continue;
        }
        if (k != count || m >= member_count || ((mask >> m) & 1u) != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        mask |= 1u << m;
        ++count;
    }
    if (v->boundary == DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        if (count != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    } else {
        if (count != ctx->brought_count || (v->foe_seen_mask & ~mask) != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        for (uint32_t k = 0u; k < 2u; ++k) {
            if (v->foe_leads[k] != DUOFORGE_VIEW_PICK_NONE && v->foe_leads[k] != h->pick_order[k]) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
        }
    }
    *out_mask = (uint8_t)mask;
    return DUOFORGE_OK;
}

duoforge_status duoforge_battle_from_view(const duoforge_context *ctx, const duoforge_public_state *view,
                                          const duoforge_hypothesis *hypothesis, duoforge_battle *out)
{
    if (ctx == NULL || view == NULL || hypothesis == NULL || out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (view->revision != DUOFORGE_VIEW_REVISION || hypothesis->revision != DUOFORGE_HYPOTHESIS_REVISION) {
        return DUOFORGE_E_SCHEMA_MISMATCH;
    }
    const size_t n = dfi_state_encoded_size_of(ctx);
    if (view->player >= DUOFORGE_SIDE_COUNT || view->state_size != n || !dfi_all_zero(view->reserved, sizeof view->reserved) ||
        !dfi_all_zero(view->pad, 3u) || !dfi_all_zero(view->state + n, DUOFORGE_VIEW_STATE_MAX - n) ||
        hypothesis->reserved0 != 0u || !dfi_all_zero(hypothesis->reserved1, 6u) ||
        !dfi_all_zero(hypothesis->reserved2, 4u)) {
        return DUOFORGE_E_MALFORMED;
    }
    if (!dfi_context_fingerprint_matches(ctx, view->state + DFI_ENC_FINGERPRINT_OFF)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    memcpy(s, view->state, n);
    const uint32_t player = view->player;
    const uint32_t foe = player ^ 1u;
    uint8_t *fs = side_at(s, foe);
    const uint32_t member_count = fs[DFI_ENC_SIDE_MEMBER_COUNT_OFF];
    if (member_count > DUOFORGE_MAX_ROSTER) {
        return DUOFORGE_E_MALFORMED;
    }
    for (uint32_t m = 0u; m < member_count; ++m) {
        uint32_t sp[DFI_STAT_POINT_COUNT];
        for (uint32_t i = 0u; i < DFI_STAT_POINT_COUNT; ++i) {
            sp[i] = hypothesis->stat_points[m][i];
        }
        if (!dfi_stat_points_valid(sp)) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    uint8_t brought = 0u;
    const duoforge_status picks = dfi_check_picks(ctx, view, hypothesis, member_count, &brought);
    if (picks != DUOFORGE_OK) {
        return picks;
    }
    /* the RNG of a world: seeded with (0, 0) */
    dfi_rng rng;
    dfi_rng_seed(&rng, 0u, 0u);
    wr64(s + DFI_ENC_RNG_STATE_OFF, rng.state);
    wr64(s + DFI_ENC_RNG_INC_OFF, rng.inc);
    wr64(s + DFI_ENC_RNG_DRAWS_OFF, rng.draws);
    /* the foe's picks and members */
    fs[DFI_ENC_SIDE_BROUGHT_OFF] = brought;
    memcpy(fs + DFI_ENC_SIDE_ORDER_OFF, hypothesis->pick_order, DUOFORGE_MAX_ROSTER);
    if (dfi_kind_limits_of(ctx->data_kind).pool_rules) {
        /* the foe's party_order: the actives of the view, the bench from the hypothesis (decision 0023), never the true state */
        const duoforge_status ps = dfi_view_world_foe_party(s, foe, brought, hypothesis->pick_order);
        if (ps != DUOFORGE_OK) {
            return ps;
        }
    }
    const uint32_t seen = view->foe_seen_mask;
    for (uint32_t m = 0u; m < member_count; ++m) {
        uint8_t *mb = member_at(s, foe, m);
        dfi_member mem;
        dfi_member_of(mb, &mem);
        memcpy(mem.stat_points, hypothesis->stat_points[m], DFI_STAT_POINT_COUNT);
        if (!dfi_closure_member_derive(&mem)) {
            return DUOFORGE_E_MALFORMED;
        }
        memcpy(mb + DFI_ENC_MEMBER_STAT_POINTS_OFF, mem.stat_points, DFI_STAT_POINT_COUNT);
        wr16(mb + DFI_ENC_MEMBER_HP_MAX_OFF, mem.hp_max);
        for (uint32_t i = 0u; i < DFI_MEMBER_STAT_COUNT; ++i) {
            wr16(mb + DFI_ENC_MEMBER_STATS_OFF + 2u * i, mem.stats[i]);
        }
        const uint8_t *kb = knowledge_at(s, player, m);
        uint32_t hp = mem.hp_max;
        if (((seen >> m) & 1u) != 0u) {
            uint32_t unused = 0u;
            const uint32_t c = dfi_hp_candidates(kb[0], kb[1], mem.hp_max, UINT32_MAX, &unused);
            if (c == 0u) {
                return DUOFORGE_E_INVALID_ARGUMENT; /* no exact HP shows the display under this maximum HP */
            }
            (void)dfi_hp_candidates(kb[0], kb[1], mem.hp_max, dfi_pick(hypothesis->hp[m], c), &hp);
        }
        wr16(mb + DFI_ENC_MEMBER_HP_OFF, hp);
        const uint32_t moves = mb[DFI_ENC_MEMBER_MOVE_COUNT_OFF];
        for (uint32_t k = 0u; k < moves && k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            uint8_t *mv = mb + DFI_ENC_MOVE_OFF + k * DFI_ENC_MOVE_SIZE;
            const uint32_t used = kb[DFI_ENC_KNOWLEDGE_USED_OFF + k];
            mv[2] = (uint8_t)(used >= mv[3] ? 0u : mv[3] - used); /* wide-operands-reviewed: <= pp_max */
        }
    }
    /* the hidden counters of both sides and the foe's charging targets */
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            uint8_t *mb = member_at(s, side, m);
            if (mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] == DUOFORGE_VIEW_HIDDEN) {
                mb[DFI_ENC_MEMBER_STATUS_COUNTER_OFF] =
                    (uint8_t)(1u + dfi_pick_weighted(hypothesis->sleep[side][m], dfi_sleep_weights, 3u)); /* wide-operands-reviewed: 1..3 */
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            uint8_t *pb = position_at(s, side, p);
            if (pb[DFI_ENC_POS_CONFUSION_OFF] == DUOFORGE_VIEW_HIDDEN) {
                pb[DFI_ENC_POS_CONFUSION_OFF] =
                    (uint8_t)(1u + dfi_pick_weighted(hypothesis->confusion[side][p], dfi_confusion_weights, 5u)); /* wide-operands-reviewed: 1..5 */
            }
            if (side == foe && pb[DFI_ENC_POS_LOCKED_TARGET_OFF] == DUOFORGE_VIEW_HIDDEN_TARGET) {
                const uint32_t occupant = pb[0];
                const uint32_t slot = pb[DFI_ENC_POS_LOCKED_MOVE_OFF];
                if (occupant >= member_count || slot == 0u || slot > DUOFORGE_MAX_MOVE_SLOTS) {
                    return DUOFORGE_E_MALFORMED;
                }
                const uint32_t move = rd16(member_at(s, foe, occupant) + DFI_ENC_MOVE_OFF +
                                           (slot - 1u) * DFI_ENC_MOVE_SIZE);
                if (move >= ctx->move_count) {
                    return DUOFORGE_E_MALFORMED;
                }
                uint8_t cand[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE];
                const uint32_t c = dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + p, cand);
                pb[DFI_ENC_POS_LOCKED_TARGET_OFF] = cand[dfi_pick(hypothesis->charge_target[p], c)];
            }
        }
    }
    const uint32_t qn = s[DFI_ENC_QUEUE_LEN_OFF];
    if (qn > DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_MALFORMED;
    }
    uint32_t pending = 0u;
    uint32_t permutation = 0u;
    uint8_t queue[DFI_QUEUE_CAPACITY * DFI_ENC_QUEUE_RECORD_SIZE] = {0};
    for (uint32_t q = 0u; q < qn; ++q) {
        uint8_t *r = s + DFI_ENC_QUEUE_OFF + q * DFI_ENC_QUEUE_RECORD_SIZE;
        const uint32_t idx = hypothesis->queue_order[q];
        if (idx >= qn || (permutation & (1u << idx)) != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
        permutation |= 1u << idx;
        if (r[0] == DFI_Q_MOVE && r[1] == foe) {
            if (r[2] >= DUOFORGE_ACTIVE_PER_SIDE) {
                return DUOFORGE_E_MALFORMED;
            }
            const duoforge_slot_command *c = &hypothesis->queued[r[2]];
            const uint32_t occupant = position_at(s, foe, r[2])[0];
            if (c->kind != DUOFORGE_SLOT_MOVE || c->mega > 1u || c->reserve != 0u ||
                !dfi_all_zero(c->reserved, 3u) || occupant >= member_count ||
                (c->move_slot >= member_at(s, foe, occupant)[DFI_ENC_MEMBER_MOVE_COUNT_OFF] &&
                 c->move_slot != DUOFORGE_MOVE_SLOT_STRUGGLE && c->move_slot != DUOFORGE_MOVE_SLOT_RECHARGE)) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
            if (c->mega != 0u && member_at(s, foe, occupant)[DFI_ENC_MEMBER_IS_MEGA_OFF] == 0u) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
            pending |= 1u << r[2];
            if (r[3] != DUOFORGE_VIEW_HIDDEN || r[4] != DUOFORGE_VIEW_HIDDEN_TARGET) {
                return DUOFORGE_E_MALFORMED;
            }
            if (c->move_slot < DUOFORGE_MAX_MOVE_SLOTS) {
                const uint32_t move = rd16(member_at(s, foe, occupant) + DFI_ENC_MOVE_OFF +
                                           c->move_slot * DFI_ENC_MOVE_SIZE);
                if (move >= ctx->move_count) {
                    return DUOFORGE_E_MALFORMED;
                }
                uint8_t targets[4];
                const uint32_t tn = dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + r[2], targets);
                bool found = false;
                for (uint32_t ti = 0u; ti < tn; ++ti) {
                    found = found || targets[ti] == c->target;
                }
                if (!found) {
                    return DUOFORGE_E_INVALID_ARGUMENT;
                }
            } else if (c->target != DUOFORGE_TARGET_NONE) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
            r[3] = c->move_slot;
            r[4] = c->target;
        }
        memcpy(queue + idx * DFI_ENC_QUEUE_RECORD_SIZE, r, DFI_ENC_QUEUE_RECORD_SIZE);
    }
    if (!dfi_all_zero(hypothesis->queue_order + qn, DFI_QUEUE_CAPACITY - qn)) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if ((pending & (1u << p)) == 0u && !dfi_all_zero((const uint8_t *)&hypothesis->queued[p], sizeof hypothesis->queued[p])) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    memcpy(s + DFI_ENC_QUEUE_OFF, queue, sizeof queue);
    struct duoforge_battle world;
    const duoforge_status st = dfi_decode_state(ctx, s, n, &world, NULL);
    if (st != DUOFORGE_OK) {
        return st == DUOFORGE_E_CONTEXT_MISMATCH ? st : DUOFORGE_E_MALFORMED;
    }
    duoforge_public_state checked;
    const duoforge_status cs = duoforge_battle_public(ctx, &world, player, &checked);
    if (cs != DUOFORGE_OK) {
        return cs;
    }
    if (!dfi_bytes_equal((const uint8_t *)view, (const uint8_t *)&checked, sizeof checked)) {
        return DUOFORGE_E_MALFORMED;
    }
    const duoforge_status counter_support = dfi_view_counter_support(ctx, &world, player);
    if (counter_support != DUOFORGE_OK) {
        return counter_support;
    }
    *out = world;
    return DUOFORGE_OK;
}

/* A hypothesis that draws nothing in particular for a world of `view` (duoforge_public_record_check): the middle word of every
 * uniform, the foe's pick order of the context's brought count (the leads, then the members seen, then the others in roster
 * order; none at team selection), its pending commands the first slot at the first target its class allows, the queue in its
 * canonical order, and zero stat points but the HP points of each seen foe member: the first of 0 to 32 under which its shown HP
 * has an exact value. False when the view is not even of the right shape for that (from_view then names it). */
static bool dfi_view_neutral_hypothesis(const duoforge_context *ctx, const duoforge_public_state *view,
                                        duoforge_hypothesis *h)
{
    const size_t n = dfi_state_encoded_size_of(ctx);
    if (view->player >= DUOFORGE_SIDE_COUNT || view->state_size != n) {
        return false;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    memcpy(s, view->state, n);
    const uint32_t player = view->player;
    const uint32_t foe = player ^ 1u;
    const uint32_t member_count = side_at(s, foe)[DFI_ENC_SIDE_MEMBER_COUNT_OFF];
    if (member_count > DUOFORGE_MAX_ROSTER) {
        return false;
    }
    memset(h, 0, sizeof *h);
    h->revision = DUOFORGE_HYPOTHESIS_REVISION;
    const uint64_t middle = (uint64_t)1u << 63;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        h->hp[m] = middle;
        h->sleep[0][m] = middle;
        h->sleep[1][m] = middle;
        h->pick_order[m] = (uint8_t)DUOFORGE_VIEW_PICK_NONE;
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        h->confusion[0][p] = middle;
        h->confusion[1][p] = middle;
        h->charge_target[p] = middle;
    }
    if (view->boundary != DUOFORGE_BOUNDARY_TEAM_SELECTION) {
        uint32_t k = 0u;
        uint32_t used = 0u;
        for (uint32_t i = 0u; i < 2u; ++i) {
            const uint32_t m = view->foe_leads[i];
            if (m < member_count && ((used >> m) & 1u) == 0u && k < ctx->brought_count) {
                h->pick_order[k++] = (uint8_t)m;
                used |= 1u << m;
            }
        }
        for (uint32_t pass = 0u; pass < 2u; ++pass) {
            for (uint32_t m = 0u; m < member_count && k < ctx->brought_count; ++m) {
                const bool seen = ((uint32_t)view->foe_seen_mask >> m & 1u) != 0u;
                if (((used >> m) & 1u) == 0u && (pass == 1u || seen)) {
                    h->pick_order[k++] = (uint8_t)m;
                    used |= 1u << m;
                }
            }
        }
    }
    for (uint32_t m = 0u; m < member_count; ++m) {
        if (((uint32_t)view->foe_seen_mask >> m & 1u) == 0u) {
            continue;
        }
        const uint8_t *kb = knowledge_at(s, player, m);
        for (uint32_t sp = 0u; sp <= 32u; ++sp) {
            dfi_member mem;
            dfi_member_of(member_at(s, foe, m), &mem);
            memset(mem.stat_points, 0, DFI_STAT_POINT_COUNT);
            mem.stat_points[0] = (uint8_t)sp;
            uint32_t unused = 0u;
            if (dfi_closure_member_derive(&mem) &&
                dfi_hp_candidates(kb[0], kb[1], mem.hp_max, UINT32_MAX, &unused) != 0u) {
                h->stat_points[m][0] = (uint8_t)sp;
                break;
            }
        }
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (((uint32_t)view->foe_pending_mask >> p & 1u) == 0u) {
            continue;
        }
        const uint32_t occupant = position_at(s, foe, p)[0];
        if (occupant >= member_count) {
            return false;
        }
        const uint8_t *mb = member_at(s, foe, occupant);
        duoforge_slot_command *c = &h->queued[p];
        c->kind = (uint8_t)DUOFORGE_SLOT_MOVE;
        if (mb[DFI_ENC_MEMBER_MOVE_COUNT_OFF] == 0u) {
            c->move_slot = (uint8_t)DUOFORGE_MOVE_SLOT_STRUGGLE;
            c->target = (uint8_t)DUOFORGE_TARGET_NONE;
            continue;
        }
        const uint32_t move = rd16(mb + DFI_ENC_MOVE_OFF);
        if (move >= ctx->move_count) {
            return false;
        }
        uint8_t targets[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE];
        (void)dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + p, targets);
        c->move_slot = 0u;
        c->target = targets[0];
    }
    for (uint32_t q = 0u; q < view->queue_count && q < DFI_QUEUE_CAPACITY; ++q) {
        h->queue_order[q] = (uint8_t)q;
    }
    return true;
}

duoforge_status duoforge_public_record_check(const duoforge_context *ctx, const duoforge_public_state *record)
{
    if (ctx == NULL || record == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    duoforge_hypothesis h;
    if (!dfi_view_neutral_hypothesis(ctx, record, &h)) {
        return DUOFORGE_E_MALFORMED;
    }
    struct duoforge_battle world;
    return duoforge_battle_from_view(ctx, record, &h, &world);
}

/* ---- the hypothesis of a battle (privileged) ---- */

duoforge_status duoforge_battle_hypothesis(const duoforge_context *ctx, const duoforge_battle *battle,
                                           uint32_t player, duoforge_hypothesis *out)
{
    if (out == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    uint8_t s[DUOFORGE_VIEW_STATE_MAX];
    size_t n = 0u;
    const duoforge_status st = dfi_view_encode(ctx, battle, player, s, &n);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t foe = player ^ 1u;
    const dfi_side *fs = &battle->sides[foe];
    duoforge_hypothesis h;
    memset(&h, 0, sizeof h);
    h.revision = DUOFORGE_HYPOTHESIS_REVISION;
    (void)dfi_encode_unchecked(ctx, battle, s);
    queue_canonical(s, h.queue_order);
    for (uint32_t q = 0u; q < battle->queue_len; ++q) {
        const dfi_queue_record *r = &battle->queue[q];
        if (r->kind == DFI_Q_MOVE && r->side == foe) {
            h.queued[r->slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            h.queued[r->slot].move_slot = r->move_slot;
            h.queued[r->slot].target = r->target;
        }
    }
    memset(h.pick_order, DUOFORGE_VIEW_PICK_NONE, sizeof h.pick_order);
    uint32_t brought = 0u;
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        brought += ((uint32_t)fs->brought_mask >> m) & 1u;
    }
    for (uint32_t k = 0u; k < brought && k < DUOFORGE_MAX_ROSTER; ++k) {
        h.pick_order[k] = fs->brought_order[k];
    }
    for (uint32_t m = 0u; m < fs->member_count && m < DUOFORGE_MAX_ROSTER; ++m) {
        const dfi_member *mem = &fs->members[m];
        memcpy(h.stat_points[m], mem->stat_points, DFI_STAT_POINT_COUNT);
        if ((((uint32_t)battle->sides[player].seen_mask >> m) & 1u) != 0u) {
            const dfi_knowledge *k = &battle->sides[player].knowledge[m];
            uint32_t unused = 0u;
            const uint32_t c = dfi_hp_candidates(k->hp_percent, k->hp_flag, mem->hp_max, UINT32_MAX, &unused);
            for (uint32_t i = 0u; i < c; ++i) {
                uint32_t hp = 0u;
                (void)dfi_hp_candidates(k->hp_percent, k->hp_flag, mem->hp_max, i, &hp);
                if (hp == mem->hp) {
                    h.hp[m] = dfi_word_of(i, c);
                }
            }
        }
    }
    for (uint32_t side = 0u; side < DUOFORGE_SIDE_COUNT; ++side) {
        const dfi_side *sd = &battle->sides[side];
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const dfi_member *mem = &sd->members[m];
            if (mem->status == DFI_STATUS_SLP && mem->status_counter >= 1u && mem->status_counter <= 3u) {
                h.sleep[side][m] = dfi_word_of_weighted(mem->status_counter - 1u, dfi_sleep_weights, 3u);
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_active_slot *pos = &sd->positions[p];
            if (pos->confusion_turns >= 1u && pos->confusion_turns <= 5u) {
                h.confusion[side][p] = dfi_word_of_weighted(pos->confusion_turns - 1u, dfi_confusion_weights, 5u);
            }
            if (side == foe && pos->charge_turns != 0u && pos->occupant < fs->member_count &&
                pos->locked_move >= 1u && pos->locked_move <= DUOFORGE_MAX_MOVE_SLOTS) {
                const uint32_t move = fs->members[pos->occupant].moves[pos->locked_move - 1u].move_id;
                uint8_t cand[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE];
                const uint32_t c =
                    move < ctx->move_count ? dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + p, cand)
                                           : 0u;
                for (uint32_t i = 0u; i < c; ++i) {
                    if (cand[i] == pos->locked_target) {
                        h.charge_target[p] = dfi_word_of(i, c);
                    }
                }
            }
        }
    }
    *out = h;
    return DUOFORGE_OK;
}

/* Neutral spreads are used only to ask the engine for a public domain.
 * Find a compatible HP shape in C; never ask the caller to invert HP rules. */
static duoforge_status neutral(const duoforge_context *ctx, const duoforge_public_state *v,
                                duoforge_hypothesis *h, duoforge_battle *world)
{
    memset(h, 0, sizeof *h);
    h->revision = DUOFORGE_HYPOTHESIS_REVISION;
    memset(h->pick_order, DUOFORGE_VIEW_PICK_NONE, sizeof h->pick_order);
    const uint32_t foe = v->player ^ 1u;
    uint32_t count = 0u;
    uint32_t mask = 0u;
    for (uint32_t k = 0u; k < 2u; ++k) {
        const uint32_t m = v->foe_leads[k];
        if (m >= DUOFORGE_MAX_ROSTER || (mask & (1u << m)) != 0u) {
            return DUOFORGE_E_MALFORMED;
        }
        h->pick_order[count++] = (uint8_t)m;
        mask |= 1u << m;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        if ((v->foe_seen_mask & (1u << m)) != 0u && (mask & (1u << m)) == 0u) {
            h->pick_order[count++] = (uint8_t)m;
        }
    }
    if (count != ctx->brought_count) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const uint8_t *mb = v->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                            DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
        const uint8_t *kb = v->state + DFI_ENC_SIDE_OFF + v->player * DFI_ENC_SIDE_SIZE +
                            DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
        if ((v->foe_seen_mask & (1u << m)) == 0u) {
            continue;
        }
        bool fits = false;
        for (uint32_t hp_points = 0u; hp_points <= 32u; ++hp_points) {
            dfi_member mem;
            dfi_member_of(mb, &mem);
            memset(mem.stat_points, 0, sizeof mem.stat_points);
            mem.stat_points[0] = (uint8_t)hp_points;
            uint32_t hp = 0u;
            if (dfi_closure_member_derive(&mem) && dfi_hp_candidates(kb[0], kb[1], mem.hp_max, 0u, &hp) != 0u) {
                h->stat_points[m][0] = (uint8_t)hp_points;
                fits = true;
                break;
            }
        }
        if (!fits) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    const uint32_t qn = v->state[DFI_ENC_QUEUE_LEN_OFF];
    if (qn > DFI_QUEUE_CAPACITY) {
        return DUOFORGE_E_MALFORMED;
    }
    for (uint32_t q = 0u; q < qn; ++q) {
        h->queue_order[q] = (uint8_t)q;
        const uint8_t *r = v->state + DFI_ENC_QUEUE_OFF + q * DFI_ENC_QUEUE_RECORD_SIZE;
        if (r[0] == DFI_Q_MOVE && r[1] == foe) {
            if (r[2] >= 2u) {
                return DUOFORGE_E_MALFORMED;
            }
            const uint8_t *pos = v->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                                 DFI_ENC_SIDE_POS_OFF + r[2] * DFI_ENC_POS_SIZE;
            if (pos[0] >= DUOFORGE_MAX_ROSTER) {
                return DUOFORGE_E_MALFORMED;
            }
            const uint8_t *mb = v->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                                DFI_ENC_SIDE_MEMBERS_OFF + pos[0] * DFI_ENC_MEMBER_SIZE;
            const uint32_t move = rd16(mb + DFI_ENC_MOVE_OFF);
            if (move >= ctx->move_count) {
                return DUOFORGE_E_MALFORMED;
            }
            uint8_t targets[4];
            (void)dfi_target_candidates(ctx->move_target_classes[move], foe * 2u + r[2], targets);
            h->queued[r[2]].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            h->queued[r[2]].target = targets[0];
        }
    }
    return duoforge_battle_from_view(ctx, v, h, world);
}

duoforge_status duoforge_public_queue_mask(const duoforge_context *ctx, const duoforge_public_state *turn_start,
                                           const duoforge_public_state *view, uint8_t *mask)
{
    if (ctx == NULL || turn_start == NULL || view == NULL || mask == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (turn_start->revision != DUOFORGE_VIEW_REVISION || view->revision != DUOFORGE_VIEW_REVISION) {
        return DUOFORGE_E_SCHEMA_MISMATCH;
    }
    if (turn_start->player >= DUOFORGE_SIDE_COUNT || view->player >= DUOFORGE_SIDE_COUNT ||
        turn_start->state_size != dfi_state_encoded_size_of(ctx) || view->state_size != dfi_state_encoded_size_of(ctx) ||
        !dfi_all_zero(view->reserved, sizeof view->reserved) || !dfi_all_zero(view->pad, sizeof view->pad) ||
        !dfi_all_zero(turn_start->reserved, sizeof turn_start->reserved) || !dfi_all_zero(turn_start->pad, sizeof turn_start->pad) ||
        !dfi_all_zero(view->state + view->state_size, DUOFORGE_VIEW_STATE_MAX - view->state_size) ||
        !dfi_all_zero(turn_start->state + turn_start->state_size, DUOFORGE_VIEW_STATE_MAX - turn_start->state_size)) {
        return DUOFORGE_E_MALFORMED;
    }
    if (!dfi_context_fingerprint_matches(ctx, view->state + DFI_ENC_FINGERPRINT_OFF) ||
        !dfi_context_fingerprint_matches(ctx, turn_start->state + DFI_ENC_FINGERPRINT_OFF)) {
        return DUOFORGE_E_CONTEXT_MISMATCH;
    }
    if (view->boundary != DUOFORGE_BOUNDARY_PIVOT || turn_start->boundary != DUOFORGE_BOUNDARY_TURN ||
        view->player != turn_start->player || view->turn != turn_start->turn || view->epoch <= turn_start->epoch) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    duoforge_hypothesis h;
    struct duoforge_battle world;
    duoforge_status st = neutral(ctx, view, &h, &world);
    if (st != DUOFORGE_OK) {
        return st;
    }
    st = neutral(ctx, turn_start, &h, &world);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const uint32_t foe = view->player ^ 1u;
    duoforge_factored_domain d;
    st = duoforge_battle_factored(ctx, &world, foe, &d);
    if (st != DUOFORGE_OK) {
        return st;
    }
    if (d.kind != DUOFORGE_CHOICE_SLOTS) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    uint8_t result[DUOFORGE_MAX_SLOT_OPTIONS * DUOFORGE_MAX_SLOT_OPTIONS] = {0};
    for (uint32_t i = 0u; i < d.slot_count[0]; ++i) {
        for (uint32_t j = 0u; j < d.slot_count[1]; ++j) {
            bool agrees = ((d.allowed[i] >> j) & 1u) != 0u;
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE && agrees; ++p) {
                const duoforge_slot_command *c = &d.slots[p][p == 0u ? i : j];
                const uint8_t *old = turn_start->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                                    DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
                const uint8_t *now = view->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                                    DFI_ENC_SIDE_POS_OFF + p * DFI_ENC_POS_SIZE;
                const bool same = dfi_bytes_equal(old, now, 5u); /* occupant and activation id */
                if (c->kind == DUOFORGE_SLOT_SWITCH && same) {
                    agrees = false;
                }
                if (same && old[0] < DUOFORGE_MAX_ROSTER) {
                    const uint32_t m = old[0];
                    const uint8_t *before = turn_start->state + DFI_ENC_SIDE_OFF + view->player * DFI_ENC_SIDE_SIZE +
                                           DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
                    const uint8_t *after = view->state + DFI_ENC_SIDE_OFF + view->player * DFI_ENC_SIDE_SIZE +
                                          DFI_ENC_SIDE_KNOWLEDGE_OFF + m * DFI_ENC_KNOWLEDGE_SIZE;
                    for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
                        if (after[DFI_ENC_KNOWLEDGE_USED_OFF + k] > before[DFI_ENC_KNOWLEDGE_USED_OFF + k] &&
                            (c->kind != DUOFORGE_SLOT_MOVE || c->move_slot != k)) {
                            agrees = false;
                        }
                    }
                    const uint8_t *bm = turn_start->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                                       DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
                    const uint8_t *am = view->state + DFI_ENC_SIDE_OFF + foe * DFI_ENC_SIDE_SIZE +
                                       DFI_ENC_SIDE_MEMBERS_OFF + m * DFI_ENC_MEMBER_SIZE;
                    if (bm[DFI_ENC_MEMBER_IS_MEGA_OFF] == 0u && am[DFI_ENC_MEMBER_IS_MEGA_OFF] != 0u && c->mega == 0u) {
                        agrees = false;
                    }
                }
            }
            result[i * DUOFORGE_MAX_SLOT_OPTIONS + j] = agrees ? 1u : 0u;
        }
    }
    memcpy(mask, result, sizeof result);
    return DUOFORGE_OK;
}
