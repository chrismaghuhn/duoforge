/*
 * The domain check of the differential runner (see domain.h).
 */
#include "domain.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

dfr_choice dfd_choice_of(const duoforge_side_choice *candidate)
{
    dfr_choice out;
    memset(&out, 0, sizeof out);
    out.kind = candidate->kind;
    if (candidate->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        out.pick_count = candidate->pick_count;
        memcpy(out.picks, candidate->picks, sizeof out.picks);
    } else {
        for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE; ++k) {
            const duoforge_slot_command *s = &candidate->slots[k];
            out.slots[k] = (df_conf_cmd){s->kind, s->move_slot, s->target, s->mega, s->reserve};
        }
    }
    return out;
}

static int compare_choices(const void *a, const void *b)
{
    return memcmp(a, b, sizeof(dfr_choice));
}

void dfd_compare(dfr_choice *engine, uint32_t engine_count, const dfr_choice *reference, uint32_t reference_count,
                 dfd_diff *out)
{
    memset(out, 0, sizeof *out);
    if (engine_count > 1u) {
        qsort(engine, engine_count, sizeof *engine, compare_choices);
    }
    uint32_t e = 0u;
    uint32_t r = 0u;
    while (e < engine_count || r < reference_count) {
        int order;
        if (e == engine_count) {
            order = 1; /* what is left of the reference is not offered */
        } else if (r == reference_count) {
            order = -1;
        } else {
            order = memcmp(&engine[e], &reference[r], sizeof engine[e]);
        }
        if (order == 0) {
            ++e;
            ++r;
        } else if (order < 0) {
            if (out->engine_only < DFD_EXAMPLES) {
                out->engine_examples[out->engine_only] = engine[e];
            }
            out->engine_only += 1u;
            ++e;
        } else {
            if (out->reference_only < DFD_EXAMPLES) {
                out->reference_examples[out->reference_only] = reference[r];
            }
            out->reference_only += 1u;
            ++r;
        }
    }
}

/* One slot command as text: "move 1 -> 2 mega", "switch 3", "pass", "none". */
static int format_command(char *out, size_t cap, const df_conf_cmd *c)
{
    switch (c->kind) {
    case DUOFORGE_SLOT_MOVE:
        if (c->target == DUOFORGE_TARGET_NONE) {
            return snprintf(out, cap, "move %u -> none%s", (unsigned)c->move_slot, c->mega != 0u ? " mega" : "");
        }
        return snprintf(out, cap, "move %u -> %u%s", (unsigned)c->move_slot, (unsigned)c->target,
                        c->mega != 0u ? " mega" : "");
    case DUOFORGE_SLOT_SWITCH:
        return snprintf(out, cap, "switch %u", (unsigned)c->reserve);
    case DUOFORGE_SLOT_PASS:
        return snprintf(out, cap, "pass");
    default:
        return snprintf(out, cap, "none");
    }
}

void dfd_format(const dfr_choice *choice, char *out, size_t cap)
{
    if (cap == 0u) {
        return;
    }
    out[0] = '\0';
    if (choice->kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
        size_t n = (size_t)snprintf(out, cap, "team");
        for (uint32_t i = 0u; i < choice->pick_count && i < DUOFORGE_MAX_ROSTER && n < cap; ++i) {
            n += (size_t)snprintf(out + n, cap - n, " %u", (unsigned)choice->picks[i]);
        }
        return;
    }
    size_t n = (size_t)snprintf(out, cap, "slots ");
    for (uint32_t k = 0u; k < DUOFORGE_ACTIVE_PER_SIDE && n < cap; ++k) {
        if (k > 0u) {
            n += (size_t)snprintf(out + n, cap - n, ", ");
        }
        if (n < cap) {
            n += (size_t)format_command(out + n, cap - n, &choice->slots[k]);
        }
    }
}
