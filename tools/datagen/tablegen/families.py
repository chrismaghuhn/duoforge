"""What the item and ability families share: the parameter codes of weather and terrain, the family
derivation from one strict pattern, the handler ids and the rows the turn code implements by id.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area from
gen_closure.py@8800b625).
"""

from .source import fail, fields, NoMatch

FAMILY_PARAM_NONE = 0xFF
# The weather and terrain codes of the family column are the engine's state values (DFI_WEATHER_* and
# DFI_TERRAIN_* of src/state/battle_internal.h, which duoforge.data.pool_tables checks), by Showdown's id.
WEATHER_CODES = {'raindance': ('RAIN', 1), 'sunnyday': ('SUN', 2), 'sandstorm': ('SAND', 3), 'snowscape': ('SNOW', 4)}
TERRAIN_CODES = {'grassyterrain': ('GRASSY', 1), 'psychicterrain': ('PSYCHIC', 2), 'electricterrain': ('ELECTRIC', 3),
                 'mistyterrain': ('MISTY', 4)}
# A rain or sun setter skips the Primal Pokemon with their orb (data/abilities.ts, Drizzle and Drought). No Primal
# Pokemon is legal in the format; the guard is part of the weather pattern and must be exactly this one.
PRIMAL_GUARD = {'raindance': ('kyogre', 'blueorb'), 'sunnyday': ('groudon', 'redorb')}
HANDLER_IDS = ['NONE', 'UNMODELED']
# Items and abilities that a step of the expansion implements in the turn code by id (they have no family): modelled
# by definition, like the closure and Team C rows. The step that marks such a row in the support manifest adds its id
# here, which changes the handler column and so the POOL table hash, as any pool change does; a row that is marked and
# still has the UNMODELED handler fails duoforge.data.pool_tables. G4: Focus Sash, Rock Head. G12: Floettite (the Mega
# Stone of Floette-Eternal), Flower Veil and Fairy Aura. G14: Rough Skin, Poison Touch and Thermal Exchange. G16: Sticky Hold (Knock Off reads it by id). AC1: Trace (the entry copy of a foe's ability). G15: Psychic Seed (Grassy Seed's rule for the other terrain). G22: Sand Rush, Swift Swim, Slush Rush and Chlorophyll (the doubled Speed in their weather, tools/datagen/pool_families.js ENGINE_ORDER), Sand Rush's immunity to Sandstorm, Inner Focus (no flinch, no Intimidate drop) and Liquid Voice (a sound move becomes Water). G23-C: Levitate (isGrounded and the Ground immunity). G49: Muscle Band, Wise Glasses (base power by category) and Bright Powder (the target's accuracy).
ENGINE_ROWS = {'items': ['airballoon', 'ironball', 'bindingband', 'focussash', 'floettite', 'psychicseed', 'electricseed', 'mistyseed', 'expertbelt', 'ejectbutton',
                         'widelens', 'muscleband', 'wiseglasses', 'brightpowder', 'redcard', 'lumberry', 'mentalherb', 'damprock', 'heatrock',
                         'smoothrock', 'icyrock', 'terrainextender', 'scopelens', 'leek',
                         # I1 (decision 0015 entry 5ef): one clause each at an existing hook (items.py I1_ITEM_FACTS)
                         'normalgem', 'kingsrock', 'zoomlens', 'shellbell', 'bigroot', 'shedshell'],
               'abilities': ['magicguard', 'bulletproof', 'rivalry', 'leafguard', 'rockhead', 'flowerveil', 'fairyaura', 'roughskin', 'poisontouch', 'thermalexchange',
                             'stickyhold', 'trace', 'levitate', 'sandrush', 'swiftswim', 'slushrush', 'chlorophyll',
                             'innerfocus', 'liquidvoice', 'flamebody', 'clearbody', 'hospitality', 'overcoat',
                             'soundproof', 'unnerve', 'speedboost', 'compoundeyes', 'ironfist', 'sharpness', 'solidrock',
                             'technician', 'multiscale', 'galewings', 'raindish', 'friendguard', 'cursedbody', 'mirrorarmor', 'auraguard',
                             'hypercutter',
                             'scrappy',
                             'infiltrator',
                             'queenlymajesty',
                             'damp',
                             'sturdy',
                             'snowcloak',
                             'sandveil',
                             'static',
                             'justified',
                             'limber',
                             'solarpower',
                             'regenerator', 'toxicdebris', 'shadowtag', 'suctioncups', 'guarddog',
                             'steadfast', 'weakarmor', 'telepathy', 'voltabsorb', 'punkrock', 'moxie', 'synchronize', 'oblivious', 'keeneye', 'bigpecks', 'magicbounce', 'pressure', 'stancechange',
                             'sandforce', 'shellarmor', 'filter', 'stalwart', 'megalauncher', 'hugepower', 'thickfat', 'firemane', 'spicyspray', 'megasol', 'cloudnine', 'sheerforce', 'illusion', 'symbiosis', 'frisk',
                             'unaware', 'marvelscale', 'waterbubble', 'reckless', 'superluck', 'moody', 'cutecharm', 'purepower', 'battlearmor',
                             'magmaarmor', 'angerpoint', 'sniper', 'piercingdrill',
                             # A2a (decision 0015 entry 5dy): one clause each at an existing hook (abilities.py A2A_ABILITY_FACTS)
                             'illuminate', 'whitesmoke', 'waterabsorb', 'eartheater', 'motordrive', 'icebody', 'surgesurfer',
                             'quickfeet', 'corrosion', 'purifyingsalt', 'gooey', 'poisonpoint', 'tangledfeet', 'naturalcure']}


def derive_family(src, champ, rid, expected, matchers, what):
    """The family fact of one item or ability: the pattern result of the family that decision 0015 lists it in.
    A listed member that deviates from the pattern of its family fails; so does an unlisted one that follows a
    pattern (it should be listed). The Champions mod may only change isNonstandard of a member. Returns
    (family, fact) with fact the Showdown name of the type, weather or terrain, None for no family."""
    e = src.entry(rid)
    if e is None:
        fail('%s %s: entry not found in %s' % (what, rid, src.rel))
    f = fields(e[2])
    found, why = {}, {}
    for family, matcher in matchers:
        try:
            found[family] = matcher(f, rid)
        except NoMatch as err:
            why[family] = str(err)
    if expected == 'NONE':
        if found:
            fail('%s %s follows the %s pattern but decision 0015 does not list it as a member' % (
                what, rid, '/'.join(sorted(found))))
        return 'NONE', None
    if expected not in found:
        fail('%s %s is listed as %s but deviates: %s' % (what, rid, expected, why[expected]))
    ce = champ.entry(rid)
    if ce is not None:
        cf = fields(ce[2])
        if set(cf) - {'inherit', 'isNonstandard'}:
            fail('%s %s: the champions mod changes %s' % (what, rid, sorted(set(cf) - {'inherit', 'isNonstandard'})))
    return expected, found[expected]
