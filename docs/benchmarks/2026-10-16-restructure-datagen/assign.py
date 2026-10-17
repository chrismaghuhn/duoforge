"""The area of every top-level statement of gen_closure.py: explicit rules, then the fixpoint, then a report."""
import json
import re
import sys
from collections import Counter, defaultdict

S5 = sys.argv[1]
S = json.load(open(S5 + '/stmts.json'))['stmts']
ORDER = ['source', 'species', 'moves', 'families', 'items', 'abilities', 'rules', 'tables', 'output', 'main']
rank = {a: i for i, a in enumerate(ORDER)}
EXPLICIT = {
    'source': 'hashlib io json os re sys gen_format PIN READER_INPUTS INPUTS TYPES STATS CATEGORIES fail Source fields '
              'scalar toid NoMatch norm shape field_is field_match wrap_names ReaderIndex',
    'species': 'SETS SETS_C SETS_G2 parse_forme type_chart IGNORED_TYPE_KEYS IGNORED_TYPE_KEYS_C IGNORED_TYPE_KEYS_P '
               'SAND_IMMUNE_TYPES POWDER_IMMUNE_TYPES FORMAT FORMAT_ID LEGAL_POOL load_legal_pool TAGS_PAST_UNOBTAINABLE '
               'BATTLE_ONLY_ROWS LEGAL_DESPITE_TAG FORME_ABILITIES_MAX LEARNSET_ENTRY learnset_moves ability_released '
               'forme_legal G59_POKEMON_FACTS',
    'families': 'FAMILY_PARAM_NONE WEATHER_CODES TERRAIN_CODES PRIMAL_GUARD derive_family HANDLER_IDS ENGINE_ROWS',
    'rules': 'K2_INHERIT_ONLY K2_BATTLE_FACTS K2_DAMAGE_ORDER K2_MOVE_FACTS check_k2_facts '
             'C2_IGNORED_KEYS C2_CHAMPIONS_OVERRIDES C2_FACTS C1_PART4_FACTS _C2_TOKEN c2_literal c2_entry_value '
             'check_c2_facts C4_IGNORED_KEYS C4_CHAMPION_OVERRIDES C4_FACTS c4_value check_c4_facts C5_IGNORED_KEYS '
             'C5_FACTS c5_value check_c5_facts C1_IGNORED_KEYS C1_FACTS c1_value check_c1_facts A0_IGNORED_KEYS '
             'A0_CHAMPIONS_OVERRIDES A0_FACTS check_a0_facts A0P1_IGNORED_KEYS A0P1_CHAMPION_OVERRIDES A0P1_FACTS '
             'A0P1_CALLBACKS A0P1_SAME_TEXT A0P1_WATERSHURIKEN_CALLBACK a0p1_value A0P1_STONES check_a0p1_pool '
             'check_a0p1_facts',
    # Skill Swap's failskillswap list (#624): the ability rows' flags, checked against the C list of dfi_fails_skillswap.
    'abilities': 'FAILSKILLSWAP_ABILITIES FAILSKILLSWAP_SOURCE failskillswap_c_ids check_failskillswap',
    'tables': 'build build_group build_pool handler_of BOUND_SOURCES check_bounds',
    'output': 'canonical define_block render closure_prefix check_prefix render_ext family_bytes handler_bytes '
              'forme_legal_bytes forme_id16 flags2_bytes heal_bytes static_flags_bytes static_hits_bytes flags3_bytes '
              'canonical_pool closure_projection ext_prefix check_pool_prefix check_names feature_summary render_pool',
    'main': 'main',
}
RULES = [
    ('abilities', r'(ABILIT|^ATE_|PINCH|pinch|ate_type|ability_param|terrain_setter|weather_setter)'),
    ('items', r'(ITEM|BERRY|BERRI|BOOSTER|STONE|SEED_PAIRS|berry|booster|item_param)'),
    ('moves', r''),  # everything else that is not a cross-area check
]
defs = {n: s['i'] for s in S for n in s['defines']}
area = {}
for a, names in EXPLICIT.items():
    for n in names.split():
        if n in defs:  # a name of a later main (#624) is absent before it
            area[defs[n]] = a
for s in S:
    if s['i'] in area:
        continue
    for a, rx in RULES:
        if any(re.search(rx, n) for n in s['defines']):
            area[s['i']] = a
            break
for s in S:
    if s['kind'] == 'If' and s['line'] > 6000:
        area[s['i']] = 'main'
    elif s['kind'] in ('If', 'Expr'):
        area.setdefault(s['i'], 'species' if s['kind'] == 'If' else 'source')
# A check that reads facts of two or more areas is a rule of its own step: it goes to `rules`.
for s in S:
    if s['defines'] and re.match(r'^(check_|c\d_|a0)', s['defines'][0]) and area[s['i']] not in ('render', 'tables'):
        used = {area[defs[u]] for u in s['uses'] if u in defs and area[defs[u]] in ('moves', 'items', 'abilities')}
        if len(used) > 1:
            area[s['i']] = 'rules'
moves_up = []
while True:
    v = False
    for s in S:
        a = area[s['i']]
        his = [(area[defs[u]], u) for u in s['uses'] if u in defs and defs[u] != s['i']]
        if not his:
            continue
        hi, why = max(his, key=lambda x: rank[x[0]])
        if rank[hi] > rank[a]:
            moves_up.append((s['defines'], a, hi, why))
            area[s['i']] = hi
            v = True
    if not v:
        break
for m in moves_up:
    print('UP', *m)
lines = Counter()
for s in S:
    lines[area[s['i']]] += s['end'] - s['line'] + 1
print(lines)
json.dump({str(k): v for k, v in area.items()}, open(S5 + '/area3.json', 'w'))
for a in ORDER:
    print('==', a, ' '.join(n for s in S if area[s['i']] == a for n in s['defines']))
