"""Python side of the agent interface.

    game = Game.for_session()          # the current session's server
    game.do(mine(name="iron-ore", x=40, y=-80, count=10), craft("iron-gear-wheel", 2))

`do` queues orders, lets them run until they finish (or something needs attention) and
returns a Report. In solo mode the game is paused whenever no call is running; in co-op it
runs in real time and `do` just waits.
"""

import json
import time

from fxa.rcon import RconError

# Orders per enqueue request, to keep single RCON commands small.
ENQUEUE_CHUNK = 40


class GameError(Exception):
    pass


def _order(type_, /, **fields):
    order = {"type": type_}
    order.update({key: value for key, value in fields.items() if value is not None})
    return order


def walk(x, y, radius=None):
    return _order("walk", x=x, y=y, radius=radius)


def mine(x=None, y=None, name=None, kind=None, count=None, radius=None):
    """Mine `count` units of ore, or `count` entities (trees, rocks, buildings), near (x, y)."""
    return _order("mine", x=x, y=y, name=name, kind=kind, count=count, radius=radius)


def craft(recipe, count=1, wait=False):
    return _order("craft", recipe=recipe, count=count, wait=wait or None)


def uncraft(recipe, count=None):
    """Cancel queued hand-crafts of `recipe` (all, or `count`); the ingredients come back."""
    return _order("uncraft", recipe=recipe, count=count)


def wait(ticks=None, craft=None, have=None, item=None, count=None, x=None, y=None, max=None):
    """Wait for ticks, for hand-crafting to finish (craft=True), until the character
    has `count` of `have`, or until the entity at (x, y) holds `count` of `item`."""
    return _order("wait", ticks=ticks, craft=craft, have=have, item=item, count=count, x=x, y=y, max=max)


def place(item, x, y, dir=None, recipe=None, ug_type=None):
    return _order("place", item=item, x=x, y=y, dir=dir, recipe=recipe, ug_type=ug_type)


def put(x, y, item, count=None):
    return _order("put", x=x, y=y, item=item, count=count)


def take(x, y, item=None, count=None):
    return _order("take", x=x, y=y, item=item, count=count)


def recipe(x, y, name):
    return _order("recipe", x=x, y=y, recipe=name)


def rotate(x, y, dir=None):
    return _order("rotate", x=x, y=y, dir=dir)


def filter(x, y, *items):
    """Let the inserter at (x, y) move only these items; no items removes the filter."""
    return _order("filter", x=x, y=y, items=list(items))


def mirror(x, y):
    """Flip the machine at (x, y) so its fluid inlets swap sides."""
    return _order("mirror", x=x, y=y)


def launch(x, y):
    return _order("launch", x=x, y=y)


def pickup(x=None, y=None, ticks=None):
    return _order("pickup", x=x, y=y, ticks=ticks)


def equip(item, slot=None):
    """Move a gun, armour or ammunition from the main inventory into its slot."""
    return _order("equip", item=item, slot=slot)


class Report:
    """Outcome of a run: per-order results, events, and the character's state after it."""

    def __init__(self, raw):
        self.raw = raw
        self.reason = raw.get("reason")
        self.results = list(raw.get("results") or [])
        self.events = list(raw.get("events") or [])
        self.dropped = raw.get("dropped") or 0
        self.queued = raw.get("queued") or 0
        self.state = raw.get("state") or {}
        self.changed = raw.get("changed") or {}
        self.tick = raw.get("tick")
        self.chat = list(raw.get("chat") or [])

    @property
    def failures(self):
        return [result for result in self.results if not result.get("ok")]

    @property
    def ok(self):
        return not self.failures and self.reason in ("done", "ticks elapsed")

    def __str__(self):
        from fxa import fmt
        return fmt.report(self)


class Game:
    def __init__(self, target, session=None):
        self.target = target
        self.session = session
        try:
            self.client = target.connect()
        except (RconError, OSError) as err:
            raise GameError(f"cannot reach the game server {target.label or target.host} ({err}); is it running?") from err

    @classmethod
    def for_session(cls, spec=None):
        from fxa import server, session
        s = session.current(spec)
        try:
            return cls(server.Server(s).target(), s)
        except server.ServerError as err:
            raise GameError(str(err)) from None

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def call(self, op, **args):
        request = {"op": op}
        request.update({key: value for key, value in args.items() if value is not None})
        raw = self.client.command("/agent " + json.dumps(request, separators=(",", ":")))
        try:
            reply = json.loads(raw)
        except ValueError:
            raise GameError(f"unexpected reply to {op}: {raw.strip()[:400]!r}") from None
        if not reply.get("ok"):
            raise GameError(reply.get("error") or "unknown error")
        return reply

    def batch(self, *requests):
        """Several requests in one round trip: batch(("state", {}), ("chat", {"since": 3}))."""
        reply = self.call("batch", requests=[{"op": op, **(args or {})} for op, args in requests])
        return list(reply.get("replies") or [])

    def enqueue(self, *orders):
        flat = []
        for order in orders:
            flat.extend(order if isinstance(order, (list, tuple)) else [order])
        for start in range(0, len(flat), ENQUEUE_CHUNK):
            self.call("enqueue", orders=flat[start:start + ENQUEUE_CHUNK], base=start)
        return len(flat)

    def run(self, ticks=600, until_idle=False):
        """Let the game run; returns when it pauses again."""
        self.call("run", ticks=int(ticks), until_idle=until_idle)
        return self.wait_for_pause()

    def wait_for_pause(self, stall=15.0):
        """Collect the report of the run in progress (or of the last one).

        In co-op the server pauses itself while nobody is connected (auto_pause); if the tick
        stops moving for `stall` seconds the run is halted and reported as "game paused"."""
        delay = 0.004
        last_tick, since = None, time.time()
        while True:
            reply = self.call("report")
            if not reply.get("running"):
                report = Report(reply)
                if self.session and report.chat:
                    self.session.log_chat(report.chat)
                return report
            tick = reply.get("tick")
            if tick != last_tick:
                last_tick, since = tick, time.time()
            elif time.time() - since > stall:
                self.call("halt", reason="game paused")
            time.sleep(delay)
            delay = min(delay * 1.5, 0.25)

    def do(self, *orders, max_ticks=36000, check=False):
        """Queue orders and run until they are finished, fail, or something interrupts."""
        self.enqueue(*orders)
        report = self.run(max_ticks, until_idle=True)
        if check and not report.ok:
            raise GameError(str(report))
        return report

    def resume(self, max_ticks=36000):
        """Continue the queue after an interruption, or rejoin a run still in progress."""
        if self.call("status").get("running"):
            return self.wait_for_pause()
        return self.run(max_ticks, until_idle=True)

    def save(self, name, timeout=180.0):
        """Write a checkpoint save; with a local session, wait until the file is complete."""
        from fxa import paths
        paths.check_name(name, "save name")
        if not self.session or self.session.meta.get("attach"):
            self.call("save", name=name)
            return name
        from fxa import server
        path = self.session.save_path(name)
        before = path.stat().st_mtime_ns if path.exists() else None
        self.call("save", name=name)
        return server.Server(self.session).wait_for_save(name, before, timeout)

    # -- multiplayer
    def chat(self, since=0, limit=50):
        reply = self.call("chat", since=since, limit=limit)
        return list(reply.get("lines") or []), reply.get("seq", 0)

    def say(self, text, to=None):
        line = self.call("say", text=text, to=to).get("line")
        if self.session and line:
            self.session.log_chat([line])
        return line

    def players(self):
        return list(self.call("players").get("players") or [])

    def wait_chat(self, since, timeout=60.0, mention_only=False, poll=0.5):
        """Block until chat lines newer than `since` arrive (or `timeout` seconds pass)."""
        deadline = time.time() + timeout
        while True:
            lines, seq = self.chat(since=since)
            lines = [l for l in lines if not l.get("self")]
            if mention_only:
                lines = [l for l in lines if l.get("mention")]
            if lines or time.time() >= deadline:
                if self.session and lines:
                    self.session.log_chat(lines)
                return lines, seq
            time.sleep(poll)

    def cancel(self):
        return self.call("cancel")

    def state(self):
        return self.call("state")

    def research(self, *techs, clear=False):
        return self.call("research", techs=list(techs), clear=clear or None)
