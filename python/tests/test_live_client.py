"""Part of duoforge.python.live_unit: the live client's protocol with a fake server.

The battle stream is python/tests/data/live_stream_ab.json: the first ten
messages that the pinned Showdown sends p1 in m5_real_ab_1 (Team A, members
reordered, against Team B), written by tools/reference/ps_client.js. Spec
sections 6 and 7: challenges and refusals, open team sheets, invalid choices,
errors, Bo3, and the etiquette.
"""
import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from duoforge_live import client, data, teams

FIXTURE = json.loads((data.ROOT / "python" / "tests" / "data" / "live_stream_ab.json").read_text(encoding="utf-8"))
ROOM = "battle-gen9championsvgc2026regmc-1"
FOE = "chris"


class FakePolicy:
    """Ranks in index order (every choice equally likely): the client is under test, not the network."""
    encoder = 2

    def rank_pairs(self, observation, obs_part, slot_part, pair_mask):
        n = pair_mask.shape[1]
        allowed = [i for i in range(pair_mask.size) if pair_mask.reshape(-1)[i]]
        return [(i // n, i % n, 1.0 / len(allowed)) for i in allowed]

    def rank_teams(self, observation, obs_part):
        return [(i, 1.0 / 360) for i in range(360)]


class FakeServer:
    """What the bot sends, and the lines the test feeds it."""

    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)

    def take(self):
        out, self.sent = self.sent, []
        return out


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def room(lines, room_id=ROOM):
    return ">" + room_id + "\n" + "\n".join(lines)


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = FakeServer()
        self.clock = Clock()
        self.logins = []

        def login(name, challstr, password):
            self.logins.append((name, challstr, password))
            return "ASSERTION"
        self.config = client.Config(name="DuoForgeBot", team="A", log_dir=self.tmp.name, team_link=None)
        self.bot = client.Bot(self.config, data.load(), FakePolicy(), login=login, clock=self.clock,
                              team_texts={"A": FIXTURE["team"], "B": teams.text("B")})
        self.bot.connection = self.server

    def tearDown(self):
        self.bot.close()
        self.tmp.cleanup()

    def feed(self, message):
        asyncio.run(self.bot.handle(message))

    def tick(self):
        asyncio.run(self.bot.tick())

    def challenge(self, fmt="gen9championsvgc2026regmc", user=FOE):
        # As the pin sends it (server/ladders-challenges.ts): a PM from the challenger to the bot.
        self.feed(f"|pm| {user}| DuoForgeBot|/challenge {fmt}|{fmt}||Accept|Reject")

    def start_battle(self, upto=4):
        """Accepts a challenge and feeds the stream up to message `upto` (the showteam lines are message 3)."""
        self.challenge()
        self.server.take()
        self.feed(room(["|init|battle", "|title|DuoForgeBot vs. chris", "|j|☆chris"]))
        for lines in FIXTURE["messages"][:upto]:
            self.feed(room(lines))

    def test_login_guest_and_registered(self):
        os.environ.pop("DUOFORGE_PS_PASSWORD", None)
        self.feed("|challstr|4|abc")
        self.assertEqual(self.logins[-1], ("DuoForgeBot", "4|abc", None))
        self.assertIn("|/trn DuoForgeBot,0,ASSERTION", self.server.take())
        os.environ["DUOFORGE_PS_PASSWORD"] = "secret-pw"
        try:
            self.feed("|challstr|4|def")
            self.assertEqual(self.logins[-1][2], "secret-pw")
            self.start_battle()
            for name in os.listdir(self.tmp.name):
                self.assertNotIn("secret-pw", Path(self.tmp.name, name).read_text(encoding="utf-8"))
            self.assertFalse(any("secret-pw" in s for s in self.server.take()))
        finally:
            del os.environ["DUOFORGE_PS_PASSWORD"]

    def test_challenge_formats(self):
        for fmt in ("gen9championsvgc2026regmc", "gen9championsvgc2026regmcbo3"):
            self.bot.busy = None
            self.challenge(fmt)
            sent = self.server.take()
            self.assertEqual(sent[0], "|/utm " + teams.pack(FIXTURE["team"]))
            self.assertEqual(sent[1], "|/accept chris")
        self.bot.busy = None
        self.challenge("gen9ou")
        self.assertEqual(self.server.take(), ["|/reject chris", "|/pm chris, " + client.WRONG_FORMAT])
        self.assertEqual(client.WRONG_FORMAT, "Sorry, I only play [Gen 9 Champions] VGC 2026 Reg M-C, Bo1 or Bo3.")

    def test_busy_rejects(self):
        self.start_battle()
        self.challenge(user="other")
        self.assertEqual(self.server.take()[-2:], ["|/reject other", "|/pm other, " + client.BUSY])
        self.assertEqual(client.BUSY, "Sorry, I'm in a battle right now. Please challenge me again in a few minutes.")

    def test_sheets_flow(self):
        self.challenge()
        self.server.take()
        self.feed(room(["|init|battle"]))
        self.assertIn(f"{ROOM}|{client.GREETING}", self.server.take())
        self.assertEqual(client.GREETING, "Hi! DuoForge bot here, good luck!")
        self.feed(room(FIXTURE["messages"][0]))
        self.feed(room(FIXTURE["messages"][1]))  # ends with the otsrequest prompt
        self.assertIn(f"{ROOM}|/acceptopenteamsheets", self.server.take())
        self.feed(room(FIXTURE["messages"][2]))  # the team preview request: no choice before the sheets
        self.assertFalse([s for s in self.server.take() if "/choose" in s])
        self.feed(room(FIXTURE["messages"][3]))  # both |showteam|
        sent = self.server.take()
        self.assertTrue(any(s.startswith(f"{ROOM}|/choose team ") and s.endswith("|1") for s in sent), sent)

    def test_sheets_denied_or_late(self):
        for how in ("denied", "late", "other team"):
            self.tearDown()  # a fresh bot and log directory for each case
            self.setUp()
            self.challenge()
            self.server.take()
            self.feed(room(["|init|battle"] + FIXTURE["messages"][0] + FIXTURE["messages"][1]))
            self.feed(room(FIXTURE["messages"][2]))
            if how == "denied":
                self.feed(room(["chris rejected open team sheets."]))
            elif how == "late":
                self.clock.now += 59
                self.tick()
                self.assertFalse([s for s in self.server.take() if "/forfeit" in s])
                self.clock.now += 2
                self.tick()
            else:
                other = FIXTURE["messages"][3][1].replace("Leftovers", "LifeOrb")
                self.feed(room([FIXTURE["messages"][3][0], other]))
            sent = self.server.take()
            self.assertIn(f"{ROOM}|{client.SHEETS}", sent, how)
            self.assertEqual(sent[-1], f"{ROOM}|/forfeit", how)
        self.assertEqual(client.SHEETS, "I'm a research bot and only play DuoForge Team A or B with open team sheets, "
                                        "so I'm forfeiting this game.")

    def test_invalid_choice_next_best(self):
        self.start_battle(upto=6)  # the first move request (rqid 3) and its update
        first = [s for s in self.server.take() if "/choose" in s][-1]
        self.assertTrue(first.endswith("|3"), first)
        self.feed(room(["|error|[Invalid choice] Can't move: no."]))
        second = self.server.take()
        self.assertEqual(len(second), 1)
        self.assertNotEqual(second[0], first)
        self.assertTrue(second[0].endswith("|3"))
        for _ in range(62):
            self.feed(room(["|error|[Invalid choice] Can't move: no."]))
        self.assertFalse([s for s in self.server.take() if "/forfeit" in s])
        self.feed(room(["|error|[Invalid choice] Can't move: no."]))  # the 64th rejection
        self.assertEqual(self.server.take()[-2:], [f"{ROOM}|{client.INTERNAL}", f"{ROOM}|/forfeit"])
        self.assertEqual(client.INTERNAL, "Internal error on my side, sorry. Forfeiting.")

    def test_unavailable_choice_is_an_internal_error(self):
        self.start_battle(upto=6)
        self.server.take()
        self.feed(room(["|error|[Unavailable choice] Can't move: no."]))
        self.assertEqual(self.server.take()[-2:], [f"{ROOM}|{client.INTERNAL}", f"{ROOM}|/forfeit"])

    def test_chat_between_update_and_request(self):
        self.start_battle(upto=5)  # up to the move request's update (message 4)
        self.server.take()
        self.feed(room(["|c|☆chris|good luck", "|j|☆watcher"]))
        self.assertFalse([s for s in self.server.take() if "/choose" in s])
        self.feed(room(FIXTURE["messages"][5]))
        self.assertTrue([s for s in self.server.take() if "/choose" in s and s.endswith("|3")])

    def test_repeated_request_one_choice(self):
        self.start_battle(upto=6)
        self.server.take()
        self.feed(room(FIXTURE["messages"][5]))  # the same request again (a reconnect)
        self.assertFalse([s for s in self.server.take() if "/choose" in s])

    def test_unknown_line_forfeits_and_keeps_running(self):
        self.start_battle(upto=5)
        self.server.take()
        self.feed(room(["|-futureline|p1a: Ceruledge"]))
        self.assertEqual(self.server.take()[-2:], [f"{ROOM}|{client.INTERNAL}", f"{ROOM}|/forfeit"])
        self.feed(room(["|win|chris"]))
        self.assertIn(f"{ROOM}|gg", self.server.take())
        self.challenge(user="next")
        self.assertEqual(self.server.take()[-1], "|/accept next")

    def test_foe_forfeits_during_sheet_wait(self):
        self.challenge()
        self.server.take()
        self.feed(room(["|init|battle"] + FIXTURE["messages"][0] + FIXTURE["messages"][1]))
        self.feed(room(FIXTURE["messages"][2]))
        self.feed(room(["|win|DuoForgeBot"]))
        sent = self.server.take()
        self.assertIn(f"{ROOM}|gg", sent)
        self.assertFalse([s for s in sent if "/forfeit" in s])
        self.clock.now += 120
        self.tick()
        self.assertFalse([s for s in self.server.take() if "/forfeit" in s])
        self.assertIsNone(self.bot.busy)
        path = Path(self.tmp.name, ROOM + "-duoforgebot.jsonl")  # one file per room and bot: two bots can share a room
        log = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(log[-1], {"end": "|win|DuoForgeBot"})

    def test_bo3_series(self):
        series = "game-bestof3-gen9championsvgc2026regmcbo3-7"
        self.challenge("gen9championsvgc2026regmcbo3")
        self.server.take()
        self.feed(room(["|init|chat", "|title|[Gen 9 Champions] VGC 2026 Reg M-C (Bo3)"], series))
        game1 = "battle-gen9championsvgc2026regmcbo3-8"
        self.feed(room(["|init|battle"], game1))
        self.feed(room(["|win|chris"], game1))
        self.assertIn(f"{game1}|gg", self.server.take())
        self.assertIsNotNone(self.bot.busy)  # the series goes on
        prompt = ('|c|~|/uhtml controls,<div class="infobox"><p style="margin:6px">Are you ready for game 2, '
                  'DuoForgeBot?</p><p style="margin:6px"><button class="button notifying" name="send" '
                  f'value="/msgroom {series},/confirmready">I\'m ready!</button></p></div>')
        waiting = ('|c|~|/uhtml controls,<div class="infobox"><p style="margin:6px">Are you ready for game 2, '
                   'DuoForgeBot?</p><p style="margin:6px"><button class="button" disabled><i class="fa fa-check">'
                   '</i> I\'m ready!</button> &ndash; waiting for opponent...</p></div>')
        self.feed(room([prompt], series))
        self.assertEqual(self.server.take(), [f"{series}|/confirmready"])
        self.feed(room([waiting], series))  # the server shows the disabled button: no second confirm
        self.feed(room([prompt], series))  # the same game asked again: still one confirm
        self.assertEqual(self.server.take(), [])
        game2 = "battle-gen9championsvgc2026regmcbo3-9"
        self.feed(room(["|init|battle"] + FIXTURE["messages"][0] + FIXTURE["messages"][1], game2))
        self.feed(room(FIXTURE["messages"][2], game2))
        self.feed(room(FIXTURE["messages"][3], game2))
        self.assertTrue([s for s in self.server.take() if s.startswith(f"{game2}|/choose team ")])
        self.challenge(user="other")
        self.assertIn("|/reject other", self.server.take())
        self.feed(room(["|win|chris"], series))
        self.assertIsNone(self.bot.busy)

    def test_own_and_cancelled_challenges(self):
        # The bot's own challenge comes back as a PM from the bot; a removed one has no format: both are no
        # challenge to answer.
        self.feed("|pm| DuoForgeBot| chris|/challenge gen9championsvgc2026regmc|x||Accept|Reject")
        self.feed("|pm| chris| DuoForgeBot|/challenge")
        self.assertEqual(self.server.take(), [])

    def test_failed_accept_frees_the_bot(self):
        # The challenger cancelled before the accept (or the server refused the battle): no room opens. After
        # 30 seconds the bot takes challenges again.
        self.challenge()
        self.server.take()
        self.clock.now += 29
        self.tick()
        self.assertIsNotNone(self.bot.busy)
        self.clock.now += 2
        self.tick()
        self.assertIsNone(self.bot.busy)
        self.challenge(user="next")
        self.assertEqual(self.server.take()[-1], "|/accept next")

    def test_raw_conversion_error_forfeits(self):
        # The converter's ConversionError is a SystemExit: raised anywhere in a decision it still only forfeits.
        from duoforge_live.data import trace_to_c

        class Broken(FakePolicy):
            def rank_teams(self, observation, obs_part):
                raise trace_to_c.ConversionError("test", "a converter refusal")
        self.bot.policy = Broken()
        self.start_battle()
        self.assertEqual(self.server.take()[-2:], [f"{ROOM}|{client.INTERNAL}", f"{ROOM}|/forfeit"])

    def test_challenge_flag_refused_on_official_hosts(self):
        for server in ("wss://sim3.psim.us/showdown/websocket", "wss://play.pokemonshowdown.com/x"):
            with self.assertRaises(SystemExit):
                client.check_arguments(client.Config(name="DuoForgeBot", team="A", log_dir=self.tmp.name,
                                                     team_link=None, challenge="chris", server=server))
        client.check_arguments(client.Config(name="DuoForgeBot", team="A", log_dir=self.tmp.name, team_link=None,
                                             challenge="other", server="ws://localhost:8000/showdown/websocket"))

    def test_login_requests_name_the_bot(self):
        # The login server refuses Python's default User-Agent (403): every request names the bot.
        import io
        import urllib.request
        seen = []

        def fake_urlopen(request, data=None, timeout=None):
            seen.append(request)
            body = b"ASSERTION" if request.data is None else b']{"actionsuccess": true, "assertion": "A2"}'
            return io.BytesIO(body)
        real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            self.assertEqual(client.login("DuoForgeBot", "4|abc", None), "ASSERTION")
            self.assertEqual(client.login("DuoForgeBot", "4|abc", "pw"), "A2")
        finally:
            urllib.request.urlopen = real
        for request in seen:
            self.assertIsInstance(request, urllib.request.Request)
            self.assertIn("bot", request.get_header("User-agent").lower())

    def test_name_must_say_bot(self):
        with self.assertRaises(SystemExit):
            client.check_arguments(client.Config(name="Chris", team="A", log_dir=self.tmp.name, team_link=None))
        client.check_arguments(client.Config(name="DuoForgeBot", team="A", log_dir=self.tmp.name, team_link=None))


class GameTest(unittest.TestCase):
    def test_game_uses_the_policy_encoding(self):
        # A real Policy whose network reads only the own roster-0 present flag: the fixture's own roster 0 is
        # Ceruledge (present under both encoders), so take Team A in file order, whose roster 0 is Rillaboom
        # (forme 0, absent under encoder 1). The team ranking differs between encoder 1 and 2.
        import numpy as np
        from duoforge import features
        from duoforge_live.game import Game
        from duoforge_live.policy import Policy
        rng = np.random.default_rng(1)
        shapes = {"t1": (features.BASE_OBS_SIZE, 8), "t2": (8, 8), "option_torso": (8, 4),  # encoders 1 and 2
                  "option_features": (features.SLOT_FEATURES, 4), "option_out": (4, 2), "team": (8, 360),
                  "value": (8, 1)}
        params = {k: {"w": rng.normal(0, 1, s).astype(np.float32), "b": np.zeros(s[1], np.float32)}
                  for k, s in shapes.items()}
        params["t1"]["w"][:] = 0
        params["t1"]["w"][71, :] = 1.0  # the own roster-0 present flag (15 global, 8 side, 2 x 24 positions)
        ranked = []
        for encoder in (1, 2):
            game = Game(data.load(), Policy(params, encoder), teams.text("A"))
            for lines in FIXTURE["messages"][:4]:
                game.feed([line.replace("|p1|", "|p1|") for line in lines])
            ranked.append([c.probability for c in game.candidates()][:5])
        self.assertNotEqual(ranked[0], ranked[1])

    def test_main_refuses_bad_arguments(self):
        import contextlib
        from duoforge_live import __main__ as cli
        for argv in (["--checkpoint", "x.npz", "--name", "Chris"],
                     ["--checkpoint", "x.npz", "--name", "DuoForgeBot", "--challenge", "chris"]):
            with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(io.StringIO()):
                cli.main(argv)
            self.assertEqual(caught.exception.code, 2, argv)

    def test_team_table_is_the_learners(self):
        from duoforge_live import game
        from duoforge_learn.selfplay import TEAM_TABLE
        self.assertEqual([tuple(int(x) for x in t) for t in TEAM_TABLE], game.TEAM_TABLE)


if __name__ == "__main__":
    unittest.main()
