#!/usr/bin/env python3
"""Canonical encoder-6 groups and ID-before-quantization oracle, synthetic rows."""
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python"))
from duoforge import features
from duoforge_learn import columns
from integer_oracle import finite, nearest, clip

def main():
    cols = columns.columns(features.FEATURE_NAMES, features.SLOT_FEATURE_NAMES)
    rng = np.random.default_rng(20261014)
    rows = rng.uniform(-4, 4, (64, 1094)).astype(np.float32)
    fields = (("species",cols.species,65535,65536),("item",cols.item,255,256),
              ("ability",cols.ability,255,256),("nature",cols.nature,24,25),("move",cols.moves,65535,65536))
    expected = []
    for row in rows:
        for table,index,factor,cap in fields:
            row[index] = (rng.integers(0, cap, index.shape) / factor).astype(np.float32)
        count = rng.integers(0, 5, (2,6));row[cols.move_count] = count / 4;row[cols.present]=count>0
        occupants = rng.integers(0,7,(2,2));row[cols.occupant]=np.eye(7,dtype=np.float32)[occupants]
        columns.check_ids(row[None,:],cols,{n:c for n,_,_,c in fields})
        scalars = []
        excluded = set(int(i) for index in (cols.present,cols.move_count,cols.occupant,
                                           cols.species,cols.item,cols.ability,cols.nature,cols.moves) for i in index.ravel())
        for i, value in enumerate(row.view(np.uint32)):
            n,d=finite(int(value));scalars.append(0 if i in excluded else clip(nearest(n * 1024,d)))
        ids = b"".join(columns.decode(row,index,table).astype("<u4").tobytes() for table,index,_,_ in fields)
        expected.append(struct.pack("<I1094h",0,*scalars)+ids+(count>0).astype("u1").tobytes()
                        +count.astype("u1").tobytes()+occupants.astype("u1").tobytes())
    source=struct.pack("<7I",1024,0,65536,65536,256,256,25)+rows.astype("<f4").tobytes()
    with tempfile.TemporaryDirectory(prefix="duoforge-inputs-") as temp:
        path=Path(temp)/"synthetic-inputs.bin";path.write_bytes(source)
        got=subprocess.run([sys.argv[1],"--inputs",str(path)],check=True,stdout=subprocess.PIPE).stdout
    want=b"".join(expected)
    if got!=want:
        for i in range(len(rows)):
            size=len(expected[i])
            if got[i*size:(i+1)*size]!=expected[i]:
                raise AssertionError(f"canonical input mismatch at row {i}, {len(got)} != {len(want)} total bytes")
    print(f"input oracle: {len(rows)} rows, {len(rows)*1094} classified columns, byte-identical; SHA256 {hashlib.sha256(got).hexdigest()}")
if __name__=="__main__":main()
