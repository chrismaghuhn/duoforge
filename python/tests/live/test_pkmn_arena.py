"""duoforge.python.pkmn_arena: the live client's PKMN Arena mode (owner, 2026-10-12) with a fake websocket only.

Nothing here connects anywhere: the connection is a scripted fake. The battle stream is the live client's fixture
(python/tests/support/data/live_stream_ab.json: what the pinned Showdown sends p1, Team A against Team B, with open team
sheets), put in an arena room. Under test: login with /trn and the team after every login, the token kept out of every
log, record, message and exception text, the open-team-sheet battle played by the policy, the documented fallback
(/choose default) with its counted reasons, retries after refused choices, the decision deadline, reconnects with
backoff and the resumed open request, the random-team ladder and the command line.
"""
import asyncio
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from duoforge_live import __main__ as cli, client, cts, data, pkmn_arena, teams
from python.tests.live.test_live_client import FIXTURE, FakePolicy

TOKEN = "pka_SeCrEt0123456789"
NAME = "Tian-Suan"
OTS = "gen9championsvgc2026regmcots"
CTS = "gen9championsvgc2026regmc"
ROOM = f"battle-{OTS}-7"
ENV = {pkmn_arena.NAME_ENV: NAME, pkmn_arena.TOKEN_ENV: TOKEN}
LOGIN = ["|updateuser| Guest 12|0|1|{}", "|challstr|4|abcdef", f"|updateuser| {NAME}|1|1|{{}}"]


def room(lines, room_id=ROOM):
    return ">" + room_id + "\n" + "\n".join(lines)


def battle_messages(room_id=ROOM, upto=len(FIXTURE["messages"])):
    return [room(["|init|battle", f"|title|{NAME} vs. Opponent", "|j|☆Opponent"], room_id)] + \
        [room(lines, room_id) for lines in FIXTURE["messages"][:upto]]


def request_of(message):
    return next(json.loads(line[len("|request|"):]) for line in FIXTURE["messages"][message]
                if line.startswith("|request|"))


class FakeClosed(Exception):
    """websockets' ConnectionClosed in shape: the close frame received."""

    def __init__(self, code):
        super().__init__(f"closed {code}")
        self.rcvd = SimpleNamespace(code=code)


class FakeSocket:
    """One connection: hands out its script (a str, or a callable run when reached), then closes with `code`. A send
    that ends with `drop` closes it instead (once)."""

    def __init__(self, script, code, sent, drop=None):
        self.script, self.code, self.sent, self.drop = list(script), code, sent, drop

    async def recv(self):
        while self.script:
            item = self.script.pop(0)
            if callable(item):
                item()
                continue
            return item
        raise FakeClosed(self.code)

    async def send(self, text):
        if self.drop is not None and text.endswith(self.drop):
            self.drop, self.script = None, []
            raise FakeClosed(1006)
        self.sent.append(text)


class FakeConnect:
    """connect(url) of the bot: one scripted connection per call."""

    def __init__(self, connections):
        self.connections = list(connections)  # [(script, close code)] or [(script, close code, drop)]
        self.urls = []
        self.sent = []

    def __call__(self, url):
        self.urls.append(url)
        script, code, *drop = self.connections.pop(0)
        socket = FakeSocket(script, code, self.sent, *drop)

        @contextlib.asynccontextmanager
        async def manager():
            yield socket
        return manager()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RaisingPolicy(FakePolicy):
    def rank_pairs(self, *args):
        raise RuntimeError("the network broke")


class BlockingPolicy(FakePolicy):
    """Blocks rank_pairs until released: a decision that misses its deadline."""

    def __init__(self):
        self.release = threading.Event()

    def rank_pairs(self, *args):
        self.release.wait(10)
        return super().rank_pairs(*args)


class ArenaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.slept = []
        self.stderr = io.StringIO()
        patch = mock.patch.dict(os.environ, ENV)
        patch.start()
        self.addCleanup(patch.stop)
        self.bot = None

    def make(self, policy=None, team=True, pool=(), fmt=OTS, connections=(), kind=None, **kw):
        async def sleep(seconds):
            self.slept.append(seconds)
        self.connect = FakeConnect(connections)
        kind = kind or ("pool" if fmt.startswith(CTS) and not fmt.startswith(OTS) else "closure")  # the set table's
        self.bot = pkmn_arena.ArenaBot(NAME, data.load(kind=kind), policy or FakePolicy(), self.tmp.name, fmt,
                                       team_text=FIXTURE["team"] if team else None, pool=pool,
                                       connect=self.connect, connection_errors=(FakeClosed,), sleep=sleep,
                                       clock=self.clock, **kw)
        self.addCleanup(self.bot.close)
        self.sent = self.connect.sent
        self.bot.connection = SimpleNamespace(send=self.record)
        return self.bot

    async def record(self, text):
        self.sent.append(text)

    def feed(self, *messages):
        async def go():
            for m in messages:
                await self.bot.handle(m)
        with contextlib.redirect_stderr(self.stderr):
            asyncio.run(go())

    def run_bot(self):
        """bot.run() until the scripted connections end it (a SystemExit); returns that exit."""
        with contextlib.redirect_stderr(self.stderr), self.assertRaises(SystemExit) as stop:
            asyncio.run(self.bot.run())
        return stop.exception

    def take(self):
        out, self.sent[:] = list(self.sent), []
        return out

    def chosen(self):
        return [s for s in self.take() if "/choose" in s]

    def battle(self, room_id=ROOM):
        path = Path(self.tmp.name, f"{room_id}-{client.toid(NAME)}.jsonl")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def run_log(self):
        self.bot.run_log.write()
        return json.loads(self.bot.run_log.path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ login, team, token
    def test_the_url_is_the_allow_listed_arena_host(self):
        import urllib.parse
        # the arena's address since its move on 2026-10-15 (llms.txt); the fake connection records it, nothing connects
        self.assertEqual((pkmn_arena.URL, pkmn_arena.HOST), ("wss://vgc.bot/showdown/websocket", "vgc.bot"))
        url = urllib.parse.urlparse(pkmn_arena.URL)
        self.assertEqual((url.scheme, url.hostname, url.path, url.query), ("wss", pkmn_arena.HOST, "/showdown/websocket", ""))
        self.make(connections=[(LOGIN, 4001)])
        self.run_bot()
        self.assertEqual(self.connect.urls, [pkmn_arena.URL])
        self.assertFalse(any(old in pkmn_arena.URL for old in pkmn_arena.OLD_HOSTS))
        self.assertFalse(client.official(pkmn_arena.URL))  # the official server's refusal is a separate check

    def test_login_with_trn_and_the_team_after_every_login(self):
        def lasts():
            self.clock.now += pkmn_arena.STABLE
        self.make(connections=[(LOGIN + [lasts], 1006), (LOGIN, 1008), (LOGIN, 4001)])
        stop = self.run_bot()
        self.assertIn("4001", str(stop))
        trn = f"|/trn {NAME},0,{TOKEN}"
        utm = "|/utm " + teams.pack(FIXTURE["team"])
        self.assertEqual(self.sent, [trn, utm] * 3)
        # the first connection lasted: the backoff starts again; the second closed at once after its login: it grows
        self.assertEqual(self.slept, [1.0, 2.0])
        log = self.run_log()
        self.assertEqual(log["counts"]["logins"], 3)
        self.assertEqual(log["counts"]["reconnects"], 2)
        self.assertEqual(log["closes"], {"1006": 1, "1008": 1, "4001": 1})

    def test_the_backoff_grows_while_no_login_succeeds(self):
        self.make(connections=[([], 1006)] * 7 + [([], 4001)])
        self.run_bot()
        self.assertEqual(self.slept, [1.0, 2.0, 5.0, 10.0, 30.0, 30.0, 30.0])

    def test_no_team_sends_no_utm(self):
        self.make(team=False, pool=[FIXTURE["team"]], connections=[(LOGIN, 4001)])
        self.run_bot()
        self.assertEqual(self.sent, [f"|/trn {NAME},0,{TOKEN}"])

    def test_a_rejected_team_stops_the_bot(self):
        popup = "|popup|Your team was rejected for the following reasons:||- Ceruledge's move Foo is illegal."
        self.make(connections=[(LOGIN + [popup], 1006)])
        stop = self.run_bot()
        self.assertIn("rejected the team", str(stop))
        self.assertIn("Foo is illegal", str(stop))

    def test_other_popups_are_printed_and_counted(self):
        self.make()
        self.feed("|popup|You played each other 10 times; wait 12 minutes.")
        self.assertIn("arena popup", self.stderr.getvalue())
        self.assertEqual(self.run_log()["counts"]["popups"], 1)

    def test_a_refused_login_stops_without_showing_the_token(self):
        self.make(connections=[(["|challstr|4|abc", f"|nametaken|{NAME}|Unknown bot name or invalid token {TOKEN}"],
                                1006)])
        stop = self.run_bot()
        self.assertIn("refused the login", str(stop))
        self.assertNotIn(TOKEN, str(stop))
        self.assertIn("[token]", str(stop))

    def test_the_token_appears_in_no_log_record_message_or_exception(self):
        # A full fake session: login, an open-team-sheet battle, a drop and reconnect, a fallback through a policy
        # error whose text names the token, popups and a refused login that echo it.
        policy = FakePolicy()
        calls = []

        def rank_pairs(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError(f"an error that names {TOKEN}")
            return FakePolicy.rank_pairs(policy, *args)
        policy.rank_pairs = rank_pairs
        first = LOGIN + battle_messages(upto=6)
        second = LOGIN + [f"|popup|echo {TOKEN}"] + [room(["|init|battle"] + [l for m in FIXTURE["messages"][:7]
                                                                                 for l in m if not l.startswith("|request|")])] + \
            [room(FIXTURE["messages"][7]), room(["|win|Opponent"]), f"|nametaken|{NAME}|bad token {TOKEN}"]
        self.make(policy=policy, connections=[(first, 1006), (second, 1006)])
        stop = self.run_bot()
        trn = [s for s in self.sent if TOKEN in s]
        self.assertEqual(trn, [f"|/trn {NAME},0,{TOKEN}"] * 2)  # the token goes to the server in the login only
        self.assertNotIn(TOKEN, str(stop))
        self.assertNotIn(TOKEN, self.stderr.getvalue())
        self.bot.close()
        files = list(Path(self.tmp.name).iterdir())
        self.assertTrue(any(f.name.startswith("arena-run-") for f in files))
        self.assertTrue(any(f.name.startswith(ROOM) for f in files))
        for f in files:
            self.assertNotIn(TOKEN, f.read_text(encoding="utf-8"), f.name)
        self.assertIn("error:RuntimeError", self.run_log()["fallback_battles"])
        # never assertNotIn on these: a failure message would print them
        self.assertFalse(TOKEN in repr(self.bot.__dict__), "the bot keeps the token")
        self.assertFalse(TOKEN in repr(self.bot.config), "the config holds the token")

    # ------------------------------------------------------------------ the open-team-sheet battle
    def test_an_ots_battle_folds_the_sheets_and_plays_without_fallback(self):
        self.make()
        self.feed(*battle_messages(upto=4))  # up to both |showteam| lines
        b = self.bot.battles[ROOM]
        self.assertIsNone(b.fallback)
        foe_payload = next(line for line in FIXTURE["messages"][3] if line.startswith("|showteam|p2|"))
        self.assertEqual(b.game.foe_sets, teams.unpack(foe_payload.split("|", 3)[3]))
        # the foe's revealed sets in DuoForge's observation: items, abilities, moves, natures; stat points hidden
        o = b.game.tracker.observation()
        foe = o["sides"][1]["members"]
        sheets = data.load().team(teams.to_text(b.game.foe_sets))
        for m, sheet in enumerate(sheets):
            self.assertEqual(int(foe[m]["species_id"]), sheet["species"])
            self.assertEqual(int(foe[m]["item"]), sheet["item"])
            self.assertEqual(int(foe[m]["ability"]), sheet["ability"])
            self.assertEqual(int(foe[m]["nature"]), sheet["nature"])
            self.assertEqual([int(x) for x in foe[m]["move_ids"][:len(sheet["moves"])]], sheet["moves"])
            self.assertEqual(int(np.sum(foe[m]["stat_points"])), 0)
            self.assertEqual(int(np.sum(foe[m]["stats"])), 0)
        sent = self.chosen()
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith(f"{ROOM}|/choose team ") and sent[0].endswith("|1"), sent)
        self.feed(*[room(m) for m in FIXTURE["messages"][4:]])
        sent = self.chosen()
        rqids = [request_of(k)["rqid"] for k in (5, 7, 9)]
        self.assertEqual([s.rsplit("|", 1)[1] for s in sent], [str(r) for r in rqids])
        self.feed(room(["|win|" + NAME]))
        log = self.run_log()
        self.assertEqual(log["counts"]["decisions"], 4)
        self.assertEqual(log["counts"]["wins"], 1)
        self.assertEqual(log["fallback_battles"], {})
        self.assertEqual(log["formats"], {OTS: 1})
        self.assertNotIn("default", json.dumps([r for r in self.battle() if "sent" in r]))
        self.assertFalse([s for s in self.sent if "/forfeit" in s or "/leave" in s])

    def test_the_run_log_holds_aggregates_only(self):
        self.make()
        self.feed(*battle_messages())
        self.feed(room(["|win|Opponent"]))
        text = json.dumps(self.run_log())
        for private in (ROOM, "battle-", "Opponent", NAME):
            self.assertNotIn(private, text)
        self.assertEqual(self.run_log()["counts"]["losses"], 1)

    def test_the_run_log_names_the_search_settings_it_plays(self):
        # HauptSession, 2026-10-14 (#494): a replay of the series plays the search the bot played; the run log's head
        # names its settings (search.load keeps them on the LiveSearch), and a bot without a search names none.
        from duoforge_live import search as live_search

        class Search:
            settings = dict(live_search.HONEST_SETTINGS)

            def decide(self, *args, **kwargs):
                return live_search.Outcome(None, "raw", None, None, 0.0)

            def close(self):
                pass
        self.make(search=Search())
        self.assertEqual(self.run_log()["search_settings"], live_search.HONEST_SETTINGS)
        self.bot.close()
        self.make()
        self.assertNotIn("search_settings", self.run_log())

    def test_the_ab_test_plays_each_battle_with_its_arms_root_rule(self):
        # The A/B test of the root rule (owner, 2026-10-14): each team battle draws its arm from the seed and its
        # number, names it in its first record and plays its root rule at every decision; the run log names the seed
        # and the arms; a battle of another format draws nothing.
        from duoforge_live import ab, search as live_search
        rules = []

        class Search:
            settings = dict(live_search.HONEST_SETTINGS)

            def decide(self, *args, **kwargs):
                rules.append(kwargs.get("rule"))
                return live_search.Outcome(None, "raw", None, None, 0.0)

            def close(self):
                pass
        self.make(search=Search(), ab_seed=11)
        head = self.run_log()["ab_root_rule"]
        self.assertEqual(head, {"seed": 11, "block": 2, "arms": ab.settings()})
        played = []
        for number, room_id in enumerate((f"battle-{OTS}-21", f"battle-{OTS}-22", f"battle-{OTS}-23")):
            rules.clear()
            self.feed(*battle_messages(room_id))
            self.feed(room(["|win|Opponent"], room_id))
            first = self.battle(room_id)[0]  # the first record: the log format, and the arm
            want = ab.arm(11, number)
            self.assertEqual(first["search_rule"], {"arm": want, "index": number, "rule": ab.rule(want),
                                                    "settings": ab.settings()[want]})
            self.assertTrue(rules)
            self.assertEqual(set(rules), {ab.rule(want)})  # every decision of the battle plays its arm's rule
            played.append(want)
        self.assertEqual(sorted(played[:2]), sorted(ab.ARMS))  # the first block: one battle of each arm
        self.assertEqual(self.run_log()["counts"]["ab_arm_" + played[0]], played.count(played[0]))
        self.feed(*battle_messages(f"battle-{CTS}-31"))  # another format: no arm, no number used
        self.assertNotIn("search_rule", self.battle(f"battle-{CTS}-31")[0])
        self.assertEqual(self.bot._ab_next, 3)

    def test_the_ab_test_needs_the_honest_search_and_the_team(self):
        from duoforge_live import search as live_search

        class Search:
            settings = dict(live_search.HONEST_SETTINGS)

            def decide(self, *args, **kwargs):
                return live_search.Outcome(None, "raw", None, None, 0.0)

            def close(self):
                pass
        for kw, message in (({}, "honest search"), ({"search": Search(), "team": False}, "--team"),
                            ({"search": type("S", (Search,), {"settings": {**live_search.HONEST_SETTINGS, "k": 4}})()},
                             "not the arms'")):
            with self.subTest(kw=list(kw)), self.assertRaisesRegex(ValueError, message):
                self.make(ab_seed=1, **kw)

    def test_the_run_log_and_each_summary_name_the_bots_commit_and_dirty_state(self):
        # HauptSession, 2026-10-13: every result names the code that ran, its commit and whether the tree was dirty
        # (a summary's own "dirty" is the game's class (b) reason, not the code's state).
        from duoforge_live import search as live_search

        class RawSearch:
            def decide(self, *args, **kwargs):
                return live_search.Outcome(None, "raw", None, None, 0.0)

            def close(self):
                pass
        code = {"commit": "8c4fe662", "dirty": False}
        self.make(search=RawSearch(), code=code)
        self.feed(*battle_messages())
        self.feed(room(["|win|Opponent"]))
        self.assertEqual(self.run_log()["code"], code)
        self.assertEqual(self.run_log()["log_format"], client.LOG_FORMAT)  # the battle logs' format (#385)
        self.assertEqual(self.battle()[0], {"log_format": client.LOG_FORMAT, "code": code})  # every battle names it
        import hashlib
        self.assertEqual(self.run_log()["team_sha256"], hashlib.sha256(FIXTURE["team"].encode("utf-8")).hexdigest())
        summary = next(r["summary"] for r in self.battle() if "summary" in r)
        self.assertEqual(summary["code"], code)

    def test_the_arena_mode_names_its_code_or_does_not_start(self):
        from duoforge_live import arena
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(arena, "provenance", side_effect=SystemExit("no commit to name: DUOFORGE_COMMIT")):
            argv = ["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--log-dir", tmp]
            with mock.patch.dict(os.environ, ENV), self.assertRaisesRegex(SystemExit, "DUOFORGE_COMMIT"):
                cli.main(argv)

    def test_a_wait_request_gets_no_answer_and_a_tie_ends_the_battle(self):
        self.make()
        self.feed(*battle_messages(upto=6))
        self.take()
        wait = {"wait": True, "side": request_of(5)["side"], "rqid": 40}
        self.feed(room(["|request|" + json.dumps(wait)]))
        self.assertEqual(self.chosen(), [])
        self.feed(room(["|tie"]))
        self.assertEqual(self.run_log()["counts"]["ties"], 1)
        self.assertNotIn(ROOM, self.bot.battles)

    def test_every_battle_is_played_one_after_the_other(self):
        self.make()
        for k, room_id in enumerate((ROOM, f"battle-{OTS}-8")):
            self.feed(*battle_messages(room_id, upto=6))
            sent = self.chosen()
            self.assertEqual(len(sent), 2, sent)
            self.assertTrue(all(s.startswith(room_id + "|/choose ") for s in sent))
            self.feed(room(["|win|" + NAME], room_id))
        self.assertEqual(self.run_log()["counts"]["battles"], 2)

    # ------------------------------------------------------------------ the fallback
    # ------------------------------------------------------------------ closed team sheets (decision 0081)
    def closed_messages(self, room_id, upto=6):
        return [room(["|init|battle"], room_id)] + \
            [room([l for l in m if not l.startswith("|showteam|")], room_id) for m in FIXTURE["messages"][:upto]]

    def test_closed_team_sheets_are_played_over_the_particles(self):
        self.make(fmt=CTS)
        closed = f"battle-{CTS}-3"
        self.feed(*self.closed_messages(closed))
        rq = [request_of(2)["rqid"], request_of(5)["rqid"]]
        sent = self.chosen()
        self.assertEqual(len(sent), 2, sent)
        self.assertTrue(sent[0].startswith(f"{closed}|/choose team ") and sent[0].endswith(f"|{rq[0]}"), sent)
        self.assertTrue(sent[1].startswith(f"{closed}|/choose move ") and sent[1].endswith(f"|{rq[1]}"), sent)
        game = self.bot.battles[closed].game
        self.assertTrue(game.closed)
        self.assertEqual(len(game.tracker.particles), cts.PARTICLES)
        self.feed(room(["|win|" + NAME], closed))
        log = self.run_log()
        self.assertEqual((log["fallback_battles"], log["fallback_decisions"]), ({}, {}))
        self.assertEqual(log["counts"]["decisions"], 2)
        self.assertEqual(log["cts"]["battles"], 1)  # with the particle tracker's counters, aggregates only
        self.assertEqual(log["cts"], {"battles": 1, **{cts.counter_kind(k): n for k, n in game.tracker.counters.items()}})
        self.assertFalse([k for k in log["cts"] if k.count(":") > 2 or " " in k], log["cts"])

    def test_a_closed_sheet_stop_falls_back_by_its_name(self):
        tables = data.load(kind="pool")
        prior = cts.SetPrior(tables, [s for s in teams._paste(FIXTURE["foe_team"]) if s["species"] != "Farigiraf"])
        self.make(fmt=CTS, prior=prior)
        closed = f"battle-{CTS}-4"
        self.feed(*self.closed_messages(closed))
        rq = [request_of(2)["rqid"], request_of(5)["rqid"]]
        self.assertEqual(self.chosen(), [f"{closed}|/choose default|{rq[0]}", f"{closed}|/choose default|{rq[1]}"])
        log = self.run_log()
        self.assertEqual(log["fallback_battles"], {"stop:cts:no-consistent-set": 1})
        self.assertEqual(log["fallback_decisions"], {"stop:cts:no-consistent-set": 2})
        self.assertIn({"fallback": "stop:cts:no-consistent-set", "detail": "stop:cts:no-consistent-set Farigiraf"},
                      self.battle(closed))

    def test_the_closed_sheet_log_keeps_the_batches_that_draw_the_particles(self):
        # The particles depend on how the stream was batched (decision 0081): the battle log keeps each batch the game
        # was fed and each choice it accepted, so the log alone draws the same particles again.
        self.make(fmt=CTS)
        closed = f"battle-{CTS}-5"
        self.feed(*self.closed_messages(closed, upto=9))
        game = self.bot.battles[closed].game
        again = cts.ParticleTracker(self.bot.data, FIXTURE["team"], self.bot.prior, cts.SEED, closed, cts.PARTICLES)
        for record in self.battle(closed):
            if "feed" in record:
                again.feed(record["feed"])
            elif "accepted" in record:
                again.accepted(record["accepted"])
        self.assertGreater(game.epoch, 2)
        self.assertEqual(again.epoch, game.epoch)
        self.assertEqual([p.sets for p in again.particles], [p.sets for p in game.tracker.particles])
        self.assertEqual([p["record"].tobytes() for p in again.public_parts()],
                         [p["record"].tobytes() for p in game.tracker.public_parts()])

    def test_the_bots_own_log_replays_to_the_same_particles_at_every_decision(self):
        # cts.LogReplay (#385, the one replay core of cts_live_eval and Search's ko_check): the bot's log, replayed under
        # the same seed, key and prior, gives at every decision point the particles and records the bot decided on,
        # before the choice is accepted, with that decision's log record.
        from duoforge_live import game as game_module
        self.make(fmt=CTS)
        closed = f"battle-{CTS}-6"
        seen, real = [], game_module.Game.candidates

        def candidates(g, *args, **kwargs):
            seen.append((g.epoch, g.request["rqid"], [p.sets for p in g.tracker.particles],
                         [p["record"].tobytes() for p in g.tracker.public_parts()]))
            return real(g, *args, **kwargs)
        with mock.patch.object(game_module.Game, "candidates", candidates):
            self.feed(*self.closed_messages(closed, upto=9))
        self.assertGreaterEqual(len(seen), 3)
        path = Path(self.tmp.name, f"{closed}-{client.toid(NAME)}.jsonl")
        self.assertEqual(cts.room_of_log(path, NAME), closed)
        replay = cts.LogReplay(self.battle(closed), self.bot.data, self.bot.policy, FIXTURE["team"], self.bot.prior,
                               cts.room_of_log(path, NAME))
        points = [(g.epoch, g.request["rqid"], [p.sets for p in g.tracker.particles],
                   [p["record"].tobytes() for p in g.tracker.public_parts()], record) for g, record in replay]
        self.assertIsNone(replay.stopped)
        self.assertEqual([p[:4] for p in points], seen)
        for epoch, rqid, _, _, record in points:
            self.assertEqual(record["decision"], rqid)  # the decision's own log record, with what was sent
            self.assertIn("sent", record)

    def test_a_replayed_decision_names_the_choice_played_after_a_refusal(self):
        # Review of the replay core: "sent" is the first try; after "[Invalid choice]" the bot plays the next one, and
        # the replay's record names it as "accepted"
        self.make(fmt=CTS)
        closed = f"battle-{CTS}-7"
        self.feed(*self.closed_messages(closed, upto=6))
        self.take()
        self.feed(room(["|error|[Invalid choice] Can't move: no."], closed))
        (again,) = self.take()
        played = again.split("|/choose ", 1)[1].rsplit("|", 1)[0]
        self.feed(*[room([l for l in m if not l.startswith("|showteam|")], closed) for m in FIXTURE["messages"][6:9]])
        replay = cts.LogReplay(self.battle(closed), self.bot.data, self.bot.policy, FIXTURE["team"], self.bot.prior,
                               closed)
        records = {g.request["rqid"]: record for g, record in replay}
        record = records[request_of(5)["rqid"]]
        self.assertNotEqual(record["sent"], played)
        self.assertEqual(record["accepted"], played)

    # ------------------------------------------------------------------ the log format 2: pending_at_end (#385)
    FORFEIT_ROOM = f"battle-{CTS}-11"

    def forfeit_log_text(self, end=("|-message|Opponent forfeited.", "|win|" + NAME), room_id=FORFEIT_ROOM):
        """A closed-sheet battle the foe forfeits (or loses on its timer) with the bot's turn-1 choice sent: the text of
        its log (python/tests/support/data/cts_log_format2.jsonl is this log)."""
        self.make(fmt=CTS)
        self.feed(*self.closed_messages(room_id, upto=6))
        self.feed(room(list(end), room_id))
        return Path(self.tmp.name, f"{room_id}-{client.toid(NAME)}.jsonl").read_text(encoding="utf-8")

    def test_a_battle_that_ends_on_a_sent_choice_logs_it_as_pending_at_end(self):
        # HauptSession, 2026-10-14: the foe's forfeit or timer ends the battle on the bot's choice, sent and never
        # accepted: it goes to {"pending_at_end"} before {"end"}, no {"accepted"}; the log's first record names its
        # format
        ends = {"forfeit": ("|-message|Opponent forfeited.", "|win|" + NAME),
                "timer": ("|-message|Opponent lost due to inactivity.", "|win|" + NAME)}
        for n, (why, end) in enumerate(ends.items()):
            with self.subTest(why):
                room_id = f"battle-{CTS}-{20 + n}"
                records = [json.loads(line) for line in self.forfeit_log_text(end, room_id).splitlines()]
                played = self.chosen()[-1].split("|/choose ", 1)[1].rsplit("|", 1)[0]
                self.assertEqual(records[0], {"log_format": client.LOG_FORMAT})
                self.assertEqual(client.LOG_FORMAT, 2)
                end_at = records.index({"end": "|win|" + NAME})
                self.assertEqual(records[end_at - 1], {"pending_at_end": played})
                last_sent = max(k for k, r in enumerate(records) if "sent" in r)
                self.assertFalse([r for r in records[last_sent:] if "accepted" in r])
                self.assertEqual(sum("pending_at_end" in r for r in records), 1)

    def test_a_battle_that_ends_with_no_choice_open_logs_pending_at_end_null(self):
        self.make(fmt=CTS)
        closed = f"battle-{CTS}-12"
        self.feed(*self.closed_messages(closed, upto=6))
        self.feed(room(FIXTURE["messages"][6], closed))  # turn 1 is played: its choice accepted, no request yet
        self.feed(room(["|win|" + NAME], closed))
        records = self.battle(closed)
        end_at = records.index({"end": "|win|" + NAME})
        self.assertEqual(records[end_at - 1], {"pending_at_end": None})
        last_sent = max(k for k, r in enumerate(records) if "sent" in r)
        self.assertTrue([r for r in records[last_sent:] if "accepted" in r])

    def test_pending_at_end_changes_the_log_only(self):
        # HauptSession's condition: the same decisions, the same choices sent; the log has the new records only
        new = self.forfeit_log_text(room_id=f"battle-{CTS}-13")
        sent_new = list(self.sent)
        real = pkmn_arena._Battle.write

        def old_write(b, record):
            if "log_format" not in record and "pending_at_end" not in record:
                real(b, record)
        self.tmp = tempfile.TemporaryDirectory()  # the same room again (its particles are seeded by it), a new log
        self.addCleanup(self.tmp.cleanup)
        with mock.patch.object(pkmn_arena._Battle, "write", old_write):
            old = self.forfeit_log_text(room_id=f"battle-{CTS}-13")
        self.assertEqual(self.sent, sent_new)
        new = [json.loads(line) for line in new.splitlines()]
        self.assertEqual([r for r in new if "log_format" not in r and "pending_at_end" not in r],
                         [json.loads(line) for line in old.splitlines()])
        self.assertEqual(len(new) - len(old.splitlines()), 2)

    def test_a_battle_that_fell_back_writes_no_pending_at_end(self):
        tables = data.load(kind="pool")
        prior = cts.SetPrior(tables, [s for s in teams._paste(FIXTURE["foe_team"]) if s["species"] != "Farigiraf"])
        self.make(fmt=CTS, prior=prior)
        closed = f"battle-{CTS}-14"
        self.feed(*self.closed_messages(closed), room(["|win|" + NAME], closed))
        records = self.battle(closed)
        self.assertIn("fallback", " ".join(map(json.dumps, records)))
        self.assertFalse([r for r in records if "pending_at_end" in r])

    def test_the_format_2_fixture_is_the_bots_own_log(self):
        # The fixtures of LogReplay's two formats (test_live_cts, Search's ko_check): format 2 is this log, format 1
        # the same without its {"log_format"} and {"pending_at_end"} records
        fixtures = data.ROOT / "python" / "tests" / "support" / "data"
        text = self.forfeit_log_text()
        self.assertEqual(text, (fixtures / "cts_log_format2.jsonl").read_text(encoding="utf-8"))
        old = [line for line in text.splitlines()
               if not (line.startswith('{"log_format"') or line.startswith('{"pending_at_end"'))]
        self.assertEqual("\n".join(old) + "\n", (fixtures / "cts_log_format1.jsonl").read_text(encoding="utf-8"))

    def test_a_random_closed_sheet_battle_plays_its_pool_team_over_the_particles(self):
        self.make(team=False, pool=[teams.text("B"), FIXTURE["team"]], fmt=CTS)
        rnd = f"battle-{CTS}random-9"
        self.feed(*self.closed_messages(rnd))
        sent = self.chosen()
        self.assertEqual(len(sent), 2)
        self.assertNotIn("default", " ".join(sent))
        self.assertTrue(self.bot.battles[rnd].game.closed)

    def test_the_search_warms_up_before_the_first_battle(self):
        # HauptSession, 2026-10-14: the first team preview of the 2e deploy missed its deadline (2.007 s, JAX compiling);
        # the bot decides a warm-up through its search before it accepts a battle (test_pkmn_arena_net: with JAX)
        from duoforge_live import search as live_search
        search = SimpleNamespace(searcher=SimpleNamespace(s=cts.PARTICLES), close=lambda: None)
        for fmt, worlds in ((CTS, cts.PARTICLES), (OTS, None)):
            with self.subTest(fmt), mock.patch.object(live_search, "warm_up",
                                                      return_value={"team": 1.5, "turn": 0.5}) as warm:
                self.make(fmt=fmt, search=search)
                self.assertEqual(self.bot.warm_up(), {"team": 1.5, "turn": 0.5})
                warm.assert_called_once_with(search, self.bot.policy, worlds)
                self.assertEqual(self.run_log()["warm_up"], {"team": 1.5, "turn": 0.5})
        with mock.patch.object(live_search, "warm_up", side_effect=RuntimeError("the search's warm-up failed: x")):
            self.make(fmt=CTS, search=search)
            with self.assertRaisesRegex(RuntimeError, "warm-up failed"):
                self.bot.warm_up()
        self.make(fmt=CTS)
        self.assertIsNone(self.bot.warm_up())  # raw play: nothing to compile ahead
        self.assertNotIn("warm_up", self.run_log())

    def test_the_command_line_warms_up_before_it_connects(self):
        from duoforge_live import arena
        order = []
        team = Path(self.tmp.name, "team.txt")
        team.write_text(FIXTURE["team"], encoding="utf-8")
        logs = Path(self.tmp.name, "logs")
        argv = ["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--team", str(team), "--log-dir",
                str(logs)]
        with mock.patch.object(arena, "provenance", return_value={"commit": "8c4fe662", "dirty": False}), \
                mock.patch.object(cli.policy, "load", return_value=FakePolicy()), \
                mock.patch.object(cli.data, "for_checkpoint", return_value=data.load(kind="closure")), \
                mock.patch.object(pkmn_arena, "check_teams"), \
                mock.patch.object(pkmn_arena.ArenaBot, "warm_up", lambda bot: order.append("warm_up")), \
                mock.patch.object(pkmn_arena.ArenaBot, "run", lambda bot: order.append("run") or asyncio.sleep(0)):
            cli.main(argv)
        self.assertEqual(order, ["warm_up", "run"])

    def test_closed_sheets_need_tables_the_set_table_reads_and_one_particle_per_world(self):
        with self.assertRaisesRegex(ValueError, "set table"):
            self.make(fmt=CTS, kind="closure")
        with self.assertRaisesRegex(ValueError, f"8 worlds.*{cts.PARTICLES} particles"):
            self.make(fmt=CTS, search=SimpleNamespace(searcher=SimpleNamespace(s=8), close=lambda: None))

    def test_a_battle_of_another_format_falls_back(self):
        self.make()
        other = "battle-gen9vgc2025regh-5"
        self.feed(room(["|init|battle"], other), room(FIXTURE["messages"][2], other))
        self.assertEqual(self.chosen(), [f"{other}|/choose default|{request_of(2)['rqid']}"])
        self.assertEqual(self.run_log()["fallback_battles"], {"format": 1})

    def test_missing_open_sheets_fall_back_in_time(self):
        self.make()
        self.feed(*[room([l for l in m if not l.startswith("|showteam|")]) for m in [["|init|battle"]] +
                    FIXTURE["messages"][:3]])
        self.assertEqual(self.chosen(), [])
        self.clock.now += pkmn_arena.SHEET_WAIT + 1
        with contextlib.redirect_stderr(self.stderr):
            asyncio.run(self.bot.tick())
        self.assertEqual(self.chosen(), [f"{ROOM}|/choose default|{request_of(2)['rqid']}"])
        self.assertEqual(self.run_log()["fallback_battles"], {"no_open_sheets": 1})

    def test_a_tracker_stop_falls_back_for_the_rest_of_the_battle(self):
        self.make()
        self.feed(*battle_messages(upto=5))
        self.take()
        self.feed(room(["|-futureline|p1a: Ceruledge"]))  # a line the tracker does not know
        self.feed(room(FIXTURE["messages"][5]))
        self.assertEqual(self.chosen(), [f"{ROOM}|/choose default|{request_of(5)['rqid']}"])
        self.feed(*[room(m) for m in FIXTURE["messages"][6:8]])
        self.assertEqual(self.chosen(), [f"{ROOM}|/choose default|{request_of(7)['rqid']}"])
        log = self.run_log()
        self.assertEqual(sum(log["fallback_battles"].values()), 1)
        self.assertEqual(sum(log["fallback_decisions"].values()), 2)
        self.assertTrue(any("fallback" in r and "detail" in r for r in self.battle()))

    def test_a_policy_error_answers_the_open_request_with_default(self):
        self.make(policy=RaisingPolicy())
        self.feed(*battle_messages(upto=6))
        sent = self.chosen()
        self.assertTrue(sent[0].startswith(f"{ROOM}|/choose team "))  # the team head still works
        self.assertEqual(sent[1:], [f"{ROOM}|/choose default|{request_of(5)['rqid']}"])
        self.assertEqual(self.run_log()["fallback_battles"], {"error:RuntimeError": 1})

    def test_refused_choices_retry_the_next_best_then_default(self):
        self.make(max_retries=2)
        self.feed(*battle_messages(upto=6))
        first = self.chosen()[-1]
        rqid = request_of(5)["rqid"]
        seen = [first]
        for _ in range(2):
            self.feed(room(["|error|[Invalid choice] Can't move: no."]))
            (again,) = self.take()
            self.assertTrue(again.endswith(f"|{rqid}") and again not in seen, again)
            seen.append(again)
        self.feed(room(["|error|[Invalid choice] Can't move: no."]))  # the third refusal: the server picks
        self.assertEqual(self.take(), [f"{ROOM}|/choose default|{rqid}"])
        log = self.run_log()
        self.assertEqual(log["counts"]["rejected_choices"], 3)
        self.assertEqual(log["fallback_battles"], {"rejections": 1})
        self.assertEqual(log["fallback_decisions"], {"rejections": 1})

    def test_a_decision_past_the_deadline_is_defaulted_and_blocks_no_second_decision(self):
        policy = BlockingPolicy()
        self.make(policy=policy, deadline=0.05)
        other = f"battle-{OTS}-8"

        async def go():
            for m in battle_messages(upto=6):
                await self.bot.handle(m)
            # the next battle while the late decision still runs: it never runs beside it
            for m in battle_messages(other, upto=6):
                await self.bot.handle(m)
            policy.release.set()
            await asyncio.wrap_future(self.bot._worker)
        with contextlib.redirect_stderr(self.stderr):
            asyncio.run(go())
        sent = self.chosen()
        self.assertIn(f"{ROOM}|/choose default|{request_of(5)['rqid']}", sent)
        self.assertIn(f"{other}|/choose default|{request_of(5)['rqid']}", sent)
        log = self.run_log()
        self.assertEqual(log["counts"]["deadline_misses"], 1)
        self.assertEqual(log["fallback_battles"], {"deadline": 1, "policy_busy": 1})

    def test_an_invalid_default_is_counted_not_retried(self):
        self.make(fmt=CTS)
        cts = f"battle-{CTS}-3"
        self.feed(room(["|init|battle"], cts), room(FIXTURE["messages"][2], cts))
        self.take()
        self.feed(room(["|error|[Invalid choice] Can't choose: nope"], cts))
        self.assertEqual(self.take(), [])
        self.assertEqual(self.run_log()["counts"]["default_rejected"], 1)

    def test_the_bot_never_forfeits(self):
        self.make()
        b = self.bot._open(ROOM)
        with contextlib.redirect_stderr(self.stderr):
            asyncio.run(self.bot._forfeit(b, client.INTERNAL, "test"))
        self.assertFalse([s for s in self.sent if "/forfeit" in s or client.INTERNAL in s])
        self.assertEqual(b.fallback, "forfeit")

    # ------------------------------------------------------------------ reconnect
    def replay(self, upto):
        """The battle's log as the server sends it again after a reconnect (no requests), then the open request."""
        lines = ["|init|battle", f"|title|{NAME} vs. Opponent", "|j|☆Opponent"]
        lines += [l for m in FIXTURE["messages"][:upto] for l in m if not l.startswith("|request|")]
        return [room(lines)]

    def test_a_reconnect_answers_the_open_request_again(self):
        open_request = room(FIXTURE["messages"][5])
        first = LOGIN + battle_messages(upto=6)
        second = LOGIN + self.replay(6) + [open_request] + [room(m) for m in FIXTURE["messages"][6:8]] + \
            [room(["|win|" + NAME])]
        self.make(connections=[(first, 1006), (second, 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        rq = request_of(5)["rqid"]
        self.assertEqual(chosen[1], chosen[2])  # the same choice again for the open request
        self.assertTrue(chosen[2].endswith(f"|{rq}"))
        self.assertTrue(chosen[3].endswith(f"|{request_of(7)['rqid']}") and "default" not in chosen[3])
        log = self.run_log()
        self.assertEqual(log["fallback_battles"], {})
        self.assertEqual(log["counts"]["wins"], 1)

    def test_a_replay_with_new_timestamps_resyncs(self):
        # The arena's replay gives every |t:| line the time of the replay (live, 2026-10-13, #455): a timestamp is
        # no battle line, so the resync must not compare it
        def stamped(messages, t):
            return [[f"|t:|{t + k}"] + m for k, m in enumerate(messages)]
        stamped_fixture = stamped(FIXTURE["messages"][:6], 1791847600)
        first = LOGIN + [room(["|init|battle", f"|title|{NAME} vs. Opponent", "|j|☆Opponent"])] + \
            [room(m) for m in stamped_fixture]
        lines = ["|init|battle", f"|title|{NAME} vs. Opponent", "|j|☆Opponent"]
        lines += [l for m in stamped(FIXTURE["messages"][:6], 0) for l in m
                  if not l.startswith("|request|")]
        replay = [room([l if not l.startswith("|t:|") else "|t:|1791847914" for l in lines])]
        second = LOGIN + replay + [room(FIXTURE["messages"][5])] + [room(m) for m in FIXTURE["messages"][6:8]] + \
            [room(["|win|" + NAME])]
        self.make(connections=[(first, 1006), (second, 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        self.assertTrue(chosen[-1].endswith(f"|{request_of(7)['rqid']}") and "default" not in chosen[-1], chosen)
        self.assertEqual(self.run_log()["fallback_battles"], {})

    def test_a_stamped_replay_with_a_different_battle_line_still_falls_back(self):
        # ignoring |t:| must not ignore the battle lines around it
        stamped = [[f"|t:|{1791847600 + k}"] + m for k, m in enumerate(FIXTURE["messages"][:6])]
        first = LOGIN + [room(["|init|battle", f"|title|{NAME} vs. Opponent", "|j|☆Opponent"])] + \
            [room(m) for m in stamped]
        lines = ["|init|battle", f"|title|{NAME} vs. Opponent", "|j|☆Opponent"]
        lines += ["|t:|1791847914" if l.startswith("|t:|") else
                  l.replace("Grimmsnarl, L50, M|100/100", "Grimmsnarl, L50, M|90/100")
                  for m in stamped for l in m if not l.startswith("|request|")]
        self.make(connections=[(first, 1006), (LOGIN + [room(lines), room(FIXTURE["messages"][5])], 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        self.assertEqual(chosen[-1], f"{ROOM}|/choose default|{request_of(5)['rqid']}")
        self.assertEqual(self.run_log()["fallback_battles"], {"reconnect": 1})

    def test_a_replay_that_differs_falls_back(self):
        lines = self.replay(6)[0].split("\n")
        changed = [lines[0]] + [l.replace("Grimmsnarl, L50, M|100/100", "Grimmsnarl, L50, M|90/100") for l in lines[1:]]
        self.make(connections=[(LOGIN + battle_messages(upto=6), 1006),
                               (LOGIN + ["\n".join(changed), room(FIXTURE["messages"][5])], 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        self.assertEqual(chosen[-1], f"{ROOM}|/choose default|{request_of(5)['rqid']}")
        self.assertEqual(self.run_log()["fallback_battles"], {"reconnect": 1})

    def test_a_choice_the_server_holds_is_not_sent_again(self):
        # Showdown sends the open request again after the log, with |sentchoice| when it holds the choice already
        held = room(FIXTURE["messages"][5] + ["|sentchoice|move 1, move 1"])
        self.make(connections=[(LOGIN + battle_messages(upto=6), 1006),
                               (LOGIN + self.replay(6) + [held] + [room(m) for m in FIXTURE["messages"][6:8]], 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        self.assertEqual(len(chosen), 3)  # team, turn 1, and turn 2 after the reconnect: nothing sent twice
        self.assertTrue(chosen[2].endswith(f"|{request_of(7)['rqid']}") and "default" not in chosen[2])
        self.assertEqual(self.run_log()["fallback_battles"], {})

    def test_a_drop_while_choosing_is_no_fallback(self):
        rq = request_of(5)["rqid"]
        self.make(connections=[(LOGIN + battle_messages(upto=6), 1006, f"|{rq}"),
                               (LOGIN + self.replay(6) + [room(FIXTURE["messages"][5])], 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        self.assertEqual(len(chosen), 2)  # the team, then the turn's choice after the reconnect
        self.assertTrue(chosen[1].endswith(f"|{rq}") and "default" not in chosen[1], chosen)
        log = self.run_log()
        self.assertEqual(log["fallback_battles"], {})
        self.assertEqual(log["closes"], {"1006": 1, "4001": 1})

    def test_a_request_that_is_no_json_object_is_answered_with_default(self):
        self.make()
        self.feed(*battle_messages(upto=5))
        self.take()
        self.feed(room(["|request|{not json"]))
        self.assertEqual(self.chosen(), [f"{ROOM}|/choose default"])
        self.feed(room(["|request|null"]))  # each such request gets its own default
        self.assertEqual(self.chosen(), [f"{ROOM}|/choose default"])
        self.assertEqual(self.run_log()["fallback_battles"], {"request": 1})

    def test_a_reconnect_before_a_random_battles_first_request(self):
        rnd = f"battle-{OTS}random-9"
        replay = room(["|init|battle"] + [l for m in FIXTURE["messages"][:2] for l in m], rnd)
        self.make(team=False, pool=[FIXTURE["team"]],
                  connections=[(LOGIN + battle_messages(rnd, upto=2), 1006),
                               (LOGIN + [replay] + [room(m, rnd) for m in FIXTURE["messages"][2:6]], 4001)])
        self.run_bot()
        chosen = [s for s in self.sent if "/choose" in s]
        self.assertEqual(len(chosen), 2)
        self.assertNotIn("default", " ".join(chosen))
        self.assertEqual(self.run_log()["fallback_battles"], {})

    # ------------------------------------------------------------------ random-team ladder
    def test_a_random_team_battle_takes_its_team_from_the_pool(self):
        self.make(team=False, pool=[teams.text("B"), FIXTURE["team"]])
        rnd = f"battle-{OTS}random-9"
        self.feed(*battle_messages(rnd, upto=6))
        sent = self.chosen()
        self.assertEqual(len(sent), 2)
        self.assertNotIn("default", " ".join(sent))
        self.assertEqual(self.bot.battles[rnd].game.tracker.own_sheets, data.load().team(FIXTURE["team"]))

    def test_a_random_team_outside_the_pool_falls_back(self):
        self.make(team=False, pool=[teams.text("B")])
        rnd = f"battle-{OTS}random-9"
        self.feed(*battle_messages(rnd, upto=6))
        self.assertEqual(self.chosen(), [f"{rnd}|/choose default|{request_of(2)['rqid']}",
                                         f"{rnd}|/choose default|{request_of(5)['rqid']}"])
        self.assertEqual(self.run_log()["fallback_battles"], {"random_team_unknown": 1})

    def test_request_matching_compares_sets_not_order(self):
        pokemon = request_of(2)["side"]["pokemon"]
        self.assertTrue(pkmn_arena.request_matches(list(reversed(pokemon)), FIXTURE["team"]))
        self.assertFalse(pkmn_arena.request_matches(pokemon, teams.text("B")))

    def test_the_run_log_names_how_the_checkpoints_read_the_tables(self):
        check = {"checkpoint": "aa" * 32, "library": "bb" * 32, "ids": "carried over"}
        tables = data.load()
        tables.checkpoint_check = check
        bot = pkmn_arena.ArenaBot(NAME, tables, FakePolicy(), self.tmp.name, OTS, team_text=FIXTURE["team"],
                                  foe_check=check)
        self.addCleanup(bot.close)
        bot.run_log.write()
        log = json.loads(bot.run_log.path.read_text(encoding="utf-8"))
        self.assertEqual(log["tables"], {"network": check, "foe_net": check})

    def test_read_pool(self):
        path = Path(self.tmp.name, "pool.txt")
        path.write_text(f"=== [{OTS}] one ===\n\n{FIXTURE['team']}\n=== [{OTS}] two ===\n\n{teams.text('B')}",
                        encoding="utf-8")
        pool = pkmn_arena.read_pool(path)
        self.assertEqual(len(pool), 2)
        self.assertEqual(data.load().team(pool[1]), data.load().team(teams.text("B")))


class CheckpointDataTest(unittest.TestCase):
    """The live start's table check (checkpoint.check_data through data.for_config): the same fingerprint, or another
    one whose embedded ids carry over to the current library's tables; the tracker always reads today's tables."""

    @classmethod
    def setUpClass(cls):
        import duoforge
        from duoforge import _layout
        from duoforge_learn import checkpoint
        with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            cls.fingerprint, cls.ids = ctx.fingerprint().hex(), checkpoint.ids_of(ctx)

    def config(self, fingerprint, ids):
        return {"format": 2, "data": {"kind": "pool", "fingerprint": fingerprint}, "ids": ids}

    def test_the_same_fingerprint_is_accepted(self):
        tables = data.for_config(self.config(self.fingerprint, None))
        self.assertEqual(tables.checkpoint_check,
                         {"checkpoint": self.fingerprint, "library": self.fingerprint, "ids": "same tables"})

    def test_another_fingerprint_whose_ids_carry_over_is_accepted_and_named(self):
        older = {kind: names[:max(1, len(names) - 3)] for kind, names in self.ids.items()}  # tables that grew since
        tables = data.for_config(self.config("ab" * 32, older))
        self.assertEqual(tables.kind, "pool")
        self.assertEqual(tables.checkpoint_check, {"checkpoint": "ab" * 32, "library": self.fingerprint,
                                                   "ids": "carried over"})
        self.assertEqual(tables.context().fingerprint().hex(), self.fingerprint)  # today's tables

    def test_another_fingerprint_with_a_moved_row_is_refused(self):
        moved = {kind: list(names) for kind, names in self.ids.items()}
        moved["move"][1], moved["move"][2] = moved["move"][2], moved["move"][1]
        with self.assertRaisesRegex(ValueError, "fingerprint .* do not carry over.*move id 1"):
            data.for_config(self.config("ab" * 32, moved))
        gone = {kind: list(names) + (["extra"] if kind == "item" else []) for kind, names in self.ids.items()}
        with self.assertRaisesRegex(ValueError, "item id .* is gone"):
            data.for_config(self.config("ab" * 32, gone))
        with self.assertRaisesRegex(ValueError, "fingerprint .* no id tables"):
            data.for_config(self.config("ab" * 32, None))


class CommandLineTest(unittest.TestCase):
    def run_main(self, argv, env):
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as stop:
            for key in (pkmn_arena.NAME_ENV, pkmn_arena.TOKEN_ENV):
                if key not in env:
                    os.environ.pop(key, None)
            cli.main(argv)
        return stop.exception, err.getvalue()

    def test_arena_mode_refuses_bad_credentials_without_showing_the_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = ["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--log-dir", tmp]
            cases = [({pkmn_arena.TOKEN_ENV: TOKEN}, base, pkmn_arena.NAME_ENV),
                     ({pkmn_arena.NAME_ENV: NAME}, base, "is not set"),
                     ({pkmn_arena.NAME_ENV: NAME, pkmn_arena.TOKEN_ENV: "secret|x"}, base, "no arena token"),
                     (ENV, base + ["--team", TOKEN], "on the command line"),
                     ({pkmn_arena.NAME_ENV: "x", pkmn_arena.TOKEN_ENV: TOKEN}, base, pkmn_arena.NAME_ENV)]
            for env, argv, message in cases:
                stop, err = self.run_main(argv, env)
                self.assertEqual(stop.code, 2, (env, argv))
                self.assertIn(message, err)
                self.assertNotIn(TOKEN, err)
                self.assertNotIn("secret|x", err)

    def test_arena_mode_takes_no_token_option_and_a_registered_format(self):
        for argv in (["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--token", TOKEN],
                     ["--server", "arena", "--format", "gen9vgc2025regh", "--checkpoint", "x.npz"]):
            stop, err = self.run_main(argv, ENV)
            self.assertEqual(stop.code, 2)
            self.assertNotIn(TOKEN, err)

    def test_the_foe_net_needs_the_honest_search(self):
        for extra in (["--foe-net", "x.npz"], ["--no-foe-net"], ["--foe-net-sha256", "0" * 64]):
            with self.subTest(extra=extra):
                stop, err = self.run_main(["--server", "arena", "--format", OTS, "--checkpoint", "x.npz"] + extra, ENV)
                self.assertEqual(stop.code, 2)
                self.assertIn("--search honest", err)

    def test_the_ab_test_is_refused_without_its_conditions(self):
        # --ab-root-rule (owner, 2026-10-14): the honest search on the --team's battles, the pinned foe model, and
        # --ab-seed only with it; every refusal before anything loads.
        base = ["--server", "arena", "--format", OTS, "--checkpoint", "x.npz"]
        cases = [(["--ab-seed", "3"], "--ab-seed"),
                 (["--ab-root-rule", "--team", __file__], "--search honest"),
                 (["--ab-root-rule", "--search", "honest"], "--team"),
                 (["--ab-root-rule", "--search", "honest", "--team", __file__, "--team-pool", __file__], "--team-pool"),
                 (["--ab-root-rule", "--search", "honest", "--team", __file__, "--no-foe-net"], "pinned foe model"),
                 (["--ab-root-rule", "--search", "honest", "--team", __file__, "--foe-net", "y.npz",
                   "--foe-net-sha256", "0" * 64], "pinned foe model")]
        for extra, message in cases:
            with self.subTest(extra=extra), mock.patch.object(cli.policy, "load") as loaded:
                stop, err = self.run_main(base + extra, ENV)
                loaded.assert_not_called()
                self.assertEqual(stop.code, 2)
                self.assertIn(message, err)

    def test_a_pin_needs_a_foe_net_to_pin(self):
        # Owner 2026-10-12: the pinned BC6 is the honest search's foe model by default (its path from --foe-net or
        # $DUOFORGE_FOE_NET); a pin with --no-foe-net pins nothing and is refused.
        stop, err = self.run_main(["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--search", "honest",
                                   "--no-foe-net", "--foe-net-sha256", "0" * 64], ENV)
        self.assertEqual(stop.code, 2)
        self.assertIn("--foe-net", err)

    def test_the_honest_search_needs_its_foe_model_configured(self):
        from duoforge_live import search
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--search", "honest",
                    "--team", __file__, "--log-dir", tmp]
            with mock.patch.object(cli.policy, "load") as loaded:
                stop, err = self.run_main(argv, {**ENV, search.FOE_NET_ENV: ""})
            loaded.assert_not_called()
        self.assertEqual(stop.code, 2)
        self.assertIn("not configured", err)

    def test_arena_logs_never_go_into_the_repository(self):
        argv = ["--server", "arena", "--format", OTS, "--checkpoint", "x.npz", "--log-dir",
                str(data.ROOT / "build" / "arena-logs")]
        stop, err = self.run_main(argv, ENV)
        self.assertEqual(stop.code, 2)
        self.assertIn("inside the repository", err)

    def test_the_showdown_mode_refuses_the_arena_host(self):
        for argv in (["--checkpoint", "x.npz", "--name", "DuoForgeBot", "--server", pkmn_arena.URL],
                     ["--ser", "arena", "--checkpoint", "x.npz", "--name", "DuoForgeBot"]):
            stop, err = self.run_main(argv, ENV)
            self.assertEqual(stop.code, 2)
            self.assertIn("--server arena", err)

    def test_the_showdown_mode_refuses_the_arenas_old_address(self):
        # the arena moved to vgc.bot (2026-10-15): its old address is no Showdown server to fall back to either
        stop, err = self.run_main(["--checkpoint", "x.npz", "--name", "DuoForgeBot", "--server",
                                   "wss://vgc.ellep.dev/showdown/websocket"], ENV)
        self.assertEqual(stop.code, 2)
        self.assertIn("vgc.ellep.dev was PKMN Arena's address before it moved to vgc.bot: use --server arena", err)

    def test_no_mode_echoes_a_token_on_the_command_line(self):
        for argv in (["--checkpoint", "x.npz", "--name", "DuoForgeBot", "--password", TOKEN],
                     ["--serv=arena", "--token", "pka_other"]):
            stop, err = self.run_main(argv, ENV)
            self.assertEqual(stop.code, 2)
            self.assertIn("on the command line", err)
            self.assertFalse(TOKEN in err or "pka_other" in err)

    def test_the_official_server_refusal_is_unchanged(self):
        stop, _ = self.run_main(["--checkpoint", "x.npz", "--name", "DuoForgeBot", "--challenge", "chris"], ENV)
        self.assertEqual(stop.code, 2)
        self.assertTrue(client.official(client.OFFICIAL_SERVER))


if __name__ == "__main__":
    unittest.main()
