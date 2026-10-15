"""Private-file reader, offline scalar bridge and full-BC6 gate execution.

No network calls. This command never uploads an artifact or its input rows.
The prepared request files freeze all candidates, chance draws and statuses
before either value evaluator runs. Neither backend can change played games.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json
import struct
import subprocess

import numpy as np
from export_bc6 import canonical, file_sha, sha, fail, write_private
import bc6_gates as gates


class Runner:
    def __init__(self, executable, artifact, digest, kind, trace=None, trace_count=0):
        self.executable=str(executable)
        command=[self.executable,"--run",str(artifact),str(kind),digest]
        if trace is not None:command += [str(trace),str(trace_count)]
        self.child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)

    def _read(self, n):
        chunks=[]
        while n:
            data=self.child.stdout.read(n)
            if not data:
                fail("bc6_runner_truncated")
            chunks.append(data);n-=len(data)
        return b"".join(chunks)

    def values(self, rows):
        rows=np.asarray(rows,dtype="<f4")
        if rows.ndim!=2 or rows.shape[1]!=1094:fail("bc6_row_shape")
        values=[]
        # One tile keeps each reply below even a small anonymous pipe.
        # Writing a huge request before reading its replies can deadlock
        # against the 4 KiB Windows pipe. No threads/temporary weights.
        for start in range(0,len(rows),16):
            chunk=rows[start:start+16];n=len(chunk)
            self.child.stdin.write(struct.pack("<I",n)+chunk.tobytes());self.child.stdin.flush()
            if struct.unpack("<I",self._read(4))[0]!=n:fail("bc6_runner_protocol")
            reply=np.frombuffer(self._read(n*8),dtype="<u4").reshape(n,2)
            if reply[:,0].any():fail("bc6_inference_failed")
            values.append(reply[:,1].view("<i4").copy())
        return np.concatenate(values) if values else np.zeros(0,np.int32)

    def close(self):
        if self.child.poll() is None:
            try:
                self.child.stdin.write(bytes(4));self.child.stdin.flush();self.child.stdin.close()
            except (OSError,BrokenPipeError):pass
        self.child.stdout.close()
        error=self.child.stderr.read();code=self.child.wait();self.child.stderr.close()
        if code:fail("bc6_runner_exit:"+str(code)+":"+error.decode("utf-8",errors="replace")[:160])

    def abort(self):
        if self.child.poll() is None:self.child.kill()
        self.child.wait()
        for stream in (self.child.stdin,self.child.stdout,self.child.stderr):stream.close()

    def __enter__(self):return self
    def __exit__(self,typ,*rest):
        if typ is None:self.close()
        else:self.abort()


def load_request(root, record):
    path=(root/record["file"]).resolve()
    if not path.is_relative_to(root.resolve()) or file_sha(path)!=record["sha256"]:
        fail("bc6_request_identity")
    with np.load(path,allow_pickle=False) as archive:
        return {key:archive[key] for key in archive.files}


def select(records, count):
    """Coverage first, then round-robin by game. Selection reads metadata only,
    never a value/prediction. No single long game fills the root inventory.
    """
    from bc6_corpus import word
    records=[r for r in records if r.get("eligible",True)]
    order=sorted(records,key=lambda r:(word(r["group"],r["seat"],r["key"]),r["file"]))
    chosen=[];used=set()
    for b in gates.BOUNDARIES:
        for p in (0,1):
            candidates=[r for r in order if r["boundary"]==b and r["seat"]==p]
            if candidates:
                r=candidates[0]
                if r["file"] not in used:chosen.append(r);used.add(r["file"])
    for key in ("field","item","ability"):
        candidates=[r for r in order if key in r["interactions"]]
        if candidates:
            r=candidates[0]
            if r["file"] not in used:chosen.append(r);used.add(r["file"])
    groups={}
    for r in order:groups.setdefault(r["group"],[]).append(r)
    for index in range(max((len(rows) for rows in groups.values()),default=0)):
        for group in sorted(groups):
            rows=groups[group]
            if index<len(rows) and rows[index]["file"] not in used:
                r=rows[index];chosen.append(r);used.add(r["file"])
    if len(chosen)<count:fail("bc6_insufficient_roots")
    return chosen[:count]


def value_batches(model, params, rows, float_oracle):
    """Pinned padding 1024, including the last partial block; both functions
    see exactly the same binary32 array shape and zero tail."""
    teacher=[];oracle=[]
    for first in range(0,len(rows),1024):
        n=min(1024,len(rows)-first);padded=np.zeros((1024,1094),np.float32)
        padded[:n]=rows[first:first+n]
        model.check(padded)
        a=np.asarray(model.value(params,padded),np.float32)
        b=np.asarray(float_oracle(params,padded),np.float32)
        if not np.isfinite(a[:n]).all() or not np.isfinite(b[:n]).all():fail("bc6_float_nonfinite")
        teacher.append(a[:n].copy());oracle.append(b[:n].copy())
    a=np.concatenate(teacher);b=np.concatenate(oracle)
    if not np.array_equal(a.view(np.uint32),b.view(np.uint32)):fail("bc6_float_extraction_not_bit_equal")
    return a


def table(record, request, values, *, cutoff=False):
    """Use the existing terminal/tiebreak/refusal classification, never model
    errors as losses. Own candidates with a refused step leave both solves.
    """
    from duoforge_search import lookahead
    from duoforge import _layout
    breaks=request["cutoff_tiebreaks" if cutoff else "tiebreaks"].astype(np.int64);breaks[breaks==0xffffffff]=lookahead.UNRESOLVED
    tab=lookahead.table(values,request["step"],request["encode"],request["results"],breaks,
        tuple(request[k] for k in ("i","j","w")),record["seat"],cutoff)
    refused=np.unique(request["i"][request["step"]==_layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"]])
    keep=np.setdiff1d(np.arange(len(request["own"])),refused)
    if not len(keep):fail("bc6_all_candidates_refused")
    return tab.values[keep].transpose(2,0,1),request["own_prior"][keep]


def evaluate(root, records, runner_path, artifact, artifact_sha, kind, model, params, float_oracle,
             live_rule, lam, solver="lp"):
    errors={s:[] for s in gates.STRATA};decisions={s:[] for s in gates.STRATA}
    coverage={s:Counter() for s in gates.STRATA};groups=set();counts=Counter()
    stream=__import__("hashlib").sha256();repeat=__import__("hashlib").sha256()
    statistics={s:{} for s in gates.STRATA}
    def note(stratum,metric,group,numerator,denominator):
        pair=statistics[stratum].setdefault(metric,{}).setdefault(group,[0.0,0])
        pair[0]+=numerator;pair[1]+=denominator
    with Runner(runner_path,artifact,artifact_sha,kind) as native:
        for record in records:
            request=load_request(root,record);rows=request["rows"]
            neural=request["open"]
            if ((request["step"]==0)&(request["encode"]!=0)).any():fail("bc6_encoding_failed")
            # Don't ask the network about terminal/refused rows: the solver's
            # utility contract reads only neural rows. Padding stays fixed.
            teacher=np.zeros(len(rows),np.float32);candidate=np.zeros_like(teacher)
            if neural.any():
                teacher[neural]=value_batches(model,params,rows[neural],float_oracle)
                raw=native.values(rows[neural]);again=native.values(rows[neural])
                stream.update(raw.astype("<i4").tobytes());repeat.update(again.astype("<i4").tobytes())
                if not np.array_equal(raw,again):fail("bc6_integer_reproduction")
                candidate[neural]=raw.astype(np.float32)/(1<<20)
            if not np.isfinite(candidate[neural]).all():fail("bc6_integer_nonfinite")
            stratum=record["stratum"];groups.add(record["group"])
            absolute=np.abs(teacher[neural].astype(np.float64)-candidate[neural])
            errors[stratum].extend(absolute.tolist())
            note(stratum,"value_mae",record["group"],float(absolute.sum()),len(absolute))
            a,prior=table(record,request,teacher);b,other_prior=table(record,request,candidate)
            # Values must be completely ignored at exact terminal/cutoff
            # leaves. Derive the cutoff utility from the actual C tiebreak
            # of the repeated step, including its named unresolved sentinel.
            cut_a,_=table(record,request,teacher,cutoff=True)
            cut_b,_=table(record,request,candidate+np.float32(0.125),cutoff=True)
            if not np.array_equal(cut_a,cut_b):fail("bc6_cutoff_utility_changed")
            counts["cutoff_rows"]+=int(((request["step"]==0)&(request["results"]==0)).sum())
            counts["cutoff_unresolved"]+=int((request["cutoff_tiebreaks"]==0xffffffff).sum())
            if not np.array_equal(prior,other_prior):fail("bc6_candidate_inventory")
            solve=(solver,request["weights"],request["qs"],prior)
            first=gates.compare_decision(a,b,record["uniform"],live_rule,lam,solve)
            second=gates.compare_decision(a,b,record["uniform"],live_rule,lam,solve)
            if first!=second:fail("bc6_decision_reproduction")
            decisions[stratum].append(first)
            for rule,metrics in first.items():
                for metric in ("agree","tv","regret"):
                    note(stratum,rule+"."+metric,record["group"],float(metrics[metric]),1)
                note(stratum,rule+".stable_agreement",record["group"],
                     int(metrics["stable"] and metrics["ev_agree"]),int(metrics["stable"]))
            coverage[stratum][f"{record['boundary']}:{record['seat']}"]+=1
            coverage[stratum].update(record["interactions"])
            for key in ("terminal","step_refused","digest_refused"):counts[key]+=record[key]
            counts["invalid_keys"]+=int((~request["valid_key"]).sum())
            counts["neural_rows"]+=int(neural.sum())
    intervals={s:{metric:gates.group_mean_interval([rows[g] for g in sorted(rows)])
                  for metric,rows in metrics.items()} for s,metrics in statistics.items()}
    return errors,decisions,coverage,groups,dict(counts),stream.hexdigest(),intervals
