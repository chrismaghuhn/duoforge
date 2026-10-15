"""Frozen full-BC6 fidelity reducer. No threshold is a command-line option.

Input rows and decision records stay private. Only aggregate reports may be
returned to the cloud. Missing strata/classes/counts are failed/incomplete,
never a passing zero-denominator metric. No adoption or throughput claim.
"""
from __future__ import annotations
from collections import Counter
import math
import numpy as np

VALUE_ROWS = 131_072
GROUPS = 256
ROOTS_PER_STRATUM = 2048
BOUNDS = dict(mae=0.01, p99=0.05, maximum=0.15, agreement=0.98, stable=0.99,
              tv_mean=0.02, tv_p99=0.10, regret_mean=0.002, regret_p99=0.02)
STRATA = ("open", "closed")
RULES = ("ev", "nash", "live")
BOUNDARIES = ("TURN", "REPLACEMENT", "PIVOT")


def interval(hits, count):
    """Wilson 95% score interval, reported, point estimate is the frozen gate."""
    if not count:
        return None
    z=1.959963984540054; p=hits/count; d=1+z*z/count
    mid=(p+z*z/(2*count))/d
    half=z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/d
    return [max(0.0,mid-half),min(1.0,mid+half)]


def summary(values):
    a=np.asarray(values,dtype=np.float64)
    if not a.size:
        return None
    if not np.isfinite(a).all():
        raise ValueError("bc6_nonfinite_metric")
    return dict(n=int(a.size),mean=float(a.mean()),p99=float(np.percentile(a,99)),maximum=float(a.max()))


def compare_decision(teacher, candidate, uniform, live_rule, lam, solver):
    """Both tables already contain exact terminal/cutoff utilities, same order.

    Their weights, foe priors, own candidates and solver settings are shared.
    All reductions use the existing search rule implementation unchanged.
    """
    from duoforge_search import honest
    if teacher.shape!=candidate.shape or live_rule not in ("ev","nash","mix"):
        raise ValueError("bc6_decision_contract")
    backend,weights,qs,prior=solver
    rank=np.arange(teacher.shape[1])
    outcomes=[]; records=[]
    for value in (teacher,candidate):
        out,record=honest.reduce(value,weights,qs,rank,uniform,lam,solver=backend,
                                **({} if backend=="lp" else dict(prior=prior)))
        outcomes.append(out); records.append(record)
    ev=np.asarray(records[0]["expected"],np.float64)
    top=np.sort(ev)
    margin=float(top[-1]-top[-2]) if len(top)>1 else math.inf
    result={}
    for rule in RULES:
        actual=live_rule if rule=="live" else rule
        distributions=[]
        for out,record in zip(outcomes,records):
            if actual=="ev":
                pi=np.zeros(ev.size);pi[out["ev"]]=1.0
            else:
                pi=np.asarray(record["x"] if actual=="nash" else record["pi_X"],np.float64)
            distributions.append(pi)
        a,b=distributions
        result[rule]=dict(agree=outcomes[0][actual]==outcomes[1][actual],
            tv=float(np.abs(a-b).sum()/2),regret=max(0.0,float((a-b)@ev)),
            stable=bool(margin>=0.02),ev_agree=outcomes[0]["ev"]==outcomes[1]["ev"])
    return result


def report(values, decisions, *, groups, coverage, mechanics, reproduction, oracle):
    """values[stratum]: finite absolute errors of nonterminal neural rows only.
    decisions[stratum]: list of compare_decision records. Counts below are
    independently checked, not derived targets from the corpus being tested.
    """
    out=dict(schema=1,bounds=BOUNDS.copy(),adoption=False,strata={})
    gates=dict(mechanics=mechanics is True,reproduction=reproduction is True,
               oracle=oracle is True,groups=len(set(groups))>=GROUPS)
    row_count=0
    for stratum in STRATA:
        errors=np.asarray(values.get(stratum,()),np.float64)
        finite=bool(np.isfinite(errors).all()) and bool(errors.size)
        if finite and (errors<0).any():raise ValueError("bc6_negative_error")
        row_count+=errors.size
        roots=decisions.get(stratum,[])
        cov=coverage.get(stratum,{})
        required=[*(f"{b}:{p}" for b in BOUNDARIES for p in (0,1)),"field","item","ability"]
        section=dict(rows=int(errors.size),roots=len(roots),finite=finite,
                     errors=summary(errors) if finite else None,coverage=dict(cov),rules={})
        gates[stratum+".coverage"]=all(cov.get(k,0)>0 for k in required)
        gates[stratum+".roots"]=len(roots)==ROOTS_PER_STRATUM
        gates[stratum+".values"]=finite and section["errors"]["mean"]<=BOUNDS["mae"] and \
            section["errors"]["p99"]<=BOUNDS["p99"] and section["errors"]["maximum"]<=BOUNDS["maximum"]
        for rule in RULES:
            rows=[r[rule] for r in roots]
            n=len(rows);hit=sum(r["agree"] for r in rows)
            stable=[r for r in rows if r["stable"]];sh=sum(r["ev_agree"] for r in stable)
            tv=summary([r["tv"] for r in rows]);regret=summary([r["regret"] for r in rows])
            section["rules"][rule]=dict(n=n,hits=hit,agreement=hit/n if n else None,
                agreement_95=interval(hit,n),stable_n=len(stable),stable_hits=sh,
                stable_agreement=sh/len(stable) if stable else None,stable_95=interval(sh,len(stable)),
                near_ties=n-len(stable),tv=tv,regret=regret)
            gates[stratum+"."+rule]=bool(n and stable) and hit/n>=BOUNDS["agreement"] and \
                sh/len(stable)>=BOUNDS["stable"] and tv["mean"]<=BOUNDS["tv_mean"] and \
                tv["p99"]<=BOUNDS["tv_p99"] and regret["mean"]<=BOUNDS["regret_mean"] and \
                regret["p99"]<=BOUNDS["regret_p99"]
        out["strata"][stratum]=section
    gates["neural_row_count"]=row_count>=VALUE_ROWS
    out.update(gates={k:bool(v) for k,v in gates.items()},fidelity_pass=all(gates.values()))
    return out


def group_mean_interval(pairs, *, seed=0x2026101500040003, resamples=2000):
    """Predeclared 95% game-cluster percentile bootstrap of a weighted mean.
    pairs: per independent game (sum, denominator), including zero-denominator
    groups for conditional stable-EV metrics. A zero-denominator resample
    makes its interval incomplete instead of silently discarding that draw.
    """
    if not pairs:return None
    a=np.asarray(pairs,np.float64)
    if a.ndim!=2 or a.shape[1]!=2 or not np.isfinite(a).all() or (a[:,1]<0).any():
        raise ValueError("bc6_group_statistics")
    rng=np.random.default_rng(seed);means=[]
    for _ in range(resamples):
        sample=a[rng.integers(0,len(a),len(a))].sum(axis=0)
        if sample[1]<=0:return None
        means.append(sample[0]/sample[1])
    return [float(x) for x in np.percentile(means,[2.5,97.5])]
