"""E4 code-only controls: fake metrics, runtime synthetic tensors and games.
No trained file is read, produced, staged or uploaded by this test.
"""
from collections import Counter
from pathlib import Path
import copy
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"python"));sys.path.insert(0,str(ROOT/"tools/eval"))
import bc6_gates as gates
import bc6_corpus as corpus
import bc6_check as check
import export_bc6 as export
import run_bc6 as run


def good_inputs():
    values={s:np.zeros(gates.VALUE_ROWS//2) for s in gates.STRATA}
    decisions={s:[{r:dict(agree=True,tv=0.0,regret=0.0,stable=True,ev_agree=True) for r in gates.RULES}
                  for _ in range(gates.ROOTS_PER_STRATUM)] for s in gates.STRATA}
    coverage={s:{**{f"{b}:{p}":1 for b in gates.BOUNDARIES for p in (0,1)},"field":1,"item":1,"ability":1}
              for s in gates.STRATA}
    return values,decisions,dict(groups=list(range(gates.GROUPS)),coverage=coverage,mechanics=True,
                                reproduction=True,oracle=True)


class GateControls(unittest.TestCase):
    def test_full_gate_accepts_exact_inventory(self):
        args=good_inputs();result=gates.report(*args[:2],**args[2])
        self.assertTrue(result["fidelity_pass"])
        self.assertFalse(result["adoption"])
        self.assertEqual(sum(s["rows"] for s in result["strata"].values()),131072)
        self.assertTrue(all(result["gates"].values()))

    def test_each_missing_class_and_stratum_refuses(self):
        for stratum in gates.STRATA:
            for key in [*(f"{b}:{p}" for b in gates.BOUNDARIES for p in (0,1)),"field","item","ability"]:
                values,decisions,kw=good_inputs();del kw["coverage"][stratum][key]
                self.assertFalse(gates.report(values,decisions,**kw)["fidelity_pass"])
            values,decisions,kw=good_inputs();decisions[stratum]=[]
            self.assertFalse(gates.report(values,decisions,**kw)["fidelity_pass"])

    def test_counts_cannot_be_derived_down_to_input_inventory(self):
        for kind in ("groups","rows","roots"):
            values,decisions,kw=good_inputs()
            if kind=="groups":kw["groups"].pop()
            if kind=="rows":values["open"]=values["open"][:-1]
            if kind=="roots":decisions["open"].pop()
            self.assertFalse(gates.report(values,decisions,**kw)["fidelity_pass"])

    def test_cluster_intervals_reproduce_and_do_not_drop_empty_samples(self):
        pairs=[(i/10,1) for i in range(24)]
        a=gates.group_mean_interval(pairs);b=gates.group_mean_interval(pairs)
        self.assertEqual(a,b)
        self.assertLess(a[0],1.15);self.assertGreater(a[1],1.15)
        self.assertIsNone(gates.group_mean_interval([(0,0)]))

    def test_p99_and_maximum_are_independent_of_mean(self):
        for mode in ("p99","maximum"):
            values,decisions,kw=good_inputs()
            if mode=="p99":values["open"][:2000]=0.051
            else:values["open"][0]=0.151
            result=gates.report(values,decisions,**kw)
            self.assertLess(result["strata"]["open"]["errors"]["mean"],0.01)
            self.assertFalse(result["fidelity_pass"])

    def test_numeric_gates_are_stratified(self):
        for error in (0.011,0.051,0.151,float("nan"),float("inf")):
            values,decisions,kw=good_inputs()
            values["closed"]=np.full(65536,error)
            self.assertFalse(gates.report(values,decisions,**kw)["fidelity_pass"])

    def test_decision_distribution_regret_and_stable_gates(self):
        for field,value in (("agree",False),("tv",0.03),("regret",0.003),("ev_agree",False)):
            values,decisions,kw=good_inputs()
            for row in decisions["closed"]:row["live"][field]=value
            result=gates.report(values,decisions,**kw)
            self.assertFalse(result["gates"]["closed.live"])
            self.assertTrue(result["gates"]["open.live"])
        values,decisions,kw=good_inputs()
        for row in decisions["open"]:
            for r in gates.RULES:row[r]["stable"]=False
        result=gates.report(values,decisions,**kw)
        self.assertFalse(result["fidelity_pass"])
        self.assertIsNone(result["strata"]["open"]["rules"]["ev"]["stable_agreement"])

    def test_independent_mechanics_reproduction_oracle_required(self):
        for key in ("mechanics","reproduction","oracle"):
            values,decisions,kw=good_inputs();kw[key]=False
            self.assertFalse(gates.report(values,decisions,**kw)["fidelity_pass"])

    def test_actual_rules_keep_uniform_and_teacher_valued_regret(self):
        a=np.array([[[0.9,0.8],[0.1,0.2]]]);b=a[:,::-1].copy()
        solve=("lp",np.array([1.]),np.array([[0.6,0.4]]),np.array([0.5,0.5]))
        equal=gates.compare_decision(a,a,0.37,"mix",0.5,solve)
        self.assertTrue(all(row["agree"] and row["tv"]==row["regret"]==0 for row in equal.values()))
        changed=gates.compare_decision(a,b,0.37,"ev",0.5,solve)
        self.assertFalse(changed["ev"]["agree"])
        self.assertEqual(changed["ev"]["tv"],1.0)
        self.assertAlmostEqual(changed["ev"]["regret"],0.72)


class FrozenInputs(unittest.TestCase):
    def test_seeded_game_and_team_families_are_disjoint_before_rows(self):
        a=corpus.plan({}, {"commit":"a"*40},{"pin":corpus.PS_PIN})
        b=corpus.plan({}, {"commit":"a"*40},{"pin":corpus.PS_PIN})
        self.assertEqual(export.canonical(a),export.canonical(b))
        groups=a["groups"]
        self.assertEqual({s:len(g) for s,g in groups.items()},dict(training=128,calibration=128,holdout=1024))
        self.assertEqual(len({g for gs in groups.values() for g in gs}),1280)
        self.assertEqual(len({g["battle_seed"] for g in a["games"]}),1152)
        for i in range(200):
            digest=export.sha(str(i).encode());self.assertEqual(corpus.split_of(digest),corpus.split_of(digest))
        self.assertEqual(a["closed_worlds"],16);self.assertEqual(a["padding"],1024)
        self.assertNotIn("checkpoint",a)

    def test_selection_is_blind_to_values_and_preserves_coverage(self):
        records=[dict(group=f"g{i%4}",seat=i%2,key=i,file=f"{i}.npz",boundary=gates.BOUNDARIES[(i//2)%3],
                      interactions=["field","item","ability"]) for i in range(24)]
        chosen=check.select(records,16)
        self.assertEqual(chosen,check.select(list(reversed(records)),16))
        self.assertEqual({f"{r['boundary']}:{r['seat']}" for r in chosen},
                         {f"{b}:{p}" for b in gates.BOUNDARIES for p in (0,1)})
        self.assertEqual(len({r["group"] for r in chosen}),4)
        with self.assertRaisesRegex(ValueError,"insufficient_roots"):check.select([],2048)
        with self.assertRaisesRegex(ValueError,"insufficient_roots"):
            check.select([{**r,"eligible":False} for r in records],16)

    def test_private_npz_is_deterministic_and_hash_guarded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=root/"a.npz";b=root/"b.npz"
            corpus.save_npz(a,dict(rows=np.arange(1094,dtype=np.float32).reshape(1,-1)))
            corpus.save_npz(b,dict(rows=np.arange(1094,dtype=np.float32).reshape(1,-1)))
            self.assertEqual(a.read_bytes(),b.read_bytes())
            record=dict(file=a.name,sha256=export.file_sha(a))
            self.assertEqual(check.load_request(root,record)["rows"].shape,(1,1094))
            a.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError,"request_identity"):check.load_request(root,record)

    def test_calibration_recipe_is_frozen_first_and_short_pivot_rows_do_not_duplicate(self):
        records=[]
        for stratum in gates.STRATA:
            for i in range(32):
                records.append(dict(group=f"{stratum}/g{i}",seat=i%2,key=i,file=f"{stratum}/{i}.npz",
                    sha256="a"*64,boundary=gates.BOUNDARIES[(i//2)%3],interactions=["field","item","ability"],
                    stratum=stratum))
        def load(root,record):
            n=32 if record["boundary"]=="PIVOT" else 128
            return dict(rows=np.zeros((n,1094),np.float32),open=np.ones(n,bool))
        class Native:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def values(self,rows):return np.zeros(len(rows),np.int32)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/"calibration-corpus.json";old.write_bytes(b"frozen game inventory")
            class Model:
                def check(self,rows):pass
                def value(self,params,rows):
                    recipe=json.loads((root/"calibration-recipe.json").read_text(encoding="utf-8"))
                    self_test.assertEqual(len(recipe["rows"]),4096)
                    self_test.assertEqual(len({tuple(x) for x in recipe["rows"]}),4096)
                    return np.zeros(len(rows),np.float32)
            self_test=self
            import bc6_oracle
            with mock.patch.object(check,"load_request",side_effect=load), \
                    mock.patch.object(check,"Runner",Native), \
                    mock.patch.object(run,"integer_parameters",return_value=({}, {}, {})), \
                    mock.patch.object(run,"pack_artifact",return_value=b"synthetic pipeline control"), \
                    mock.patch.object(bc6_oracle,"integer_trace",return_value=b""):
                result=run.calibrate(root,records,{},Model(),None,lambda p,x:np.zeros(len(x),np.float32),
                    {},b"metadata",("a"*64,"b"*64),"unused synthetic runner",2)
            self.assertEqual(result["selected_unit"],256)
            self.assertEqual(result["rows"],4096)
            self.assertFalse(result["heldout_read"])
            self.assertEqual(old.read_bytes(),b"frozen game inventory")
            self.assertTrue((root/"calibration.json").is_file())

    def test_teacher_keeps_original_leaf_order_with_terminal_between_neural_rows(self):
        rows=np.zeros((3,1094),np.float32);rows[:,0]=[1,2,3]
        req=dict(rows=rows,open=np.array([True,False,True]),step=np.zeros(3,np.uint32),
                 encode=np.zeros(3,np.uint32),results=np.array([0,1,0],np.uint32),
                 cutoff_tiebreaks=np.zeros(3,np.uint32),valid_key=np.ones(3,bool))
        record=dict(file="private.npz",group="game",stratum="open",seat=0,boundary="TURN",
                    interactions=[],uniform=0.2,terminal=1,step_refused=0,digest_refused=0)
        class Model:
            def check(self,x):pass
            def value(self,p,x):
                np.testing.assert_array_equal(x[:3,0],[1,2,3])
                return x[:,0]
        class Native:
            def __init__(self,*a,**k):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def values(self,x):
                np.testing.assert_array_equal(x[:,0],[1,3])
                return (x[:,0]*(1<<20)).astype(np.int32)
        req["weights"]=np.array([1.]);req["qs"]=np.array([[1.]])
        def table(r,q,values,cutoff=False):
            return np.zeros((1,1,1)),np.array([1.])
        score={r:dict(agree=True,tv=0.,regret=0.,stable=True,ev_agree=True) for r in gates.RULES}
        with mock.patch.object(check,"load_request",return_value=req),mock.patch.object(check,"Runner",Native), \
                mock.patch.object(check,"table",side_effect=table), \
                mock.patch.object(gates,"compare_decision",return_value=score):
            result=check.evaluate(Path("unused"),[record],"unused",Path("unused"),"a"*64,2,Model(),None,
                                  lambda p,x:x[:,0],"ev",0.5)
        self.assertEqual(result[0]["open"],[0.0,0.0])
        self.assertEqual(result[4]["neural_rows"],2)
        self.assertEqual(result[4]["terminal"],1)

    def test_sha_pin_precedes_build_parsing_lock_or_any_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/"wrong.npz";source.write_bytes(b"not an NPZ")
            out=root/"must-not-exist"
            result=subprocess.run([sys.executable,str(ROOT/"tools/eval/run_bc6.py"),"--checkpoint",str(source),
                "--out",str(out),"--build-dir",str(root/"build"),"--training-commit","a"*40],
                text=True,capture_output=True)
            self.assertEqual(result.returncode,2,result.stdout+result.stderr)
            self.assertIn("export_teacher_sha256",result.stderr)
            self.assertFalse(out.exists());self.assertFalse((root/"build").exists())


class NativeSynthetic(unittest.TestCase):
    def test_streaming_real_c_matches_independent_integer_intermediates(self):
        from test_export_bc6 import synthetic_source,COLS
        from duoforge import features
        from bc6_oracle import integer_trace
        import graph_oracle
        runner=Path(os.environ["DUOFORGE_BC6_RUNNER"])
        context=subprocess.check_output([str(runner),"--context","2"],text=True).split()
        engine=dict(fingerprint=context[0],species_count=int(context[1]),move_count=int(context[2]),
                    semantics=int(context[3]),context_schema=int(context[4]))
        tensors,scales,_=export.integer_parameters(synthetic_source(),1024)
        data=export.pack_artifact(tensors,scales,engine,"1"*64,"2"*64,
            run.metadata("a"*40,"b"*64,"c"*40,False),*export.feature_hashes(features,COLS))
        rows=graph_oracle.rows()[:2]
        expected=integer_trace(1024,tensors,scales,rows)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);artifact=root/"synthetic.dfeval";trace=root/"trace.bin"
            artifact.write_bytes(data)
            with check.Runner(runner,artifact,export.sha(data),2,trace,2) as c:
                a=c.values(np.resize(rows,(33,1094)));b=c.values(np.resize(rows,(33,1094)))
                self.assertEqual(a.tobytes(),b.tobytes())
                self.assertEqual(a.shape,(33,))
                self.assertEqual(c.values(np.zeros((0,1094),np.float32)).size,0)
            self.assertEqual(expected,trace.read_bytes())
            self.assertEqual(artifact.read_bytes(),data)  # Owner's artifact is never unlinked
            with check.Runner(runner,artifact,export.sha(data),2) as c:
                bad=rows.copy();bad[0,0]=np.nan
                with self.assertRaisesRegex(ValueError,"inference_failed"):c.values(bad)
            with self.assertRaisesRegex(ValueError,"runner_truncated"):
                with check.Runner(runner,artifact,"0"*64,2) as c:c.values(rows)


if __name__=="__main__":unittest.main(verbosity=2)
