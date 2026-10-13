"""PKMN Arena (https://vgc.ellep.dev, spec https://vgc.ellep.dev/llms.txt): the live client's mode for the public VGC
bot ladder (owner, 2026-10-12), next to the Showdown modes and never instead of them.

    python -m duoforge_live --server arena --format ID --checkpoint P [--team FILE] [--team-pool FILE]
                            [--search raw|honest [--foe-net P]] [--log-dir DIR]

The arena speaks the Showdown protocol on one fixed host (URL). The bot's name comes from ARENA_BOT_NAME and its token
from ARENA_BOT_TOKEN, both only from the environment: the token is never taken from the command line or a URL, never
logged, never written to a file, and every text the mode prints or logs passes through redact(). Login is the direct
"/trn NAME,0,TOKEN" after |challstr|; the team (--team) goes with /utm after every login, so after every reconnect too.

The server puts the bot in battles (no /accept); it plays every one, one at a time, with the request's rqid on every
/choose. Under open team sheets (the OTS format) the tracker folds the foe's |showteam| (decision 0016 section 2: its
items, abilities, moves and natures; its stat points stay hidden as in DuoForge's observation). Under closed team sheets
(the CTS format, decision 0081) the battle is played over the particles of game.Game.closed_sheets: 16 drawn foe teams
from the pinned set table (cts.SetPrior.from_table), the search's world w built from particle w's record; the bot
then never accepts open sheets. Its battle log keeps every batch the game was fed ("feed") and every choice it accepted
("accepted"), so the log draws the same particles again, and the particle tracker's counters go to the run log ("cts").
When the engine cannot represent a battle -- a tracker Stop (a particle tracker's named cts: stops among them), an
error of the tracker, the options or the policy, more refused choices than MAX_RETRIES, a decision not made within
DECISION_DEADLINE -- the rest of that battle is answered with "/choose default": the server's simulator picks, never a
Python rule. Each such battle and each defaulted decision is counted by its reason in the run log (aggregates only,
arena-run-*.json); the battle logs hold match ids and stay private, outside the repository (the CLI refuses a log
directory inside it).

The random-team ladders (the format id with "random" appended) give the bot a published team it learns only from the
first request; the request lacks the natures and stat points the tracker's own sheet needs, so such a battle is played
by the policy only when exactly one team of --team-pool matches the request's species, items, abilities and moves, and
falls back otherwise.

A dropped connection reconnects after BACKOFF (1, 2, 5, 10, 30 s), logs in and sends the team again. The server sends
an open battle's log and its open request again: when the log starts with every battle line the tracker folded, the
new lines are folded and an open request already answered is answered again; any other replay falls back.
"""
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from . import client, cts, search as live_search, teams
from .client import toid, _room_line
from .data import trace_to_c
from .game import Game
from .lines import Stop, line_kind

URL = "wss://vgc.ellep.dev/showdown/websocket"
HOST = "vgc.ellep.dev"
NAME_ENV, TOKEN_ENV = "ARENA_BOT_NAME", "ARENA_BOT_TOKEN"
TOKEN_PREFIX = "pka_"
# The registered formats (llms.txt): closed and open team sheets. Each has a random-team ladder: the id + "random".
FORMATS = ("gen9championsvgc2026regmc", "gen9championsvgc2026regmcots")
BACKOFF = (1.0, 2.0, 5.0, 10.0, 30.0)  # seconds before the n-th reconnect in a row
DECISION_DEADLINE = 20.0  # seconds a decision may take before it is defaulted (the arena gives 45, 90 at preview)
SHEET_WAIT = 20.0  # seconds after the team preview request for both open sheets
MAX_RETRIES = 16  # next-best choices after "[Invalid choice]" at one decision point, then the battle falls back
_NAME = re.compile(r"^[A-Za-z0-9._-]+(?: [A-Za-z0-9._-]+)*$")  # llms.txt: 3-18 characters
_CLOSE_STOP = 4001  # another connection logged in as the bot
STABLE = 60.0  # seconds a logged-in connection must last to reset the backoff


def _refuse(message):
    print(f"duoforge_live: {redact(message)}", file=sys.stderr)
    raise SystemExit(2)


def redact(text, environ=None):
    """text with the token (if one is set) replaced by "[token]"."""
    token = (os.environ if environ is None else environ).get(TOKEN_ENV)
    return text.replace(token, "[token]") if token else text


def check_token(token):
    """SystemExit for a missing token or one that is no arena token; the value is never shown."""
    if not token:
        _refuse(f"{TOKEN_ENV} is not set: the arena token comes only from the environment")
    if not token.startswith(TOKEN_PREFIX) or any(c in token for c in "|,\r\n \t"):
        _refuse(f"{TOKEN_ENV} is no arena token ({TOKEN_PREFIX}..., without '|', ',', blanks or line breaks); "
                "its value is not shown")


def check_argv(argv, environ=None):
    """SystemExit, without echoing anything, when the command line holds the token or anything like one: the token
    belongs in ARENA_BOT_TOKEN only. Before argparse, whose errors would print the arguments."""
    token = (os.environ if environ is None else environ).get(TOKEN_ENV)
    if any(TOKEN_PREFIX in arg or (token and token in arg) for arg in argv):
        _refuse("the arena token is on the command line: it belongs in ARENA_BOT_TOKEN only")


def credentials(environ=None):
    """The bot's registered name from ARENA_BOT_NAME; the token is checked here and read again at each login, never
    kept. SystemExit when either is missing or malformed."""
    environ = os.environ if environ is None else environ
    name = environ.get(NAME_ENV, "")
    if not (3 <= len(name) <= 18 and _NAME.match(name)):
        _refuse(f"{NAME_ENV} must hold the bot's registered name (3-18 letters, digits, single spaces, '.', '-', '_')")
    token = environ.get(TOKEN_ENV, "")
    check_token(token)
    return name


def check_format(fmt):
    if fmt not in FORMATS:
        _refuse(f"--format is one of {list(FORMATS)}, the format the bot is registered for")
    return fmt


def read_pool(path):
    """The pastes of a team pool file: Showdown's export of several teams, each after a "=== ... ===" line."""
    text = Path(path).read_text(encoding="utf-8")
    chunks = re.split(r"^===.*===[ \t]*$", text, flags=re.M)
    pool = [c.strip() + "\n" for c in chunks if c.strip()]
    if not pool:
        _refuse(f"--team-pool {path}: no team")
    return pool


def check_teams(data, team_text, pool):
    """SystemExit for a team the tracker or /utm cannot use (an unknown name, a missing gender): before connecting."""
    for label, text in [("--team", team_text)] * (team_text is not None) + [("--team-pool", t) for t in pool]:
        try:
            data.team(text)
            teams.pack(text)
        except (Exception, trace_to_c.ConversionError) as err:
            _refuse(f"{label}: a team the tracker cannot read: {type(err).__name__}: {err}")


def _sheet_key(species, item, ability, moves):
    k = teams._pack_name
    return k(species).lower(), k(item).lower(), k(ability).lower(), tuple(sorted(k(m).lower() for m in moves))


def request_matches(pokemon, paste):
    """Whether a request's side.pokemon are the six sets of a paste by species, item, ability and moves (protocol
    names compared as ids; no rule involved)."""
    got = sorted(_sheet_key(p["details"].split(",")[0], p.get("item", ""), p.get("baseAbility", ""), p.get("moves", ()))
                 for p in pokemon)
    want = sorted(_sheet_key(s["species"], s["item"], s["ability"], s["moves"]) for s in teams._paste(paste))
    return got == want


def sha256_of(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_foe_net(path, sha256=None):
    """(Honest's foe_net (model, params, encoder, ext_supported) of a format-2 checkpoint in its trained layout, how it
    reads the library's tables): the network that models the foe in the search's worlds (M7). It must read the current
    tables as the main network must (data.for_checkpoint: checkpoint.check_data); with sha256 the file must have that
    digest. ValueError otherwise."""
    from duoforge_learn import checkpoint
    from .data import for_checkpoint
    if sha256 is not None and sha256_of(path).lower() != sha256.lower():
        raise ValueError(f"the foe network {path} is not the pinned file (SHA-256 {sha256})")
    check = for_checkpoint(path).checkpoint_check
    params, config = checkpoint.load_trained(path)
    return (checkpoint.trained_model(config, params), params, checkpoint.encoder_of(config),
            checkpoint.ext_supported_of(config)), check


def close_code(err):
    """The close code a websockets ConnectionClosed (or an alike error) received, or None."""
    rcvd = getattr(err, "rcvd", None)
    return getattr(rcvd, "code", None)


class RunLog:
    """The run's aggregates (arena-run-<UTC start>.json in the log directory): counts only, no room or user ids."""

    def __init__(self, log_dir, mode, fmt, now=None, tables=None, code=None):
        start = now or datetime.now(timezone.utc)
        self.path = Path(log_dir) / f"arena-run-{start.strftime('%Y%m%dT%H%M%SZ')}.json"
        self.head = {"started": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": mode, "format": fmt}
        if code is not None:  # the bot's commit and dirty state (arena.provenance)
            self.head["code"] = code
        if tables:  # how each checkpoint reads the library's tables: both fingerprints, the check_ids result
            self.head["tables"] = tables
        self.counts = Counter()  # logins, reconnects, battles, wins, losses, ties, decisions, rejected choices, ...
        self.fallback_battles = Counter()  # battles that fell back to /choose default, by reason
        self.fallback_decisions = Counter()  # decisions answered with /choose default, by the battle's reason
        self.closes = Counter()  # dropped connections by close code
        self.formats = Counter()  # battles by format id
        self.search = Counter()  # the search's outcome causes over every decision it played
        self.cts = Counter()  # closed-sheet battles and their particle trackers' counters (redraws, levels, stops)

    def as_dict(self):
        return {**self.head, "counts": dict(self.counts), "fallback_battles": dict(self.fallback_battles),
                "fallback_decisions": dict(self.fallback_decisions), "closes": dict(self.closes),
                "formats": dict(self.formats), "search_causes": dict(self.search), "cts": dict(self.cts)}

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(redact(json.dumps(self.as_dict(), indent=1, sort_keys=True)) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


class _Battle(client._Battle):
    """One arena battle room: the client's battle state plus the fallback and the raw requests."""

    def __init__(self, room, log_path, fmt):
        super().__init__(room, None, log_path)
        self.format = fmt
        self.fallback = None  # the reason: the rest of the battle is answered with /choose default
        self.raw = None  # the last request (JSON) of the room: its rqid, wait and teamPreview (protocol only)
        self.answered = set()  # rqids answered by a choice of the policy or a default
        self.history = []  # the battle lines folded so far (no room lines, requests or errors): a replay's prefix
        self.buffer = []  # a random-team battle's lines until its first request names the team
        self.resync = False  # reconnected: the room's next |init|battle replays its log
        self.resend = False  # reconnected: the open request, sent again, is answered again

    def write(self, record):
        if not self.log.closed:
            self.log.write(redact(json.dumps(record, ensure_ascii=False)) + "\n")
            self.log.flush()


def _stop_key(reason):
    """The fallback reason of a tracker Stop: a particle tracker's stop by its name (stop:cts:redraw-cap, ...), any
    other by its kind (stop:feature, ...)."""
    return "stop:" + (reason.split(" ")[0] if reason.startswith("cts:") else reason.split(":")[0])


def _history_line(line):
    # |t:| is a timestamp, not a battle line: the arena's replay after a reconnect gives every one the time of the
    # replay (live, 2026-10-13, #455), so the resync compares the battle lines only
    kind = line_kind(line)
    return not _room_line(line) and kind not in ("request", "sentchoice", "t:")


class ArenaBot(client.Bot):
    """The live client on PKMN Arena. connect(url) gives an async context manager of a websocket (tests: a fake);
    connection_errors are the errors that mean a dropped connection (default: websockets' and OSError)."""

    def __init__(self, name, data, policy, log_dir, fmt, team_text=None, pool=(), search=None, mode="raw",
                 connect=None, connection_errors=None, sleep=asyncio.sleep, clock=time.monotonic, environ=None,
                 deadline=DECISION_DEADLINE, max_retries=MAX_RETRIES, sheet_wait=SHEET_WAIT, foe_check=None,
                 prior=None):
        # closed team sheets: the set prior (the pinned table unless given), one particle per world of the search
        self.prior = None
        if not fmt.startswith(FORMATS[1]):
            if prior is None:
                try:
                    prior = cts.SetPrior.from_table(data)
                except ValueError as err:
                    raise ValueError(f"closed team sheets: the set table does not load under the {data.kind!r} "
                                     f"tables: {err}") from None
            worlds = getattr(getattr(search, "searcher", None), "s", cts.PARTICLES)
            if worlds != cts.PARTICLES:
                raise ValueError(f"closed team sheets: the search has {worlds} worlds, the tracker {cts.PARTICLES} "
                                 "particles (world w is particle w)")
            self.prior = prior
        config = client.Config(name=name, team="own", log_dir=log_dir)
        super().__init__(config, data, policy, login=None, clock=clock, team_texts={"own": team_text},
                         search=search, prior=self.prior)  # client.Bot keeps it: the closed sheets
        self.format = fmt
        self.team_text, self.pool = team_text, list(pool)
        self.packed = teams.pack(team_text) if team_text is not None else None
        self.connect, self.connection_errors, self.sleep = connect, connection_errors, sleep
        self.environ = environ  # None: os.environ, read at each login (the token is never kept on the bot)
        self.deadline, self.max_retries, self.sheet_wait = deadline, max_retries, sheet_wait
        checks = {"network": getattr(data, "checkpoint_check", None), "foe_net": foe_check}
        from .arena import provenance
        self.code = provenance()  # every result names the code that ran (HauptSession, 2026-10-13); none refuses
        self.run_log = RunLog(log_dir, mode, fmt, tables={k: v for k, v in checks.items() if v is not None},
                              code=self.code)
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="duoforge-arena-policy")
        self._worker = None  # the future of the last decision; a late one blocks the next (no two at once)
        self._dropped = ()  # the connection's errors: never a battle's fallback, the run loop reconnects
        self.warned = set()

    def close(self):
        super().close()
        self._executor.shutdown(wait=False)
        self.run_log.write()

    # ------------------------------------------------------------------ connection
    async def run(self):
        connect = self.connect
        errors = self.connection_errors
        if connect is None or errors is None:
            import websockets
            from websockets.exceptions import WebSocketException
            connect = connect or (lambda url: websockets.connect(url, max_size=None))
            errors = errors or (WebSocketException, OSError)
        self._dropped = errors
        attempt = 0
        while True:
            since = self.clock()
            try:
                async with connect(URL) as ws:
                    self.connection, self.named = ws, False
                    for b in self.battles.values():
                        b.resync = b.resend = True
                    while True:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            await self.tick()
                            continue
                        await self.handle(message)
                        await self.tick()
            except errors as err:
                code = close_code(err)
                self.run_log.closes[str(code)] += 1
                if code == _CLOSE_STOP:
                    self.run_log.write()
                    raise SystemExit("duoforge_live: another connection logged in as this bot (close 4001); "
                                     "stopping so that the two do not take turns") from None
                print(redact(f"duoforge_live: the arena connection dropped ({type(err).__name__}, close code "
                             f"{code}); reconnecting"), file=sys.stderr)
            finally:
                self.connection = None
            if self.named and self.clock() - since >= STABLE:
                attempt = 0  # that connection logged in and lasted: the backoff starts again
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            attempt += 1
            self.run_log.counts["reconnects"] += 1
            self.run_log.write()
            await self.sleep(delay)

    async def _global(self, lines):
        for line in lines:
            parts = line.split("|")
            kind = parts[1] if len(parts) > 1 else ""
            if kind == "challstr":
                token = (os.environ if self.environ is None else self.environ).get(TOKEN_ENV, "")
                check_token(token)
                self.run_log.counts["logins_sent"] += 1
                await self.send(f"|/trn {self.config.name},0,{token}")
            elif kind == "updateuser":
                if len(parts) > 3 and parts[3] == "1" and toid(parts[2]) == toid(self.config.name) and not self.named:
                    self.named = True
                    self.run_log.counts["logins"] += 1
                    if self.packed is not None:
                        await self.send("|/utm " + self.packed)
            elif kind == "nametaken":
                self.run_log.write()
                raise SystemExit(redact(f"duoforge_live: the arena refused the login: {line}"))
            elif kind == "popup":
                text = "|".join(parts[2:])
                self.run_log.counts["popups"] += 1
                if "team was rejected" in text.lower():
                    self.run_log.write()
                    raise SystemExit(redact(f"duoforge_live: the arena rejected the team (--team): {text}"))
                print(redact(f"duoforge_live: arena popup: {text}"), file=sys.stderr)

    # ------------------------------------------------------------------ fallback
    def _mark(self, b, reason, detail=None):
        if b.fallback is not None:
            return
        b.fallback = reason
        b.write({"fallback": reason, **({"detail": detail} if detail else {})})
        self.run_log.fallback_battles[reason] += 1
        if reason not in self.warned:
            self.warned.add(reason)
            print(redact(f"duoforge_live: arena fallback ({reason}): the rest of the battle is /choose default "
                         "(counted in the run log)"), file=sys.stderr)

    async def _fall(self, b, reason, detail=None):
        self._mark(b, reason, detail)
        await self._answer_default(b)

    async def _answer_default(self, b):
        r = b.raw
        if b.stopped or r is None or r.get("wait"):
            return
        rqid = r.get("rqid")
        if rqid in b.answered:
            return
        b.answered.add(rqid)
        self.run_log.fallback_decisions[b.fallback] += 1
        b.write({"sent": "default", "decision": rqid, "fallback": b.fallback})
        await self.send(f"{b.room}|/choose default" + (f"|{rqid}" if isinstance(rqid, int) else ""))

    # ------------------------------------------------------------------ battle rooms
    def _open(self, room):
        parts = room.split("-")
        fmt = parts[1] if len(parts) >= 3 else ""
        log_dir = Path(self.config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        b = _Battle(room, log_dir / f"{room}-{toid(self.config.name)}.jsonl", fmt)
        self.battles[room] = b
        self.run_log.counts["battles"] += 1
        self.run_log.formats[fmt] += 1
        random_teams = fmt == self.format + "random"
        if fmt != self.format and not random_teams:
            self._mark(b, "format", f"a battle of {fmt!r}, the bot plays {self.format!r}")
        elif not random_teams and self.team_text is None:
            self._mark(b, "no_team", "a team battle without --team")
        elif not random_teams:
            b.game = self._game(room, self.team_text)
        return b

    def _game(self, room, text):
        search = self.search if self.paused is None else None  # after a class (b) error every game is raw
        if self.prior is not None:  # closed team sheets: the bot's format (a battle of another fell back)
            game = Game.closed_sheets(self.data, self.policy, text, self.prior, search=search, room=room,
                                      episode=self.episodes)
            self.run_log.cts["battles"] += 1
        else:
            game = Game(self.data, self.policy, text, search=search, room=room, episode=self.episodes)
        self.episodes += 1
        return game

    def _random_game(self, b):
        """The game of a random-team battle from its first request: the one --team-pool team it names."""
        pokemon = b.raw.get("side", {}).get("pokemon", [])
        found = [text for text in self.pool if request_matches(pokemon, text)]
        if len(found) != 1:
            self._mark(b, "random_team_unknown" if not found else "random_team_ambiguous",
                       f"{len(found)} --team-pool teams match the request's team")
            return
        b.game = self._game(b.room, found[0])

    def _resync(self, b, lines):
        """The lines of a replayed log still to fold: those after the battle lines folded before the reconnect."""
        b.resync = False
        if b.fallback is None and b.game is None:  # a random-team battle before its first request: all again
            b.buffer = []
            return lines
        if b.fallback is not None:
            return [line for line in lines if line_kind(line) != "init"]
        n, seen, out = len(b.history), 0, []
        for line in lines:
            if line_kind(line) == "sentchoice":
                out.append(line)  # the caller reads it
                continue
            if seen < n:
                if _history_line(line):
                    if line != b.history[seen]:
                        break
                    seen += 1
                continue
            out.append(line)
        if seen < n:
            self._mark(b, "reconnect", f"the replayed log differs from the folded one after {seen} of {n} lines")
            return [line for line in lines if line_kind(line) != "init"]
        return out

    async def _battle(self, room, lines):
        if room in self.finished:
            return
        b = self.battles.get(room) or self._open(room)
        if b.ended:
            return
        if b.resync and "|init|battle" in lines:
            lines = self._resync(b, lines)
        # |sentchoice| (after a reconnect, beside the log or the open request): the server holds the choice sent
        # before the drop, so it is not sent again; a session line, never folded
        held = any(line_kind(line) == "sentchoice" for line in lines)
        lines = [line for line in lines if line_kind(line) != "sentchoice"]
        if held:
            b.resend = False
        resent = None
        for line in lines:
            b.write({"in": line})
            if live_search.timer_on(line):
                b.timer_on = True
            elif live_search.timer_off(line):
                b.timer_on, b.timer = False, None
            seconds = live_search.parse_timer(line)
            if seconds is not None:
                b.timer = (seconds, self.clock())
                b.timer_fresh = not (b.game is not None and b.game.ready and b.game.epoch <= b.decided)
            if line.startswith("|request|"):
                try:
                    request = json.loads(line[len("|request|"):])
                    if not isinstance(request, dict):
                        raise ValueError("not an object")
                except ValueError as err:
                    self._mark(b, "request", f"a request that is no JSON object: {err}")
                    b.raw = {}  # answered with a default without an rqid
                    b.answered.discard(None)
                    continue
                if b.resend:  # the first request after a reconnect: an answered one is still open
                    b.resend = False
                    if request.get("rqid") in b.answered:
                        resent = request.get("rqid")
                        if b.fallback is not None:
                            b.answered.discard(resent)
                b.raw = request
        for line in lines:
            if line.startswith("|error|"):
                await self._error(b, line)
            elif line.startswith("|win|") or line == "|tie" or line.startswith("|tie|"):
                await self._end(b, line)
                return
            elif line.startswith("|uhtml|otsrequest|") and b.fallback is None and self.prior is None:
                await self.send(f"{room}|/acceptopenteamsheets")
        battle_lines = [line for line in lines if not line.startswith("|error|")]
        if b.stopped or not battle_lines:
            return
        if b.fallback is None and b.game is None:  # a random-team battle before its first request
            b.buffer.extend(battle_lines)
            if b.raw is None:
                return
            battle_lines, b.buffer = b.buffer, []
            self._random_game(b)
        if b.fallback is not None:
            await self._answer_default(b)
            return
        try:
            # a resent open request alone is no sign that the choice was taken
            if b.pending is not None and resent is None and not all(_room_line(line) for line in battle_lines):
                if b.game.closed:
                    b.write({"accepted": b.pending})
                b.game.accepted(b.pending)
                b.pending = None
            b.history.extend(line for line in battle_lines if _history_line(line))
            if b.game.closed:  # the batch as fed: the particles depend on it (decision 0081)
                b.write({"feed": battle_lines})
            b.game.feed(battle_lines)
            await self._after_feed(b)
            if resent is not None and b.fallback is None and b.candidates and b.game.request is not None \
                    and b.game.request.get("rqid") == resent:
                await self._choose(b)  # the open request again after a reconnect: the same choice again
        except self._dropped:
            raise  # a dropped connection, not the battle: the run loop reconnects and the request comes again
        except Stop as e:  # a line the tracker cannot represent
            await self._fall(b, _stop_key(e.reason), f"stop:{e.reason}")
        except (Exception, trace_to_c.ConversionError) as e:  # ConversionError is a SystemExit
            await self._fall(b, f"error:{type(e).__name__}", f"{type(e).__name__}: {e}")

    async def tick(self):
        """Falls back when the open sheets do not come in time, and decides a request whose timer line did not come."""
        for b in list(self.battles.values()):
            if b.stopped or b.fallback is not None or b.game is None:
                continue
            if b.deadline is not None and not b.game.ready and self.clock() > b.deadline:
                await self._fall(b, "no_open_sheets", f"both open team sheets did not come in {self.sheet_wait} s")
            elif b.awaiting is not None and self.clock() - b.awaiting > client.TIMER_WAIT:
                try:
                    await self._after_feed(b)
                except self._dropped:
                    raise
                except Stop as e:
                    await self._fall(b, _stop_key(e.reason), f"stop:{e.reason}")
                except (Exception, trace_to_c.ConversionError) as e:
                    await self._fall(b, f"error:{type(e).__name__}", f"{type(e).__name__}: {e}")

    async def _after_feed(self, b):
        game = b.game
        r = game.request
        if r is not None and r.get("teamPreview") and not game.ready and b.deadline is None:
            b.deadline = self.clock() + self.sheet_wait
        if not (game.asked() and game.epoch > b.decided):
            return
        budget = None
        if self.search is not None:
            if b.timer_on and not r.get("update") and not b.timer_fresh:
                if b.awaiting is None:
                    b.awaiting = self.clock()
                if self.clock() - b.awaiting <= client.TIMER_WAIT:
                    return  # the timer line of this request follows it
                b.write({"timer": "missing", "decision": r["rqid"]})
            budget = live_search.deadline_seconds(*(b.timer or (None, 0.0)), self.clock())
            b.awaiting, b.timer_fresh = None, False
        if not r.get("update"):
            b.unavailable = 0
            b.rejections = 0
        b.decided = game.epoch
        searched = len(game.outcomes)
        candidates = await self._decide(b, budget)
        if candidates is None:
            return  # fell back
        b.candidates, b.index = candidates, 0
        self.run_log.counts["decisions"] += 1
        record = {"decision": r["rqid"], "top": [[c.text, c.probability] for c in candidates[:3]],
                  "sent": candidates[0].text}
        if len(game.outcomes) > searched:
            record["search"] = game.outcomes[-1].as_dict()
            self.run_log.search[game.outcomes[-1].cause] += 1
        b.write(record)
        if game.dirty is not None and self.paused is None:
            self.paused = game.dirty  # the rest of this game and every later one play raw
            b.write({"dirty": game.dirty})
            print(redact(f"duoforge_live: search error, the rest of the session plays raw: {game.dirty}"),
                  file=sys.stderr)
        await self._choose(b)

    async def _decide(self, b, budget):
        """The game's candidates, computed beside the event loop within the deadline; None after a fallback."""
        if self._worker is not None and not self._worker.done():
            await self._fall(b, "policy_busy", "a decision that missed its deadline still runs")
            return None
        call = b.game.candidates if budget is None else partial(b.game.candidates, budget)
        self._worker = self._executor.submit(call)
        try:
            return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(self._worker)), self.deadline)
        except asyncio.TimeoutError:
            self.run_log.counts["deadline_misses"] += 1
            await self._fall(b, "deadline", f"no decision within {self.deadline} s")
            return None

    async def _choose(self, b):
        rqid = b.game.request["rqid"]
        b.pending = b.candidates[b.index].text
        b.answered.add(rqid)
        await self.send(f"{b.room}|/choose {b.pending}|{rqid}")

    async def _error(self, b, line):
        if b.stopped:
            return
        if b.fallback is not None:
            if line.startswith("|error|[Invalid choice]"):
                self.run_log.counts["default_rejected"] += 1
            b.write({"error": line})
            return
        if line.startswith("|error|[Invalid choice]") and b.candidates and b.pending is not None:
            b.write({"rejected": b.candidates[b.index].text, "error": line})
            b.rejections += 1
            self.run_log.counts["rejected_choices"] += 1
            if b.rejections > self.max_retries or b.index + 1 >= len(b.candidates):
                b.answered.discard(b.game.request["rqid"])  # the open request gets the default
                await self._fall(b, "rejections", f"{b.rejections} choices rejected")
                return
            b.index += 1
            await self._choose(b)
        elif line.startswith("|error|[Unavailable choice]") and b.pending is not None:
            b.write({"unavailable": b.pending, "error": line})  # the updated request follows
            b.pending = None
            b.unavailable += 1
            self.run_log.counts["unavailable_choices"] += 1
            if b.unavailable > client.MAX_UNAVAILABLE:
                await self._fall(b, "unavailable", f"{b.unavailable} unavailable choices")
        elif line.startswith("|error|[Unavailable choice]"):
            await self._fall(b, "unavailable", f"an unavailable choice without a choice sent: {line}")
        else:
            b.write({"error": line})

    async def _forfeit(self, b, message, cause):
        """The arena bot never forfeits: what would forfeit on Showdown falls back."""
        await self._fall(b, "forfeit", cause)

    async def _end(self, b, line):
        b.ended = b.stopped = True
        if line.startswith("|win|"):
            result = "wins" if toid(line[len("|win|"):]) == toid(self.config.name) else "losses"
        else:
            result = "ties"
        self.run_log.counts[result] += 1
        b.write({"end": line})
        if b.game is not None and b.game.search is not None:
            b.write({"summary": {**b.game.summary(), "code": self.code}})
        if b.game is not None and b.game.closed:
            for key, n in b.game.tracker.counters.items():  # aggregates only: a stop's kind, never its text
                self.run_log.cts[cts.counter_kind(key)] += n
        b.log.close()
        del self.battles[b.room]
        self.finished.add(b.room)
        self.run_log.write()
