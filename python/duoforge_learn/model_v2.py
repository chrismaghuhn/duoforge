"""Model v2: the actor-critic with embeddings (decision 0017, spec section 8), in JAX.

It reads the same inputs as v1 (the encoder's observation part, slot part
and pair mask) and recovers the ids the encoder scales (species and moves by
65535, items and abilities by 255, natures by 24) from the columns that
columns.Columns names. Members are embedded and pooled per side with sum
and max, a member's moves as order-free tokens, so the network is
equivariant to roster order and move order: the occupants of the four
positions and an option's actor, move and reserve are addressed by
gathering, never fed in as indices. Team selection scores each member for
lead slot 0, lead slot 1 and the back, plus each ordered lead pair; a
tuple's logit is the sum, over the same 360 tuples as v1.
"""
import jax
import jax.numpy as jnp
import numpy as np

from .selfplay import TEAM_TABLE

MASKED = -1e9
CAPACITIES = {"species": 1024, "move": 1024, "item": 256, "ability": 256, "nature": 25}
PRESETS = {
    "S": {"embed": 32, "member": 64, "position": 64, "hidden": 256, "layers": 2, "option": 64},
    "M": {"embed": 64, "member": 128, "position": 128, "hidden": 640, "layers": 3, "option": 128},
    "L": {"embed": 64, "member": 256, "position": 256, "hidden": 1024, "layers": 5, "option": 256},
}
_NATURE_DIM = 8
_TEAM = jnp.asarray(TEAM_TABLE, dtype=jnp.int32)


def config(preset="S", **dims):
    """A v2 configuration: a preset's dimensions with overrides."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}: one of {sorted(PRESETS)}")
    unknown = set(dims) - set(PRESETS[preset])
    if unknown:
        raise ValueError(f"unknown model dimensions {sorted(unknown)}")
    cfg = {"version": 2, **PRESETS[preset], **{k: int(v) for k, v in dims.items()}}
    cfg["capacities"] = dict(CAPACITIES)
    return cfg


def _dense(key, n_in, n_out, scale=1.0):
    w = jax.random.normal(key, (n_in, n_out), dtype=jnp.float32) * (scale * np.sqrt(2.0 / n_in))
    return {"w": w, "b": jnp.zeros((n_out,), dtype=jnp.float32)}


def _norm(n):
    return {"g": jnp.ones((n,), dtype=jnp.float32), "b": jnp.zeros((n,), dtype=jnp.float32)}


def _sizes(cfg, cols):
    e, dm, dp, h, do = cfg["embed"], cfg["member"], cfg["position"], cfg["hidden"], cfg["option"]
    member_in = 3 * e + 2 * e + _NATURE_DIM + cols.member.shape[-1] + 2
    position_in = cols.position.shape[-1] + 1 + dm
    torso_in = cols.glob.shape[0] + cols.side.size + 4 * dp + 4 * dm
    option_in = cols.slot_scalar.shape[0] + e + 2 * dm + do
    return e, dm, dp, h, do, member_in, position_in, torso_in, option_in


def init(key, cfg, cols):
    """Fresh parameters."""
    e, dm, dp, h, do, member_in, position_in, torso_in, option_in = _sizes(cfg, cols)
    caps = cfg["capacities"]
    k = iter(jax.random.split(key, 32))
    params = {
        "species": jax.random.normal(next(k), (caps["species"], e), dtype=jnp.float32) * 0.1,
        "move": jax.random.normal(next(k), (caps["move"], e), dtype=jnp.float32) * 0.1,
        "item": jax.random.normal(next(k), (caps["item"], e), dtype=jnp.float32) * 0.1,
        "ability": jax.random.normal(next(k), (caps["ability"], e), dtype=jnp.float32) * 0.1,
        "nature": jax.random.normal(next(k), (caps["nature"], _NATURE_DIM), dtype=jnp.float32) * 0.1,
        "struggle": jax.random.normal(next(k), (e,), dtype=jnp.float32) * 0.1,
        "move_token": _dense(next(k), e + 1, e),
        "member1": _dense(next(k), member_in, dm),
        "member2": _dense(next(k), dm, dm),
        "position": _dense(next(k), position_in, dp),
        "torso": [_dense(next(k), torso_in, h)] + [_dense(next(k), h, h) for _ in range(cfg["layers"] - 1)],
        "torso_norm": [_norm(h) for _ in range(cfg["layers"])],
        "option_context": _dense(next(k), h, do),
        "option1": _dense(next(k), option_in, do),
        "option2": _dense(next(k), do, do),
        "option_out": _dense(next(k), do, 2, 0.01),
        "team_context": _dense(next(k), h, do),
        "team1": _dense(next(k), dm + do, do),
        "team_out": _dense(next(k), do, 3, 0.01),
        "pair1": _dense(next(k), 2 * dm + do, do),
        "pair_out": _dense(next(k), do, 1, 0.01),
        "value": _dense(next(k), h, 1, 0.01),
    }
    return params


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


def apply(params, cfg, cols, obs, slots, mask):
    """obs (B, O), slots (B, 2, 32, F), mask (B, 32, 32) bool ->
    (pair log-probabilities (B, 1024), team log-probabilities (B, 360),
    value (B,))."""
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

    # Options: the actor of slot list s is the occupant of own position s.
    kind_move = slots[..., cols.slot_is_move[0]]
    kind_switch = slots[..., cols.slot_is_switch[0]]
    actor = occ[:, 0, :]                                                      # (B,2)
    actor_h = jnp.take_along_axis(h[:, 0], actor[..., None], axis=1) * occupied[:, 0, :, None]  # (B,2,Dm)
    actor_tokens = jnp.take_along_axis(tokens[:, 0], actor[:, :, None, None], axis=1)            # (B,2,4,E)
    slot_k = _ids(slots[..., cols.slot_move[0]], 4)                           # (B,2,32)
    move_tok = jnp.take_along_axis(actor_tokens, jnp.clip(slot_k, 0, 3)[..., None], axis=2)      # (B,2,32,E)
    move_tok = jnp.where((slot_k == 4)[..., None], params["struggle"], move_tok) * kind_move[..., None]
    reserve = jnp.clip(_ids(slots[..., cols.slot_reserve[0]], 5), 0, 5)
    reserve_h = jnp.take_along_axis(h[:, 0][:, None], reserve[..., None], axis=2) * kind_switch[..., None]
    context = jax.nn.relu(_layer(params["option_context"], x))
    option_in = jnp.concatenate([
        slots[..., cols.slot_scalar], move_tok, jnp.broadcast_to(actor_h[:, :, None, :], reserve_h.shape),
        reserve_h, jnp.broadcast_to(context[:, None, None, :], reserve_h.shape[:3] + context.shape[-1:])], axis=-1)
    hidden = jax.nn.relu(_layer(params["option2"], jax.nn.relu(_layer(params["option1"], option_in))))
    out = _layer(params["option_out"], hidden)                                # (B,2,32,2)
    pairs = out[:, 0, :, 0][:, :, None] + out[:, 1, :, 1][:, None, :]
    pairs = jnp.where(mask, pairs, MASKED).reshape(b, -1)

    own = h[:, 0]                                                             # (B,6,Dm)
    team_ctx = jax.nn.relu(_layer(params["team_context"], x))
    scores = _layer(params["team_out"], jax.nn.relu(_layer(params["team1"], jnp.concatenate(
        [own, jnp.broadcast_to(team_ctx[:, None, :], own.shape[:2] + team_ctx.shape[-1:])], axis=-1))))  # (B,6,3)
    pair_in = jnp.concatenate([
        jnp.broadcast_to(own[:, :, None, :], (b, 6, 6, own.shape[-1])),
        jnp.broadcast_to(own[:, None, :, :], (b, 6, 6, own.shape[-1])),
        jnp.broadcast_to(team_ctx[:, None, None, :], (b, 6, 6, team_ctx.shape[-1]))], axis=-1)
    pair = _layer(params["pair_out"], jax.nn.relu(_layer(params["pair1"], pair_in)))[..., 0]   # (B,6,6)
    t = _TEAM
    team = (scores[:, t[:, 0], 0] + scores[:, t[:, 1], 1] + pair[:, t[:, 0], t[:, 1]]
            + scores[:, t[:, 2], 2] + scores[:, t[:, 3], 2])                  # (B,360)
    value = _layer(params["value"], x)[:, 0]
    return jax.nn.log_softmax(pairs), jax.nn.log_softmax(team), value
