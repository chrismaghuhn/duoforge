"""Deterministic private E4 games and prepared search requests.

Freeze game groups before extracting any rows. No evaluation or fitting here:
the pinned teacher supplies candidates only; Showdown's seeded random policy
plays the games. Accepted C worlds supply the eventual neural inputs. Never
relabel an open-sheet world as closed: closed uses the real ParticleTracker.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import io
import json
import subprocess
import sys

import numpy as np
from export_bc6 import canonical, file_sha, sha, write_private

ROOT=Path(__file__).resolve().parents[2]
SEED=0x2026101500040001
SPLIT_SEED=0x2026101500040002
PS_PIN="b2cb775b0616115b775534eaeff50300e1fc81fc"
GAMES={"training":128,"calibration":128,"holdout":1024}
MAX_STEPS=96
MAX_PER_SEAT=2
COVERAGE_EXTRAS=("PIVOT","REPLACEMENT")
SEARCH=dict(seed=SEED ^ 0x53524348,k=8,m=8,s=16,capacity=1024,workers=1,rule="ev",lam=0.5,species_prior="count")
RANDOM_TEAMS=64


def word(*parts):
    return int.from_bytes(__import__("hashlib").sha256(canonical([SEED,*parts])).digest()[:8],"little")


def split_of(team_sha):
    # Team generation families never cross splits; no row-level random split.
    n=word(SPLIT_SEED,team_sha)%6
    return "training" if n==0 else "calibration" if n==1 else "holdout"


def plan(teams, engine, generator):
    groups={s:[f"e4-v1/{s}/{g:04d}" for g in range(n)] for s,n in GAMES.items()}
    return dict(schema=1,seed=SEED,split_seed=SPLIT_SEED,groups=groups,
        training="reserved; no training or data extraction in this conversion",
        games=[dict(group=group,split=s,index=i,battle_seed="sodium,"+"".join(
            f"{word(group,j):016x}" for j in range(4)),policy_seed=word(group,"policy")&0xffffffff)
            for s in ("calibration","holdout") for i,group in enumerate(groups[s])],
        registry=teams,engine=engine,generator=generator,search=SEARCH,
        root_limit_per_seat=MAX_PER_SEAT,extra_first_boundary=list(COVERAGE_EXTRAS),
        max_steps=MAX_STEPS,random_teams_per_split=RANDOM_TEAMS,
        neural_rows_minimum=131072,heldout_roots_per_stratum=2048,
        named_refusals="count, keep frozen attempt inventory; never substitute another game",
        live_rule="ev",solver="lp",padding=1024,closed_worlds=16)


def save_npz(path, arrays):
    out=io.BytesIO();np.savez_compressed(out,**arrays)
    write_private(path,out.getvalue(),False)


def requests_for_game(root, spec, trace, node, checkout):
    """Replay the newly generated random game with the existing client oracle.
    Its spec/traces live only below the private run directory, never in repo.
    """
    name=spec["name"]
    for kind,value in (("specs",spec),("traces",trace)):
        dest=root/"tests/reference"/kind;dest.mkdir(parents=True,exist_ok=True,mode=0o700)
        write_private(dest/(name+".json"),canonical(value),False)
    result=subprocess.run([node,str(ROOT/"tools/reference/ps_client.js"),str(checkout),str(root),name],
        capture_output=True,text=True,encoding="utf-8",check=True,timeout=600)
    messages=[json.loads(line) for line in result.stdout.splitlines()]
    return [[m["lines"] for m in messages if m["to"]==f"p{seat+1}"] for seat in (0,1)]


def collect(split, games, out, checkpoint_path, tables, model, params, node, checkout, sources):
    """Private corpus of the actual open/closed tracker -> accepted worlds.
    Successful requests are saved before value evaluation. Unsupported games
    stop by name and count; model/encoding/unexpected errors abort the run.
    """
    sys.path.insert(0,str(ROOT/"tools/reference"))
    from diff_driver import NodeWorker
    import duoforge
    from duoforge import _layout
    from duoforge_live import cts, game, policy, search as live_search, teams as live_teams, lines
    from duoforge_search import honest, seeds
    from duoforge_learn import checkpoint
    encoder=checkpoint.encoder_of(checkpoint.load(checkpoint_path)[1])
    ext=checkpoint.ext_supported_of(checkpoint.load(checkpoint_path)[1])
    net=policy.ModelPolicy(model,params,encoder,ext)
    records=[];refusals=Counter();attempts=[]
    folder=out/split;folder.mkdir(mode=0o700)
    sets=[s for _,text in sources for s in live_teams.unpack(live_teams.pack(text))]
    prior=cts.SetPrior(tables,sets)
    kind=__import__("duoforge_learn.train",fromlist=["DATA_KINDS"]).DATA_KINDS[tables.kind]

    class Capture(honest.Honest):
        def _decision(self,p,key,own,own_p,weights,last_step,costs,budget=None,*,refused="score",groups=None,
                      steps_left=None):
            request=self._prepare(p,key,own,weights,last_step,costs,groups)
            # Digest sibling vs old expand: independently repeat the actual C
            # step with identical seeds/choices; projection failure is not a
            # battle refusal. Also repeat the digest to check reproducibility.
            total=len(request.rows);digests=np.zeros((total,32),np.uint8)
            digest_status=np.zeros(total,np.uint32);cutoff_tiebreaks=np.zeros(total,np.uint32)
            for start in range(0,total,self.capacity):
                end=min(total,start+self.capacity);w=request.plan[2][start:end].astype(np.uint32)
                args=(self.worlds,self.encoder,self.ext_supported,self.seed,
                    np.full(self.s,key,np.uint64),np.full(self.s,p,np.uint8),w,w,request.choices[start:end])
                old=tuple(x.copy() for x in self.leaves.expand(*args))
                def cutoff_values(outputs):
                    values=np.zeros(len(outputs[1]),np.uint32)
                    for x in np.flatnonzero((outputs[1]==0)&(outputs[4]==0)):
                        try:values[x]=self.leaves.tiebreak(int(x))
                        except duoforge.DuoforgeError as error:
                            if error.status_name!="DUOFORGE_E_UNSUPPORTED":raise
                            values[x]=0xffffffff
                    return values
                first=tuple(x.copy() for x in self.leaves.expand_digest(*args))
                first_breaks=cutoff_values(first)
                second=tuple(x.copy() for x in self.leaves.expand_digest(*args))
                second_breaks=cutoff_values(second)
                if any(not np.array_equal(a,b) for a,b in zip(old,first[:5])) or \
                        not np.array_equal(first_breaks,second_breaks):
                    raise ValueError("bc6_expansion_or_cutoff_classification")
                if any(not np.array_equal(a,b) for a,b in zip(first,second)):
                    raise ValueError("bc6_digest_reproduction")
                row,st,enc,_,res,dig,ds=first
                valid=(st==0)&(ds==0)
                if (valid&~dig.any(axis=1)).any():raise ValueError("bc6_zero_valid_digest")
                keys,refused_keys=self.leaves.observation_keys(np.arange(end-start),p)
                if not np.array_equal(refused_keys,~valid) or not np.array_equal(keys,np.where(valid[:,None],dig,0)):
                    raise ValueError("bc6_digest_valid_key_mask")
                cutoff_tiebreaks[start:end]=first_breaks
                if not all(np.array_equal(a,b) for a,b in ((row,request.rows[start:end]),(st,request.step[start:end]),
                        (enc,request.encode[start:end]),(res,request.results[start:end]))):
                    raise ValueError("bc6_expansion_classification")
                if ((st==0)&(enc!=0)).any():raise ValueError("bc6_encoding_failed")
                if ((st!=0)&(st!=_layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"])).any():
                    raise ValueError("bc6_step_unexplained")
                digests[start:end]=dig;digest_status[start:end]=ds
            ident=f"{len(records):06d}"
            arrays={name:getattr(request,name) for name in ("own","weights","foe_pairs","qs","choices","rows",
                    "step","encode","results","tiebreaks","open")}
            arrays.update(i=request.plan[0],j=request.plan[1],w=request.plan[2],own_prior=np.asarray(own_p),
                          digest=digests,digest_status=digest_status,cutoff_tiebreaks=cutoff_tiebreaks,
                          valid_key=(request.step==0)&(digest_status==0))
            path=folder/(ident+".npz");save_npz(path,arrays)
            refused_own=np.unique(request.plan[0][request.step==_layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]])
            eligible=len(refused_own)<len(request.own)
            records.append(dict(file=str(path.relative_to(out)),sha256=file_sha(path),**self.identity,
                                eligible=eligible,refusal=None if eligible else "engine_refused_leaves",
                                seat=int(p),key=int(key),uniform=float(seeds.play_uniforms(self.seed,np.array([key],np.uint64))[0]),
                                neural_rows=int(request.open.sum()),leaf_count=total,worlds=self.s,
                                step_refused=int((request.step!=0).sum()),terminal=int((request.results!=0).sum()),
                                digest_refused=int(((request.step==0)&(digest_status!=0)).sum())))
            self.last.append({})  # parent decide appends its frozen hypotheses
            return dict(kind="forced",choice=int(own[0]))  # stream's real choice is accepted, never this shadow's

    with duoforge.Context(data_kind=kind) as context:
        table,_,_=honest.live_spread_table(context)
        with Capture(context,model,params,encoder,ext,table=table,foe_net=(model,params,encoder,ext),**SEARCH) as search:
            live=live_search.LiveSearch(search)
            worker=NodeWorker(node,str(checkout))
            try:
                for g in games:
                    group=g["group"];i=g["index"]
                    selected=[sources[word(group,"team",p)%len(sources)] for p in (0,1)]
                    spec=dict(name=f"e4_{split}_{i:04d}",format="gen9championsvgc2026regmc",data="pool",
                        seed=g["battle_seed"],teams=[text for _,text in selected])
                    played=worker.play({k:spec[k] for k in ("format","seed","teams")},
                        dict(seed=g["policy_seed"],max_steps=MAX_STEPS,switch_weight=0.1,mega_weight=0.5,domain_rate=0))
                    spec["choices"]=played["choices"]
                    trace=json.loads(worker.record(spec,spec["name"]+".json"))
                    streams=requests_for_game(out/"generated",spec,trace,node,checkout)
                    attempts.append(dict(group=group,source_teams=[s[0] for s in selected],
                        spec_sha256=sha(canonical(spec)),trace_sha256=sha(canonical(trace)),ended=played["ended"]))
                    for arm in ("open","closed"):
                        for p in (0,1):
                            room=f"{group}/{arm}/{p}";episode=g["index"]+1+(128 if split=="holdout" else 0)
                            kwargs=dict(search=live,room=room,episode=episode)
                            battle=game.Game.closed_sheets(tables,net,spec["teams"][p],prior,seed=word(group,"particles"),
                                n=16,**kwargs) if arm=="closed" else game.Game(tables,net,spec["teams"][p],**kwargs)
                            done=0;captured=0;boundaries=set();flags=set()
                            try:
                                for message in streams[p]:
                                    if any(x.startswith("|win|") or x=="|tie" for x in message):break
                                    m=[x for x in message if not (arm=="closed" and x.startswith("|showteam|"))]
                                    for line in m:
                                        if line.startswith(("|-weather|","|-fieldstart|","|-sidestart|")):flags.add("field")
                                        if line.startswith(("|-item|","|-enditem|")):flags.add("item")
                                        if line.startswith("|-ability|") or "[from] ability:" in line:flags.add("ability")
                                    battle.feed(m)
                                    if not (battle.ready and battle.epoch>done):continue
                                    done=battle.epoch
                                    if battle.asked():
                                        # Classify boundary from the tracker's own authoritative request parts.
                                        base=(battle.tracker.particles[0].tracker if arm=="closed" else battle.tracker)
                                        part=base.public_parts();boundary=int(part["request"]["boundary_kind"])
                                        name=__import__("duoforge_search.lookahead",fromlist=["_BOUNDARIES"])._BOUNDARIES[boundary]
                                        take=name!="TEAM_SELECTION" and (captured<MAX_PER_SEAT or
                                            name in COVERAGE_EXTRAS and name not in boundaries)
                                        search.identity=dict(group=group,stratum=arm,boundary=name,interactions=sorted(flags))
                                        old=search.k;start=len(records)
                                        try:
                                            if not take:search.k=1  # keep preview/turn history, no shadow leaves
                                            battle.candidates(3600.0)
                                        finally:search.k=old
                                        if battle.dirty is not None:raise ValueError("bc6_candidate_or_encoding_failed")
                                        captured+=len(records)>start
                                        if len(records)>start:boundaries.add(name)
                                        if battle.outcomes and battle.outcomes[-1].fallback is not None:
                                            refusals[f"{arm}:search:{battle.outcomes[-1].cause}"]+=1
                                    choice=trace["steps"][done-1]["input"].get(f"p{p+1}") if done<=len(trace["steps"]) else None
                                    if choice is not None:battle.accepted(choice)
                            except lines.Stop as error:
                                refusals[f"{arm}:tracker:{error.reason.split(':')[0]}"]+=1
                            # Never silently skip a model, parser or invariant error.
                    print(json.dumps(dict(phase="corpus",split=split,game=i+1,roots=len(records))),flush=True)
            finally:
                worker.close();live.close()
    for record in records:
        if not record["eligible"]:refusals[record["stratum"]+":engine_refused_leaves"]+=1
    manifest=dict(schema=1,split=split,requests=records,attempts=attempts,refusals=dict(refusals))
    write_private(out/(split+".json"),canonical(manifest),False)
    return manifest
