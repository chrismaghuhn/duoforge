"""The live client: websocket, login, challenges, battle rooms, Bo3 and etiquette.

Spec sections 6 and 7. The bot accepts challenges in the two formats only,
plays one battle (or Bo3 series) at a time, accepts open team sheets and
plays only against Team A or B. Every refusal is explicit: a PM, or a chat
message and a forfeit. The decisions come from game.Game; any error of the
tracker, the options or the policy (the converter's ConversionError, a
SystemExit, included) forfeits with the internal-error message and the bot
keeps running. The password is read from DUOFORGE_PS_PASSWORD only when a
login needs it; it is never logged.
"""
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import teams
from .data import trace_to_c
from .game import Game
from .tracker import ROOM_LINES, _kind

FORMATS = {"gen9championsvgc2026regmc": 1, "gen9championsvgc2026regmcbo3": 3}  # format id -> games in the set
OFFICIAL_SERVER = "wss://sim3.psim.us/showdown/websocket"
LOGIN_URL = "https://play.pokemonshowdown.com/action.php"
USER_AGENT = "DuoForgeBot/1 (research bot; github.com/chrismaghuhn/duoforge)"  # the default is refused (403)
SHEET_WAIT = 60.0  # seconds after the team preview request (the VGC timer gives 90)
ACCEPT_WAIT = 30.0  # seconds for the battle room after an accept; none comes when the challenger cancelled
MAX_REJECTIONS = 64

GREETING = "Hi! DuoForge bot here, good luck!"
GG = "gg"
WRONG_FORMAT = "Sorry, I only play [Gen 9 Champions] VGC 2026 Reg M-C, Bo1 or Bo3."
BUSY = "Sorry, I'm in a battle right now. Please challenge me again in a few minutes."
SHEETS = ("I'm a research bot and only play DuoForge Team A or B with open team sheets, "
          "so I'm forfeiting this game.")
INTERNAL = "Internal error on my side, sorry. Forfeiting."


@dataclass
class Config:
    name: str
    team: str  # "A", "B" or "random"
    log_dir: str
    team_link: str = None
    challenge: str = None  # local server only: challenge this user after login
    challenge_format: str = "gen9championsvgc2026regmc"
    server: str = OFFICIAL_SERVER


def toid(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def official(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return host.endswith("psim.us") or host.endswith("pokemonshowdown.com")


def _refuse(message):
    print(f"duoforge_live: {message}", file=sys.stderr)
    raise SystemExit(2)


def check_arguments(config):
    """SystemExit (status 2, the message on stderr) for a configuration the spec forbids."""
    if "bot" not in config.name.lower():
        _refuse(f"the name {config.name!r} must say that this is a bot (contain 'bot')")
    if config.team not in ("A", "B", "random"):
        _refuse(f"--team is A, B or random, not {config.team!r}")
    if config.challenge_format not in FORMATS:
        _refuse(f"--challenge-format is one of {sorted(FORMATS)}")
    if config.challenge and official(config.server):
        _refuse("--challenge is for a local server only, never the official one")


def login(name, challstr, password):
    """An assertion for /trn: a guest name without a password, else a registered one (action.php)."""
    if password is None:
        query = urllib.parse.urlencode({"act": "getassertion", "userid": toid(name), "challstr": challstr})
        request = urllib.request.Request(f"{LOGIN_URL}?{query}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as r:
            assertion = r.read().decode("utf-8").strip()
        if not assertion or assertion.startswith(";"):
            raise SystemExit(f"duoforge_live: the name {name!r} is registered; set DUOFORGE_PS_PASSWORD")
        return assertion
    body = urllib.parse.urlencode({"act": "login", "name": name, "pass": password, "challstr": challstr}).encode()
    request = urllib.request.Request(LOGIN_URL, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as r:
        text = r.read().decode("utf-8")
    reply = json.loads(text[1:] if text.startswith("]") else text)
    if not reply.get("actionsuccess") or not reply.get("assertion"):
        raise SystemExit(f"duoforge_live: the login of {name!r} failed")
    return reply["assertion"]


class _Battle:
    """One battle room."""

    def __init__(self, room, game, log_path):
        self.room = room
        self.game = game
        self.log = open(log_path, "a", encoding="utf-8")
        self.deadline = None  # the end of the sheet wait
        self.checked_sheets = False
        self.decided = 0  # the epoch of the last decision point answered
        self.candidates = []
        self.index = 0
        self.rejections = 0
        self.pending = None  # the choice sent last, accepted once the battle goes on
        self.stopped = False  # forfeited or ended: no more choices
        self.ended = False

    def write(self, record):
        if not self.log.closed:
            self.log.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.log.flush()


class Bot:
    def __init__(self, config, data, policy, login=login, clock=time.monotonic, team_texts=None, rng=None):
        self.config = config
        self.data = data
        self.policy = policy
        self.login = login
        self.clock = clock
        self.team_texts = team_texts or {"A": teams.text("A"), "B": teams.text("B")}
        self.rng = rng or random.Random()
        self.connection = None
        self.busy = None  # {"user", "format", "games", "team", "since", "room"} while a battle or series runs
        self.battles = {}
        self.finished = set()  # battle rooms that ended: later lines (|deinit|) are ignored
        self.confirmed = set()  # (series room, game number) answered with /confirmready
        self.challenged = False

    async def run(self):
        import asyncio
        import websockets  # only the live connection needs it
        async with websockets.connect(self.config.server, max_size=None) as ws:
            self.connection = ws
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    await self.tick()
                    continue
                await self.handle(message)
                await self.tick()

    async def send(self, text):
        await self.connection.send(text)

    def close(self):
        """Closes the logs of battles that are still open."""
        for b in self.battles.values():
            b.log.close()

    async def handle(self, message):
        room, _, rest = message[1:].partition("\n") if message.startswith(">") else ("", "", message)
        lines = rest.split("\n")
        if room.startswith("battle-"):
            await self._battle(room, lines)
        elif room.startswith("game-bestof"):
            await self._series(room, lines)
        elif room == "":
            await self._global(lines)

    async def tick(self):
        """Ends a sheet wait that ran out, and frees the bot when an accepted challenge opened no room."""
        if self.busy is not None and not self.busy["room"] and self.clock() - self.busy["since"] > ACCEPT_WAIT:
            self.busy = None
        for b in list(self.battles.values()):
            if b.deadline is not None and not b.stopped and not b.game.ready and self.clock() > b.deadline:
                await self._forfeit(b, self._sheets_message(), "no open team sheets in time")

    # ------------------------------------------------------------------ global messages
    async def _global(self, lines):
        for line in lines:
            parts = line.split("|")
            kind = parts[1] if len(parts) > 1 else ""
            if kind == "challstr":
                challstr = "|".join(parts[2:])
                assertion = self.login(self.config.name, challstr, os.environ.get("DUOFORGE_PS_PASSWORD"))
                await self.send(f"|/trn {self.config.name},0,{assertion}")
            elif kind == "updateuser":
                if len(parts) > 3 and parts[3] == "1" and self.config.challenge and not self.challenged:
                    self.challenged = True
                    team = self._pick_team()
                    self.busy = {"user": toid(self.config.challenge), "format": self.config.challenge_format,
                                 "games": FORMATS[self.config.challenge_format], "team": team,
                                 "since": self.clock(), "room": False}
                    await self.send("|/utm " + teams.pack(self.team_texts[team]))
                    await self.send(f"|/challenge {self.config.challenge}, {self.config.challenge_format}")
            elif kind == "pm" and len(parts) > 4:
                await self._pm(parts[2], parts[3], "|".join(parts[4:]))
            elif kind == "nametaken":
                raise SystemExit(f"duoforge_live: the server refused the name: {line}")
            elif kind == "popup":
                print(f"duoforge_live: popup: {'|'.join(parts[2:])}", file=sys.stderr)

    def _pick_team(self):
        return self.rng.choice(("A", "B")) if self.config.team == "random" else self.config.team

    async def _pm(self, sender, recipient, text):
        """A challenge comes as a PM "/challenge FORMAT|..." from the challenger (server/ladders-challenges.ts);
        "/challenge" alone removes one, and the bot's own challenges come back the same way."""
        me = toid(self.config.name)
        if not text.startswith("/challenge ") or toid(recipient) != me or toid(sender) == me:
            return
        user, fmt = toid(sender), text[len("/challenge "):].split("|")[0]
        if fmt not in FORMATS:
            await self.send(f"|/reject {user}")
            await self.send(f"|/pm {user}, {WRONG_FORMAT}")
        elif self.busy is not None:
            await self.send(f"|/reject {user}")
            await self.send(f"|/pm {user}, {BUSY}")
        else:
            team = self._pick_team()
            self.busy = {"user": user, "format": fmt, "games": FORMATS[fmt], "team": team, "since": self.clock(),
                         "room": False}
            await self.send("|/utm " + teams.pack(self.team_texts[team]))
            await self.send(f"|/accept {user}")

    # ------------------------------------------------------------------ Bo3 series rooms
    async def _series(self, room, lines):
        if self.busy is not None:
            self.busy["room"] = True
        for line in lines:
            ready = re.search(r"Are you ready for game (\d+)", line)
            # Only the enabled button carries the command; after the answer the server shows a disabled one.
            if line.startswith("|c|~|/uhtml controls,") and ready and "/confirmready" in line \
                    and (room, ready.group(1)) not in self.confirmed:
                self.confirmed.add((room, ready.group(1)))
                await self.send(f"{room}|/confirmready")
            elif line.startswith("|win|") or line == "|tie" or line.startswith("|tie|"):
                self.busy = None

    # ------------------------------------------------------------------ battle rooms
    def _open(self, room):
        """The battle of a room the server opened for the bot; None when the bot has no team for it (a room
        it did not accept, with --team random)."""
        team = self.busy["team"] if self.busy is not None else self.config.team
        if team not in self.team_texts:
            print(f"duoforge_live: ignoring the battle room {room}: no accepted challenge", file=sys.stderr)
            self.finished.add(room)
            return None
        if self.busy is not None:
            self.busy["room"] = True
        log_dir = Path(self.config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{room}-{toid(self.config.name)}.jsonl"  # two bots of one machine can share a room
        b = _Battle(room, Game(self.data, self.policy, self.team_texts[team]), log_path)
        self.battles[room] = b
        return b

    def _sheets_message(self):
        return SHEETS + (f" {self.config.team_link}" if self.config.team_link else "")

    async def _battle(self, room, lines):
        if room in self.finished:
            return
        b = self.battles.get(room)
        if b is None:
            b = self._open(room)
            if b is None:
                return
            if "|init|battle" in lines:
                await self.send(f"{room}|{GREETING}")
        if b.ended:
            return
        for line in lines:
            b.write({"in": line})
        for line in lines:
            if line.startswith("|error|"):
                await self._error(b, line)
            elif line.startswith("|win|") or line == "|tie" or line.startswith("|tie|"):
                await self._end(b, line)
                return
            elif line.startswith("|uhtml|otsrequest|"):
                await self.send(f"{room}|/acceptopenteamsheets")
            elif line.endswith(" rejected open team sheets.") and not line.startswith(self.config.name + " "):
                await self._forfeit(b, self._sheets_message(), "open team sheets rejected")
        battle_lines = [line for line in lines if not line.startswith("|error|")]
        if b.stopped or not battle_lines:
            return
        try:
            if b.pending is not None and not all(_room_line(line) for line in battle_lines):
                b.game.accepted(b.pending)
                b.pending = None
            b.game.feed(battle_lines)
            await self._after_feed(b)
        except (Exception, trace_to_c.ConversionError) as e:  # ConversionError is a SystemExit
            await self._forfeit(b, INTERNAL, f"{type(e).__name__}: {e}")

    async def _after_feed(self, b):
        game = b.game
        r = game.request
        if r is not None and r.get("teamPreview") and not game.ready and b.deadline is None:
            b.deadline = self.clock() + SHEET_WAIT
        if game.ready and not b.checked_sheets and game.foe_sets is not None:
            b.checked_sheets = True
            if not any(teams.match(game.foe_sets, text) for text in self.team_texts.values()):
                await self._forfeit(b, self._sheets_message(), "the foe's team is not Team A or B")
                return
        if game.asked() and game.epoch > b.decided:
            b.decided = game.epoch
            b.candidates = game.candidates()
            b.index = b.rejections = 0
            b.write({"decision": r["rqid"], "top": [[c.text, c.probability] for c in b.candidates[:3]],
                     "sent": b.candidates[0].text})
            await self._choose(b)

    async def _choose(self, b):
        text = b.candidates[b.index].text
        b.pending = text
        await self.send(f"{b.room}|/choose {text}|{b.game.request['rqid']}")

    async def _error(self, b, line):
        if b.stopped:
            return
        if line.startswith("|error|[Invalid choice]") and b.candidates:
            b.write({"rejected": b.candidates[b.index].text, "error": line})
            b.rejections += 1
            if b.rejections >= MAX_REJECTIONS or b.index + 1 >= len(b.candidates):
                await self._forfeit(b, INTERNAL, f"{b.rejections} choices rejected")
                return
            b.index += 1
            await self._choose(b)
        elif line.startswith("|error|[Unavailable choice]"):
            await self._forfeit(b, INTERNAL, f"an unavailable choice: {line}")

    async def _forfeit(self, b, message, cause):
        if b.stopped:
            return
        b.stopped = True
        b.write({"forfeit": cause})
        await self.send(f"{b.room}|{message}")
        await self.send(f"{b.room}|/forfeit")

    async def _end(self, b, line):
        b.ended = b.stopped = True
        await self.send(f"{b.room}|{GG}")
        b.write({"end": line})
        b.log.close()
        del self.battles[b.room]
        self.finished.add(b.room)
        await self.send(f"|/leave {b.room}")
        if self.busy is not None and self.busy["games"] == 1:
            self.busy = None


def _room_line(line):
    """A line of the room that is not part of the battle (chat, joins, the timer, text)."""
    kind = _kind(line)
    return kind is None or kind in ROOM_LINES
