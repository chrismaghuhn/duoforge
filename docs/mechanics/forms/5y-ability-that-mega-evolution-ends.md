<a id="5y"></a>

# 5y. The ability that a Mega Evolution ends (a conformance fix, found by the first G29 mirror campaigns; no public value, no version bump).

- Area: forms
- Step: -
- Tests: -

5y. **The ability that a Mega Evolution ends (a conformance fix, found by the first G29 mirror campaigns; no public value, no version bump).** `Pokemon.setAbility` runs the old ability's `End` event before it sets the new one (`sim/pokemon.ts:1923`, `singleEvent('End', oldAbility, ...)`), and the Mega Evolution's `formeChange` calls it (`:1487`). Of the 19 abilities with an `onEnd` (`data/abilities.ts`; the Champions mod has none) three are modelled: Unburden (`:5243-5245`, removes its volatile; done since step G24), **Flash Fire** (`:1351-1353`, removes the `flashfire` volatile: a Gardevoir whose Trace copied Flash Fire has it after a Fire move hit it, and the Mega Evolution ends it with `-end|X|ability: Flash Fire|[silent]`; `dfi_run_mega` kept it, so the position still showed Flash Fire) and Unnerve (`:5265-5267`, clears the `unnerved` flag of its ability state, which the engine does not keep: the foes' berries follow the ability that the holder has now). `dfi_run_mega` now clears the Flash Fire flag with Unburden's. The Trace copy (`dfi_trace`) ends nothing: the ability that it replaces is Trace itself, which has no `onEnd`. Nothing else that the engine keeps on a position belongs to an ability. Evidence: the corpus case `fz_9900100_705_min` (Gardevoir copies Ceruledge's Flash Fire, Bitter Blade hits it, it Mega Evolves), which diverged before the fix (observation, step 2) and passes after, and a mutation check (the Flash Fire clear removed: the corpus case diverges again).
