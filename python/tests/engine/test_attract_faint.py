"""Issue #395 (lane B, step G87): an Attract source that faints in the battle's last action keeps its byte at TERMINAL, and the
Update before a REPLACEMENT boundary clears it.

The battles are the engine's own random play: the G71 Cute Charm teams (tools/cloud/aws_fuzz/campaigns/g71-triggers and g71-cute-charm),
9 pairs x 4 replicas, seed 9720000, the random factored choices of RandomPolicy. The three episodes below were found by that play; their
choice sequences are stored here. Every run of the play must make the same choices (checked against the policy's own choices), and the
stored choices are played for those episodes. No state bytes are stored.

- terminal_env18_ep0: the battle's last action faints the Attract source (Milotic, side 1); the battle ends (TERMINAL). The byte stays
  and the state check passes. It was refused before issue #395 (invariants.c, the source-active rule of dfi_attract_byte_ok).
- terminal_env14_ep5: the same at TERMINAL, with the infatuation started in the last action (Cute Charm) and its source fainting.
- replacement_env8_ep0: the source (side 0, member 0) faints in step 4; the battle goes on to a REPLACEMENT boundary, where the Update
  has ended the infatuation: the byte is 0 and the state check passes.
"""
import ctypes
import os
import unittest

import numpy as np

from duoforge import Batch, Context, RandomPolicy, _layout, state_layout, teams
from duoforge._lib import load_library

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
CAMPAIGNS = os.path.join(ROOT, 'tools', 'cloud', 'aws_fuzz', 'campaigns')
TEAMS = {
    'G2': os.path.join(CAMPAIGNS, 'g71-triggers', 'G2.txt'),
    'H2': os.path.join(CAMPAIGNS, 'g71-triggers', 'H2.txt'),
    'G': os.path.join(CAMPAIGNS, 'g71-cute-charm', 'G.txt'),
    'H': os.path.join(CAMPAIGNS, 'g71-cute-charm', 'H.txt'),
    'I': os.path.join(CAMPAIGNS, 'g71-cute-charm', 'I.txt'),
    'J': os.path.join(CAMPAIGNS, 'g71-cute-charm', 'J.txt'),
}
PAIRS = [('G2', 'H2'), ('H2', 'G2'), ('G2', 'G2'), ('G', 'H'), ('H', 'G'), ('G', 'J'), ('J', 'G'), ('G', 'I'), ('I', 'G')]
REPLICAS = 4
SEED = 9720000
MAX_EPISODES = 400
MAX_STEPS = 300

# Per case: the environment, the episode, the number of steps, the last step's expectation, and the stored choices (per step, per
# player: [slot 0, slot 1, picks 0..5], the FACTORED_CHOICE record).
CASES = {
    'terminal_env18_ep0': {'env': 18, 'episode': 0, 'steps': 11, 'terminal': True, 'choices': [[[0, 0, 5, 2, 4, 0, 0, 0], [0, 0, 2, 4, 3, 1, 0, 0]], [[4, 0, 0, 0, 0, 0, 0, 0], [2, 8, 0, 0, 0, 0, 0, 0]], [[0, 0, 0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0, 0, 0]], [[6, 9, 0, 0, 0, 0, 0, 0], [1, 2, 0, 0, 0, 0, 0, 0]], [[0, 0, 0, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0, 0, 0]], [[5, 2, 0, 0, 0, 0, 0, 0], [7, 0, 0, 0, 0, 0, 0, 0]], [[3, 3, 0, 0, 0, 0, 0, 0], [5, 0, 0, 0, 0, 0, 0, 0]], [[0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]], [[7, 3, 0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0, 0, 0]], [[0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]], [[2, 5, 0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0, 0, 0]]]},
    'terminal_env14_ep5': {'env': 14, 'episode': 5, 'steps': 12, 'terminal': True, 'choices': [[[0, 0, 4, 5, 2, 1, 0, 0], [0, 0, 5, 2, 1, 0, 0, 0]], [[3, 5, 0, 0, 0, 0, 0, 0], [6, 6, 0, 0, 0, 0, 0, 0]], [[1, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]], [[1, 2, 0, 0, 0, 0, 0, 0], [3, 10, 0, 0, 0, 0, 0, 0]], [[0, 1, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]], [[5, 5, 0, 0, 0, 0, 0, 0], [5, 7, 0, 0, 0, 0, 0, 0]], [[0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]], [[4, 0, 0, 0, 0, 0, 0, 0], [6, 10, 0, 0, 0, 0, 0, 0]], [[7, 0, 0, 0, 0, 0, 0, 0], [5, 6, 0, 0, 0, 0, 0, 0]], [[0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0]], [[5, 0, 0, 0, 0, 0, 0, 0], [1, 4, 0, 0, 0, 0, 0, 0]], [[6, 0, 0, 0, 0, 0, 0, 0], [0, 4, 0, 0, 0, 0, 0, 0]]]},
    'replacement_env8_ep0': {'env': 8, 'episode': 0, 'steps': 4, 'terminal': False, 'choices': [[[0, 0, 2, 3, 0, 4, 0, 0], [0, 0, 2, 4, 1, 5, 0, 0]], [[6, 5, 0, 0, 0, 0, 0, 0], [2, 11, 0, 0, 0, 0, 0, 0]], [[1, 1, 0, 0, 0, 0, 0, 0], [4, 0, 0, 0, 0, 0, 0, 0]], [[0, 2, 0, 0, 0, 0, 0, 0], [0, 3, 0, 0, 0, 0, 0, 0]]]},
}
# The source bytes of the cases: the REPLACEMENT case holds code 1 (side 0 member 0) on flat 3 before its step 4, and the byte
# is 0 after it. The TERMINAL cases: flat 0 holds code 8 (env 18), flat 2 holds code 2 (env 14), at the battle's end.
REPLACEMENT_FLAT, REPLACEMENT_CODE = 3, 1
TERMINAL_BYTES = {'terminal_env18_ep0': (0, 8), 'terminal_env14_ep5': (2, 2)}


def _setups(ctx):
    sides = {}
    for name, path in TEAMS.items():
        with open(path, encoding='utf-8') as fh:
            members = teams.parse(fh.read(), name)
        sides[name] = teams.side_setup(ctx, members, name)
    out = np.zeros(len(PAIRS) * REPLICAS, dtype=_layout.SETUP)
    for k, (a, b) in enumerate(PAIRS):
        for r in range(REPLICAS):
            out[k * REPLICAS + r]['sides'][0] = sides[a]
            out[k * REPLICAS + r]['sides'][1] = sides[b]
    return out


_LAYOUT = {name: (off, size) for name, off, size in state_layout.fields(pool=True)}
ATTRACT = _LAYOUT['tail5.attract_source'][0]


def _hp(raw, side, member):
    off = _LAYOUT['side%d.member%d.hp' % (side, member)][0]
    return raw[off] | (raw[off + 1] << 8)


def _ser(choice):
    return [[int(v) for v in choice[p]['slot']] + [int(v) for v in choice[p]['picks']] for p in range(2)]


class AttractFaintTest(unittest.TestCase):
    def test_terminal_and_replacement_cases(self):
        lib = load_library()
        ctx = Context(data_kind=_layout.CONSTANTS['DUOFORGE_DATA_KIND_POOL'])
        self.addCleanup(ctx.close)
        setups = _setups(ctx)
        envs = setups.shape[0]
        batch = Batch(ctx, setups, 2, SEED)
        self.addCleanup(batch.close)
        policy = RandomPolicy(SEED, envs)
        policy.start_episodes(np.arange(envs), np.zeros(envs, dtype=np.uint32))
        episode = np.zeros(envs, dtype=np.int64)  # the episode each environment is in
        next_episode = np.ones(envs, dtype=np.int64)
        steps = np.zeros(envs, dtype=np.int64)  # the steps of that episode
        case_steps = {name: 0 for name in CASES}
        finished = set()
        for _ in range(20000):
            if len(finished) == len(CASES):
                break
            batch.query_factored()
            choices = policy.choose_factored(batch)
            for name, case in CASES.items():
                env = case['env']
                if name in finished or episode[env] != case['episode'] or batch.result(env) != 0:
                    continue
                k = case_steps[name]
                self.assertEqual(_ser(choices[env]), case['choices'][k], (name, k, 'the policy makes the stored choice'))
                if name == 'replacement_env8_ep0' and k == 3:
                    self.assertEqual(batch.encode(env)[ATTRACT + REPLACEMENT_FLAT], REPLACEMENT_CODE,
                                     'the source (side 0 member 0) is infatuating before its step')
                for p in range(2):
                    choices[env, p]['slot'] = case['choices'][k][p][:2]
                    choices[env, p]['picks'] = case['choices'][k][p][2:]
            batch.step_factored(choices)  # an engine refusal raises here
            for name, case in CASES.items():
                env = case['env']
                if name in finished or episode[env] != case['episode']:
                    continue
                case_steps[name] += 1
                if case_steps[name] == case['steps']:
                    finished.add(name)
                    self._check_case(lib, ctx, batch, name, env, case)
            for env in range(envs):
                steps[env] += 1
                if batch.result(env) == 0 and steps[env] < MAX_STEPS:
                    continue
                if next_episode[env] >= MAX_EPISODES:
                    continue
                ep = int(next_episode[env])
                next_episode[env] += 1
                batch.reset(env, ep)
                policy.start_episode(env, ep)
                episode[env] = ep
                steps[env] = 0
        self.assertEqual(finished, set(CASES), 'every case reached its last step')

    def _check_case(self, lib, ctx, batch, name, env, case):
        raw = batch.encode(env)
        self.assertEqual(lib.duoforge_battle_check(ctx.handle, ctypes.c_void_p(int(batch._battle(env)))), 0,
                         (name, 'the state check passes'))
        if case['terminal']:
            self.assertNotEqual(batch.result(env), 0, (name, 'the battle is TERMINAL'))
            flat, code = TERMINAL_BYTES[name]
            self.assertEqual(raw[ATTRACT + flat], code, (name, 'the fainted source keeps its byte'))
            self.assertEqual(_hp(raw, (code - 1) // 6, (code - 1) % 6), 0, (name, 'the source is fainted'))
        else:
            self.assertEqual(batch.result(env), 0, (name, 'the battle goes on'))
            self.assertEqual(raw[_LAYOUT['boundary'][0]], _layout.CONSTANTS['DUOFORGE_BOUNDARY_REPLACEMENT'],
                             (name, 'the step stops at a REPLACEMENT boundary'))
            self.assertEqual(raw[ATTRACT + REPLACEMENT_FLAT], 0, (name, 'the Update ended the infatuation: the byte is 0'))
            self.assertEqual(_hp(raw, 0, 0), 0, (name, 'the source (side 0 member 0) fainted'))


if __name__ == '__main__':
    unittest.main()
