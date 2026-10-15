"""Synthetic BC6 extraction and real open/closed corpus wiring; never trained data."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
import jax
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"python"));sys.path.insert(0,str(ROOT/"tools/eval"))
import bc6_corpus as corpus
import bc6_check as check
from bc6_oracle import float_value
from duoforge import features
from duoforge_learn import policy, checkpoint
from duoforge_learn.columns import columns


class FloatExtraction(unittest.TestCase):
    def test_full_value_path_matches_original_jax_bits_with_nonzero_heads(self):
        from test_export_bc6 import synthetic_source
        from duoforge_learn import checkpoint as ck
        import graph_oracle
        flat=synthetic_source()
        # Restore the source's actual dict/list tree independently from the
        # quantizer's wire mapping. Non-value heads are deliberately nonzero.
        leaves={"".join(f"[{int(t)}]" if t.isdigit() else f"['{t}']" for t in name.split('.')):value
                for name,value in flat.items()}
        params=ck.unflatten(leaves)
        import export_bc6
        cfg=export_bc6.EXPECTED_MODEL;model=policy.make(cfg)
        oracle=jax.jit(lambda p,x:float_value(p,cfg,columns(),x))
        rows=graph_oracle.rows()
        for count in (1,4,16):
            inputs=np.resize(rows,(count,1094))
            a=np.asarray(model.value(params,inputs));b=np.asarray(oracle(params,inputs))
            self.assertTrue(np.isfinite(a).all())
            self.assertTrue(np.any(a!=0))
            np.testing.assert_array_equal(a.view(np.uint32),b.view(np.uint32))

    def test_real_private_game_capture_open_and_sixteen_closed_worlds(self):
        import duoforge
        from duoforge import _layout
        from duoforge_live import data, teams
        cfg=policy.v2_config("S");model=policy.make(cfg)
        params=model.init(jax.random.PRNGKey(4917))
        with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            config=dict(model=cfg,encoder=6,ext_supported=0x082000835233ffff,
                features=list(features.FEATURE_NAMES),slot_features=list(features.SLOT_FEATURE_NAMES),
                data=dict(kind="pool",fingerprint=ctx.fingerprint().hex()),ids=checkpoint.ids_of(ctx),
                teams=[],update=0,decisions=0,train={})
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/"synthetic.npz";checkpoint.save(path,params,config)
            tables=data.for_config({**config,"format":2})
            try:
                g=corpus.plan({}, {}, {})["games"][0]
                # Same production capture, shortened synthetic-only played
                # game. Constants of the production protocol remain fixed.
                with mock.patch.object(corpus,"MAX_STEPS",8):
                    result=corpus.collect("calibration",[g],root,path,tables,model,params,
                        os.environ["DUOFORGE_NODE"],Path(os.environ["DUOFORGE_PS_REFERENCE_DIR"]),
                        [("synthetic-a",teams.text("A")),("synthetic-b",teams.text("B"))])
                records=result["requests"]
                self.assertTrue(records)
                self.assertTrue((root/"calibration-corpus.json").is_file())
                self.assertFalse((root/"calibration.json").exists())
                self.assertEqual({r["stratum"] for r in records},{"open","closed"})
                self.assertTrue(all(r["worlds"]==16 for r in records))
                for record in records:
                    req=check.load_request(root,record)
                    self.assertEqual(req["rows"].shape[1],1094)
                    self.assertEqual(req["digest"].shape,(len(req["rows"]),32))
                    self.assertTrue((req["encode"][req["step"]==0]==0).all())
                    self.assertTrue((req["open"]==(req["step"]==0)&(req["results"]==0)).all())
                self.assertEqual(path.exists(),True)
            finally:
                if tables._ctx is not None:tables._ctx.close()


if __name__=="__main__":unittest.main(verbosity=2)
