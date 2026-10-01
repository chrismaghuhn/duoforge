/*
 * duoforge.bench.tally: the action tally (docs/decisions/0008) on random
 * real-team battles. Every counted choice adds up: commands split into
 * moves, switches, replacements and passes; moves into per-id uses and
 * Struggle, and into foe, ally and no target; leads two per team
 * selection. A known move command counts its move id, a voluntary switch
 * counts at TURN; a choice that does not fit the boundary is refused and
 * changes nothing.
 */
#include <stdio.h>
#include <string.h>

#include "support/check.h"
#include "support/fixtures.h"
#include "tally.h"

static uint64_t next(uint64_t *s)
{
    *s += 0x9E3779B97F4A7C15u;
    uint64_t z = *s;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static bool sums_hold(const dfb_tally *t)
{
    uint64_t uses = 0u;
    for (uint32_t i = 0u; i < DFB_TALLY_MOVE_IDS; ++i) {
        uses += t->move_uses[i];
    }
    uint64_t leads = 0u;
    for (uint32_t i = 0u; i < DUOFORGE_MAX_ROSTER; ++i) {
        leads += t->leads[i];
    }
    return t->moves + t->switches + t->replacements + t->passes == t->slot_commands &&
           uses + t->struggles == t->moves && t->target_foe + t->target_ally + t->target_none == t->moves &&
           leads == 2u * t->team_selections && t->megas <= t->moves;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.bench.tally");
    duoforge_context *ctx = df_make_context(&df_config_k1);
    static duoforge_side_choice cands[DUOFORGE_MAX_CANDIDATES];
    dfb_tally tally[2];
    dfb_tally_reset(&tally[0]);
    dfb_tally_reset(&tally[1]);
    uint64_t rng = 99u;
    uint64_t counted = 0u;
    bool known_move = false;
    bool known_switch = false;
    for (uint64_t seed = 1u; seed <= 8u; ++seed) {
        duoforge_battle_setup s;
        df_setup_teams(&s);
        s.rng_initstate = seed;
        duoforge_battle *b = df_make_battle(ctx, &s);
        for (uint32_t step = 0u; step < 400u; ++step) {
            duoforge_decision_bundle bd;
            memset(&bd, 0, sizeof bd);
            for (uint32_t p = 0u; p < 2u; ++p) {
                duoforge_request rq;
                DF_CHECK(&t, duoforge_battle_request(ctx, b, p, &rq) == DUOFORGE_OK);
                bd.epoch = rq.epoch;
                if (rq.requested == 0u) {
                    continue;
                }
                uint32_t n = 0u;
                DF_CHECK(&t, duoforge_battle_candidates(ctx, b, p, cands, DUOFORGE_MAX_CANDIDATES, &n) ==
                                 DUOFORGE_OK && n > 0u);
                const duoforge_side_choice *c = &cands[(size_t)(next(&rng) % n)];
                bd.responses[p] = *c;
                bd.response_mask = (uint8_t)(bd.response_mask | (1u << p));
                /* A known command counts where it belongs. */
                duoforge_observation o;
                DF_CHECK(&t, duoforge_battle_observe(ctx, b, p, &o) == DUOFORGE_OK);
                const dfb_tally before = tally[p];
                DF_CHECK(&t, dfb_tally_choice(ctx, b, p, c, &tally[p]) == DUOFORGE_OK);
                counted += 1u;
                const duoforge_slot_command *k0 = &c->slots[0];
                if (c->kind == DUOFORGE_CHOICE_SLOTS && k0->kind == DUOFORGE_SLOT_MOVE &&
                    k0->move_slot < DUOFORGE_MAX_MOVE_SLOTS) {
                    const uint32_t id = o.sides[p].members[o.sides[p].occupant[0]].move_ids[k0->move_slot];
                    DF_CHECK(&t, tally[p].move_uses[id] > before.move_uses[id]);
                    known_move = true;
                }
                if (c->kind == DUOFORGE_CHOICE_SLOTS && k0->kind == DUOFORGE_SLOT_SWITCH &&
                    o.boundary_kind == DUOFORGE_BOUNDARY_TURN) {
                    DF_CHECK(&t, tally[p].switches > before.switches);
                    known_switch = true;
                }
                /* A team selection at a later boundary does not fit. */
                if (c->kind == DUOFORGE_CHOICE_SLOTS) {
                    duoforge_side_choice wrong;
                    memset(&wrong, 0, sizeof wrong);
                    wrong.kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
                    const dfb_tally kept = tally[p];
                    DF_CHECK(&t, dfb_tally_choice(ctx, b, p, &wrong, &tally[p]) == DUOFORGE_E_INVALID_ARGUMENT &&
                                     memcmp(&kept, &tally[p], sizeof kept) == 0);
                }
            }
            if (bd.response_mask == 0u) {
                break; /* TERMINAL */
            }
            duoforge_step_result res;
            if (!DF_CHECK(&t, duoforge_battle_step(ctx, b, &bd, &res) == DUOFORGE_OK)) {
                break;
            }
        }
        duoforge_battle_destroy(b);
    }
    DF_CHECK(&t, tally[0].choices + tally[1].choices == counted && counted > 0u);
    DF_CHECK(&t, sums_hold(&tally[0]) && sums_hold(&tally[1]));
    DF_CHECK(&t, tally[0].team_selections == 8u && tally[1].team_selections == 8u);
    DF_CHECK(&t, known_move && known_switch && tally[0].megas + tally[1].megas > 0u &&
                     tally[0].replacements + tally[1].replacements > 0u);
    dfb_tally sum;
    dfb_tally_reset(&sum);
    dfb_tally_add(&sum, &tally[0]);
    dfb_tally_add(&sum, &tally[1]);
    DF_CHECK(&t, sum.choices == counted && sums_hold(&sum));
    fprintf(stderr, "  tally: %llu choices, %llu moves, %llu switches, %llu replacements, %llu passes\n",
            (unsigned long long)sum.choices, (unsigned long long)sum.moves, (unsigned long long)sum.switches,
            (unsigned long long)sum.replacements, (unsigned long long)sum.passes);
    duoforge_context_destroy(ctx);
    return df_test_end(&t);
}
