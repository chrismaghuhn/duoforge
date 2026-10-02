#!/usr/bin/env python3
"""The protocol of the persistent worker (tools/reference/ps_worker.js), with
raw pipes: what it answers, in which order, what it does with a line it cannot
use, and that stdout carries nothing but responses. It needs Node and the
pinned Showdown checkout.

usage: python3 tools/reference/test_ps_worker.py <node> <pinned checkout>

CTest runs it as duoforge.reference.worker_protocol when the checkout and Node
are present.
"""
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # a direct run must not leave __pycache__ in the source tree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
WORKER = os.path.join(HERE, 'ps_worker.js')
NODE = None
CHECKOUT = None


def committed(kind, name):
    """The text of tests/reference/<kind>/<name>.json, line ends as LF."""
    with io.open(os.path.join(ROOT, 'tests', 'reference', kind, name + '.json'), 'rb') as f:
        return f.read().decode('utf-8').replace('\r\n', '\n')


def spec_of(name):
    return json.loads(committed('specs', name))


class Session:
    """One worker process over raw pipes."""

    def __init__(self, *node_args):
        self.proc = subprocess.Popen([NODE, *node_args, WORKER, CHECKOUT], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def send_line(self, text):
        """One request line, as it is; returns the one response line, parsed."""
        self.proc.stdin.write(text.encode('utf-8') + b'\n')
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line.endswith(b'\n'):
            raise AssertionError('no response line to %r (the worker exited with %r)' % (text[:80], self.proc.poll()))
        try:
            return json.loads(line.decode('utf-8'))
        except ValueError:
            raise AssertionError('stdout holds something that is not a response: %r' % line[:120]) from None

    def send(self, request):
        return self.send_line(json.dumps(request))

    def finish(self):
        """EOF on stdin: (exit status, what is left on stdout, stderr)."""
        self.proc.stdin.close()
        rest = self.proc.stdout.read()
        err = self.proc.stderr.read()
        self.proc.stdout.close()
        self.proc.stderr.close()
        return self.proc.wait(timeout=30), rest, err.decode('utf-8', 'replace')

    def kill(self):
        """Cleanup: the process is gone and every pipe is closed."""
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            pipe.close()


class Worker(unittest.TestCase):
    def session(self, *node_args):
        s = Session(*node_args)
        self.addCleanup(s.kill)
        return s

    def test_version(self):
        s = self.session()
        trace = json.loads(committed('traces', 's2_turn_core_1'))  # the pin and the harness the traces were made with
        reply = s.send({'id': 7, 'cmd': 'version'})
        node = subprocess.run([NODE, '--version'], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(reply, {'id': 7, 'ok': True, 'node': node, 'pin': trace['pin'], 'harness': trace['harness']})
        self.assertEqual(list(reply), ['id', 'ok', 'node', 'pin', 'harness'])

    def test_record_is_the_committed_trace_and_the_ids_come_back_in_order(self):
        s = self.session()
        for i, name in enumerate(('s2_turn_core_1', 'c05_helmet_order', 's2_turn_core_1')):  # closure, Team C, again
            reply = s.send({'id': 100 + i, 'cmd': 'record', 'spec': spec_of(name), 'spec_file': name + '.json'})
            self.assertEqual((reply['id'], reply['ok'], list(reply)), (100 + i, True, ['id', 'ok', 'trace']))
            self.assertEqual(reply['trace'], committed('traces', name), name)

    def test_a_request_that_throws_is_answered_and_the_worker_keeps_serving(self):
        s = self.session()
        broken = spec_of('s2_turn_core_1')
        broken['choices'][1]['p1'] = 'move 9'  # a choice Showdown rejects: run() throws
        reply = s.send({'id': 1, 'cmd': 'record', 'spec': broken, 'spec_file': 'broken.json'})
        self.assertEqual((reply['id'], reply['ok'], list(reply)), (1, False, ['id', 'ok', 'error', 'stack']))
        self.assertIn('choice rejected', reply['error'])
        self.assertIsInstance(reply['stack'], str)
        self.assertTrue(reply['stack'].startswith('Error: '), reply['stack'])
        self.assertLessEqual(len(reply['stack'].split('\n')), 6)
        good = s.send({'id': 2, 'cmd': 'record', 'spec': spec_of('s2_turn_core_1'), 'spec_file': 's2_turn_core_1.json'})
        self.assertEqual((good['id'], good['ok']), (2, True))
        self.assertEqual(good['trace'], committed('traces', 's2_turn_core_1'))  # no state left over from the failed run

    def test_requests_it_cannot_use_are_refused_one_response_each(self):
        s = self.session()
        spec = spec_of('s2_turn_core_1')
        cases = [
            # (a request line, the id of its response, a part of its error)
            ('not json', None, 'malformed request'),
            ('', None, 'malformed request'),
            ('[1, 2]', None, 'not a JSON object'),
            ('"text"', None, 'not a JSON object'),
            ('null', None, 'not a JSON object'),
            ('{"cmd": "version"}', None, 'id must be an integer'),
            ('{"id": "7", "cmd": "version"}', None, 'id must be an integer'),
            ('{"id": 1.5, "cmd": "version"}', None, 'id must be an integer'),
            ('{"id": 8}', 8, 'unknown command'),
            ('{"id": 9, "cmd": "replay"}', 9, 'unknown command: "replay"'),
            ('{"id": 17, "cmd": "play"}', 17, 'play: battle must be an object'),
            ('{"id": 10, "cmd": "constructor"}', 10, 'unknown command'),  # not found on the prototype chain
            (json.dumps({'id': 11, 'cmd': 'record', 'spec_file': 'x.json'}), 11, 'spec must be an object'),
            (json.dumps({'id': 12, 'cmd': 'record', 'spec': [], 'spec_file': 'x.json'}), 12, 'spec must be an object'),
            (json.dumps({'id': 13, 'cmd': 'record', 'spec': spec}), 13, 'spec_file must be a file name'),
            (json.dumps({'id': 14, 'cmd': 'record', 'spec': spec, 'spec_file': 'dir/x.json'}), 14,
             'spec_file must be a file name'),
            (json.dumps({'id': 15, 'cmd': 'record', 'spec': spec, 'spec_file': 'dir\\x.json'}), 15,
             'spec_file must be a file name'),
            (json.dumps({'id': 16, 'cmd': 'record', 'spec': {'format': 'gen9championsvgc2026regmc'},
                         'spec_file': 'x.json'}), 16, ''),  # run() throws on the missing seed and teams
        ]
        for line, want_id, part in cases:
            with self.subTest(line=line[:60]):
                reply = s.send_line(line)
                self.assertEqual((reply['id'], reply['ok']), (want_id, False))
                self.assertIn(part, reply['error'])
                self.assertEqual(list(reply), ['id', 'ok', 'error', 'stack'])
        self.assertEqual(s.send({'id': 99, 'cmd': 'version'})['ok'], True)  # still serving

    def test_the_trace_names_the_spec_file_of_its_own_request(self):
        """Not the file of an earlier request: the worker keeps nothing from one run to the next."""
        s = self.session()
        for name in ('s2_turn_core_1', 'c05_helmet_order'):
            reply = s.send({'id': 1, 'cmd': 'record', 'spec': spec_of(name), 'spec_file': name + '.json'})
            self.assertEqual(json.loads(reply['trace'])['spec'], name + '.json')
        renamed = s.send({'id': 2, 'cmd': 'record', 'spec': spec_of('s2_turn_core_1'), 'spec_file': 'renamed.json'})
        self.assertEqual(json.loads(renamed['trace'])['spec'], 'renamed.json')
        want = copy.deepcopy(json.loads(committed('traces', 's2_turn_core_1')))
        want['spec'] = 'renamed.json'
        self.assertEqual(json.loads(renamed['trace']), want)

    def play_request(self, rid=1, battle_seed=1, policy_seed=1, **policy):
        """A play request for team A against team B: the battle of the spec of a committed battle, the choices left out."""
        spec = spec_of('m5_real_ab_1')
        battle = {'format': spec['format'], 'seed': 'sodium,' + '%064x' % battle_seed, 'teams': spec['teams']}
        return {'id': rid, 'cmd': 'play', 'battle': battle,
                'policy': {'seed': policy_seed, 'max_steps': 300, 'switch_weight': 0.1, 'mega_weight': 0.5, **policy}}

    def test_play_answers_with_choices_that_replay(self):
        """The choices are the answers of both sides, and recording them as a spec gives a battle of the same
        length and result: what Showdown judged in the play is what it replays."""
        s = self.session()
        request = self.play_request()
        reply = s.send(request)
        self.assertEqual((reply['id'], reply['ok'], list(reply)), (1, True, ['id', 'ok', 'choices', 'ended', 'steps', 'domain']))
        self.assertEqual((reply['steps'], reply['ended']), (len(reply['choices']), True))
        self.assertEqual(reply['domain'], {'samples': [], 'request_changed': 0})  # no domain_rate: nothing sampled
        self.assertTrue(all(set(entry) <= {'p1', 'p2'} and entry for entry in reply['choices']))
        self.assertRegex(reply['choices'][0]['p1'], r'^team \d{4}$')
        spec = {'name': 'play_test', 'purpose': 'test', 'format': request['battle']['format'],
                'seed': request['battle']['seed'], 'teams': request['battle']['teams'], 'choices': reply['choices']}
        recorded = s.send({'id': 2, 'cmd': 'record', 'spec': spec, 'spec_file': 'play_test.json'})
        self.assertTrue(recorded['ok'], recorded)
        trace = json.loads(recorded['trace'])
        self.assertEqual(len(trace['steps']), reply['steps'])
        self.assertEqual([step['input'] for step in trace['steps']], reply['choices'])
        self.assertTrue(trace['steps'][-1]['state']['ended'])

    def test_play_is_the_same_for_the_same_request_and_not_for_another_policy_seed(self):
        s = self.session()
        first = s.send(self.play_request(1))
        again = s.send(self.play_request(2))
        other = s.send(self.play_request(3, policy_seed=2))
        self.assertEqual({k: v for k, v in first.items() if k != 'id'}, {k: v for k, v in again.items() if k != 'id'})
        self.assertNotEqual(first['choices'], other['choices'])

    def test_play_stops_at_max_steps(self):
        s = self.session()
        reply = s.send(self.play_request(max_steps=2))
        self.assertEqual((reply['ok'], reply['steps'], reply['ended'], len(reply['choices'])), (True, 2, False, 2))

    def test_play_samples_the_domain_of_requests_without_changing_the_battle(self):
        """With a domain_rate the reply holds, for the sampled requests, what Showdown accepts; the choices are the
        same as without it."""
        s = self.session()
        plain = s.send(self.play_request(1))
        every = s.send(self.play_request(2, domain_rate=1))
        self.assertEqual((every['ok'], list(every)), (True, ['id', 'ok', 'choices', 'ended', 'steps', 'domain']))
        for key in ('choices', 'ended', 'steps'):
            self.assertEqual(every[key], plain[key], key)
        domain = every['domain']
        self.assertEqual(list(domain), ['samples', 'request_changed'])
        asked = sum(len(entry) for entry in every['choices'])
        self.assertEqual(len(domain['samples']) + domain['request_changed'], asked)  # every request, rate 1
        first = domain['samples'][0]
        self.assertEqual((list(first), first['step'], first['side']), (['step', 'side', 'accepted'], 0, 0))
        self.assertEqual(len(first['accepted']), 360)  # team preview: the ordered picks of four of six
        self.assertIn(every['choices'][0]['p1'], first['accepted'])
        for sample in domain['samples']:
            side = 'p1' if sample['side'] == 0 else 'p2'
            self.assertIn(every['choices'][sample['step']][side], sample['accepted'])
        # A lower rate samples some of them, the same ones every time, with the sets of the full run.
        some = s.send(self.play_request(3, domain_rate=0.3))
        again = s.send(self.play_request(4, domain_rate=0.3))
        self.assertEqual(some['domain'], again['domain'])
        full = {(x['step'], x['side']): x for x in domain['samples']}
        self.assertTrue(0 < len(some['domain']['samples']) < len(domain['samples']))
        for sample in some['domain']['samples']:
            self.assertEqual(sample, full[(sample['step'], sample['side'])])

    def test_play_refuses_a_request_that_is_not_the_documented_one(self):
        s = self.session()
        good = self.play_request()
        cases = [
            ('a missing policy', {k: v for k, v in good.items() if k != 'policy'}, 'play: policy must be an object'),
            ('a missing battle', {k: v for k, v in good.items() if k != 'battle'}, 'play: battle must be an object'),
            ('a policy key too many', dict(good, policy=dict(good['policy'], extra=1)), 'play: policy has the keys'),
            ('a seed that is not a uint32', dict(good, policy=dict(good['policy'], seed=2 ** 32)), 'play: policy.seed'),
            ('a weight above 1', dict(good, policy=dict(good['policy'], mega_weight=2)), 'play: policy.mega_weight'),
            ('a domain rate above 1', dict(good, policy=dict(good['policy'], domain_rate=1.5)), 'play: policy.domain_rate'),
            ('a domain rate that is text', dict(good, policy=dict(good['policy'], domain_rate='1')), 'play: policy.domain_rate'),
            ('one team', dict(good, battle=dict(good['battle'], teams=['x'])), 'play: battle.teams'),
        ]
        for what, request, part in cases:
            with self.subTest(what):
                reply = s.send(request)
                self.assertEqual((reply['id'], reply['ok']), (1, False))
                self.assertIn(part, reply['error'])
        self.assertTrue(s.send(good)['ok'])  # and it keeps serving

    def test_stdout_carries_only_responses(self):
        """What a library prints after the start goes to stderr: a preload prints through console.log and
        process.stdout as soon as the worker is running."""
        with tempfile.TemporaryDirectory() as tmp:
            preload = os.path.join(tmp, 'stray.js')
            with io.open(preload, 'w', encoding='utf-8') as f:
                f.write("setImmediate(() => { console.log('stray console.log'); process.stdout.write('stray write\\n'); });\n")
            s = self.session('--require', preload)
            reply = s.send({'id': 1, 'cmd': 'version'})  # the first line on stdout is this response
            self.assertEqual((reply['id'], reply['ok']), (1, True))
            status, rest, err = s.finish()
        self.assertEqual((status, rest), (0, b''))
        self.assertIn('stray console.log', err)
        self.assertIn('stray write', err)

    def test_it_exits_at_eof_with_status_0(self):
        s = self.session()
        s.send({'id': 1, 'cmd': 'version'})
        status, rest, err = s.finish()
        self.assertEqual((status, rest, err), (0, b'', ''))

    def test_a_last_line_without_a_line_end_is_still_a_request(self):
        s = self.session()
        s.proc.stdin.write(b'{"id": 5, "cmd": "version"}')  # no LF
        s.proc.stdin.close()
        out = s.proc.stdout.read()
        self.assertEqual(json.loads(out.decode('utf-8'))['id'], 5)
        self.assertEqual(out.count(b'\n'), 1)
        self.assertEqual(s.proc.wait(timeout=30), 0)

    def test_usage_and_a_checkout_that_is_not_built(self):
        run = lambda *args: subprocess.run([NODE, WORKER, *args], capture_output=True, text=True, timeout=60)
        p = run()
        self.assertEqual((p.returncode, p.stdout, p.stderr), (2, '', 'usage: ps_worker.js <pinned checkout>\n'))
        p = run('a', 'b')
        self.assertEqual((p.returncode, p.stdout), (2, ''))
        with tempfile.TemporaryDirectory() as tmp:
            p = run(tmp)
        self.assertEqual((p.returncode, p.stdout), (2, ''))
        self.assertIn('dist', p.stderr)
        self.assertIn('not found', p.stderr)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.stderr.write('usage: test_ps_worker.py <node> <pinned checkout>\n')
        sys.exit(2)
    NODE, CHECKOUT = sys.argv[1], sys.argv[2]
    unittest.main(argv=[sys.argv[0]] + sys.argv[3:])
