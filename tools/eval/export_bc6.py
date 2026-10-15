#!/usr/bin/env python3
"""Local-only BC6 value conversion. No training, download, discovery or adoption.

The CLI pins the real teacher before NPZ parsing. Synthetic tests use the pure
array functions, never another checkpoint accepted by the production CLI.
All outputs must be outside every Git checkout. No repository is modified.
"""
from __future__ import annotations
import argparse
from collections import OrderedDict
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zipfile

import numpy as np

TEACHER = "bda5de8e4e960f3df41b029cd4d3d87fc48838fdd47c8562a78649e222ee9f39"
BC6_MASK = 0x082000835233ffff  # Owner-local SHA-verified teacher config (TEACHER above).
METHOD = "symmetric-i8-per-output-exact-rne-v1"
MAX_PARAMETERS = 1_802_441
MAX_SCALE_RELATIVE_ERROR = Fraction(1, 10000)
EXPECTED_MODEL = dict(version=2, embed=64, member=128, position=128, hidden=640, layers=3, option=128,
                      capacities=dict(species=1024, move=1024, item=256, ability=256, nature=25))


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)+"\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): digest.update(chunk)
    return digest.hexdigest()


def fail(reason):
    raise ValueError(reason)


def nearest(n, d):
    """Exact signed round-nearest, ties-to-even, no host floating operation."""
    if d <= 0: fail("export_round_denominator")
    q, r = divmod(abs(n), d)
    q += 2*r > d or (2*r == d and q % 2 != 0)
    return -q if n < 0 else q


def rational(value):
    n, d = float(value).as_integer_ratio()  # binary32 -> binary64 is exact
    return Fraction(n, d)


def scale_record(ratio, maximum):
    if ratio <= 0 or maximum < 1: fail("export_scale_bound")
    maximum = min(maximum, (1 << 32)-1)
    for shift in range(63, -1, -1):
        multiplier = nearest(ratio.numerator << shift, ratio.denominator)
        if 1 <= multiplier <= maximum:
            error = abs(Fraction(multiplier, 1 << shift)-ratio)/ratio
            if error > MAX_SCALE_RELATIVE_ERROR: fail("export_scale_precision")
            return (multiplier, shift)
    fail("export_scale_unrepresentable")


def quantize(array, scale, dtype):
    info = np.iinfo(dtype)
    out = np.empty(array.shape, dtype=dtype)
    for i, value in enumerate(array.flat):
        n, d = float(value).as_integer_ratio()
        q = nearest(n*scale.numerator, d*scale.denominator)
        if q < info.min or q > info.max: fail("export_parameter_range")
        out.flat[i] = q
    return out


def source_shapes(cols):
    e, m, p, h, o = 64, 128, 128, 640, 128
    out = OrderedDict((name, (rows, width)) for name, rows, width in
        [("species",1024,e),("move",1024,e),("item",256,e),("ability",256,e),("nature",25,8)])
    out["struggle"] = (e,)
    sizes = [("move_token",e+1,e),("member1",5*e+42,m),("member2",m,m),("position",106+m,p),
             *[(f"torso.{i}",94+4*p+4*m if i==0 else h,h) for i in range(3)],
             ("option_context",h,o),("option1",len(cols.slot_scalar)+e+2*m+o,o),
             ("option2",o,o),("option_out",o,2),("team_context",h,o),("team1",m+o,o),
             ("team_out",o,3),("pair1",2*m+o,o),("pair_out",o,1),("value",h,1)]
    for name, ni, no in sizes:
        out[name+".w"] = (ni,no); out[name+".b"] = (no,)
    for i in range(3):
        out[f"torso_norm.{i}.g"]=(h,);out[f"torso_norm.{i}.b"]=(h,)
    return out


def value_sources():
    out = OrderedDict((name,name) for name in ("species","move","item","ability","nature"))
    for name in ("move_token","member1","member2","position"):
        for field in ("w","b"): out[name+"."+field]=name+"."+field
    for i in range(3):
        for field in ("w","b"): out[f"torso.{i}.{field}"]=f"torso.{i}.{field}"
        for field in ("g","b"): out[f"norm.{i}.{field}"]=f"torso_norm.{i}.{field}"
    for field in ("w","b"): out["value."+field]="value."+field
    assert len(out)==27
    return out


def flatten(tree, prefix=""):
    out={}
    if isinstance(tree, dict):
        for name, child in tree.items():out.update(flatten(child,prefix+"."+str(name) if prefix else str(name)))
    elif isinstance(tree, (list,tuple)):
        for i,child in enumerate(tree):out.update(flatten(child,prefix+"."+str(i)))
    else:out[prefix]=np.asarray(tree)
    return out


def inspect_source(params, config, features, cols):
    if config.get("format")!=2 or config.get("encoder")!=6: fail("export_checkpoint_format_encoder")
    if config.get("model")!=EXPECTED_MODEL: fail("export_checkpoint_graph_configuration")
    if config.get("features")!=list(features.FEATURE_NAMES): fail("export_feature_inventory")
    if config.get("slot_features")!=list(features.SLOT_FEATURE_NAMES): fail("export_slot_inventory")
    from duoforge_learn import checkpoint
    try:
        mask=checkpoint.ext_supported_of(config)
    except ValueError as error:
        fail("export_encoder_mask:"+str(error))
    if mask!=BC6_MASK:fail("export_feature_mask")
    flat=flatten(params);expected=source_shapes(cols)
    if set(flat)!=set(expected):fail("export_source_unclassified:"+",".join(sorted(set(flat)^set(expected))))
    audit=[];mapping=value_sources();needed=set(mapping.values())
    for name, shape in expected.items():
        a=flat[name]
        if a.shape!=shape or a.dtype.kind!="f" or a.dtype.itemsize!=4:fail("export_source_shape_dtype:"+name)
        if not np.isfinite(a).all():fail("export_source_nonfinite:"+name)
        if name in needed:
            audit.append(dict(name=name,shape=list(a.shape),elements=a.size,sha256_f32_le=sha(a.astype("<f4").tobytes())))
    if len(audit)!=27 or sum(a["elements"] for a in audit)!=MAX_PARAMETERS:fail("export_source_accounting")
    return flat, audit, sorted(set(flat)-needed)


def integer_parameters(flat, unit):
    if unit not in (256,512,1024,2048,4096,8192,16384): fail("export_input_unit")
    mapping=value_sources();tensors=OrderedDict([("input.unit",np.array([unit],dtype="<i2"))]);scales={};audit={}
    for wire, source in mapping.items():
        original=flat[source]
        if wire in ("species","move","item","ability","nature"):
            maximum=rational(np.max(np.abs(original)))
            weight_scale=Fraction(127)/maximum if maximum else Fraction(1)
            tensors[wire]=quantize(original,weight_scale,"i1")
            scales[wire]=[scale_record(Fraction(unit)/weight_scale,(1<<32)-1)]
            audit[wire]=dict(weight_scale=[weight_scale.numerator,weight_scale.denominator])
        elif wire.endswith(".w"):
            name=wire[:-2];weights=original.T;bias=flat[source[:-1]+"b"]
            qw=np.empty(weights.shape,dtype="i1");qb=np.empty(bias.shape,dtype="<i8");ratios=[];source_scales=[]
            for channel, row in enumerate(weights):
                maximum=rational(np.max(np.abs(row)))
                weight_scale=Fraction(127)/maximum if maximum else Fraction(1)
                qw[channel]=quantize(row,weight_scale,"i1")
                qb[channel]=quantize(bias[channel:channel+1],unit*weight_scale,"<i8")[0]
                target=Fraction(1)/weight_scale if name!="value" else Fraction(1<<20,unit)/weight_scale
                ratios.append(target);source_scales.append([weight_scale.numerator,weight_scale.denominator])
            if max(abs(int(x)) for x in qb)>1<<40:fail("export_bias_bound:"+name)
            input_bound=1<<31 if name in ("torso.1","torso.2","value") else 32768
            bound=weights.shape[1]*input_bound*int(np.max(np.abs(qw.astype(np.int16))))+(1<<40)
            allowed=((1<<63)-1)//bound
            scales[wire]=[scale_record(x,allowed) for x in ratios]
            tensors[wire]=qw;tensors[name+".b"]=qb
            audit[wire]=dict(channel_weight_scales=source_scales,loader_bound=bound)
        elif wire.startswith("norm."):
            q=quantize(original,Fraction(unit),"<i4")
            limit=1<<20 if wire.endswith(".g") else 1<<24
            if np.max(np.abs(q.astype(np.int64)))>limit:fail("export_normalization_bound:"+wire)
            tensors[wire]=q
        elif wire.endswith(".b"):
            if wire not in tensors:fail("export_bias_order:"+wire)
        else:fail("export_wire_unclassified:"+wire)
    if list(tensors)!=["input.unit",*mapping]:fail("export_wire_inventory")
    return tensors,scales,audit


def feature_hashes(features, cols):
    names=sha(json.dumps(list(features.FEATURE_NAMES),separators=(",",":")).encode())
    mapping=[None]*1094
    for group in ("glob","side","position","occupant","member","present","species","item","ability","nature","moves","pp","move_count"):
        indexes=getattr(cols,group)
        for coords in np.ndindex(indexes.shape):
            i=int(indexes[coords])
            if mapping[i] is not None:fail("export_column_duplicate")
            mapping[i]=(group,coords)
    if any(x is None for x in mapping):fail("export_column_unclassified")
    layout=sha(json.dumps(list(zip(features.FEATURE_NAMES,mapping)),separators=(",",":")).encode())
    return names,layout


def pack_artifact(tensors,scales,engine,teacher_sha,calibration_sha,metadata,features_sha,layout_sha):
    for value in (teacher_sha,calibration_sha,engine["fingerprint"],features_sha,layout_sha):
        if not re.fullmatch("[0-9a-f]{64}",value) or int(value,16)==0:fail("export_identity")
    count=len(tensors)
    if count!=28:fail("export_wire_count")
    buf=bytearray(256+128*count);buf[:8]=b"DFEVAL\0\0"
    for at,value in [(8,1),(12,256),(24,1001),(28,1),(32,6),(36,1094),(48,engine["semantics"]),
                     (52,engine["context_schema"]),(56,count),(60,len(metadata)),(88,engine["species_count"]),(92,engine["move_count"])]:
        struct.pack_into("<I",buf,at,value)
    for at,value in [(40,BC6_MASK),(64,256),(72,len(buf))]:struct.pack_into("<Q",buf,at,value)
    for at,value in [(96,engine["fingerprint"]),(128,teacher_sha),(160,calibration_sha),(192,features_sha),(224,layout_sha)]:buf[at:at+32]=bytes.fromhex(value)
    buf.extend(metadata);buf.extend(bytes(-len(buf)%8));struct.pack_into("<Q",buf,80,len(buf))
    for index,(name,a) in enumerate(tensors.items()):
        at=256+128*index;tag=name.encode("ascii")
        if len(tag)>31:fail("export_tensor_name")
        buf[at:at+len(tag)]=tag;dtype={1:1,2:2,4:3,8:4}[a.dtype.itemsize]
        struct.pack_into("<II",buf,at+32,dtype,a.ndim)
        for j,width in enumerate(a.shape):struct.pack_into("<I",buf,at+40+4*j,width)
        data=a.astype(a.dtype.newbyteorder("<"),copy=False).tobytes()
        struct.pack_into("<QQ",buf,at+56,len(buf),len(data));buf.extend(data);buf.extend(bytes(-len(buf)%8))
        if name in scales:
            struct.pack_into("<Q",buf,at+72,len(buf));struct.pack_into("<I",buf,at+80,len(scales[name]))
            for record in scales[name]:buf.extend(struct.pack("<II",*record))
    struct.pack_into("<Q",buf,16,len(buf))
    if len(buf)>4*1024*1024:fail("export_file_capacity")
    return bytes(buf)


def outside_checkout(path):
    path=Path(path).resolve()
    for parent in (path.parent,*path.parent.parents):
        if (parent/".git").exists():
            # The cloud reserves inert .git markers at /workspace and /tmp.
            # A marker is not itself a repository. Confirm with Git, and still
            # inspect outer parents if an invalid inner marker shadows one.
            env={k:v for k,v in os.environ.items() if k not in ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR")}
            probe=subprocess.run(["git","-C",str(parent),"rev-parse","--git-dir"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
            if probe.returncode==0:fail("export_output_inside_checkout")
    return path


def write_private(path,data,check):
    path=outside_checkout(path)
    if check:
        if not path.is_file() or path.read_bytes()!=data:fail("export_check_mismatch")
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as f:f.write(data)


def clean_commit(repo):
    run=lambda *args:subprocess.check_output(["git","-C",str(repo),*args],text=True).strip()
    if run("status","--porcelain"):fail("export_dirty_code")
    return run("rev-parse","HEAD")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("repo","checkpoint","manifest","output","audit"):parser.add_argument("--"+name,required=True,type=Path)
    parser.add_argument("--check",action="store_true");args=parser.parse_args()
    for path in (args.checkpoint,args.manifest,args.output,args.audit):outside_checkout(path)
    if args.checkpoint.stat().st_size>256*1024*1024:fail("export_checkpoint_capacity")
    if file_sha(args.checkpoint)!=TEACHER:fail("export_teacher_sha256")
    repo=args.repo.resolve();engine_commit=clean_commit(repo);export_commit=clean_commit(Path(__file__).parent)
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["teacher_sha256"]!=TEACHER or manifest["engine"]["commit"]!=engine_commit:fail("export_manifest_identity")
    if manifest["quantization"]["method"]!=METHOD:fail("export_quantization_method")
    identities={}
    for field in ("split","calibration"):
        entry=manifest[field];data=outside_checkout(entry["path"]).read_bytes()
        if sha(data)!=entry["sha256"]:fail("export_manifest_sha256:"+field)
        identities[field]=json.loads(data)
    if identities["calibration"]["selected_unit"]!=manifest["quantization"]["unit"]:fail("export_calibration_unit")
    groups=identities["split"]["groups"]
    for left,right in [("training","calibration"),("training","holdout"),("calibration","holdout")]:
        if not groups[left] or not groups[right] or set(groups[left])&set(groups[right]):fail("export_split_overlap_or_empty")
    training=manifest["source_training"]
    if not re.fullmatch("[0-9a-f]{40}",training["commit"]) or not isinstance(training["dirty"],bool):fail("export_training_provenance")
    seed=manifest["seed"]
    if type(seed) is not int or not 0<=seed<1<<64:fail("export_seed")
    with zipfile.ZipFile(args.checkpoint) as archive:
        if sum(i.file_size for i in archive.infolist())>256*1024*1024:fail("export_source_capacity")
    sys.path.insert(0,str(repo/"python"))
    from duoforge import features
    from duoforge_learn import checkpoint
    from duoforge_learn.columns import columns
    params,config=checkpoint.load_trained(args.checkpoint);cols=columns()
    flat,inventory,omitted=inspect_source(params,config,features,cols)
    tensors,scales,quant=integer_parameters(flat,manifest["quantization"]["unit"])
    names_sha,layout_sha=feature_hashes(features,cols)
    metadata=(f"export_commit={export_commit}\nexport_dirty=0\nseed={seed}\n"
              f"split_sha256={manifest['split']['sha256']}\ntraining_commit={training['commit']}\ntraining_dirty={int(training['dirty'])}\n").encode("ascii")
    data=pack_artifact(tensors,scales,manifest["engine"],TEACHER,manifest["calibration"]["sha256"],metadata,names_sha,layout_sha)
    report=dict(schema=1,teacher_sha256=TEACHER,artifact_sha256=sha(data),artifact_bytes=len(data),
        engine_commit=engine_commit,engine_dirty=False,export_commit=export_commit,export_dirty=False,
        exporter_file_sha256=file_sha(__file__),manifest_sha256=file_sha(args.manifest),source_config_sha256=sha(canonical(config)),
        learned_source_tensors=inventory,learned_elements=sum(t["elements"] for t in inventory),
        omitted_policy_team_only=omitted,quantization=quant,integer_wire=[dict(name=n,shape=list(a.shape),
        dtype=a.dtype.str,sha256=sha(a.tobytes()),scales=scales.get(n,[])) for n,a in tensors.items()],
        fidelity_gates="NOT_RUN_BY_EXPORTER",adoption=False)
    if not args.check and (args.output.exists() or args.audit.exists()):fail("export_output_exists")
    write_private(args.output,data,args.check);write_private(args.audit,canonical(report),args.check)
    print(json.dumps(dict(check=args.check,artifact_sha256=sha(data),artifact_bytes=len(data),value_tensors=27,
                         learned_elements=MAX_PARAMETERS,fidelity_gates="NOT_RUN_BY_EXPORTER")))


if __name__=="__main__":
    try:main()
    except (ValueError,KeyError,FileNotFoundError) as error:
        print(type(error).__name__+": "+str(error),file=sys.stderr);sys.exit(2)
