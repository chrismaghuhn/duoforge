#!/usr/bin/env python3
"""Independent frozen value graphs: runtime synthetic tensors, exact intermediates.

Does not import the C registry generator or its definitions. No private model.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python"))
from duoforge import features
from duoforge_learn.columns import columns
from integer_oracle import finite, nearest, clip
from normalization_oracle import norm

SHAPES = {"full": (1001,64,128,128,640,3,1802441,4194304),
          "small": (1002,32,64,64,256,2,333769,1048576),
          "medium": (1003,48,96,96,368,3,773193,2097152)}
COLS = columns()
META = ("export_commit="+"a"*40+"\nexport_dirty=0\nseed=0\nsplit_sha256="+"b"*64
        +"\ntraining_commit="+"c"*40+"\ntraining_dirty=0\n").encode("ascii")


def patterns(shape, salt, span):
    x = np.arange(math.prod(shape), dtype=np.uint64) + salt
    x = ((x ^ (x >> 16)) * 2246822519) & 0xffffffff
    x = ((x ^ (x >> 13)) * 3266489917) & 0xffffffff
    return ((x ^ (x >> 16)) % (2*span+1)).astype(np.int64).reshape(shape)-span


def parameters(label, unit):
    _,e,m,p,h,layers,_,_ = SHAPES[label]
    tensors = {"input.unit": np.array([unit], dtype=np.int64)}
    scales = {}
    for i,(name,rows,width) in enumerate([("species",1024,e),("move",1024,e),
            ("item",256,e),("ability",256,e),("nature",25,8)]):
        tensors[name] = patterns((rows,width), 31+i, 32)
        scales[name] = [(unit,4)]
    for i,(name,ni,no) in enumerate([("move_token",e+1,e),("member1",5*e+42,m),
            ("member2",m,m),("position",106+m,p),
            *[(f"torso.{j}",94+4*p+4*m if j==0 else h,h) for j in range(layers)],("value",h,1)]):
        tensors[name+".w"] = patterns((no,ni), 53+i, 3)
        tensors[name+".b"] = patterns((no,), 71+i, 5)*unit
        scales[name+".w"] = [(1,0 if name=="value" else 4)]*no
        if name.startswith("torso."):
            j=int(name.split(".")[1])
            tensors[f"norm.{j}.g"] = patterns((h,), 97+j, 3)*unit
            tensors[f"norm.{j}.b"] = (40000+patterns((h,), 113+j, 1000)
                                           if j==1 else patterns((h,), 113+j, 2)*unit)
    tensors["value.b"] = np.array([8 << 20], dtype=np.int64)
    # Canonical inventory order is independent of construction iteration order.
    names = ["input.unit","species","move","item","ability","nature"]
    names += [f"{n}.{s}" for n in ("move_token","member1","member2","position") for s in ("w","b")]
    for j in range(layers):names += [f"torso.{j}.w",f"torso.{j}.b",f"norm.{j}.g",f"norm.{j}.b"]
    names += ["value.w","value.b"]
    assert set(names)==set(tensors) and len(names)==16+4*layers
    assert sum(v.size for k,v in tensors.items() if k!="input.unit")==SHAPES[label][6]
    return {n:tensors[n] for n in names}, scales


def artifact(label, unit, context):
    tensors, scales = parameters(label,unit)
    count=len(tensors);buf=bytearray(256+128*count);buf[:8]=b"DFEVAL\0\0"
    fingerprint,species,moves=context
    for at,value in [(8,1),(12,256),(24,SHAPES[label][0]),(28,1),(32,6),(36,1094),
                     (48,3),(52,3),(56,count),(60,len(META)),(88,int(species)),(92,int(moves))]:
        struct.pack_into("<I",buf,at,value)
    for at,value in [(40,0x082000835233ffff),(64,256),(72,len(buf))]:struct.pack_into("<Q",buf,at,value)
    buf[96:128]=bytes.fromhex(fingerprint);buf[128:160]=bytes([3])*32;buf[160:192]=bytes([4])*32
    buf[192:224]=hashlib.sha256(json.dumps(list(features.FEATURE_NAMES),separators=(",",":")).encode()).digest()
    groups=("glob","side","position","occupant","member","present","species","item","ability","nature","moves","pp","move_count")
    mapping=[None]*1094
    for group in groups:
        values=getattr(COLS,group)
        for coords in np.ndindex(values.shape):
            at=int(values[coords]);assert mapping[at] is None;mapping[at]=(group,coords)
    assert all(v is not None for v in mapping)
    canonical=json.dumps(list(zip(features.FEATURE_NAMES,mapping)),separators=(",",":"))
    buf[224:256]=hashlib.sha256(canonical.encode()).digest()
    buf.extend(META);buf.extend(bytes(-len(buf)%8));struct.pack_into("<Q",buf,80,len(buf))
    offsets={}
    for index,(name,value) in enumerate(tensors.items()):
        at=256+128*index;encoded=name.encode("ascii");buf[at:at+len(encoded)]=encoded
        dtype=2 if name=="input.unit" else 4 if name.endswith(".b") and not name.startswith("norm.") else 3 if name.startswith("norm.") else 1
        value_bytes=value.astype({1:"i1",2:"<i2",3:"<i4",4:"<i8"}[dtype]).tobytes()
        struct.pack_into("<II",buf,at+32,dtype,value.ndim)
        for i,d in enumerate(value.shape):struct.pack_into("<I",buf,at+40+4*i,d)
        offsets[name]=len(buf)
        struct.pack_into("<QQ",buf,at+56,len(buf),len(value_bytes));buf.extend(value_bytes);buf.extend(bytes(-len(buf)%8))
        if name in scales:
            struct.pack_into("<Q",buf,at+72,len(buf));struct.pack_into("<I",buf,at+80,len(scales[name]))
            for scale in scales[name]:buf.extend(struct.pack("<II",*scale))
    struct.pack_into("<Q",buf,16,len(buf))
    assert len(buf)<=SHAPES[label][7]
    return buf,tensors,scales,offsets


def rows():
    # Deterministic finite synthetic rows, including binary32 rounding boundaries.
    out=(patterns((4,1094),133,128)/64).astype(np.float32)
    for row_index,row in enumerate(out):
        for index,factor,capacity in [(COLS.species,65535,1024),(COLS.moves,65535,1024),
                (COLS.item,255,256),(COLS.ability,255,256),(COLS.nature,24,25)]:
            ids=(np.arange(index.size).reshape(index.shape)+row_index*13) % capacity
            ids.flat[-1]=capacity-1
            row[index]=ids/factor
        count=(np.arange(12).reshape(2,6)+row_index)%5
        occupant=np.array([[0,6],[5,2]])
        if row_index==1:count[:]=0;occupant[:]=6
        if row_index==2:count[0,:]=0;occupant[0,:]=6
        row[COLS.move_count]=count/4;row[COLS.present]=count>0
        row[COLS.occupant]=np.eye(7,dtype=np.float32)[occupant]
        row[COLS.pp]=np.arange(48).reshape(2,6,4)%17/16
    out[3]=out[0]  # A/B/C/A, full scratch poisoning between calls.
    return out


def expected(label, unit, tensors, scales, observations):
    _,e,m,p,h,layers,_,_=SHAPES[label]
    frames=[]
    excluded=set(int(i) for field in (COLS.present,COLS.move_count,COLS.occupant,COLS.species,
                COLS.item,COLS.ability,COLS.nature,COLS.moves) for i in field.ravel())
    dense_weights={k:v.tolist() for k,v in tensors.items() if k.endswith(".w")}

    def dense(name,x,relu=False,short=True):
        result=[]
        for channel,(weights,bias) in enumerate(zip(dense_weights[name+".w"],tensors[name+".b"].tolist())):
            value=bias+sum(a*b for a,b in zip(x,weights))
            assert -(1<<63)<=value<1<<63
            if relu:value=max(0,value)
            mul,shift=scales[name+".w"][channel]
            value=nearest(value*mul,1<<shift)
            result.append(clip(value) if short else value)
        assert short or all(-(1<<31)<=x<1<<31 for x in result)
        return result

    for row_index,row in enumerate(observations):
        seen=set()
        def emit(name,index,value):
            key=(name,index);assert key not in seen;seen.add(key)
            vector=[int(v) for v in np.asarray(value).ravel()]
            tag=name.encode("ascii")
            frames.append(struct.pack("<4I",row_index,index,len(vector),len(tag))+tag+struct.pack("<"+"i"*len(vector),*vector))
        scalars=[]
        for i,bits in enumerate(row.view(np.uint32)):
            n,d=finite(int(bits));scalars.append(0 if i in excluded else clip(nearest(n*unit,d)))
        scalar=np.array(scalars)
        def ids(index,factor):
            return np.array([nearest(finite(int(row.view(np.uint32)[i]))[0]*factor,
                                     finite(int(row.view(np.uint32)[i]))[1]) for i in index.ravel()]).reshape(index.shape)
        species,items,abilities,natures,moves=(ids(index,factor) for index,factor in
            [(COLS.species,65535),(COLS.item,255),(COLS.ability,255),(COLS.nature,24),(COLS.moves,65535)])
        counts=ids(COLS.move_count,4);registered=counts>0
        occupants=row[COLS.occupant].argmax(axis=-1)
        emit("scalars",0,scalars);emit("registered",0,registered);emit("occupant",0,occupants)
        def embed(name,identity):
            mul,shift=scales[name][0]
            return [clip(nearest(int(v)*mul,1<<shift)) for v in tensors[name][identity]]
        members=np.zeros((2,6,m),dtype=np.int64)
        for side in range(2):
            for member in range(6):
                index=side*6+member;tokens=[]
                for k in range(4):
                    inp=embed("move",moves[side,member,k])+[int(scalar[COLS.pp[side,member,k]])]
                    emit("move_input",index*4+k,inp)
                    token=dense("move_token",inp,True);emit("move_token",index*4+k,token);tokens.append(token)
                valid=tokens[:counts[side,member]]
                sums=[clip(sum(v[j] for v in valid)) for j in range(e)]
                maxima=[max((v[j] for v in valid),default=0) for j in range(e)]
                emit("move_sum",index,sums);emit("move_max",index,maxima)
                inp=(embed("species",species[side,member])+sums+maxima+embed("item",items[side,member])
                     +embed("ability",abilities[side,member])+embed("nature",natures[side,member])
                     +scalar[COLS.member[side,member]].tolist()+[unit if side==0 else 0,unit if registered[side,member] else 0])
                emit("member_input",index,inp)
                hidden=dense("member1",inp,True);emit("member1",index,hidden)
                hidden=dense("member2",hidden,True);emit("member2",index,hidden)
                if not registered[side,member]:hidden=[0]*m
                members[side,member]=hidden;emit("member_mask",index,hidden)
        positions=np.zeros((2,2,p),dtype=np.int64);sums=[];maxima=[]
        for side in range(2):
            for pos in range(2):
                index=2*side+pos;occ=occupants[side,pos]
                gathered=members[side,occ].tolist() if occ<6 else [0]*m
                emit("gather",index,gathered)
                inp=scalar[COLS.position[side,pos]].tolist()+[unit if occ<6 else 0]+gathered
                emit("position_input",index,inp)
                value=dense("position",inp,True);emit("position",index,value);positions[side,pos]=value
            valid=members[side][registered[side]].tolist()
            total=[clip(sum(v[j] for v in valid)) for j in range(m)]
            top=[max((v[j] for v in valid),default=0) for j in range(m)]
            sums.append(total);maxima.append(top)
            emit("side_sum",side,total);emit("side_max",side,top)
        x=(scalar[COLS.glob].tolist()+scalar[COLS.side].ravel().tolist()+positions.ravel().tolist()
           +[v for side in sums for v in side]+[v for side in maxima for v in side])
        emit("torso_input",0,x)
        en,ed=finite(0x3727c5ac);epsilon=nearest(en*unit*unit,ed);assert epsilon>0
        for i in range(layers):
            value=dense(f"torso.{i}",x,short=False);emit("torso_dense",i,value)
            normalized=norm(value,tensors[f"norm.{i}.g"].tolist(),tensors[f"norm.{i}.b"].tolist(),
                            (epsilon,31,47,1,16,1,0))
            assert normalized[0]==0
            normalized=normalized[1:];emit("torso_norm",i,normalized)
            activated=[max(v,0) for v in normalized];emit("torso_relu",i,activated)
            x=activated if i==0 else [a+b for a,b in zip(x,activated)]
            assert all(-(1<<31)<=v<1<<31 for v in x);emit("torso",i,x)
        assert max(x)>32767  # Gate catches int16 narrowing between torso layers.
        value=dense("value",x,short=False);emit("value",0,value)
        assert len(seen)==189+4*layers
    return b"".join(frames)


def main():
    runner,label=sys.argv[1:3];context=subprocess.check_output([runner,"--context"],text=True).split()
    observations=rows();checks=0;streams=[]
    with tempfile.TemporaryDirectory(prefix="duoforge-synthetic-graph-") as temp:
        root=Path(temp);path=root/"synthetic.dfeval";source=root/"rows.bin";output=root/"trace.bin"
        source.write_bytes(struct.pack("<I",len(observations))+observations.astype("<f4").tobytes())
        def invoke(args):
            run=subprocess.run(args,text=True,capture_output=True)
            if run.returncode:
                raise AssertionError(f"{label}: runner failed ({run.returncode})\n{run.stdout}\n{run.stderr}")
            return run
        def refuse(buf,reason):
            nonlocal checks
            path.write_bytes(buf)
            invoke([runner,"--refuse",str(path.resolve()),hashlib.sha256(buf).hexdigest(),reason])
            checks+=1
        for unit in (1024,4096):
            buf,tensors,scales,offsets=artifact(label,unit,context)
            want=expected(label,unit,tensors,scales,observations)
            path.write_bytes(buf)
            run=invoke([runner,"--run",str(path.resolve()),hashlib.sha256(buf).hexdigest(),str(source),str(output)])
            for line in run.stdout.splitlines():
                if line.startswith("graph_resources "):print(line)
            got=output.read_bytes()
            if got!=want:
                offset=next((i for i,(a,b) in enumerate(zip(got,want)) if a!=b),min(len(got),len(want)))
                raise AssertionError(f"{label} unit {unit}: intermediate mismatch at byte {offset}; sizes {len(got)}/{len(want)}")
            streams.append(hashlib.sha256(got).hexdigest())
        # Source-mask correction: undefined bits, old encoders/masks and a
        # different defined mask all refuse, preserving the model sentinel.
        for version,mask,reason in [(6,0x082000835233ffff | (1<<44),"eval_encoder_mask"),
                (5,(1<<43)-1,"eval_encoder_mask"),(6,(1<<43)-1,"eval_graph_schema"),
                (6,0x082000835233fffe,"eval_graph_schema")]:
            buf,_,_,_=artifact(label,1024,context)
            struct.pack_into("<I",buf,32,version);struct.pack_into("<Q",buf,40,mask)
            path.write_bytes(buf)
            invoke([runner,"--contract",str(path.resolve()),hashlib.sha256(buf).hexdigest(),
                    str(version),hex(mask),reason])
            checks+=1
        base,tensors,scales,offsets=artifact(label,1024,context)
        path.write_bytes(base)
        invoke([runner,"--oom",str(path.resolve()),hashlib.sha256(base).hexdigest(),str(SHAPES[label][0])])
        checks+=4
        for at,fmt,value,reason in [(24,"I",9999,"eval_graph_unregistered"),(28,"I",2,"eval_graph_schema"),
                (56,"I",len(tensors)-1,"eval_tensor_inventory"),(192,"B",base[192]^1,"eval_graph_schema"),
                (224,"B",base[224]^1,"eval_graph_schema"),(256+40,"I",2,"eval_tensor_invalid:input.unit")]:
            buf=base.copy();struct.pack_into("<"+fmt,buf,at,value);refuse(buf,reason)
        for unit in (0,128,300):
            buf=base.copy();struct.pack_into("<h",buf,offsets["input.unit"],unit);refuse(buf,"eval_input_unit")
        for name,value in [("norm.0.g",(1<<20)+1),("norm.0.b",(1<<24)+1)]:
            buf=base.copy();struct.pack_into("<i",buf,offsets[name],value);refuse(buf,"eval_tensor_invalid:"+name)
        buf=base.copy();buf[256+128:256+160]=buf[256:288];refuse(buf,"eval_tensor_invalid:species")
        buf=base.copy();buf[256+128:256+256],buf[256+256:256+384]=buf[256+256:256+384],buf[256+128:256+256]
        refuse(buf,"eval_tensor_invalid:species")
        buf=base.copy()+bytes(SHAPES[label][7]+1-len(base));struct.pack_into("<Q",buf,16,len(buf))
        refuse(buf,"eval_file_capacity")
    print(f"{label}: 8 rows; {(189+4*SHAPES[label][5])*8} independent stage records; {checks} malformed/capacity controls; SHA256={','.join(streams)}")


if __name__=="__main__":main()
