"""Local-only synthetic gates. Never a fidelity result for the private teacher."""
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_bc6 as ex

ROOT=Path(__file__).resolve().parents[3]
RUNNER=Path(os.environ["DUOFORGE_E4_RUNNER"])
sys.path.insert(0,str(ROOT/"python"))
from duoforge import features
from duoforge_learn.columns import columns
COLS=columns()


def synthetic_source():
    out={}
    for index,(name,shape) in enumerate(ex.source_shapes(COLS).items()):
        values=((np.arange(np.prod(shape),dtype=np.int64)*3+index*5)%7-3).reshape(shape)
        out[name]=(values/128).astype(np.float32)
        if name.startswith("torso_norm.") and name.endswith(".g"):out[name][:]=1
    return out


def config():
    return dict(format=2,encoder=6,model=ex.EXPECTED_MODEL,
        features=list(features.FEATURE_NAMES),slot_features=list(features.SLOT_FEATURE_NAMES),ext_supported=0x082000835233ffff)


class ExactArithmetic(unittest.TestCase):
    def test_nearest_matches_independent_fraction_round(self):
        for n in range(-257,258):
            for d in range(1,32):self.assertEqual(ex.nearest(n,d),round(Fraction(n,d)))

    def test_scale_limit_precision_and_refusal(self):
        for ratio in (Fraction(1,127),Fraction(1024,65535),Fraction(17,3),Fraction(1,1<<50)):
            for limit in (65535,(1<<32)-1):
                m,s=ex.scale_record(ratio,limit)
                self.assertTrue(1<=m<=limit and 0<=s<=63)
                self.assertLessEqual(abs(Fraction(m,1<<s)-ratio)/ratio,Fraction(1,10000))
        for ratio,limit in [(Fraction(0),99),(Fraction(-1),99),(Fraction(1,1<<100),99),(Fraction(3,2),1)]:
            with self.assertRaisesRegex(ValueError,"export_scale"):ex.scale_record(ratio,limit)

    def test_ties_ranges_and_no_clipping(self):
        a=np.array([-2.5,-1.5,-.5,0,.5,1.5,2.5],dtype=np.float32)
        self.assertEqual(ex.quantize(a,Fraction(1),"i1").tolist(),[-2,-2,0,0,0,2,2])
        with self.assertRaisesRegex(ValueError,"export_parameter_range"):
            ex.quantize(np.array([128],dtype=np.float32),Fraction(1),"i1")


class FullInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.flat=synthetic_source()

    def test_every_source_classified_and_f32_bits_accounted(self):
        flat,audit,omitted=ex.inspect_source(self.flat,config(),features,COLS)
        self.assertEqual((len(flat),len(audit),len(omitted)),(46,27,19))
        self.assertEqual(sum(x["elements"] for x in audit),1802441)
        for row in audit:
            self.assertEqual(row["sha256_f32_le"],hashlib.sha256(self.flat[row["name"]].astype("<f4").tobytes()).hexdigest())

    def test_source_inventory_shape_dtype_nonfinite_and_contract_controls(self):
        for change in ("missing","extra","shape","dtype","nonfinite","omitted_nonfinite"):
            with self.subTest(change=change):
                values=dict(self.flat)
                if change=="missing":values.pop("value.b")
                if change=="extra":values["unknown.w"]=np.zeros(1,dtype=np.float32)
                if change=="shape":values["value.b"]=np.zeros(2,dtype=np.float32)
                if change=="dtype":values["value.b"]=np.zeros(1,dtype=np.float64)
                if change=="nonfinite":values["value.b"]=np.array([np.nan],dtype=np.float32)
                if change=="omitted_nonfinite":values["struggle"]=np.full((64,),np.inf,dtype=np.float32)
                with self.assertRaisesRegex(ValueError,"export_source"):ex.inspect_source(values,config(),features,COLS)
        for key,value in [("encoder",5),("ext_supported",0),("features",[]),("slot_features",[]),("model",{})]:
            cfg=config();cfg[key]=value
            with self.subTest(field=key),self.assertRaisesRegex(ValueError,"export_"):ex.inspect_source(self.flat,cfg,features,COLS)

    def test_source_mask_is_defined_encoder_specific_and_pinned(self):
        # Independent literal from HS's source metadata, not the generator.
        self.assertEqual(ex.BC6_MASK,0x082000835233ffff)
        cfg=config();cfg["ext_supported"]|=1<<44
        with self.assertRaisesRegex(ValueError,"export_encoder_mask"):
            ex.inspect_source(self.flat,cfg,features,COLS)
        cfg=config();cfg["ext_supported"]=(1<<43)-1
        with self.assertRaisesRegex(ValueError,"export_feature_mask"):
            ex.inspect_source(self.flat,cfg,features,COLS)
        cfg=config();cfg["ext_supported"]^=1
        with self.assertRaisesRegex(ValueError,"export_feature_mask"):
            ex.inspect_source(self.flat,cfg,features,COLS)
        cfg=config();cfg["encoder"]=5
        with self.assertRaisesRegex(ValueError,"export_checkpoint_format_encoder"):
            ex.inspect_source(self.flat,cfg,features,COLS)

    def test_all_tensors_deterministic_transposed_and_loaded_by_real_c(self):
        ex.inspect_source(self.flat,config(),features,COLS)
        tensors,scales,audit=ex.integer_parameters(self.flat,1024)
        again,again_scales,_=ex.integer_parameters(self.flat,1024)
        self.assertEqual(list(tensors),["input.unit",*ex.value_sources()])
        self.assertEqual(len(tensors),28)
        self.assertEqual(scales,again_scales)
        for name in tensors:self.assertEqual(tensors[name].tobytes(),again[name].tobytes())
        # Independent Fraction arithmetic verifies every source element of one
        # full transpose, including per-channel bias units, without requantizing
        # dequantized weights as if those were the original bits.
        for channel in range(64):
            source=self.flat["move_token.w"][:,channel]
            maximum=max(abs(Fraction(float(x))) for x in source)
            scale=Fraction(127)/maximum if maximum else Fraction(1)
            self.assertEqual(tensors["move_token.w"][channel].tolist(),[round(Fraction(float(v))*scale) for v in source])
            self.assertEqual(int(tensors["move_token.b"][channel]),round(Fraction(float(self.flat["move_token.b"][channel]))*1024*scale))
        context=subprocess.check_output([str(RUNNER),"--context"],text=True).split()
        engine=dict(fingerprint=context[0],species_count=int(context[1]),move_count=int(context[2]),semantics=3,context_schema=3)
        metadata=("export_commit="+"a"*40+"\nexport_dirty=0\nseed=0\nsplit_sha256="+"b"*64+"\ntraining_commit="+"c"*40+"\ntraining_dirty=0\n").encode()
        fhash,lhash=ex.feature_hashes(features,COLS)
        self.assertEqual(lhash,"ce49380275606c348666bd988f52839c6aee86a37fc91478d6afade95c972eff")
        buf=ex.pack_artifact(tensors,scales,engine,"1"*64,"2"*64,metadata,fhash,lhash)
        buf2=ex.pack_artifact(again,again_scales,engine,"1"*64,"2"*64,metadata,fhash,lhash)
        self.assertEqual(buf,buf2);self.assertLessEqual(len(buf),4194304)
        self.assertEqual(struct.unpack_from("<Q",buf,16)[0],len(buf))
        self.assertEqual(struct.unpack_from("<I",buf,56)[0],28)
        # Directory inventory is checked independently of the exporter loop.
        want=["input.unit","species","move","item","ability","nature"]
        want += [f"{n}.{s}" for n in ("move_token","member1","member2","position") for s in ("w","b")]
        for i in range(3):want += [f"torso.{i}.w",f"torso.{i}.b",f"norm.{i}.g",f"norm.{i}.b"]
        want += ["value.w","value.b"]
        actual=[buf[256+i*128:288+i*128].split(b"\0")[0].decode() for i in range(28)]
        self.assertEqual(actual,want)
        with tempfile.TemporaryDirectory(prefix="synthetic-export-") as temp:
            root=Path(temp);path=root/"fixture.dfeval";rows_path=root/"rows.bin";trace_path=root/"trace.bin"
            ex.write_private(path,buf,False);ex.write_private(path,buf,True)
            if os.name!="nt":self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaisesRegex(ValueError,"export_check_mismatch"):ex.write_private(path,buf+b"X",True)
            with self.assertRaises(FileExistsError):ex.write_private(path,buf,False)
            sys.path.insert(0,str(ROOT/"tools/eval/tests"))
            import graph_oracle
            rows=graph_oracle.rows();rows_path.write_bytes(struct.pack("<I",len(rows))+rows.astype("<f4").tobytes())
            run=subprocess.run([str(RUNNER),"--run",str(path),hashlib.sha256(buf).hexdigest(),str(rows_path),str(trace_path)],text=True,capture_output=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertFalse(path.exists())  # C proves inference after source removal
            self.assertGreater(trace_path.stat().st_size,0)
        print(json.dumps(dict(synthetic=True,learned_parameters=1802441,wire_tensors=28,artifact_bytes=len(buf),artifact_sha256=hashlib.sha256(buf).hexdigest(),real_teacher_fidelity="NOT_RUN")))

    def test_outputs_refuse_repository_paths(self):
        for path in (ROOT/"ignored.dfeval",ROOT/"build/ignored.dfeval"):
            with self.assertRaisesRegex(ValueError,"export_output_inside_checkout"):ex.outside_checkout(path)
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);project=base/"project";project.mkdir()
            subprocess.run(["git","-C",str(project),"init","-q"],check=True)
            marker=base/"reserved";marker.mkdir();(marker/".git").mkdir()
            self.assertEqual(ex.outside_checkout(marker/"outside.dfeval"),marker/"outside.dfeval")
            inner=project/"inner";inner.mkdir();(inner/".git").mkdir()
            with self.assertRaisesRegex(ValueError,"export_output_inside_checkout"):ex.outside_checkout(inner/"forbidden.dfeval")
            alias=base/"alias"
            try:alias.symlink_to(project,target_is_directory=True)
            except OSError:
                if os.name!="nt":raise
                print("Windows symlink creation unavailable; direct and nested Git guards exercised")
            else:
                with self.assertRaisesRegex(ValueError,"export_output_inside_checkout"):
                    ex.outside_checkout(alias/"forbidden.dfeval")

    def test_real_teacher_cli_refuses_wrong_hash_before_parsing_or_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/"not-the-teacher.npz";source.write_bytes(b"not a checkpoint")
            output=root/"forbidden.dfeval";audit=root/"audit.json"
            run=subprocess.run([sys.executable,str(Path(ex.__file__)),"--repo",str(ROOT),
                "--checkpoint",str(source),"--manifest",str(root/"absent.json"),
                "--output",str(output),"--audit",str(audit)],text=True,capture_output=True)
            self.assertEqual(run.returncode,2,run.stdout+run.stderr)
            self.assertIn("export_teacher_sha256",run.stderr)
            self.assertFalse(output.exists());self.assertFalse(audit.exists())
            self.assertEqual(source.read_bytes(),b"not a checkpoint")


if __name__=="__main__":unittest.main(verbosity=2)
