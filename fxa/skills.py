"""Skills: reusable routines in the sandboxed Python subset (see sandbox.py),
stored as .fxs files in the layers (see layers.py). Run one with `fx skill run
NAME key=value ...`.

A skill file looks like this:

    \"\"\"Top up gun turrets with magazines.

    Longer description, what the parameters mean, what it returns. \"\"\" META =
    {"params": {"r": "radius around the character"}, "requires": ["gun-turret"],
    "game": ">=2.0"}

    def main(r=60, target=20):
        turrets = entities(r=r, name="gun-turret") ... return {"stocked": n}

What a skill can call (all of it plain data in, plain data out):
  orders     walk mine craft uncraft wait place put take recipe rotate filter
             mirror launch pickup equip (the same orders as `fx do`; they only
             build order dicts)
  running    do(orders, max_ticks=36000) -> report dict; go(orders, label) also
             carries on through alerts (enemy nearby, damage, losses) until the
             orders finish, fail, or the character dies
  looking    state() entities(...) buildings(...) find(...) scan(...)
             recipe(name) tech(name) production(names) power() enemies()
             can_place(item, x, y) players() chat(since) mods() exists(names)
             inventory() holding(x, y, item)
  helpers    belt_path(corners, item) at_tiles(item, tiles, dir) inserter(x, y,
             takes_from, item) tiles_along(corners) take_from(points, item,
             limit) free_spot(item, x, y) seq(value)
  talking    say(text, to=None)
  other      research(*techs) save(name) skill(name, **params) params(): the
             parameters given
  builtins   print len range min max sorted sum abs round int float str list
             dict set enumerate zip floor ceil sqrt hypot dist fail(message)
             type_name(value) ...
"""

import ast
import json
from dataclasses import dataclass
from pathlib import Path

from fxa import fmt, game as G, layers, layout, paths, sandbox

ALERTS = (
    "enemy nearby",
    "character damaged",
    "building destroyed",
    "research queue empty",
)
LOOK_OPS = (
    "state",
    "entities",
    "buildings",
    "find",
    "scan",
    "map",
    "recipe",
    "tech",
    "techs",
    "production",
    "power",
    "enemies",
    "can_place",
    "players",
    "chat",
    "mods",
    "exists",
)


class SkillError(Exception):
    pass


@dataclass
class Result:
    value: object
    output: str
    steps: int


def report_dict(r):
    return {
        "ok": r.ok,
        "reason": r.reason,
        "results": r.results,
        "failures": r.failures,
        "events": r.events,
        "state": r.state,
        "changed": r.changed,
        "tick": r.tick,
        "queued": r.queued,
        "dropped": r.dropped,
        "chat": r.chat,
    }


def _orders(value):
    items = value if isinstance(value, list) else [value]
    flat = []
    for item in items:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    for order in flat:
        if not (isinstance(order, dict) and isinstance(order.get("type"), str)):
            raise SkillError("do() takes orders made by walk(), place(), ...")
    return flat


def api(game, stack, budget, params, out):
    """The functions a skill can call, bound to one game connection."""
    host = {}

    for name in (
        "walk",
        "mine",
        "craft",
        "uncraft",
        "wait",
        "place",
        "put",
        "take",
        "recipe",
        "rotate",
        "filter",
        "mirror",
        "launch",
        "pickup",
        "equip",
    ):
        host[name] = getattr(G, name)

    def do(orders, max_ticks=36000):
        return report_dict(game.do(_orders(orders), max_ticks=int(max_ticks)))

    def go(orders, label="", max_ticks=120000):
        r = game.do(_orders(orders), max_ticks=int(max_ticks))
        while r.reason in ALERTS:
            r = game.resume()
        fails = [
            (x.get("n"), x.get("type"), x.get("error")) for x in r.failures
        ]
        if label:
            out(
                f"{label} -> {r.reason}, {len(r.results)} orders"
                + (f", failed: {fails}" if fails else "")
                + "\n"
            )
        return report_dict(r)

    host["do"], host["go"] = do, go

    def look(op):
        def call(**args):
            return game.call(op, **args)

        return call

    for op in LOOK_OPS:
        host[op] = look(op)

    def entities(
        x=None,
        y=None,
        r=None,
        name=None,
        type=None,
        all=None,
        limit=None,
        x1=None,
        y1=None,
        x2=None,
        y2=None,
    ):
        reply = game.call(
            "entities",
            x=x,
            y=y,
            r=r,
            name=name,
            type=type,
            all=all,
            limit=limit,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
        )
        return fmt.seq(reply.get("entities"))

    def chat(since=0, limit=50):
        return game.chat(since=since, limit=limit)[0]

    def players():
        return game.players()

    def exists(names):
        return game.call("exists", names=list(names)).get("exists") or {}

    def inventory():
        return (game.state().get("character") or {}).get("inventory") or {}

    def holding(x, y, item):
        found = entities(x=x, y=y, r=0.6)
        if not found:
            return 0
        return sum(
            counts.get(item, 0)
            for counts in (found[0].get("items") or {}).values()
        )

    def take_from(points, item, limit=None):
        orders, total = [], 0
        for x, y in points:
            n = holding(x, y, item)
            if limit is not None:
                n = min(n, limit - total)
            if n > 0:
                orders.append(G.take(x, y, item, n))
                total += n
        return orders

    def free_spot(
        item,
        x,
        y,
        offsets=((0, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (3, 3), (-3, 3)),
    ):
        for dx, dy in offsets:
            if game.call("can_place", item=item, x=x + dx, y=y + dy).get(
                "can_place"
            ):
                return [x + dx, y + dy]
        return None

    def say(text, to=None):
        return game.say(str(text), to=to)

    def research(*techs):
        return game.research(*techs)

    def save(name):
        return str(game.save(paths.check_name(name, "save name")))

    def skill(name, **kw):
        return run_in(stack, name, kw, game, budget, out)

    host.update(
        entities=entities,
        chat=chat,
        players=players,
        exists=exists,
        inventory=inventory,
        holding=holding,
        take_from=take_from,
        free_spot=free_spot,
        say=say,
        research=research,
        save=save,
        skill=skill,
        belt_path=layout.belt_path,
        at_tiles=layout.at_tiles,
        inserter=layout.inserter,
        tiles_along=layout.tiles_along,
        seq=fmt.seq,
        params=lambda: dict(params),
    )
    return host


def _load(stack, name):
    item = layers.resolve(stack, "skills", name)
    return item, item.path.read_text(encoding="utf-8")


def _check_requires(item, game):
    need = item.meta.get("requires") or []
    if isinstance(need, str):
        need = [n.strip() for n in need.split(",") if n.strip()]
    if not need:
        return
    found = game.call("exists", names=list(need)).get("exists") or {}
    missing = [n for n in need if not found.get(n)]
    if missing:
        raise SkillError(
            f"skill {item.id} needs {', '.join(missing)}, which this game does "
            "not have"
        )


def run_in(stack, name, params, game, budget, out):
    item, source = _load(stack, name)
    _check_requires(item, game)
    interp = sandbox.Interpreter(
        api(game, stack, budget, params, out),
        budget=budget,
        output=out,
        filename=f"{item.id}.fxs",
    )
    scope = interp.run(source)
    main = scope.get("main")
    if not isinstance(main, sandbox.Function):
        raise SkillError(f"skill {item.id} has no main() function")
    return interp.call(main, kwargs=params)


def run(stack, name, params, game, max_steps=None):
    budget = sandbox.Budget(max_steps=max_steps)
    chunks = []

    def out(text):
        chunks.append(text)
        print(text, end="", flush=True)

    value = run_in(stack, name, params, game, budget, out)
    return Result(value=value, output="", steps=budget.steps)


def check_file(path):
    problems = []
    source = Path(path).read_text(encoding="utf-8")
    try:
        tree = sandbox.parse(source, Path(path).name)
    except sandbox.SandboxError as err:
        return [str(err)]
    if not any(
        isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body
    ):
        problems.append("no main() function")
    meta = layers.skill_meta(path)
    if meta.get("broken"):
        problems.append(meta["summary"])
    if not meta.get("summary"):
        problems.append(
            "no docstring (its first line is the summary shown by `fx skill "
            "list`)"
        )
    return problems


def parse_params(pairs):
    out = {}
    for pair in pairs:
        if "=" not in pair:
            raise SkillError(f"parameters are key=value, got {pair!r}")
        key, raw = pair.split("=", 1)
        paths.check_name(key.replace("_", "x"), "parameter name")
        try:
            value = json.loads(raw)
        except ValueError:
            try:
                value = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                value = raw
        out[key] = value
    return out
