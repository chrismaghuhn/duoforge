"""Independent E4 integer trace and extracted BC6 float value oracles.

The Python-integer graph is copied from the E3g independent oracle, without
its synthetic-only assertion that the generated torso deliberately exceeds
int16. All arithmetic, range checks and 201 stage records remain. The C
implementation and quantizer are never called by this reference graph.
"""
from pathlib import Path
import struct
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
from integer_oracle import finite, nearest, clip
from normalization_oracle import norm
from duoforge_learn.columns import columns
COLS = columns()
SHAPES = {"full": (1001,64,128,128,640,3,1802441,4194304)}

def integer_trace(unit, tensors, scales, observations, statistics=None):
    from integer_oracle import clip as scalar_clip
    def clip(value):
        if statistics is not None and not -(1<<15)<=value<(1<<15):
            statistics["i16_saturations"]=statistics.get("i16_saturations",0)+1
        return scalar_clip(value)
    label = "full"
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
        value=dense("value",x,short=False);emit("value",0,value)
        assert len(seen)==189+4*layers
    return b"".join(frames)



# Value-path float extraction. Keep operation/normalization order explicit.

def _layer(p, x):
    return x @ p["w"] + p["b"]


def _ln(p, x):
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / jnp.sqrt(var + 1e-5) * p["g"] + p["b"]


def _ids(x, scale):
    return jnp.round(x * scale).astype(jnp.int32)


def _pool(h, valid, axis):
    """Sum and max of h over `axis` where valid (an empty pool gives zeros)."""
    v = valid[..., None]
    total = jnp.sum(jnp.where(v, h, 0.0), axis=axis)
    top = jnp.max(jnp.where(v, h, -jnp.inf), axis=axis)
    return total, jnp.where(jnp.isfinite(top), top, 0.0)



def float_value(params, cfg, cols, obs):
    global jax, jnp
    import jax
    import jax.numpy as jnp
    b = obs.shape[0]
    caps = cfg["capacities"]
    count = _ids(obs[:, cols.move_count], 4)                                  # (B,2,6)
    registered = count > 0
    valid_moves = jnp.arange(4)[None, None, None, :] < count[..., None]       # (B,2,6,4)
    move_ids = jnp.clip(_ids(obs[:, cols.moves], 65535), 0, caps["move"] - 1)
    tokens = jax.nn.relu(_layer(params["move_token"], jnp.concatenate(
        [params["move"][move_ids], obs[:, cols.pp][..., None]], axis=-1)))     # (B,2,6,4,E)
    move_sum, move_max = _pool(tokens, valid_moves, axis=3)
    side_flag = jnp.broadcast_to(jnp.array([1.0, 0.0])[None, :, None, None], (b, 2, 6, 1))
    member_in = jnp.concatenate([
        params["species"][jnp.clip(_ids(obs[:, cols.species], 65535), 0, caps["species"] - 1)],
        move_sum, move_max,
        params["item"][jnp.clip(_ids(obs[:, cols.item], 255), 0, caps["item"] - 1)],
        params["ability"][jnp.clip(_ids(obs[:, cols.ability], 255), 0, caps["ability"] - 1)],
        params["nature"][jnp.clip(_ids(obs[:, cols.nature], 24), 0, caps["nature"] - 1)],
        obs[:, cols.member], side_flag, registered[..., None].astype(jnp.float32)], axis=-1)
    h = jax.nn.relu(_layer(params["member2"], jax.nn.relu(_layer(params["member1"], member_in))))
    h = h * registered[..., None]                                             # (B,2,6,Dm)

    occupant = jnp.argmax(obs[:, cols.occupant], axis=-1)                    # (B,2,2): 0..5, 6 = none
    occupied = occupant < 6
    occ = jnp.clip(occupant, 0, 5)
    occ_h = jnp.take_along_axis(h, occ[..., None], axis=2) * occupied[..., None]   # (B,2,2,Dm)
    positions = jax.nn.relu(_layer(params["position"], jnp.concatenate(
        [obs[:, cols.position], occupied[..., None].astype(jnp.float32), occ_h], axis=-1)))
    side_sum, side_max = _pool(h, registered, axis=2)                         # (B,2,Dm)
    x = jnp.concatenate([obs[:, cols.glob], obs[:, cols.side].reshape(b, -1), positions.reshape(b, -1),
                         side_sum.reshape(b, -1), side_max.reshape(b, -1)], axis=-1)
    for i, (layer, norm) in enumerate(zip(params["torso"], params["torso_norm"])):
        y = jax.nn.relu(_ln(norm, _layer(layer, x)))
        x = y if i == 0 else x + y

    return _layer(params["value"], x)[:, 0]
