/* Decision 0082: independent wire vectors and information-boundary controls. */
#include <string.h>
#include "combat/events.h"
#include "state/observation_digest.h"
#include "state/observation_key.h"
#include "state/closure_member.h"
#include "data/formats/reg-mc/pool_tables.h"
#include "state/knowledge.h"
#include "support/pool.h"
#include "state/request.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/observation_digest_vectors.h"

typedef struct request_fixture {
    duoforge_step_result result;
    duoforge_request request;
    duoforge_observation view;
    duoforge_observation_ext ext;
    duoforge_factored_domain domain;
} request_fixture;

static void make_request(request_fixture *f)
{
    memset(f, 0, sizeof *f);
    f->result.kind = DUOFORGE_STEP_BOUNDARY; f->result.boundary_kind = DUOFORGE_BOUNDARY_TURN; f->result.request_mask = 3u;
    f->request.boundary_kind = DUOFORGE_BOUNDARY_TURN; f->request.requested = 1u; f->request.slot_mask = 1u;
    f->request.candidate_count = 2u;
    f->view.boundary_kind = DUOFORGE_BOUNDARY_TURN; f->view.sides[0].requested_slots = 1u; f->view.sides[1].requested_slots = 2u;
    duoforge_side_view *own = &f->view.sides[0];
    own->member_count = 2u; own->occupant[0] = 0u; own->occupant[1] = DUOFORGE_ROSTER_NONE;
    own->brought_order[0] = 0u; own->brought_order[1] = 1u;
    for (uint32_t j = 2u; j < 6u; ++j) { own->brought_order[j] = DUOFORGE_ROSTER_NONE; }
    duoforge_member_view *m = &own->members[0];
    m->species_id = 0x0123u; m->hp = 150u; m->hp_max = 200u; m->move_ids[0] = 7u; m->move_ids[1] = 8u;
    for (uint32_t j = 0u; j < 5u; ++j) { m->stats[j] = (uint16_t)(101u + j); }
    m->pp[0] = 3u; m->pp[1] = 4u; m->pp_max[0] = 10u; m->pp_max[1] = 20u;
    for (uint32_t j = 0u; j < 6u; ++j) { m->stat_points[j] = (uint8_t)(1u + j); }
    m->move_count = 2u; m->hp_kind = DUOFORGE_HP_EXACT; m->pp_kind = DUOFORGE_PP_EXACT;
    m->location = DUOFORGE_LOCATION_ACTIVE; m->mega_capable = 1u; m->gender = 1u;
    m->nature = 3u; m->ability = 4u; m->item = 5u;
    own->members[1] = *m; own->members[1].species_id = 0x0124u;
    own->members[1].hp = 80u; own->members[1].hp_max = 100u; own->members[1].location = DUOFORGE_LOCATION_BENCH;
    f->ext.revision = DUOFORGE_OBSERVATION_EXT_REVISION;
    f->ext.sides[0].members[0].forme = 0x0102u; f->ext.sides[0].members[1].forme = 0x0102u;
    for (uint32_t p = 0u; p < 2u; ++p) {
        memset(own->positions[p].stages, 6, sizeof own->positions[p].stages);
        own->positions[p].locked_slot = DUOFORGE_MOVE_SLOT_NONE;
        own->positions[p].locked_target = DUOFORGE_TARGET_NONE;
    }
    own->positions[0].confused = 1u; own->positions[0].acted = 1u;
    own->reflect_turns = 3u; own->light_screen_turns = 4u; own->tailwind_turns = 2u;
    f->ext.sides[0].stealth_rock = 1u;
    f->domain.kind = DUOFORGE_CHOICE_SLOTS; f->domain.slot_count[0] = 2u; f->domain.slot_count[1] = 1u;
    f->domain.slots[0][0].kind = DUOFORGE_SLOT_MOVE; f->domain.slots[0][0].target = 2u;
    f->domain.slots[0][1].kind = DUOFORGE_SLOT_SWITCH; f->domain.slots[0][1].reserve = 1u;
    f->domain.allowed[0] = 1u; f->domain.allowed[1] = 1u;
}

static duoforge_status encode_request(const request_fixture *f, uint8_t *out, uint32_t capacity, uint32_t *size)
{
    return dfi_observation_request_encode(&f->result, &f->request, &f->view, &f->ext, &f->domain, out, capacity, size);
}

static void line_vectors(df_test *t)
{
    const dfi_visible_identity identity = {0x0102u, 1u, 1u};
    for (uint32_t i = 0u; i < sizeof df_observation_lines / sizeof df_observation_lines[0]; ++i) {
        uint8_t expected[DFI_OBSERVATION_LINE_MAX]; uint8_t bytes[DFI_OBSERVATION_LINE_MAX];
        const size_t n = strlen(df_observation_lines[i].hex) / 2u;
        DF_CHECK(t, df_hex_to_bytes(df_observation_lines[i].hex, expected, n));
        uint32_t size = 0u;
        DF_CHECK(t, dfi_observation_line_encode(&df_observation_lines[i].event, &identity, bytes, sizeof bytes, &size) == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, size, n); DF_CHECK_BYTES(t, bytes, expected, n, df_observation_lines[i].name);
        uint8_t before[DFI_OBSERVATION_LINE_MAX]; memset(before, 0xA5, sizeof before); memcpy(bytes, before, sizeof bytes);
        DF_CHECK(t, dfi_observation_line_encode(&df_observation_lines[i].event, &identity, bytes, 0u, &size) == DUOFORGE_E_CAPACITY);
        DF_CHECK_BYTES(t, bytes, before, sizeof bytes, "line capacity refusal is atomic");
        /* Every known kind must name an unclassified flag combination,
         * not accept it through a catch-all serialization path. */
        dfi_observation_digest rejected;
        DF_CHECK(t, dfi_observation_digest_init(&rejected, 0u) == DUOFORGE_OK);
        rejected.identity[0] = identity;
        duoforge_event variant = df_observation_lines[i].event; variant.flags = 255u;
        dfi_observation_fold(&rejected, &variant, 0u);
        DF_CHECK(t, rejected.status == DUOFORGE_E_UNSUPPORTED && !rejected.complete);
        DF_CHECK(t, strstr(rejected.reason, df_observation_lines[i].name) != NULL);
    }
    duoforge_event bad = dfi_event_make(44u, 0u); uint8_t bytes[64]; uint32_t size = 0u;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    bad = dfi_event_make(DUOFORGE_EVENT_FAINT, 0u); bad.flags = 1u;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    bad.flags = 0u; bad.cause = 255u;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    bad = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, 0u); bad.detail = 255u;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    /* Speed Swap (step K3, #473; decision 0015 5de): VOLATILE_START detail 16 with cause NONE and the other target is a line;
     * 15 (Focus Energy, not modelled) is refused. */
    bad = dfi_event_make(DUOFORGE_EVENT_VOLATILE_START, 0u); bad.detail = DUOFORGE_VOLATILE_SPEED_SWAP; bad.other = 2u;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    bad.detail = 15u;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    bad = df_observation_lines[1].event;
    DF_CHECK(t, dfi_observation_line_encode(&bad, NULL, bytes, sizeof bytes, &size) == DUOFORGE_E_INVARIANT);
    bad = df_observation_lines[3].event; bad.hp_kind = DUOFORGE_HP_UNKNOWN;
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_INVARIANT);
    DF_CHECK(t, dfi_observation_line_encode(NULL, &identity, bytes, sizeof bytes, &size) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, dfi_observation_line_encode(&bad, &identity, bytes, sizeof bytes, NULL) == DUOFORGE_E_NULL_ARGUMENT);
}

static void request_vectors(df_test *t)
{
    request_fixture f; make_request(&f);
    uint8_t bytes[DFI_OBSERVATION_REQUEST_MAX]; uint8_t expected[DFI_OBSERVATION_REQUEST_MAX];
    const uint32_t expected_size = (uint32_t)(strlen(DF_OBSERVATION_REQUEST_HEX) / 2u);
    DF_CHECK(t, df_hex_to_bytes(DF_OBSERVATION_REQUEST_HEX, expected, expected_size));
    uint32_t size = 0u;
    DF_CHECK(t, encode_request(&f, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, size, expected_size); DF_CHECK_BYTES(t, bytes, expected, size, "independent request whitelist");
    request_fixture hidden = f;
    hidden.result.epoch = 999u; hidden.result.reserved = 255u; hidden.request.epoch = 888u;
    hidden.view.epoch = 777u; hidden.view.reserved = 255u; hidden.view.sides[0].reserved = 255u;
    hidden.view.sides[0].members[0].reserved = 255u;
    memset(&hidden.view.sides[1].members, 0xA5, sizeof hidden.view.sides[1].members);
    memset(hidden.view.sides[1].occupant, 0xA5, sizeof hidden.view.sides[1].occupant);
    memset(&hidden.ext.sides[1], 0xA5, sizeof hidden.ext.sides[1]);
    hidden.ext.epoch = 444u; memset(hidden.ext.reserved0, 0xA5, sizeof hidden.ext.reserved0);
    memset(hidden.ext.reserved1, 0xA5, sizeof hidden.ext.reserved1); hidden.ext.sides[0].reserved = 255u;
    hidden.domain.epoch = 666u; memset(hidden.domain.reserved, 0xA5, sizeof hidden.domain.reserved);
    memset(hidden.domain.slots[0][0].reserved, 0xA5, sizeof hidden.domain.slots[0][0].reserved);
    DF_CHECK(t, encode_request(&hidden, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    DF_CHECK_BYTES(t, bytes, expected, size, "foe particle fields and validation metadata are absent");
    request_fixture changed = f; changed.domain.slots[0][0].move_slot = 1u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    DF_CHECK(t, memcmp(bytes, expected, size) != 0); /* same count, different available move */
    changed = f; changed.request.slot_mask = 2u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    DF_CHECK(t, memcmp(bytes, expected, size) != 0);
    changed = f; changed.view.sides[0].members[0].pp[0] = 2u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    DF_CHECK(t, memcmp(bytes, expected, size) != 0);
    memset(bytes, 0xA5, sizeof bytes); uint8_t before[sizeof bytes]; memcpy(before, bytes, sizeof bytes);
    DF_CHECK(t, encode_request(&f, bytes, expected_size - 1u, &size) == DUOFORGE_E_CAPACITY);
    DF_CHECK_EQ_U64(t, size, expected_size); DF_CHECK_BYTES(t, bytes, before, sizeof bytes, "request capacity refusal is atomic");
    changed = f; changed.result.boundary_kind = 255u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    changed = f; changed.domain.kind = 255u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    changed = f; changed.domain.slot_count[0] = 33u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_INVARIANT);
    changed = f; changed.domain.slots[0][0].kind = 255u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    changed = f; changed.ext.sides[0].positions[0].transform_source = 1u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    changed = f; changed.ext.revision = 2u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_UNSUPPORTED);
    request_fixture maximum = f; maximum.view.sides[0].member_count = DUOFORGE_MAX_ROSTER;
    maximum.domain.slot_count[0] = DUOFORGE_MAX_SLOT_OPTIONS; maximum.domain.slot_count[1] = DUOFORGE_MAX_SLOT_OPTIONS;
    for (uint32_t j = 0u; j < DUOFORGE_MAX_SLOT_OPTIONS; ++j) { maximum.domain.allowed[j] = UINT32_MAX; }
    DF_CHECK(t, encode_request(&maximum, bytes, sizeof bytes, &size) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, size, 874u);
    maximum.view.sides[0].member_count = DUOFORGE_MAX_ROSTER + 1u;
    DF_CHECK(t, encode_request(&maximum, bytes, sizeof bytes, &size) == DUOFORGE_E_INVARIANT);
    changed = f; changed.request.player = 2u;
    DF_CHECK(t, encode_request(&changed, bytes, sizeof bytes, &size) == DUOFORGE_E_INVALID_ARGUMENT);
}

static void stream_vector(df_test *t)
{
    request_fixture f; make_request(&f); dfi_observation_digest digest;
    uint8_t key[32] = {0};
    DF_CHECK(t, !dfi_observation_key_nonzero(key) && !dfi_observation_key_nonzero(NULL));
    for (uint32_t i = 0u; i < sizeof key; ++i) {
        key[i] = 1u; DF_CHECK(t, dfi_observation_key_nonzero(key)); key[i] = 0u;
    }
    DF_CHECK(t, dfi_observation_digest_init(&digest, 0u) == DUOFORGE_OK);
    digest.identity[1] = (dfi_visible_identity){0x0102u, 1u, 1u};
    for (uint32_t i = 0u; i < 3u; ++i) { dfi_observation_fold(&digest, &df_observation_lines[i].event, i); }
    dfi_observation_finish_view(&digest, &f.result, &f.request, &f.view, &f.ext, &f.domain, 3u);
    uint8_t expected[32]; DF_CHECK(t, df_hex_to_bytes(DF_OBSERVATION_STREAM_SHA256, expected, sizeof expected));
    DF_CHECK(t, digest.status == DUOFORGE_OK && digest.complete); DF_CHECK_EQ_U64(t, digest.rows, 3u);
    DF_CHECK_BYTES(t, digest.digest, expected, sizeof expected, "independent framed SHA-256 vector");
    DF_CHECK(t, dfi_observation_digest_init(&digest, 2u) == DUOFORGE_E_INVALID_ARGUMENT);
    DF_CHECK(t, !digest.complete && strstr(digest.reason, "observation_viewer") != NULL);
    DF_CHECK(t, dfi_observation_digest_init(NULL, 0u) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, dfi_observation_digest_init(&digest, 0u) == DUOFORGE_OK);
    duoforge_event unknown = dfi_event_make(44u, 0u);
    dfi_observation_fold(&digest, &unknown, 0u);
    DF_CHECK(t, digest.status == DUOFORGE_E_UNSUPPORTED && strstr(digest.reason, "UNKNOWN") != NULL);
    dfi_observation_finish_view(&digest, &f.result, &f.request, &f.view, &f.ext, &f.domain, 1u);
    DF_CHECK(t, !digest.complete); uint8_t zero[32] = {0};
    DF_CHECK_BYTES(t, digest.digest, zero, sizeof zero, "refused projection cannot publish a key");
    DF_CHECK(t, dfi_observation_digest_init(&digest, 0u) == DUOFORGE_OK);
    dfi_observation_fold(&digest, &df_observation_lines[0].event, DUOFORGE_MAX_EVENTS);
    DF_CHECK(t, digest.status == DUOFORGE_E_CAPACITY);
}

static void rows_mismatch(df_test *t)
{
    request_fixture f; make_request(&f);
    uint8_t zero[32] = {0};
    /* Simulate a missed fold and a duplicate fold for two staged engine events. */
    for (uint32_t rows = 1u; rows <= 3u; rows += 2u) {
        dfi_observation_digest digest;
        DF_CHECK(t, dfi_observation_digest_init(&digest, 0u) == DUOFORGE_OK);
        for (uint32_t i = 0u; i < rows; ++i) {
            dfi_observation_fold(&digest, &df_observation_lines[0].event, i);
        }
        DF_CHECK(t, digest.status == DUOFORGE_OK);
        DF_CHECK_EQ_U64(t, digest.rows, rows);
        dfi_observation_finish_view(&digest, &f.result, &f.request, &f.view, &f.ext, &f.domain, 2u);
        DF_CHECK(t, digest.status == DUOFORGE_E_INVARIANT && !digest.complete);
        DF_CHECK(t, strcmp(digest.reason, "observation_rows_mismatch:2") == 0);
        DF_CHECK_BYTES(t, digest.digest, zero, sizeof zero, "row mismatch cannot publish a key");
    }
}

static void hidden_worlds_and_identity(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_c1);
    duoforge_battle *a = df_make_f1(ctx); duoforge_battle *b = NULL;
    const uint32_t roster = a->sides[1].positions[0].occupant;
    a->sides[1].members[roster].hp = 40u; a->sides[1].members[roster].hp_max = 100u;
    dfi_events known = {0}; known.count = 1u;
    known.rec[0] = dfi_event_make(DUOFORGE_EVENT_DAMAGE, 2u);
    dfi_event_set_hp(&known.rec[0], &a->sides[1].members[roster]);
    DF_CHECK(t, dfi_events_fold_knowledge(a, a, &known, 0u));
    DF_CHECK(t, duoforge_battle_clone(ctx, a, &b) == DUOFORGE_OK);
    if (b == NULL) { duoforge_battle_destroy(a); duoforge_context_destroy(ctx); return; }
    b->sides[1].members[roster].hp = 80u; b->sides[1].members[roster].hp_max = 200u;
    b->rng.state ^= UINT64_C(1);
    DF_CHECK(t, duoforge_battle_check(ctx, a) == DUOFORGE_OK && duoforge_battle_check(ctx, b) == DUOFORGE_OK);
    dfi_observation_digest left; dfi_observation_digest right;
    DF_CHECK(t, dfi_observation_digest_init(&left, 0u) == DUOFORGE_OK);
    DF_CHECK(t, dfi_observation_digest_init(&right, 0u) == DUOFORGE_OK);
    duoforge_event raw = dfi_event_make(DUOFORGE_EVENT_DAMAGE, 2u); duoforge_event projected;
    dfi_event_set_hp(&raw, &a->sides[1].members[roster]); dfi_event_project(&raw, 0u, &projected);
    dfi_observation_fold(&left, &projected, 0u);
    dfi_event_set_hp(&raw, &b->sides[1].members[roster]); dfi_event_project(&raw, 0u, &projected);
    dfi_observation_fold(&right, &projected, 0u);
    duoforge_step_result result = {0}; result.kind = DUOFORGE_STEP_BOUNDARY;
    result.boundary_kind = a->boundary_kind; result.request_mask = a->request_mask;
    dfi_observation_finish(&left, ctx, a, &result, 1u); dfi_observation_finish(&right, ctx, b, &result, 1u);
    DF_CHECK(t, left.complete && right.complete && left.status == DUOFORGE_OK && right.status == DUOFORGE_OK);
    DF_CHECK_BYTES(t, left.digest, right.digest, sizeof left.digest, "hidden exact HP/maxima and RNG do not split the foe view");
    b->sides[1].members[roster].hp = 82u;
    dfi_event_set_hp(&known.rec[0], &b->sides[1].members[roster]);
    DF_CHECK(t, dfi_events_fold_knowledge(b, b, &known, 0u));
    DF_CHECK(t, dfi_observation_digest_init(&right, 0u) == DUOFORGE_OK);
    dfi_event_set_hp(&raw, &b->sides[1].members[roster]); dfi_event_project(&raw, 0u, &projected);
    dfi_observation_fold(&right, &projected, 0u); dfi_observation_finish(&right, ctx, b, &result, 1u);
    DF_CHECK(t, right.complete && memcmp(left.digest, right.digest, sizeof left.digest) != 0);
    DF_CHECK(t, dfi_observation_digest_init(&left, 0u) == DUOFORGE_OK);
    raw = dfi_event_switch(a, 2u);
    const uint16_t at_emission = a->sides[1].members[raw.id].species_id;
    dfi_observation_capture(&left, a, &raw, 0u);
    a->sides[1].members[raw.id].species_id = at_emission == 0u ? 1u : 0u;
    dfi_event_project(&raw, 0u, &projected);
    DF_CHECK_EQ_U64(t, left.identity[0].forme, at_emission);
    uint8_t bytes[64]; uint8_t same[64]; uint32_t n = 0u; uint32_t same_n = 0u;
    DF_CHECK(t, dfi_observation_line_encode(&projected, &left.identity[0], bytes, sizeof bytes, &n) == DUOFORGE_OK);
    projected.id = (uint16_t)((uint32_t)projected.id ^ 1u);
    DF_CHECK(t, dfi_observation_line_encode(&projected, &left.identity[0], same, sizeof same, &same_n) == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, n, same_n); DF_CHECK_BYTES(t, bytes, same, n, "particle index is not visible identity");
    raw.reserved[0] = 4u; /* the line displays roster 3, not its hidden holder */
    DF_CHECK(t, dfi_observation_digest_init(&left, 0u) == DUOFORGE_OK);
    dfi_observation_capture(&left, a, &raw, 0u);
    DF_CHECK_EQ_U64(t, left.identity[0].forme, a->sides[1].members[3].species_id);
    DF_CHECK(t, dfi_observation_digest_init(&right, 1u) == DUOFORGE_OK);
    dfi_observation_capture(&right, a, &raw, 0u);
    DF_CHECK_EQ_U64(t, right.identity[0].forme, a->sides[1].members[raw.id].species_id);
    raw.id = UINT16_MAX;
    DF_CHECK(t, dfi_observation_digest_init(&right, 1u) == DUOFORGE_OK);
    dfi_observation_capture(&right, a, &raw, 0u);
    DF_CHECK(t, right.status == DUOFORGE_E_INVARIANT && !right.complete);
    duoforge_battle_destroy(b); duoforge_battle_destroy(a); duoforge_context_destroy(ctx);
}

static void first_bundle(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, duoforge_decision_bundle *bundle)
{
    memset(bundle, 0, sizeof *bundle); bundle->epoch = b->request_epoch; bundle->response_mask = b->request_mask;
    for (uint32_t p = 0u; p < 2u; ++p) {
        if (((uint32_t)b->request_mask & (1u << p)) == 0u) { continue; }
        duoforge_factored_domain d;
        DF_CHECK(t, duoforge_battle_factored(ctx, b, p, &d) == DUOFORGE_OK);
        duoforge_side_choice *c = &bundle->responses[p]; c->epoch = d.epoch; c->side = (uint8_t)p; c->kind = d.kind;
        if (d.kind == DUOFORGE_CHOICE_TEAM_SELECTION) {
            c->pick_count = d.pick_count;
            for (uint32_t j = 0u; j < d.pick_count; ++j) { c->picks[j] = (uint8_t)j; }
        } else {
            bool found = false;
            for (uint32_t i = 0u; i < d.slot_count[0] && !found; ++i) {
                for (uint32_t j = 0u; j < d.slot_count[1] && !found; ++j) {
                    if ((d.allowed[i] & (UINT32_C(1) << j)) != 0u) {
                        c->slots[0] = d.slots[0][i]; c->slots[1] = d.slots[1][j]; found = true;
                    }
                }
            }
            DF_CHECK(t, found);
        }
    }
}

static void trapping_changes_request(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_pool_dev);
    duoforge_battle_setup setup; df_setup_teams(&setup);
    for (uint32_t side = 0u; side < 2u; ++side) {
        for (uint32_t j = 0u; j < setup.sides[side].member_count; ++j) {
            duoforge_member_setup *m = &setup.sides[side].members[j];
            m->move_count = 1u; memset(m->moves, 0, sizeof m->moves); m->moves[0].move_id = DFI_MOVE_PROTECT;
        }
    }
    duoforge_member_setup *foe = &setup.sides[1].members[0];
    foe->species_id = DFI_FORME_GENGAR; foe->item = (uint8_t)(DFI_ITEM_GENGARITE + 1u);
    foe->ability = (uint8_t)(DFI_ABILITY_CURSEDBODY + 1u);
    duoforge_battle *trapped = df_make_battle(ctx, &setup);
    duoforge_decision_bundle bundle; first_bundle(t, ctx, trapped, &bundle); duoforge_step_result result;
    DF_CHECK(t, duoforge_battle_step(ctx, trapped, &bundle, &result) == DUOFORGE_OK);
    /* White-box boundary fixture: both states have the same Mega forme;
     * the current ability override is the only trap-source difference.
     * This tests request projection, not a claim of identical CTS parents. */
    DF_CHECK(t, dfi_closure_member_mega_evolve(&trapped->sides[1].members[0]));
    trapped->sides[1].mega_used = 1u;
    dfi_events mega = {0}; mega.count = 1u; mega.rec[0] = dfi_event_make(DUOFORGE_EVENT_MEGA, 2u);
    mega.rec[0].id2 = (uint16_t)(DFI_ITEM_GENGARITE + 1u);
    DF_CHECK(t, dfi_events_fold_knowledge(trapped, trapped, &mega, 0u));
    duoforge_battle *free_world = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, trapped, &free_world) == DUOFORGE_OK);
    if (free_world == NULL) { duoforge_battle_destroy(trapped); duoforge_context_destroy(ctx); return; }
    free_world->tail.sides[1].ability_now[0] = (uint8_t)(DFI_ABILITY_CURSEDBODY + 1u);
    DF_CHECK(t, duoforge_battle_check(ctx, trapped) == DUOFORGE_OK && duoforge_battle_check(ctx, free_world) == DUOFORGE_OK);
    first_bundle(t, ctx, free_world, &bundle);
    static duoforge_event a[2][DUOFORGE_MAX_EVENTS]; static duoforge_event b[2][DUOFORGE_MAX_EVENTS];
    duoforge_event_buffer ba[2] = {{a[0], DUOFORGE_MAX_EVENTS, 0u}, {a[1], DUOFORGE_MAX_EVENTS, 0u}};
    duoforge_event_buffer bb[2] = {{b[0], DUOFORGE_MAX_EVENTS, 0u}, {b[1], DUOFORGE_MAX_EVENTS, 0u}};
    dfi_observation_digest key_a; dfi_observation_digest key_b; key_a.viewer = 0u; key_b.viewer = 0u;
    duoforge_step_result result_a; duoforge_step_result result_b;
    DF_CHECK(t, dfi_battle_step_observed(ctx, free_world, &bundle, NULL, 0u, NULL, &result_a, ba, &key_a) == DUOFORGE_OK);
    DF_CHECK(t, dfi_battle_step_observed(ctx, trapped, &bundle, NULL, 0u, NULL, &result_b, bb, &key_b) == DUOFORGE_OK);
    DF_CHECK(t, key_a.complete && key_b.complete);
    DF_CHECK_EQ_U64(t, ba[0].count, bb[0].count);
    DF_CHECK_BYTES(t, (const uint8_t *)a[0], (const uint8_t *)b[0], (size_t)ba[0].count * sizeof a[0][0],
        "trapping control has identical projected step events");
    DF_CHECK_EQ_U64(t, result_a.boundary_kind, result_b.boundary_kind); DF_CHECK_EQ_U64(t, result_a.request_mask, result_b.request_mask);
    duoforge_factored_domain da; duoforge_factored_domain db;
    DF_CHECK(t, duoforge_battle_factored(ctx, free_world, 0u, &da) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_factored(ctx, trapped, 0u, &db) == DUOFORGE_OK);
    uint32_t switches_a = 0u; uint32_t switches_b = 0u;
    for (uint32_t p = 0u; p < 2u; ++p) {
        for (uint32_t j = 0u; j < da.slot_count[p]; ++j) { if (da.slots[p][j].kind == DUOFORGE_SLOT_SWITCH) { ++switches_a; } }
        for (uint32_t j = 0u; j < db.slot_count[p]; ++j) { if (db.slots[p][j].kind == DUOFORGE_SLOT_SWITCH) { ++switches_b; } }
    }
    DF_CHECK(t, switches_a > 0u && switches_b == 0u);
    DF_CHECK(t, memcmp(key_a.digest, key_b.digest, sizeof key_a.digest) != 0);
    duoforge_battle_destroy(free_world); duoforge_battle_destroy(trapped); duoforge_context_destroy(ctx);
}

static void step_plumbing(df_test *t)
{
    duoforge_context *ctx = df_make_context(&df_config_c4);
    duoforge_battle *observed = df_make_g7(ctx); duoforge_battle *legacy = NULL;
    DF_CHECK(t, duoforge_battle_clone(ctx, observed, &legacy) == DUOFORGE_OK);
    if (legacy == NULL) { duoforge_battle_destroy(observed); duoforge_context_destroy(ctx); return; }
    duoforge_decision_bundle bundle; first_bundle(t, ctx, observed, &bundle);
    duoforge_step_result result; duoforge_step_result other;
    dfi_observation_digest digest; digest.viewer = 0u;
    DF_CHECK(t, dfi_battle_step_observed(ctx, observed, &bundle, NULL, 0u, NULL, &result, NULL, &digest) == DUOFORGE_OK);
    DF_CHECK(t, duoforge_battle_step(ctx, legacy, &bundle, &other) == DUOFORGE_OK);
    bool equal = false;
    DF_CHECK(t, duoforge_battle_equal(ctx, observed, legacy, &equal) == DUOFORGE_OK && equal);
    DF_CHECK_BYTES(t, (const uint8_t *)&result, (const uint8_t *)&other, sizeof result, "legacy step result preserved");
    DF_CHECK(t, digest.complete && digest.status == DUOFORGE_OK);
    DF_CHECK_EQ_U64(t, digest.rows, 5u); /* four leads consumed once, then TURN */
    /* Inject a lost row after the real step; refusal must not alter the battle. */
    dfi_observation_digest missing_row = digest;
    missing_row.rows -= 1u;
    dfi_observation_finish(&missing_row, ctx, observed, &result, 5u);
    DF_CHECK(t, missing_row.status == DUOFORGE_E_INVARIANT && !missing_row.complete);
    DF_CHECK(t, strcmp(missing_row.reason, "observation_rows_mismatch:5") == 0);
    uint8_t zero[32] = {0};
    DF_CHECK_BYTES(t, missing_row.digest, zero, sizeof zero, "row mismatch clears a previously published key");
    DF_CHECK(t, duoforge_battle_equal(ctx, observed, legacy, &equal) == DUOFORGE_OK && equal);
    first_bundle(t, ctx, observed, &bundle);
    DF_CHECK(t, dfi_battle_step_observed(ctx, observed, &bundle, NULL, 0u, NULL, &result, NULL, &digest) == DUOFORGE_E_UNSUPPORTED);
    DF_CHECK(t, !digest.complete);
    DF_CHECK_BYTES(t, digest.digest, zero, sizeof zero, "unsupported step clears the previous key");
    DF_CHECK(t, duoforge_battle_equal(ctx, observed, legacy, &equal) == DUOFORGE_OK && equal);
    digest.complete = true; memset(digest.digest, 0xA5, sizeof digest.digest);
    DF_CHECK(t, dfi_battle_step_observed(NULL, observed, &bundle, NULL, 0u, NULL, &result, NULL, &digest) == DUOFORGE_E_NULL_ARGUMENT);
    DF_CHECK(t, !digest.complete); DF_CHECK_BYTES(t, digest.digest, zero, sizeof zero, "null preflight clears scratch key");
    duoforge_battle_destroy(legacy); duoforge_battle_destroy(observed); duoforge_context_destroy(ctx);
}

/* Step K4 (#475, decision 0015 5dl): FIELD_START and FIELD_END accept detail 6 (Gravity) and refuse 7 (Magic Room, K5). */
static void field_detail_vectors(df_test *t)
{
    const dfi_visible_identity identity = {0x0102u, 1u, 1u};
    const uint32_t kinds[2] = {DUOFORGE_EVENT_FIELD_START, DUOFORGE_EVENT_FIELD_END};
    for (uint32_t k = 0u; k < 2u; ++k) {
        for (uint32_t detail = 0u; detail <= 8u; ++detail) {
            dfi_observation_digest d;
            DF_CHECK(t, dfi_observation_digest_init(&d, 0u) == DUOFORGE_OK);
            d.identity[0] = identity;
            duoforge_event e = dfi_event_make(kinds[k], DUOFORGE_NO_POSITION);
            e.detail = (uint8_t)detail;
            dfi_observation_fold(&d, &e, 0u);
            const bool accepted = detail == DUOFORGE_FIELD_GRAVITY ||
                                  (detail >= DUOFORGE_FIELD_GRASSY_TERRAIN && detail <= DUOFORGE_FIELD_MISTY_TERRAIN);
            DF_CHECK(t, accepted ? d.status == DUOFORGE_OK : (d.status == DUOFORGE_E_UNSUPPORTED && !d.complete));
        }
    }
    DF_CHECK_EQ_U64(t, DUOFORGE_FIELD_GRAVITY, 6u);
}

int main(void)
{
    df_test t; df_test_begin(&t, "duoforge.observation.digest");
    line_vectors(&t); request_vectors(&t); stream_vector(&t); rows_mismatch(&t);
    hidden_worlds_and_identity(&t); trapping_changes_request(&t); step_plumbing(&t);
    field_detail_vectors(&t);
    return df_test_end(&t);
}
