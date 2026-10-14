#include "state/observation_digest.h"
#include <string.h>
#include "core/arith.h"
#include "core/bytes.h"
#include "state/closure_member.h"
#include "state/observation_key.h"

/* Presence bits for the fields in their public record order. No new public
 * identifiers: this is the private version-1 byte schema of decision 0082. */
#define DFI_LINE_POS UINT32_C(1)
#define DFI_LINE_OTHER UINT32_C(2)
#define DFI_LINE_CAUSE UINT32_C(4)
#define DFI_LINE_ID UINT32_C(8)
#define DFI_LINE_ID2 UINT32_C(16)
#define DFI_LINE_HP UINT32_C(32)
#define DFI_LINE_DETAIL UINT32_C(64)
#define DFI_LINE_AMOUNT UINT32_C(128)
#define DFI_LINE_FLAGS UINT32_C(256)
#define DFI_LINE_IDENTITY UINT32_C(512) /* visible identity in place of DFI_LINE_ID */
#define DFI_CAUSE_BIT(x) (UINT64_C(1) << DUOFORGE_CAUSE_##x)
#define BASIC (DFI_CAUSE_BIT(NONE) | DFI_CAUSE_BIT(MOVE) | DFI_CAUSE_BIT(ITEM) | DFI_CAUSE_BIT(ABILITY))

typedef struct dfi_line_schema {
    uint32_t fields;
    uint64_t causes;
    uint32_t flags;
} dfi_line_schema;

static bool dfi_line_schema_of(uint32_t kind, dfi_line_schema *out)
{
    dfi_line_schema s = {0u, DFI_CAUSE_BIT(NONE), 0u};
    switch (kind) {
    case DUOFORGE_EVENT_TURN: s.fields = DFI_LINE_ID; break;
    case DUOFORGE_EVENT_SWITCH: s.fields = DFI_LINE_POS|DFI_LINE_CAUSE|DFI_LINE_IDENTITY|DFI_LINE_ID2|DFI_LINE_HP; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(MOVE); break;
    case DUOFORGE_EVENT_DRAG: s.fields = DFI_LINE_POS|DFI_LINE_IDENTITY|DFI_LINE_HP; break;
    case DUOFORGE_EVENT_REVIVE: s.fields = DFI_LINE_POS|DFI_LINE_CAUSE|DFI_LINE_IDENTITY|DFI_LINE_ID2|DFI_LINE_HP; s.causes = DFI_CAUSE_BIT(MOVE); break;
    case DUOFORGE_EVENT_ILLUSION_END: s.fields = DFI_LINE_POS|DFI_LINE_IDENTITY|DFI_LINE_HP; break;
    case DUOFORGE_EVENT_MOVE:
        s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2|DFI_LINE_AMOUNT|DFI_LINE_FLAGS; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(ABILITY);
        s.flags = DUOFORGE_EVENT_FLAG_STILL|DUOFORGE_EVENT_FLAG_LOCKED|DUOFORGE_EVENT_FLAG_SPREAD|
                  DUOFORGE_EVENT_FLAG_MISS|DUOFORGE_EVENT_FLAG_NOTARGET; break;
    case DUOFORGE_EVENT_DAMAGE:
    case DUOFORGE_EVENT_HEAL:
        s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_HP;
        s.causes = BASIC|DFI_CAUSE_BIT(RECOIL)|DFI_CAUSE_BIT(DRAIN)|DFI_CAUSE_BIT(BURN)|DFI_CAUSE_BIT(CONFUSION)|DFI_CAUSE_BIT(TERRAIN)|
                   DFI_CAUSE_BIT(POISON)|DFI_CAUSE_BIT(WEATHER)|DFI_CAUSE_BIT(LEECH_SEED)|DFI_CAUSE_BIT(CURSE); break;
    case DUOFORGE_EVENT_FAINT:
    case DUOFORGE_EVENT_CRIT:
    case DUOFORGE_EVENT_PROTECT:
    case DUOFORGE_EVENT_CONFUSION_START:
    case DUOFORGE_EVENT_CONFUSION_END:
    case DUOFORGE_EVENT_CONFUSED:
    case DUOFORGE_EVENT_FLASH_FIRE:
    case DUOFORGE_EVENT_PROTECT_BROKEN: s.fields = DFI_LINE_POS; break;
    case DUOFORGE_EVENT_MISS: s.fields = DFI_LINE_POS|DFI_LINE_OTHER; break;
    case DUOFORGE_EVENT_SUPER_EFFECTIVE:
    case DUOFORGE_EVENT_RESISTED: s.fields = DFI_LINE_POS|DFI_LINE_AMOUNT; break;
    case DUOFORGE_EVENT_CANT:
        s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2;
        s.causes = DFI_CAUSE_BIT(MOVE)|DFI_CAUSE_BIT(ABILITY)|DFI_CAUSE_BIT(PARALYSIS)|DFI_CAUSE_BIT(SLEEP)|DFI_CAUSE_BIT(FREEZE)|DFI_CAUSE_BIT(FLINCH)|
                   DFI_CAUSE_BIT(NO_PP)|DFI_CAUSE_BIT(RECHARGE)|DFI_CAUSE_BIT(DISABLE)|DFI_CAUSE_BIT(TAUNT)|DFI_CAUSE_BIT(HEAL_BLOCK)|
                   DFI_CAUSE_BIT(IMPRISON)|DFI_CAUSE_BIT(ATTRACT); break;
    case DUOFORGE_EVENT_IMMUNE: s.fields = DFI_LINE_POS|DFI_LINE_CAUSE|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(ABILITY); break;
    case DUOFORGE_EVENT_FAIL: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL; s.causes = BASIC; break;
    case DUOFORGE_EVENT_BLOCKED: s.fields = DFI_LINE_POS|DFI_LINE_DETAIL; break;
    case DUOFORGE_EVENT_BOOST:
    case DUOFORGE_EVENT_UNBOOST: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL|DFI_LINE_AMOUNT; s.causes = BASIC; break;
    case DUOFORGE_EVENT_STATUS: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL; s.causes = BASIC; break;
    case DUOFORGE_EVENT_CURE_STATUS:
        s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL|DFI_LINE_FLAGS; s.causes = BASIC; s.flags = DUOFORGE_EVENT_FLAG_MESSAGE; break;
    case DUOFORGE_EVENT_WEATHER:
        s.fields = DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL|DFI_LINE_FLAGS; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(ABILITY); s.flags = DUOFORGE_EVENT_FLAG_UPKEEP; break;
    case DUOFORGE_EVENT_FIELD_START: s.fields = DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(ABILITY); break;
    case DUOFORGE_EVENT_FIELD_END: s.fields = DFI_LINE_DETAIL; break;
    case DUOFORGE_EVENT_SIDE_START:
    case DUOFORGE_EVENT_SIDE_END: s.fields = DFI_LINE_OTHER|DFI_LINE_DETAIL|DFI_LINE_AMOUNT; break;
    case DUOFORGE_EVENT_ITEM_END:
        s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2|DFI_LINE_DETAIL|DFI_LINE_FLAGS; s.causes = BASIC|DFI_CAUSE_BIT(ITEM_TAKEN); s.flags = DUOFORGE_EVENT_FLAG_EATEN; break;
    case DUOFORGE_EVENT_FORME: s.fields = DFI_LINE_POS|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(ABILITY); break;
    case DUOFORGE_EVENT_MEGA: s.fields = DFI_LINE_POS|DFI_LINE_ID2; break;
    case DUOFORGE_EVENT_PREPARE: s.fields = DFI_LINE_POS|DFI_LINE_ID; break;
    case DUOFORGE_EVENT_ANIMATION:
        s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_ID|DFI_LINE_FLAGS; s.flags = DUOFORGE_EVENT_FLAG_MISS|DUOFORGE_EVENT_FLAG_NOTARGET; break;
    case DUOFORGE_EVENT_ABILITY: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(MOVE)|DFI_CAUSE_BIT(ABILITY); break;
    case DUOFORGE_EVENT_ACTIVATE: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(MOVE)|DFI_CAUSE_BIT(ABILITY); break;
    case DUOFORGE_EVENT_UPKEEP:
    case DUOFORGE_EVENT_CLEAR_ALL_BOOSTS: break;
    case DUOFORGE_EVENT_RESULT: s.fields = DFI_LINE_DETAIL; break;
    case DUOFORGE_EVENT_SINGLE_TURN: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_ID; break;
    case DUOFORGE_EVENT_VOLATILE_START:
    case DUOFORGE_EVENT_VOLATILE_END: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2|DFI_LINE_DETAIL|DFI_LINE_AMOUNT; s.causes = BASIC; break;
    case DUOFORGE_EVENT_TYPE_CHANGE: s.fields = DFI_LINE_POS|DFI_LINE_CAUSE|DFI_LINE_ID2|DFI_LINE_DETAIL|DFI_LINE_AMOUNT; s.causes = DFI_CAUSE_BIT(MOVE); break;
    case DUOFORGE_EVENT_ITEM_START: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(MOVE); break;
    case DUOFORGE_EVENT_ITEM_SHOWN: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(NONE)|DFI_CAUSE_BIT(ABILITY); break;
    case DUOFORGE_EVENT_SWAP:
    case DUOFORGE_EVENT_COPY_BOOST: s.fields = DFI_LINE_POS|DFI_LINE_OTHER|DFI_LINE_CAUSE|DFI_LINE_ID2; s.causes = DFI_CAUSE_BIT(MOVE); break;
    default: return false;
    }
    *out = s;
    return true;
}

static bool dfi_line_variant(const duoforge_event *e, const dfi_line_schema *s)
{
    if (e->cause >= 64u || (s->causes & (UINT64_C(1) << e->cause)) == 0u ||
        ((uint32_t)e->flags & ~s->flags) != 0u) {
        return false;
    }
    switch (e->kind) {
    case DUOFORGE_EVENT_BOOST:
    case DUOFORGE_EVENT_UNBOOST: return e->detail < 7u && e->amount <= 12u;
    case DUOFORGE_EVENT_STATUS:
    case DUOFORGE_EVENT_CURE_STATUS: return e->detail <= DUOFORGE_AILMENT_TOX;
    case DUOFORGE_EVENT_FAIL: return e->detail <= DUOFORGE_AILMENT_TOX;
    case DUOFORGE_EVENT_BLOCKED:
        return e->detail == 0u || e->detail == DUOFORGE_FIELD_PSYCHIC_TERRAIN ||
               e->detail == DUOFORGE_BLOCK_WIDE_GUARD || e->detail == DUOFORGE_BLOCK_QUICK_GUARD;
    case DUOFORGE_EVENT_WEATHER: return e->detail <= DUOFORGE_WEATHER_SNOW;
    case DUOFORGE_EVENT_FIELD_START:
    case DUOFORGE_EVENT_FIELD_END: return e->detail >= DUOFORGE_FIELD_GRASSY_TERRAIN && e->detail <= DUOFORGE_FIELD_MISTY_TERRAIN;
    case DUOFORGE_EVENT_SIDE_START:
    case DUOFORGE_EVENT_SIDE_END: return e->detail < 2u && e->amount >= DUOFORGE_SIDE_TAILWIND && e->amount <= DUOFORGE_SIDE_STICKY_WEB;
    case DUOFORGE_EVENT_TYPE_CHANGE:
        return (e->detail < 18u || e->detail == DUOFORGE_TYPE_NONE) && e->amount <= 18u;
    case DUOFORGE_EVENT_ITEM_END: return e->detail <= 1u;
    case DUOFORGE_EVENT_VOLATILE_START:
    case DUOFORGE_EVENT_VOLATILE_END: return e->detail >= DUOFORGE_VOLATILE_HEAL_BLOCK && e->detail <= DUOFORGE_VOLATILE_CURSE;
    case DUOFORGE_EVENT_RESULT: return e->detail >= DUOFORGE_RESULT_SIDE_0 && e->detail <= DUOFORGE_RESULT_TIE;
    default: return true; /* The schema above explicitly classified this kind. */
    }
}

static void dfi_u8(uint8_t *out, uint32_t *n, uint8_t x) { out[*n] = x; *n += 1u; }
static void dfi_u16(uint8_t *out, uint32_t *n, uint16_t x) { dfi_store_u16le(out + *n, x); *n += 2u; }
static void dfi_u32(uint8_t *out, uint32_t *n, uint32_t x) { dfi_store_u32le(out + *n, x); *n += 4u; }
static void dfi_sequence(uint8_t *out, uint32_t *n, const uint8_t *in, uint32_t size)
{
    memcpy(out + *n, in, size); *n += size;
}

static duoforge_status dfi_copy_payload(const uint8_t *bytes, uint32_t n,
    uint8_t *out, uint32_t capacity, uint32_t *size)
{
    *size = n;
    if (capacity < n) { return DUOFORGE_E_CAPACITY; }
    if (out == NULL) { return DUOFORGE_E_NULL_ARGUMENT; }
    memcpy(out, bytes, n);
    return DUOFORGE_OK;
}

duoforge_status dfi_observation_line_encode(const duoforge_event *e,
    const dfi_visible_identity *identity, uint8_t *out, uint32_t capacity, uint32_t *size)
{
    if (e == NULL || size == NULL) { return DUOFORGE_E_NULL_ARGUMENT; }
    dfi_line_schema s;
    if (!dfi_line_schema_of(e->kind, &s) || !dfi_line_variant(e, &s)) { return DUOFORGE_E_UNSUPPORTED; }
    if ((s.fields & DFI_LINE_IDENTITY) != 0u && (identity == NULL || identity->valid != 1u)) { return DUOFORGE_E_INVARIANT; }
    if ((s.fields & DFI_LINE_HP) != 0u && e->hp_kind != DUOFORGE_HP_EXACT && e->hp_kind != DUOFORGE_HP_PERCENT) {
        return DUOFORGE_E_INVARIANT;
    }
    uint8_t bytes[DFI_OBSERVATION_LINE_MAX];
    uint32_t n = 0u;
    dfi_u8(bytes, &n, e->kind);
    if ((s.fields & DFI_LINE_POS) != 0u) { dfi_u8(bytes, &n, e->position); }
    if ((s.fields & DFI_LINE_OTHER) != 0u) { dfi_u8(bytes, &n, e->other); }
    if ((s.fields & DFI_LINE_CAUSE) != 0u) { dfi_u8(bytes, &n, e->cause); }
    if ((s.fields & DFI_LINE_ID) != 0u) { dfi_u16(bytes, &n, e->id); }
    if ((s.fields & DFI_LINE_IDENTITY) != 0u) { dfi_u16(bytes, &n, identity->forme); dfi_u8(bytes, &n, identity->gender); }
    if ((s.fields & DFI_LINE_ID2) != 0u) { dfi_u16(bytes, &n, e->id2); }
    if ((s.fields & DFI_LINE_HP) != 0u) {
        dfi_u16(bytes, &n, e->hp); dfi_u16(bytes, &n, e->hp_max);
        dfi_u8(bytes, &n, e->hp_kind); dfi_u8(bytes, &n, e->hp_flag); dfi_u8(bytes, &n, e->status);
    }
    if ((s.fields & DFI_LINE_DETAIL) != 0u) { dfi_u8(bytes, &n, e->detail); }
    if ((s.fields & DFI_LINE_AMOUNT) != 0u) { dfi_u8(bytes, &n, e->amount); }
    if ((s.fields & DFI_LINE_FLAGS) != 0u) { dfi_u8(bytes, &n, e->flags); }
    return dfi_copy_payload(bytes, n, out, capacity, size);
}

static bool dfi_boundary_known(uint32_t kind)
{
    switch (kind) {
    case DUOFORGE_BOUNDARY_TEAM_SELECTION:
    case DUOFORGE_BOUNDARY_TURN:
    case DUOFORGE_BOUNDARY_REPLACEMENT:
    case DUOFORGE_BOUNDARY_PIVOT:
    case DUOFORGE_BOUNDARY_TERMINAL: return true;
    default: return false;
    }
}

/* 21 header bytes, 54 per own member, 33 per own position, 10 own side
 * bytes, 5 domain header bytes, 5 per option and 4 per allowed-pair row. */
_Static_assert(21u + 54u * DUOFORGE_MAX_ROSTER + 33u * DUOFORGE_ACTIVE_PER_SIDE + 10u + 5u +
    5u * DUOFORGE_ACTIVE_PER_SIDE * DUOFORGE_MAX_SLOT_OPTIONS + 4u * DUOFORGE_MAX_SLOT_OPTIONS <=
    DFI_OBSERVATION_REQUEST_MAX, "request whitelist fits bounded scratch");

duoforge_status dfi_observation_request_encode(const duoforge_step_result *result,
    const duoforge_request *request, const duoforge_observation *view,
    const duoforge_observation_ext *ext, const duoforge_factored_domain *domain,
    uint8_t *out, uint32_t capacity, uint32_t *size)
{
    if (result == NULL || request == NULL || view == NULL || ext == NULL || domain == NULL || size == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const uint32_t viewer = request->player;
    if (viewer >= DUOFORGE_SIDE_COUNT || view->player != viewer) { return DUOFORGE_E_INVALID_ARGUMENT; }
    if (!dfi_boundary_known(result->boundary_kind) ||
        (result->kind != DUOFORGE_STEP_BOUNDARY && result->kind != DUOFORGE_STEP_REPROMPT) ||
        (domain->kind != 0u && domain->kind != DUOFORGE_CHOICE_SLOTS && domain->kind != DUOFORGE_CHOICE_TEAM_SELECTION) ||
        (ext->revision != 0u && ext->revision != 1u)) {
        return DUOFORGE_E_UNSUPPORTED;
    }
    const duoforge_side_view *own = &view->sides[viewer];
    const duoforge_side_ext *extra = &ext->sides[viewer];
    if (own->member_count > DUOFORGE_MAX_ROSTER || domain->member_count > DUOFORGE_MAX_ROSTER ||
        domain->pick_count > DUOFORGE_MAX_ROSTER || result->request_mask > 3u ||
        request->boundary_kind != result->boundary_kind || view->boundary_kind != result->boundary_kind ||
        request->requested > 1u || request->slot_mask > 3u) { return DUOFORGE_E_INVARIANT; }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if (domain->slot_count[p] > DUOFORGE_MAX_SLOT_OPTIONS) { return DUOFORGE_E_INVARIANT; }
        /* The current engine refuses Transform. Its roster-index source
         * needs a visible identity schema before it can join this whitelist. */
        if (extra->positions[p].transform_source != 0u ||
            ((uint32_t)own->positions[p].reserved & ~(DUOFORGE_POSITION_FLAG_FOLLOW_ME |
                DUOFORGE_POSITION_FLAG_HELPING_HAND | DUOFORGE_POSITION_FLAG_UNBURDEN)) != 0u) {
            return DUOFORGE_E_UNSUPPORTED;
        }
    }
    uint8_t bytes[DFI_OBSERVATION_REQUEST_MAX];
    uint32_t n = 0u;
    dfi_u8(bytes, &n, result->kind);
    dfi_u8(bytes, &n, result->boundary_kind);
    dfi_u8(bytes, &n, result->request_mask);
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        dfi_u8(bytes, &n, view->sides[s].requested_slots);
    }
    dfi_u8(bytes, &n, request->requested);
    dfi_u8(bytes, &n, request->slot_mask);
    dfi_u32(bytes, &n, request->candidate_count);
    dfi_u8(bytes, &n, own->member_count);
    dfi_u8(bytes, &n, own->mega_used);
    dfi_sequence(bytes, &n, own->occupant, DUOFORGE_ACTIVE_PER_SIDE);
    dfi_sequence(bytes, &n, own->brought_order, DUOFORGE_MAX_ROSTER);
    for (uint32_t m = 0u; m < own->member_count; ++m) {
        const duoforge_member_view *v = &own->members[m];
        dfi_u16(bytes, &n, v->species_id); dfi_u16(bytes, &n, v->hp); dfi_u16(bytes, &n, v->hp_max);
        for (uint32_t j = 0u; j < DUOFORGE_MAX_MOVE_SLOTS; ++j) { dfi_u16(bytes, &n, v->move_ids[j]); }
        for (uint32_t j = 0u; j < 5u; ++j) { dfi_u16(bytes, &n, v->stats[j]); }
        dfi_sequence(bytes, &n, v->pp, DUOFORGE_MAX_MOVE_SLOTS);
        dfi_sequence(bytes, &n, v->pp_max, DUOFORGE_MAX_MOVE_SLOTS);
        dfi_sequence(bytes, &n, v->stat_points, 6u);
        dfi_u8(bytes, &n, v->move_count); dfi_u8(bytes, &n, v->hp_kind); dfi_u8(bytes, &n, v->hp_flag);
        dfi_u8(bytes, &n, v->pp_kind); dfi_u8(bytes, &n, v->location); dfi_u8(bytes, &n, v->mega_capable);
        dfi_u8(bytes, &n, v->is_mega); dfi_u8(bytes, &n, v->gender); dfi_u8(bytes, &n, v->nature);
        dfi_u8(bytes, &n, v->ability); dfi_u8(bytes, &n, v->item); dfi_u8(bytes, &n, v->item_used);
        dfi_u8(bytes, &n, v->status);
        dfi_u16(bytes, &n, extra->members[m].forme); dfi_u8(bytes, &n, extra->members[m].item_now);
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const duoforge_position_view *v = &own->positions[p];
        const duoforge_position_ext *x = &extra->positions[p];
        dfi_sequence(bytes, &n, v->stages, 7u);
        dfi_u8(bytes, &n, v->confused); dfi_u8(bytes, &n, v->charging); dfi_u8(bytes, &n, v->locked_slot);
        dfi_u8(bytes, &n, v->locked_target); dfi_u8(bytes, &n, v->acted); dfi_u8(bytes, &n, v->protect_chain);
        dfi_u8(bytes, &n, v->flash_fire); dfi_u8(bytes, &n, v->protecting);
        dfi_u8(bytes, &n, v->reserved); /* This field carries the documented POSITION_FLAG bits, not padding. */
        dfi_u32(bytes, &n, x->volatiles); dfi_u16(bytes, &n, x->ability_now);
        dfi_sequence(bytes, &n, x->type_now, 2u);
        dfi_u8(bytes, &n, x->encore_slot); dfi_u8(bytes, &n, x->disable_slot); dfi_u8(bytes, &n, x->stockpile);
        dfi_u8(bytes, &n, x->perish); dfi_u8(bytes, &n, x->move_failed);
        dfi_u32(bytes, &n, ext->volatiles2[viewer][p]);
    }
    dfi_u8(bytes, &n, own->reflect_turns); dfi_u8(bytes, &n, own->light_screen_turns); dfi_u8(bytes, &n, own->tailwind_turns);
    dfi_u8(bytes, &n, extra->aurora_veil_turns); dfi_u8(bytes, &n, extra->stealth_rock); dfi_u8(bytes, &n, extra->spikes);
    dfi_u8(bytes, &n, extra->toxic_spikes); dfi_u8(bytes, &n, extra->sticky_web);
    dfi_u8(bytes, &n, extra->guard_flags); dfi_u8(bytes, &n, extra->conditions);
    dfi_u8(bytes, &n, domain->kind); dfi_u8(bytes, &n, domain->member_count); dfi_u8(bytes, &n, domain->pick_count);
    dfi_sequence(bytes, &n, domain->slot_count, DUOFORGE_ACTIVE_PER_SIDE);
    if (domain->kind == DUOFORGE_CHOICE_SLOTS) {
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            for (uint32_t j = 0u; j < domain->slot_count[p]; ++j) {
                const duoforge_slot_command *c = &domain->slots[p][j];
                if (c->kind != DUOFORGE_SLOT_MOVE && c->kind != DUOFORGE_SLOT_SWITCH &&
                    c->kind != DUOFORGE_SLOT_PASS && c->kind != DUOFORGE_SLOT_NONE && c->kind != DUOFORGE_SLOT_REVIVE) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
                dfi_u8(bytes, &n, c->kind); dfi_u8(bytes, &n, c->move_slot); dfi_u8(bytes, &n, c->target);
                dfi_u8(bytes, &n, c->mega); dfi_u8(bytes, &n, c->reserve);
            }
        }
        for (uint32_t j = 0u; j < domain->slot_count[0]; ++j) { dfi_u32(bytes, &n, domain->allowed[j]); }
    }
    return dfi_copy_payload(bytes, n, out, capacity, size);
}

static void dfi_observation_error(dfi_observation_digest *digest, duoforge_status status,
    const char *reason, uint32_t entry)
{
    if (digest->status != DUOFORGE_OK) { return; }
    digest->status = status;
    digest->complete = false;
    memset(digest->digest, 0, sizeof digest->digest);
    uint32_t n = 0u;
    while (reason[n] != '\0' && n < 100u) { digest->reason[n] = reason[n]; ++n; }
    digest->reason[n++] = ':';
    uint8_t digits[10];
    uint32_t count = 0u;
    do {
        digits[count++] = (uint8_t)(entry % 10u); /* wide-operands-reviewed: digit 0..9 */
        entry /= 10u;
    } while (entry != 0u);
    while (count != 0u) { digest->reason[n++] = "0123456789"[digits[--count]]; }
    digest->reason[n] = '\0';
}

duoforge_status dfi_observation_digest_init(dfi_observation_digest *digest, uint32_t viewer)
{
    if (digest == NULL) { return DUOFORGE_E_NULL_ARGUMENT; }
    memset(digest, 0, sizeof *digest);
    digest->viewer = viewer;
    if (viewer >= DUOFORGE_SIDE_COUNT) {
        dfi_observation_error(digest, DUOFORGE_E_INVALID_ARGUMENT, "observation_viewer", viewer);
        return digest->status;
    }
    static const uint8_t domain[] = "duoforge.observation-digest.v1";
    dfi_sha256_init(&digest->hash);
    const uint8_t seat = (uint8_t)viewer; /* wide-operands-reviewed: viewer < 2 */
    if (!dfi_sha256_update(&digest->hash, domain, sizeof domain) || !dfi_sha256_update(&digest->hash, &seat, 1u)) {
        dfi_observation_error(digest, DUOFORGE_E_EXHAUSTED, "observation_hash_length", 0u);
    }
    return digest->status;
}

void dfi_observation_capture(dfi_observation_digest *digest, const struct duoforge_battle *battle,
    const duoforge_event *event, uint32_t index)
{
    if (digest->status != DUOFORGE_OK || index >= DUOFORGE_MAX_EVENTS) { return; }
    if (event->kind != DUOFORGE_EVENT_SWITCH && event->kind != DUOFORGE_EVENT_DRAG &&
        event->kind != DUOFORGE_EVENT_REVIVE && event->kind != DUOFORGE_EVENT_ILLUSION_END) { return; }
    const uint32_t side = (uint32_t)event->position / DUOFORGE_ACTIVE_PER_SIDE;
    uint32_t member = event->id;
    if ((event->kind == DUOFORGE_EVENT_SWITCH || event->kind == DUOFORGE_EVENT_DRAG) &&
        side != digest->viewer && event->reserved[0] != 0u) { member = (uint32_t)event->reserved[0] - 1u; }
    if (side >= DUOFORGE_SIDE_COUNT || member >= battle->sides[side].member_count || member >= DUOFORGE_MAX_ROSTER) {
        dfi_observation_error(digest, DUOFORGE_E_INVARIANT, "observation_identity", event->kind); return;
    }
    const dfi_member *m = &battle->sides[side].members[member];
    uint32_t forme = m->species_id;
    if (battle->tail.sides[side].forme_now[member] != 0u) {
        forme = (uint32_t)battle->tail.sides[side].forme_now[member] - 1u;
    } else if (m->is_mega != 0u) {
        forme = dfi_mega_of(m->species_id, m->item);
    }
    if (!dfi_u32_to_u16(forme, &digest->identity[index].forme)) {
        dfi_observation_error(digest, DUOFORGE_E_INVARIANT, "observation_identity_forme", event->kind); return;
    }
    digest->identity[index].gender = m->gender;
    digest->identity[index].valid = 1u;
}

static const char *dfi_line_name(uint32_t kind)
{
    switch (kind) {
    case DUOFORGE_EVENT_TURN: return "TURN";
    case DUOFORGE_EVENT_SWITCH: return "SWITCH";
    case DUOFORGE_EVENT_DRAG: return "DRAG";
    case DUOFORGE_EVENT_REVIVE: return "REVIVE";
    case DUOFORGE_EVENT_ILLUSION_END: return "ILLUSION_END";
    case DUOFORGE_EVENT_MOVE: return "MOVE";
    case DUOFORGE_EVENT_DAMAGE: return "DAMAGE";
    case DUOFORGE_EVENT_HEAL: return "HEAL";
    case DUOFORGE_EVENT_FAINT: return "FAINT";
    case DUOFORGE_EVENT_CANT: return "CANT";
    case DUOFORGE_EVENT_MISS: return "MISS";
    case DUOFORGE_EVENT_CRIT: return "CRIT";
    case DUOFORGE_EVENT_SUPER_EFFECTIVE: return "SUPER_EFFECTIVE";
    case DUOFORGE_EVENT_RESISTED: return "RESISTED";
    case DUOFORGE_EVENT_IMMUNE: return "IMMUNE";
    case DUOFORGE_EVENT_FAIL: return "FAIL";
    case DUOFORGE_EVENT_PROTECT: return "PROTECT";
    case DUOFORGE_EVENT_BLOCKED: return "BLOCKED";
    case DUOFORGE_EVENT_BOOST: return "BOOST";
    case DUOFORGE_EVENT_UNBOOST: return "UNBOOST";
    case DUOFORGE_EVENT_STATUS: return "STATUS";
    case DUOFORGE_EVENT_CURE_STATUS: return "CURE_STATUS";
    case DUOFORGE_EVENT_CONFUSION_START: return "CONFUSION_START";
    case DUOFORGE_EVENT_CONFUSION_END: return "CONFUSION_END";
    case DUOFORGE_EVENT_CONFUSED: return "CONFUSED";
    case DUOFORGE_EVENT_FLASH_FIRE: return "FLASH_FIRE";
    case DUOFORGE_EVENT_WEATHER: return "WEATHER";
    case DUOFORGE_EVENT_FIELD_START: return "FIELD_START";
    case DUOFORGE_EVENT_FIELD_END: return "FIELD_END";
    case DUOFORGE_EVENT_SIDE_START: return "SIDE_START";
    case DUOFORGE_EVENT_SIDE_END: return "SIDE_END";
    case DUOFORGE_EVENT_ITEM_END: return "ITEM_END";
    case DUOFORGE_EVENT_FORME: return "FORME";
    case DUOFORGE_EVENT_MEGA: return "MEGA";
    case DUOFORGE_EVENT_PREPARE: return "PREPARE";
    case DUOFORGE_EVENT_ANIMATION: return "ANIMATION";
    case DUOFORGE_EVENT_ABILITY: return "ABILITY";
    case DUOFORGE_EVENT_ACTIVATE: return "ACTIVATE";
    case DUOFORGE_EVENT_UPKEEP: return "UPKEEP";
    case DUOFORGE_EVENT_RESULT: return "RESULT";
    case DUOFORGE_EVENT_SINGLE_TURN: return "SINGLE_TURN";
    case DUOFORGE_EVENT_VOLATILE_START: return "VOLATILE_START";
    case DUOFORGE_EVENT_VOLATILE_END: return "VOLATILE_END";
    case DUOFORGE_EVENT_TYPE_CHANGE: return "TYPE_CHANGE";
    case DUOFORGE_EVENT_ITEM_START: return "ITEM_START";
    case DUOFORGE_EVENT_CLEAR_ALL_BOOSTS: return "CLEAR_ALL_BOOSTS";
    case DUOFORGE_EVENT_ITEM_SHOWN: return "ITEM_SHOWN";
    case DUOFORGE_EVENT_SWAP: return "SWAP";
    case DUOFORGE_EVENT_COPY_BOOST: return "COPY_BOOST";
    case DUOFORGE_EVENT_PROTECT_BROKEN: return "PROTECT_BROKEN";
    default: return "UNKNOWN";
    }
}

void dfi_observation_fold(dfi_observation_digest *digest, const duoforge_event *projected, uint32_t index)
{
    if (digest->status != DUOFORGE_OK) { return; }
    if (index >= DUOFORGE_MAX_EVENTS || digest->rows >= DUOFORGE_MAX_EVENTS) {
        dfi_observation_error(digest, DUOFORGE_E_CAPACITY, "observation_rows", index); return;
    }
    uint8_t bytes[DFI_OBSERVATION_LINE_MAX];
    uint32_t n = 0u;
    const duoforge_status s = dfi_observation_line_encode(projected, &digest->identity[index], bytes, sizeof bytes, &n);
    if (s != DUOFORGE_OK) {
        dfi_observation_error(digest, s, "observation_line_unclassified", projected->kind);
        uint32_t at = 0u;
        while (digest->reason[at] != '\0') { ++at; }
        digest->reason[at++] = '/';
        const char *name = dfi_line_name(projected->kind);
        for (uint32_t k = 0u; name[k] != '\0' && at + 1u < sizeof digest->reason; ++k) {
            digest->reason[at++] = name[k];
        }
        digest->reason[at] = '\0';
        return;
    }
    uint8_t length[4]; dfi_store_u32le(length, n);
    if (!dfi_sha256_update(&digest->hash, length, sizeof length) || !dfi_sha256_update(&digest->hash, bytes, n)) {
        dfi_observation_error(digest, DUOFORGE_E_EXHAUSTED, "observation_hash_length", index); return;
    }
    digest->rows += 1u;
}

void dfi_observation_finish(dfi_observation_digest *digest, const duoforge_context *ctx,
    const duoforge_battle *battle, const duoforge_step_result *result, uint32_t event_count)
{
    if (digest->status != DUOFORGE_OK) { return; }
    if (digest->rows != event_count) {
        dfi_observation_error(digest, DUOFORGE_E_INVARIANT, "observation_rows_mismatch", event_count); return;
    }
    duoforge_request request;
    duoforge_observation view;
    duoforge_observation_ext ext;
    duoforge_factored_domain domain;
    duoforge_status s = duoforge_battle_request(ctx, battle, digest->viewer, &request);
    if (s == DUOFORGE_OK) { s = duoforge_battle_observe(ctx, battle, digest->viewer, &view); }
    if (s == DUOFORGE_OK) { s = duoforge_battle_observe_ext(ctx, battle, digest->viewer, &ext); }
    if (s == DUOFORGE_OK) { s = duoforge_battle_factored(ctx, battle, digest->viewer, &domain); }
    if (s != DUOFORGE_OK) {
        dfi_observation_error(digest, s, "observation_request_query", result->boundary_kind); return;
    }
    dfi_observation_finish_view(digest, result, &request, &view, &ext, &domain, event_count);
}

void dfi_observation_finish_view(dfi_observation_digest *digest,
    const duoforge_step_result *result, const duoforge_request *request,
    const duoforge_observation *view, const duoforge_observation_ext *ext,
    const duoforge_factored_domain *domain, uint32_t event_count)
{
    if (digest->status != DUOFORGE_OK) { return; }
    if (digest->rows != event_count) {
        dfi_observation_error(digest, DUOFORGE_E_INVARIANT, "observation_rows_mismatch", event_count); return;
    }
    uint8_t bytes[DFI_OBSERVATION_REQUEST_MAX];
    uint32_t n = 0u;
    const duoforge_status s = dfi_observation_request_encode(result, request, view, ext, domain, bytes, sizeof bytes, &n);
    if (s != DUOFORGE_OK) {
        dfi_observation_error(digest, s, "observation_request_unclassified", result != NULL ? result->boundary_kind : 0u); return;
    }
    uint8_t count[4]; uint8_t length[4];
    dfi_store_u32le(count, digest->rows); dfi_store_u32le(length, n);
    if (!dfi_sha256_update(&digest->hash, count, sizeof count) ||
        !dfi_sha256_update(&digest->hash, length, sizeof length) ||
        !dfi_sha256_update(&digest->hash, bytes, n) || !dfi_sha256_final(&digest->hash, digest->digest)) {
        dfi_observation_error(digest, DUOFORGE_E_EXHAUSTED, "observation_hash_length", digest->rows); return;
    }
    if (!dfi_observation_key_nonzero(digest->digest)) {
        dfi_observation_error(digest, DUOFORGE_E_INVARIANT, "observation_digest_zero", 0u); return;
    }
    digest->complete = true;
}
