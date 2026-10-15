from mk import mon, team

def EXC(item=None, moves=('Earthquake', 'Protect', 'Swords Dance', 'Fissure'), ability='Mold Breaker', evs='2 HP / 32 Atk / 32 Spe', nature='Adamant'):
    return mon('Excadrill', item, ability, evs, nature, list(moves), 'M')
def STA(item=None, moves=('Brave Bird', 'Roost'), ability='Intimidate'):
    return mon('Staraptor', item, ability, '32 HP / 2 SpD / 32 Spe', 'Jolly', list(moves), 'F')
def GAR(item=None, moves=('Earthquake', 'Protect', 'Rock Slide'), ability='Rough Skin', evs='32 HP / 32 Atk / 2 Spe'):
    return mon('Garchomp', item, ability, evs, 'Jolly', list(moves), 'M')
def ROT(item=None, moves=('Hydro Pump', 'Nasty Plot', 'Thunder Wave'), ability='Levitate'):
    return mon('Rotom-Wash', item, ability, '32 HP / 32 SpA / 2 SpD', 'Modest', list(moves))
def RMW(item=None, moves=('Leaf Storm', 'Nasty Plot', 'Thunder Wave'), ability='Levitate'):
    return mon('Rotom-Mow', item, ability, '32 HP / 32 SpA / 2 SpD', 'Modest', list(moves))
def HYD(item=None, moves=('Dark Pulse', 'Nasty Plot', 'Earthquake'), ability='Levitate'):
    return mon('Hydreigon', item, ability, '32 HP / 32 SpA / 2 SpD', 'Modest', list(moves), 'M')
def SNO(item=None, moves=('Body Slam', 'Curse'), ability='Thick Fat'):
    return mon('Snorlax', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def AZU(item=None, moves=('Aqua Jet', 'Protect'), ability='Thick Fat'):
    return mon('Azumarill', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def MAM(item=None, moves=('Earthquake', 'Curse'), ability='Thick Fat'):
    return mon('Mamoswine', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def FOR(item=None, moves=('Spikes', 'Protect', 'Gyro Ball'), ability='Sturdy'):
    return mon('Forretress', item, ability, '32 HP / 32 Def / 2 SpD', 'Impish', list(moves), 'M')
def SKA(item=None, moves=('Roost', 'Protect'), ability='Sturdy'):
    return mon('Skarmory', item, ability, '32 HP / 32 Def / 2 SpD', 'Impish', list(moves), 'M')
def PIN(item=None, moves=('Guillotine', 'Earthquake', 'Rock Slide', 'Circle Throw'), ability='Hyper Cutter', evs='2 HP / 32 Atk / 32 Spe', nature='Adamant'):
    return mon('Pinsir', item, ability, evs, nature, list(moves), 'M')
def PAN(item=None, moves=('Fire Punch', 'Hammer Arm', 'Circle Throw', 'Knock Off'), ability='Mold Breaker', evs='32 HP / 32 Atk / 2 SpD', nature='Adamant'):
    return mon('Pangoro', item, ability, evs, nature, list(moves), 'M')
def TIN(item=None, moves=('Thunder Wave', 'Skill Swap', 'Gigaton Hammer', 'Protect'), ability='Mold Breaker', evs='32 HP / 2 Atk / 32 SpD', nature='Careful'):
    return mon('Tinkaton', item, ability, evs, nature, list(moves), 'F')
def RAM(item=None, moves=('Dragon Tail', 'Roar', 'Rock Slide', 'Protect'), ability='Mold Breaker', evs='32 HP / 32 Atk / 2 SpD', nature='Adamant'):
    return mon('Rampardos', item, ability, evs, nature, list(moves), 'M')
def BAS(item=None, moves=('Aqua Jet', 'Wave Crash', 'Protect', 'Waterfall'), ability='Mold Breaker', evs='32 HP / 32 Atk / 2 SpD', nature='Adamant'):
    return mon('Basculegion', item, ability, evs, nature, list(moves), 'M')
def DRG(item=None, moves=('Extreme Speed', 'Dragon Dance', 'Roost'), ability='Multiscale'):
    return mon('Dragonite', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def RHY(item=None, moves=('Rock Polish', 'Earthquake', 'Protect'), ability='Solid Rock'):
    return mon('Rhyperior', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def GHO(item=None, moves=('Nasty Plot', 'Shadow Ball', 'Protect'), ability='Good as Gold'):
    return mon('Gholdengo', item, ability, '32 HP / 32 SpA / 2 SpD', 'Modest', list(moves))
def ESP(item=None, moves=('Calm Mind', 'Psychic', 'Protect'), ability='Magic Bounce'):
    return mon('Espeon', item, ability, '32 HP / 32 SpA / 2 SpD', 'Modest', list(moves), 'F')
def MET(item=None, moves=('Protect', 'Iron Head'), ability='Clear Body'):
    return mon('Metagross', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves))
def INC(item=None, moves=('Fake Out', 'Protect', 'Flare Blitz'), ability='Intimidate'):
    return mon('Incineroar', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def GYA(item=None, moves=('Thunder Wave', 'Dragon Tail', 'Protect', 'Waterfall'), ability='Intimidate'):
    return mon('Gyarados', item, ability, '32 HP / 32 Atk / 2 SpD', 'Adamant', list(moves), 'M')
def RAI(item=None, moves=('Nasty Plot', 'Thunderbolt', 'Protect'), ability='Static'):
    return mon('Raichu', item, ability, '32 HP / 32 SpA / 2 SpD', 'Timid', list(moves), 'F')
def POR(item=None, moves=('Earthquake', 'Recover', 'Shadow Ball'), ability='Trace'):
    return mon('Porygon2', item, ability, '32 HP / 32 SpA / 2 SpD', 'Modest', list(moves))

BATTLES = {
 'mb_levitate_earthquake': dict(
   purpose='Mold Breaker (step K6, decision 0015 5dn): Excadrill (Mold Breaker) uses Earthquake into the Levitate holders Rotom-Wash and Hydreigon: both are hit (the ability is ignored). The next turn Garchomp (no breaker) uses Earthquake into the same two: -immune [from] ability: Levitate for both.',
   teams=[team(EXC(), STA(), GAR(), SNO(), AZU(), MAM()), team(ROT(), HYD(), SNO(), AZU(), MAM(), STA())],
   p1=['move 1, move 2', 'switch 3, move 2', 'move 1, move 2'],
   p2=['move 2, move 2', 'move 2, move 2', 'move 2, move 2'], seed=0x6101),
 'mb_levitate_ally': dict(
   purpose='Mold Breaker: Excadrill (Mold Breaker) uses Earthquake with its own ally Rotom-Mow (Levitate) beside it: the ally is hit too (every ability of every other Pokemon is ignored, the ally included; the user\'s own is not read). Mamoswine (no breaker), who moves later in the same turn, uses Earthquake: Rotom-Mow is immune again (-immune [from] ability: Levitate): the suppression ended with Excadrill\'s action.',
   teams=[team(EXC(), RMW(), GAR(), SNO(), AZU(), STA()), team(MAM(), SNO(), ROT(), HYD(), AZU(), STA())],
   p1=['move 1, move 2', 'move 1, move 2'],
   p2=['move 1, move 2', 'move 1, move 2'], seed=0x6102),
 'mb_sturdy_ohko': dict(
   purpose='Mold Breaker: Excadrill (Mold Breaker) uses Fissure into Forretress (Sturdy): Sturdy does not make the one-hit KO immune (no -immune line); the move rolls its accuracy and KOs (-ohko). Next turn Pinsir (Hyper Cutter, no breaker) uses Guillotine into a Sturdy Skarmory: -immune [from] ability: Sturdy.',
   teams=[team(EXC(), STA(), PIN(), SNO(), AZU(), MAM()), team(FOR(), SKA(), SNO(), AZU(), MAM(), STA())],
   p1=['move 4 1, move 2', 'switch 3, move 2', 'move 1 2, move 2'],
   p2=['move 2, move 2', 'move 2, move 2', 'move 2, move 2'], seed=0x6103),
 'mb_sturdy_survive': dict(
   purpose='Mold Breaker: Excadrill (Mold Breaker) boosts with Swords Dance, then one Earthquake takes a full-HP Forretress (Sturdy) from full HP to 0: Sturdy does not leave 1 HP (no -ability|Sturdy line).',
   teams=[team(EXC(), STA(), GAR(), SNO(), AZU(), MAM()), team(FOR(), SKA(), SNO(), AZU(), MAM(), STA())],
   p1=['move 3, move 2', 'move 1, move 2'],
   p2=['move 2, move 2', 'move 2, move 2'], seed=0x6104),
 'mb_sturdy_survive_control': dict(
   purpose='Control of mb_sturdy_survive: the same Swords Dance and Earthquake from an Excadrill with Sand Rush (no breaker): the full-HP Forretress survives at 1 HP and shows -ability|Sturdy.',
   teams=[team(EXC(ability='Sand Rush'), STA(), GAR(), SNO(), AZU(), MAM()), team(FOR(), SKA(), SNO(), AZU(), MAM(), STA())],
   p1=['move 3, move 2', 'move 1, move 2'],
   p2=['move 2, move 2', 'move 2, move 2'], seed=0x6104),
 'mb_multiscale_solidrock': dict(
   purpose='Mold Breaker: Pinsir (Mold Breaker) Rock Slide and Basculegion (Mold Breaker) Aqua Jet into a full-HP Dragonite (Multiscale) and Rhyperior (Solid Rock): neither damage-reducing ability applies (the numbers are the unreduced ones).',
   teams=[team(PIN(ability='Mold Breaker', moves=('Rock Slide', 'Earthquake', 'Guillotine', 'Circle Throw')), BAS(), GAR(), SNO(), AZU(), STA()), team(DRG(), RHY(), SNO(), AZU(), MAM(), STA())],
   p1=['move 1, move 1 2', 'move 1, move 1 2'],
   p2=['move 2, move 1', 'move 2, move 1'], seed=0x6105),
 'mb_thickfat_status': dict(
   purpose='Mold Breaker: Tinkaton (Mold Breaker) Thunder Wave into Gholdengo (Good as Gold): the status move lands (-status|par), and Pangoro (Mold Breaker) Fire Punch into Snorlax (Thick Fat): the Fire damage is not halved.',
   teams=[team(TIN(), PAN(), GAR(), SNO(), AZU(), STA()), team(GHO(), SNO(), MAM(), AZU(), ROT(), STA())],
   p1=['move 1 1, move 1 2', 'move 4, move 2'],
   p2=['move 1, move 2', 'move 1, move 2'], seed=0x6106),
 'mb_goodasgold_control': dict(
   purpose='Control of mb_thickfat_status: Tinkaton with Own Tempo (no breaker) uses Thunder Wave into Gholdengo (Good as Gold): -immune [from] ability: Good as Gold.',
   teams=[team(TIN(ability='Own Tempo'), PAN(), GAR(), SNO(), AZU(), STA()), team(GHO(), SNO(), MAM(), AZU(), ROT(), STA())],
   p1=['move 1 1, move 2', 'move 4, move 2'],
   p2=['move 1, move 2', 'move 1, move 2'], seed=0x6106),
 'mb_non_breakable_applies': dict(
   purpose='Mold Breaker: abilities that no breaker ignores still act: Pangoro (Mold Breaker) Hammer Arm into Garchomp (Rough Skin) hurts the user with Rough Skin, and Pinsir (Mold Breaker) Circle Throw into Raichu (Static) can be paralysed by Static.',
   teams=[team(PAN(), PIN(ability='Mold Breaker'), GAR(), SNO(), AZU(), STA()), team(GAR(), RAI(), SNO(), AZU(), MAM(), STA())],
   p1=['move 2 1, move 4 2', 'move 2 1, move 4 2'],
   p2=['move 2, move 1', 'move 2, move 1'], seed=0x6107),
 'mb_pinsir_mega': dict(
   purpose='Mold Breaker: Pinsir (Mold Breaker, Pinsirite) announces Mold Breaker when it enters; it Mega Evolves (Aerilate) and its Earthquake then meets Levitate: -immune [from] ability: Levitate (the flag follows the current ability).',
   teams=[team(PIN(item='Pinsirite', ability='Mold Breaker', moves=('Earthquake', 'Return', 'Protect', 'Circle Throw')), STA(), GAR(), SNO(), AZU(), MAM()), team(ROT(), HYD(), SNO(), AZU(), MAM(), STA())],
   p1=['move 1 mega, move 2'],
   p2=['move 2, move 2'], seed=0x6109),
 'mb_trace': dict(
   purpose='Mold Breaker: Porygon2 (Trace) enters against Excadrill (Mold Breaker) and copies it: -ability|Mold Breaker|Trace|[from] ability: Trace and the Start line; its next Earthquake ignores the Levitate of Rotom-Wash.',
   teams=[team(EXC(), STA(), GAR(), SNO(), AZU(), MAM()), team(SNO(), ROT(), POR(), AZU(), MAM(), STA())],
   p1=['move 3, move 2', 'move 3, move 2'],
   p2=['move 2, move 1', 'switch 3, move 1'], seed=0x610a),
 'mb_skill_swap': dict(
   purpose='Mold Breaker: Tinkaton (Mold Breaker) Skill Swap with Hydreigon (Levitate): both Start lines; Hydreigon now has Mold Breaker and its next Earthquake ignores the Levitate that Tinkaton now has.',
   teams=[team(TIN(), STA(), GAR(), SNO(), AZU(), MAM()), team(HYD(), SNO(), ROT(), AZU(), MAM(), STA())],
   p1=['move 2 1, move 2', 'move 4, move 2'],
   p2=['move 2, move 2', 'move 3, move 2'], seed=0x610b),
 'mb_magic_bounce': dict(
   purpose='Mold Breaker: Tinkaton (Mold Breaker) Thunder Wave into Espeon (Magic Bounce) is not reflected (-status|par); Gyarados (no breaker) Thunder Wave into the same Espeon is reflected and paralyses Gyarados.',
   teams=[team(TIN(), GYA(), GAR(), SNO(), AZU(), STA()), team(ESP(), SNO(), MAM(), AZU(), ROT(), STA())],
   p1=['move 1 1, move 1 1', 'move 4, move 3'],
   p2=['move 1, move 2', 'move 1, move 2'], seed=0x610c),
 'mb_drag_hazard': dict(
   purpose='Mold Breaker (the drag window): Forretress lays Spikes on the foe side; Rampardos (Mold Breaker) uses Dragon Tail and the dragged-in reserve, a Levitate holder, is grounded and takes the Spikes (the suppressor is still active when the drag-in runs).',
   teams=[team(RAM(), FOR(), GAR(), SNO(), AZU(), STA()), team(SNO(), AZU(), ROT(), HYD(), MAM(), STA())],
   p1=['move 4, move 1', 'move 1 1, move 3'],
   p2=['move 2, move 2', 'move 2, move 2'], seed=0x610d),
 'mb_drag_hazard_control': dict(
   purpose='Control of mb_drag_hazard: the same Dragon Tail from a Rampardos with Sheer Force (no breaker): the dragged-in Levitate reserve is not grounded and takes no Spikes damage.',
   teams=[team(RAM(ability='Sheer Force'), FOR(), GAR(), SNO(), AZU(), STA()), team(SNO(), AZU(), ROT(), HYD(), MAM(), STA())],
   p1=['move 4, move 1', 'move 1 1, move 3'],
   p2=['move 2, move 2', 'move 2, move 2'], seed=0x610d),
 'mb_drag_intimidate': dict(
   purpose='Mold Breaker (the drag window): Rampardos (Mold Breaker) uses Dragon Tail and the dragged-in reserve has Intimidate: the Clear Body of Rampardos\'s ally Metagross is ignored (the Attack drop is not blocked).',
   teams=[team(RAM(), MET(), GAR(), SNO(), AZU(), STA()), team(SNO(), AZU(), INC(ability='Intimidate'), STA(), MAM(), ROT())],
   p1=['move 1 1, move 1', 'move 4, move 1'],
   p2=['move 2, move 2', 'move 2, move 2'], seed=0x610e),
 'mb_drag_intimidate_control': dict(
   purpose='Control of mb_drag_intimidate: the same Dragon Tail from a Rampardos with Sheer Force (no breaker): the dragged-in Intimidate is blocked by Metagross (Clear Body).',
   teams=[team(RAM(ability='Sheer Force'), MET(), GAR(), SNO(), AZU(), STA()), team(SNO(), AZU(), INC(ability='Intimidate'), STA(), MAM(), ROT())],
   p1=['move 1 1, move 1', 'move 4, move 1'],
   p2=['move 2, move 2', 'move 2, move 2'], seed=0x610e),
}
