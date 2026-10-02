/*
 * duoforge.state.pool_g8 (white-box): step G8 of the content expansion, Throat Chop and Psychic Noise's Heal
 * Block, in the POOL state tail (decision 0015 section 7) and in the request.
 *
 * The recorded battles (g8_throat_chop, g8_heal_block, g8_heal_block_pair under "data": "pool") are replayed
 * through the step with the reference's draws, as in duoforge.reference.conformance_pool_data, which compares
 * everything the reference shows. Here the state that the reference does not show is read: the tail counters after
 * each turn (what a step starts, what the residual counts down, what a faint clears), and the request that the
 * engine offers while a lockout or a Heal Block holds, against what the same battle's Showdown requests allowed
 * (the differential domain check of the random battles is documented in the step's report).
 *
 * Also: dfi_place and dfi_vacate clear the position's tail and the occupant's Soak type (a switch ends every
 * volatile), a lockout or a block on a position of the other side is not touched, and two Heal Blocks that end in
 * one residual at equal Speed are ordered by a SPEED_TIE draw (the reference shuffles them and the two -end lines
 * show the outcome); both orders are tested, against the reference in the recorded tie_a and tie_b battles.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "data/pool_tables.h"
#include "reference/conformance_pool.h"
#include "state/battle_internal.h"
#include "state/identity.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"

static void build_setup(const df_conf_battle *cb, duoforge_battle_setup *s)
{
    memset(s, 0, sizeof *s);
    s->rng_initstate = 1u;
    s->rng_initseq = 2u;
    for (uint32_t side = 0; side < 2u; ++side) {
        s->sides[side].member_count = cb->member_count;
        for (uint32_t m = 0; m < cb->member_count; ++m) {
            const df_conf_member *src = &cb->members[side][m];
            duoforge_member_setup *dst = &s->sides[side].members[m];
            dst->species_id = src->species;
            dst->gender = src->gender;
            dst->nature = src->nature;
            for (uint32_t i = 0; i < 6u; ++i) {
                dst->stat_points[i] = src->sp[i];
            }
            dst->ability = src->ability;
            dst->item = src->item;
            dst->move_count = src->move_count;
            for (uint32_t k = 0; k < src->move_count; ++k) {
                dst->moves[k].move_id = src->moves[k];
            }
        }
    }
}

static void bundle_of(const df_conf_step *st, const duoforge_battle *b, duoforge_decision_bundle *bd)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = (uint8_t)(st->answered0 | (st->answered1 << 1u)); /* wide-operands-reviewed */
    for (uint32_t s = 0; s < 2u; ++s) {
        if ((s == 0u && !st->answered0) || (s == 1u && !st->answered1)) {
            continue;
        }
        duoforge_side_choice *r = &bd->responses[s];
        r->epoch = b->request_epoch;
        r->side = (uint8_t)s;
        if (st->team) {
            r->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
            r->pick_count = 4u;
            for (uint32_t i = 0; i < 4u; ++i) {
                r->picks[i] = st->picks[s][i];
            }
        } else {
            r->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
            for (uint32_t k = 0; k < 2u; ++k) {
                const df_conf_cmd *c = &st->cmds[s][k];
                r->slots[k] = (duoforge_slot_command){c->kind, c->move_slot, c->target, c->mega, c->reserve, {0u, 0u, 0u}};
            }
        }
    }
}

static const df_conf_battle *find(const char *name)
{
    for (size_t i = 0; i < sizeof conf_battles / sizeof conf_battles[0]; ++i) {
        if (strcmp(conf_battles[i].name, name) == 0) {
            return &conf_battles[i];
        }
    }
    return NULL;
}

/* The battle `name` after its first `steps` steps (the reference's draws as the tape); NULL when it fails. */
static duoforge_battle *replay(df_test *t, const duoforge_context *ctx, const char *name, uint32_t steps)
{
    const df_conf_battle *cb = find(name);
    if (!DF_CHECK(t, cb != NULL && steps <= cb->step_count)) {
        return NULL;
    }
    duoforge_battle_setup setup;
    build_setup(cb, &setup);
    duoforge_battle *b = NULL;
    if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
        return NULL;
    }
    for (uint32_t si = 0u; si < steps; ++si) {
        const df_conf_step *st = &cb->steps[si];
        duoforge_decision_bundle bd;
        bundle_of(st, b, &bd);
        duoforge_step_result res;
        uint32_t used = 0xFFFFFFFFu;
        const duoforge_status status =
            dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res);
        if (!DF_CHECK(t, status == DUOFORGE_OK && used == st->tape_len)) {
            fprintf(stderr, "  %s step %u: %s\n", name, si, duoforge_status_name(status));
            duoforge_battle_destroy(b);
            return NULL;
        }
    }
    DF_CHECK(t, duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    return b;
}

static const dfi_tail_pos *tail_at(const duoforge_battle *b, uint32_t side, uint32_t slot)
{
    return &b->tail.sides[side].positions[slot];
}

static void expect_tail(df_test *t, const duoforge_battle *b, uint32_t side, uint32_t slot, uint32_t throat_chop,
                        uint32_t heal_block, const char *what)
{
    const dfi_tail_pos *p = tail_at(b, side, slot);
    if (!DF_CHECK(t, p->throat_chop_turns == throat_chop && p->heal_block_turns == heal_block &&
                         p->last_move == 0u && p->encore_slot == 0u && p->encore_turns == 0u)) {
        fprintf(stderr, "  %s: throat chop %u (want %u), heal block %u (want %u)\n", what, p->throat_chop_turns,
                throat_chop, p->heal_block_turns, heal_block);
    }
}

/* What the engine offers a slot of `player`: how many candidates use the move slot `move_slot` for the slot `slot`,
 * and how many use Struggle. */
typedef struct offered {
    uint32_t count;
    uint32_t of_move_slot;
    uint32_t struggle;
} offered;

static offered offered_for(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint32_t player,
                           uint32_t slot, uint32_t move_slot)
{
    static duoforge_side_choice buf[DUOFORGE_MAX_CANDIDATES];
    offered o = {0u, 0u, 0u};
    uint32_t count = 0u;
    if (!DF_CHECK(t, duoforge_battle_candidates(ctx, b, player, buf, DUOFORGE_MAX_CANDIDATES, &count) == DUOFORGE_OK)) {
        return o;
    }
    o.count = count;
    for (uint32_t i = 0u; i < count; ++i) {
        const duoforge_slot_command *c = &buf[i].slots[slot];
        if (c->kind == (uint8_t)DUOFORGE_SLOT_MOVE) {
            o.of_move_slot += c->move_slot == move_slot ? 1u : 0u;
            o.struggle += c->move_slot == DUOFORGE_MOVE_SLOT_STRUGGLE ? 1u : 0u;
        }
    }
    return o;
}

/* The public view extension (decision 0018) after each step of the recorded battles: for every step, which positions
 * (bit = side * 2 + slot) have Throat Chop and which have Heal Block. The rows are what the protocol lines say alone
 * (a -start|X|Throat Chop|[silent] or -start|X|move: Heal Block sets it, the matching -end, a switch, a drag or a
 * faint of the position clears it: decision 0018 section 6.1); tools/reference/test_trace_to_c.py derives them
 * from the committed traces and requires this table to be exactly that. */
static const struct {
    const char *battle;
    uint32_t step;
    uint32_t throat_chop;
    uint32_t heal_block;
} view_ext_rows[] = {
    {"g8_throat_chop", 0u, 0x0u, 0x0u},
    {"g8_throat_chop", 1u, 0xcu, 0x0u},
    {"g8_throat_chop", 2u, 0x0u, 0x0u},
    {"g8_throat_chop", 3u, 0x0u, 0x0u},
    {"g8_throat_chop", 4u, 0x0u, 0x0u},
    {"g8_throat_chop", 5u, 0x0u, 0x0u},
    {"g8_throat_chop", 6u, 0x0u, 0x0u},
    {"g8_throat_chop", 7u, 0x0u, 0x0u},
    {"g8_heal_block", 0u, 0x0u, 0x0u},
    {"g8_heal_block", 1u, 0x0u, 0x4u},
    {"g8_heal_block", 2u, 0x0u, 0x8u},
    {"g8_heal_block", 3u, 0x0u, 0x0u},
    {"g8_heal_block", 4u, 0x0u, 0x0u},
    {"g8_heal_block", 5u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 0u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 1u, 0x0u, 0x5u},
    {"g8_heal_block_pair", 2u, 0x0u, 0x5u},
    {"g8_heal_block_pair", 3u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 4u, 0x0u, 0x0u},
    {"g8_heal_block_pair", 5u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 0u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 1u, 0x0u, 0x5u},
    {"g8_heal_block_tie_a", 2u, 0x0u, 0x5u},
    {"g8_heal_block_tie_a", 3u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 4u, 0x0u, 0x0u},
    {"g8_heal_block_tie_a", 5u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 0u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 1u, 0x0u, 0x5u},
    {"g8_heal_block_tie_b", 2u, 0x0u, 0x5u},
    {"g8_heal_block_tie_b", 3u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 4u, 0x0u, 0x0u},
    {"g8_heal_block_tie_b", 5u, 0x0u, 0x0u},
};

/* Both viewers' extension after every step of every battle of the table equals the expected one byte for byte:
 * revision, viewer, epoch, the two supported bits, the two position bits of the rows and nothing else (the
 * hidden counters never show; Throat Chop is public, so the foe sees it as well), and the two viewers' position
 * sections are the same. */
static void check_view_ext(df_test *t, const duoforge_context *ctx)
{
    static const char *const names[] = {"g8_throat_chop", "g8_heal_block", "g8_heal_block_pair", "g8_heal_block_tie_a",
                                        "g8_heal_block_tie_b"};
    uint32_t compared = 0u;
    for (size_t n = 0u; n < sizeof names / sizeof names[0]; ++n) {
        const df_conf_battle *cb = find(names[n]);
        if (!DF_CHECK(t, cb != NULL)) {
            continue;
        }
        duoforge_battle_setup setup;
        build_setup(cb, &setup);
        duoforge_battle *b = NULL;
        if (!DF_CHECK(t, duoforge_battle_create(ctx, &setup, &b) == DUOFORGE_OK && b != NULL)) {
            continue;
        }
        for (uint32_t si = 0u; si < cb->step_count; ++si) {
            const df_conf_step *st = &cb->steps[si];
            duoforge_decision_bundle bd;
            bundle_of(st, b, &bd);
            duoforge_step_result res;
            uint32_t used = 0u;
            if (!DF_CHECK(t, dfi_battle_step_tape(ctx, b, &bd, &conf_tape[st->tape_off], st->tape_len, &used, &res) ==
                                 DUOFORGE_OK)) {
                break;
            }
            uint32_t tc = 0xFFu;
            uint32_t hb = 0xFFu;
            for (size_t r = 0u; r < sizeof view_ext_rows / sizeof view_ext_rows[0]; ++r) {
                if (strcmp(view_ext_rows[r].battle, names[n]) == 0 && view_ext_rows[r].step == si) {
                    tc = view_ext_rows[r].throat_chop;
                    hb = view_ext_rows[r].heal_block;
                }
            }
            if (!DF_CHECK(t, tc != 0xFFu && hb != 0xFFu)) {
                fprintf(stderr, "  %s step %u: no row\n", names[n], si);
                continue;
            }
            duoforge_observation_ext ext[2];
            for (uint32_t viewer = 0u; viewer < 2u; ++viewer) {
                duoforge_observation ob;
                memset(&ob, 0, sizeof ob);
                DF_CHECK(t, duoforge_battle_observe_ext(ctx, b, viewer, &ext[viewer]) == DUOFORGE_OK &&
                                duoforge_battle_observe(ctx, b, viewer, &ob) == DUOFORGE_OK);
                duoforge_observation_ext want;
                memset(&want, 0, sizeof want);
                want.revision = (uint8_t)DUOFORGE_OBSERVATION_EXT_REVISION;
                want.player = (uint8_t)viewer;
                want.epoch = ob.epoch;
                want.supported = ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK) |
                                 ((uint64_t)1u << DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD); /* step G7's bit */
                for (uint32_t flat = 0u; flat < 4u; ++flat) {
                    want.sides[flat / 2u].positions[flat % 2u].volatiles =
                        (((tc >> flat) & 1u) != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_THROAT_CHOP : 0u) |
                        (((hb >> flat) & 1u) != 0u ? (uint32_t)DUOFORGE_POSITION_EXT_HEAL_BLOCK : 0u);
                }
                if (!DF_CHECK(t, memcmp(&ext[viewer], &want, sizeof want) == 0)) {
                    fprintf(stderr, "  %s step %u viewer %u: the extension differs from the protocol's (want Throat Chop "
                                    "0x%x, Heal Block 0x%x)\n",
                            names[n], si, viewer, tc, hb);
                }
                compared += 1u;
            }
            DF_CHECK(t, memcmp(ext[0].sides, ext[1].sides, sizeof ext[0].sides) == 0);
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK_EQ_U64(t, compared, 2u * (uint32_t)(sizeof view_ext_rows / sizeof view_ext_rows[0]));
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_g8");
    (void)conf_events;
    duoforge_context *kp = df_make_context(&df_config_pool);

    /* Throat Chop (g8_throat_chop, steps: 0 team preview, 1 turn 1, 2 turn 2, ...). Turn 1: Sneasler's Throat Chop
     * hits Salamence, Kingambit's hits Archaludon (a Choice Scarf holder with Snarl alone). The counter is 2 when set
     * and the residual of the turn counts it down, so the next request has the sound moves barred and the one after
     * has them back. */
    {
        duoforge_battle *b = replay(&t, kp, "g8_throat_chop", 1u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "before turn 1: Salamence");
            duoforge_battle_destroy(b);
        }
        b = replay(&t, kp, "g8_throat_chop", 2u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 1u, 0u, "after turn 1: Salamence");
            expect_tail(&t, b, 1u, 1u, 1u, 0u, "after turn 1: Archaludon");
            expect_tail(&t, b, 0u, 0u, 0u, 0u, "after turn 1: Sneasler");
            expect_tail(&t, b, 0u, 1u, 0u, 0u, "after turn 1: Kingambit");
            /* Salamence: Hyper Voice (slot 0) is a sound move, Protect (1) and Tailwind (2) are not. Archaludon has
             * Snarl alone: Struggle, and its switches. */
            offered a = offered_for(&t, kp, b, 1u, 0u, 0u);
            DF_CHECK_EQ_U64(&t, a.of_move_slot, 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 1u).of_move_slot != 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 2u).of_move_slot != 0u);
            offered s = offered_for(&t, kp, b, 1u, 1u, 0u);
            DF_CHECK_EQ_U64(&t, s.of_move_slot, 0u);
            DF_CHECK(&t, s.struggle != 0u);
            /* The other side's slots are not touched: Sneasler still has all of its moves. */
            DF_CHECK(&t, offered_for(&t, kp, b, 0u, 0u, 0u).of_move_slot != 0u);
            duoforge_battle_destroy(b);
        }
        b = replay(&t, kp, "g8_throat_chop", 3u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 2: Salamence");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 2: Archaludon");
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 0u).of_move_slot != 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 1u, 0u).of_move_slot != 0u);
            DF_CHECK_EQ_U64(&t, offered_for(&t, kp, b, 1u, 1u, 0u).struggle, 0u);
            duoforge_battle_destroy(b);
        }
        /* Turn 4: Sneasler's Throat Chop into Protect adds nothing, Kingambit's knocks Archaludon out. */
        b = replay(&t, kp, "g8_throat_chop", 5u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 4: Salamence");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 4: the fainted position");
            duoforge_battle_destroy(b);
        }
    }

    /* Heal Block (g8_heal_block): Farigiraf's Psychic Noise hits Ceruledge on turn 1 and Milotic on turn 2. The
     * block is 2 turns: 1 left after the turn it was set in, gone after the next residual. A heal that the block
     * stops is not in the reference's events (the comparison of conformance_pool_data); here the state after
     * each turn and the domain. */
    {
        duoforge_battle *b = replay(&t, kp, "g8_heal_block", 2u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 1u, "after turn 1: Ceruledge");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 1: Milotic");
            /* Ceruledge: Bitter Blade (slot 0, a heal move) is barred; Protect and Swords Dance are not. */
            DF_CHECK_EQ_U64(&t, offered_for(&t, kp, b, 1u, 0u, 0u).of_move_slot, 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 1u).of_move_slot != 0u);
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 2u).of_move_slot != 0u);
            duoforge_battle_destroy(b);
        }
        b = replay(&t, kp, "g8_heal_block", 3u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 2: Ceruledge");
            expect_tail(&t, b, 1u, 1u, 0u, 1u, "after turn 2: Milotic");
            DF_CHECK(&t, offered_for(&t, kp, b, 1u, 0u, 0u).of_move_slot != 0u);
            duoforge_battle_destroy(b);
        }
        /* Turn 3: Ceruledge faints (its position's tail is clear, the block of Milotic ends). */
        b = replay(&t, kp, "g8_heal_block", 4u);
        if (b != NULL) {
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "after turn 3: the fainted Ceruledge");
            expect_tail(&t, b, 1u, 1u, 0u, 0u, "after turn 3: Milotic");
            duoforge_battle_destroy(b);
        }
    }

    /* Two blocks that end in one residual (g8_heal_block_pair): both are set on turn 1 and counted down on turn 1
     * and turn 2, and the end lines come in the order of the holders' Speed (the comparison of
     * conformance_pool_data). */
    {
        duoforge_battle *b = replay(&t, kp, "g8_heal_block_pair", 2u);
        if (b != NULL) {
            expect_tail(&t, b, 0u, 0u, 0u, 1u, "pair, after turn 1: the fast Farigiraf");
            expect_tail(&t, b, 1u, 0u, 0u, 1u, "pair, after turn 1: the slow Farigiraf");
            duoforge_battle_destroy(b);
        }
        b = replay(&t, kp, "g8_heal_block_pair", 4u);
        if (b != NULL) {
            expect_tail(&t, b, 0u, 0u, 0u, 0u, "pair, after turn 2: the fast Farigiraf");
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "pair, after turn 2: the slow Farigiraf");
            duoforge_battle_destroy(b);
        }
    }

    /* A switch (dfi_vacate, then dfi_place, which clears the same way before it overwrites an occupant) ends every
     * volatile: the position's five tail fields and the leaving member's Soak type are cleared; the other position and
     * the other members' Soak types are not. */
    {
        duoforge_battle *b = replay(&t, kp, "g8_heal_block", 2u);
        if (b != NULL) {
            const uint32_t occupant = b->sides[1].positions[0].occupant;
            const uint32_t other = b->sides[1].positions[1].occupant;
            DF_CHECK(&t, occupant < DUOFORGE_MAX_ROSTER && other < DUOFORGE_MAX_ROSTER && occupant != other);
            b->tail.sides[1].positions[0] = (dfi_tail_pos){1u, 2u, 3u, 1u, 1u};
            b->tail.sides[1].positions[1] = (dfi_tail_pos){2u, 0u, 0u, 2u, 1u};
            b->tail.sides[1].soak_type[occupant] = 5u;
            b->tail.sides[1].soak_type[other] = 7u;
            b->tail.sides[0].positions[0].heal_block_turns = 1u;
            DF_CHECK(&t, dfi_vacate(b, (dfi_position_id){1u, 0u}) == DUOFORGE_OK);
            expect_tail(&t, b, 1u, 0u, 0u, 0u, "vacated position");
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].soak_type[occupant], 0u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].soak_type[other], 7u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[1].throat_chop_turns, 2u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[1].positions[1].heal_block_turns, 1u);
            DF_CHECK_EQ_U64(&t, b->tail.sides[0].positions[0].heal_block_turns, 1u);
            duoforge_battle_destroy(b);
        }
    }

    /* Equal Speed (g8_heal_block_tie_a: the twin Farigiraf of both sides): two Heal Blocks end in one residual, the
     * reference shuffles their order and the two -end lines show it, so the engine draws the SPEED_TIE and orders the
     * pair by it (the recorded tie_a and tie_b battles are the two orders against the reference's draws). Here: the
     * turn is accepted under every seed of the engine's own generator, always with both lines, and both orders
     * occur (0 keeps the lower position first, 1 swaps). Each side brings its Farigiraf and a Protect user. */
    {
        const df_conf_battle *cb = find("g8_heal_block_tie_a");
        DF_CHECK(&t, cb != NULL);
        uint32_t first_p1 = 0u;
        uint32_t first_p2 = 0u;
        for (uint32_t seed = 1u; cb != NULL && seed <= 24u; ++seed) {
            duoforge_battle_setup setup;
            build_setup(cb, &setup);
            setup.rng_initstate = seed;
            DF_CHECK(&t, setup.sides[0].members[0].species_id == setup.sides[1].members[0].species_id &&
                             setup.sides[0].members[0].nature == setup.sides[1].members[0].nature &&
                             memcmp(setup.sides[0].members[0].stat_points, setup.sides[1].members[0].stat_points, 6u) == 0);
            duoforge_battle *b = NULL;
            DF_CHECK(&t, duoforge_battle_create(kp, &setup, &b) == DUOFORGE_OK && b != NULL);
            if (b == NULL) {
                continue;
            }
            duoforge_decision_bundle bd;
            duoforge_step_result res;
            memset(&bd, 0, sizeof bd);
            bd.epoch = b->request_epoch;
            bd.response_mask = 3u;
            for (uint32_t s = 0u; s < 2u; ++s) {
                duoforge_side_choice *c = &bd.responses[s];
                c->epoch = b->request_epoch;
                c->side = (uint8_t)s;
                c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                c->pick_count = 4u;
                c->picks[0] = 0u;
                c->picks[1] = 2u;
                c->picks[2] = 1u;
                c->picks[3] = 3u;
            }
            DF_CHECK(&t, duoforge_battle_step(kp, b, &bd, &res) == DUOFORGE_OK);
            for (uint32_t turn = 0u; turn < 2u; ++turn) {
                /* Turn 1: both Farigiraf use Psychic Noise at the foe's first position, the others Protect. Turn 2:
                 * every one Protect (move slot 1 of the Farigiraf, 0 of the others). */
                memset(&bd, 0, sizeof bd);
                bd.epoch = b->request_epoch;
                bd.response_mask = 3u;
                for (uint32_t s = 0u; s < 2u; ++s) {
                    duoforge_side_choice *c = &bd.responses[s];
                    c->epoch = b->request_epoch;
                    c->side = (uint8_t)s;
                    c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
                    c->slots[0] = (duoforge_slot_command){
                        (uint8_t)DUOFORGE_SLOT_MOVE, (uint8_t)(turn == 0u ? 0u : 1u),
                        (uint8_t)(turn == 0u ? (s == 0u ? 2u : 0u) : DUOFORGE_TARGET_NONE), 0u, 0u, {0u, 0u, 0u}};
                    c->slots[1] = (duoforge_slot_command){(uint8_t)DUOFORGE_SLOT_MOVE, 0u, (uint8_t)DUOFORGE_TARGET_NONE,
                                                          0u, 0u, {0u, 0u, 0u}};
                }
                static duoforge_event ev_buf[2][DUOFORGE_MAX_EVENTS];
                duoforge_event_buffer buffers[2] = {{ev_buf[0], DUOFORGE_MAX_EVENTS, 0u},
                                                    {ev_buf[1], DUOFORGE_MAX_EVENTS, 0u}};
                const duoforge_status st = duoforge_battle_step_events(kp, b, &bd, &res, buffers);
                if (!DF_CHECK(&t, st == DUOFORGE_OK)) {
                    fprintf(stderr, "  equal Speed, seed %u turn %u: %s\n", seed, turn + 1u, duoforge_status_name(st));
                    break;
                }
                if (turn == 0u) {
                    expect_tail(&t, b, 0u, 0u, 0u, 1u, "equal Speed, after turn 1: p1 Farigiraf");
                    expect_tail(&t, b, 1u, 0u, 0u, 1u, "equal Speed, after turn 1: p2 Farigiraf");
                    continue;
                }
                uint32_t ends = 0u;
                uint32_t first = 0xFFu;
                for (uint32_t i = 0u; i < buffers[0].count; ++i) {
                    const duoforge_event *e = &buffers[0].events[i];
                    if (e->kind == (uint8_t)DUOFORGE_EVENT_VOLATILE_END &&
                        e->detail == (uint8_t)DUOFORGE_VOLATILE_HEAL_BLOCK) {
                        first = ends == 0u ? e->position : first;
                        ends += 1u;
                    }
                }
                DF_CHECK_EQ_U64(&t, ends, 2u);
                first_p1 += first == 0u ? 1u : 0u;
                first_p2 += first == 2u ? 1u : 0u;
                expect_tail(&t, b, 0u, 0u, 0u, 0u, "equal Speed, after turn 2: p1 Farigiraf");
                expect_tail(&t, b, 1u, 0u, 0u, 0u, "equal Speed, after turn 2: p2 Farigiraf");
            }
            duoforge_battle_destroy(b);
        }
        DF_CHECK(&t, first_p1 != 0u && first_p2 != 0u);
        DF_CHECK_EQ_U64(&t, first_p1 + first_p2, 24u);
    }

    check_view_ext(&t, kp);

    duoforge_context_destroy(kp);
    return df_test_end(&t);
}
