"""Compact text renderings of game replies, written to be cheap to read."""

import re

GPS = re.compile(r"\[gps=(-?[\d.]+),(-?[\d.]+)(?:,[^\]]*)?\]")


def seq(value):
    """Lua sends an empty array as {}; treat that as an empty list."""
    return value if isinstance(value, list) else []


def num(value):
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def amount(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{value / 1000:.0f}k"
    return num(value)


def items(counts):
    if not counts:
        return "-"
    return ", ".join(
        f"{name} {amount(count)}" for name, count in sorted(counts.items())
    )


def fields(data, skip=()):
    parts = []
    for key, value in data.items():
        if key in skip:
            continue
        if isinstance(value, dict):
            value = "{" + items(value) + "}" if value else "{}"
        elif isinstance(value, list):
            value = "(" + ", ".join(num(v) for v in value) + ")"
        else:
            value = num(value)
        parts.append(f"{key}={value}")
    return " ".join(parts)


def event(entry):
    return f"{entry.get('type')}@{entry.get('tick')} " + fields(
        entry, skip=("type", "tick")
    )


def changes(counts):
    if not counts:
        return "-"
    return ", ".join(
        f"{name} {count:+d}" for name, count in sorted(counts.items())
    )


def brief(state):
    if state.get("dead"):
        return f"DEAD, respawn in {state.get('respawn_in')} ticks"
    return (
        f"at ({num(state.get('x'))}, {num(state.get('y'))}) hp "
        f"{state.get('health')} crafting {state.get('crafting')}"
    )


def report(rep):
    lines = [f"[tick {rep.tick}] {rep.reason}"]
    for result in rep.results:
        head = f"  {result.get('n')} {result.get('type')}"
        if result.get("ok"):
            info = result.get("info")
            lines.append(
                f"{head} ok {result.get('ticks')}t"
                + (" " + fields(info) if info else "")
            )
        else:
            lines.append(f"{head} FAILED: {result.get('error')}")
    if rep.dropped:
        lines.append(f"  dropped {rep.dropped} later orders")
    if rep.queued:
        lines.append(f"  {rep.queued} orders still queued")
    for entry in rep.events:
        lines.append("  ! " + event(entry))
    if rep.raw.get("saved"):
        lines.append(f"  saved {rep.raw['saved']}")
    for line in rep.chat:
        lines.append("  > " + chat_line(line))
    lines.append(brief(rep.state))
    lines.append("inv changes: " + changes(rep.changed))
    return "\n".join(lines)


def chat_line(line):
    """One chat line; map pings ([gps=x,y]) are shown as plain coordinates."""
    text = GPS.sub(
        lambda m: f"[at {m.group(1)},{m.group(2)}]", str(line.get("text", ""))
    )
    text = "".join(
        c for c in text if c >= " " or c == "\t"
    )  # no terminal escapes from other players
    who = line.get("from", "?")
    to = f" -> {line['to']}" if line.get("to") else ""
    mark = " (@)" if line.get("mention") else ""
    return f"#{line.get('id')} {who}{to}{mark}: {text}"


def chat(lines):
    lines = seq(lines)
    return (
        "\n".join(chat_line(line) for line in lines) if lines else "(no chat)"
    )


def players(found):
    found = seq(found)
    if not found:
        return "no players"
    out = []
    for p in found:
        if not p.get("connected"):
            out.append(f"{p['name']}: offline")
            continue
        bits = [f"at ({num(p.get('x'))}, {num(p.get('y'))})"]
        if p.get("dist") is not None:
            bits.append(f"{num(p['dist'])} tiles away")
        if p.get("spectator"):
            bits.append("spectating")
        elif p.get("health") is not None:
            bits.append(f"hp {p['health']}")
        else:
            bits.append("no character")
        if p.get("vehicle"):
            bits.append(f"in {p['vehicle']}")
        if p.get("afk_ticks", 0) > 3600:
            bits.append(f"afk {p['afk_ticks'] // 3600} min")
        if p.get("admin"):
            bits.append("admin")
        out.append(f"{p['name']}: " + ", ".join(bits))
    return "\n".join(out)


def clock(tick):
    seconds = int(tick) // 60
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def state(reply):
    mode = reply.get("mode", "solo")
    speed = (
        f"speed {num(reply.get('speed'))}" if mode == "solo" else "real time"
    )
    lines = [
        f"[tick {reply.get('tick')} = {clock(reply.get('tick', 0))} played] "
        f"{mode} as {reply.get('name')}, {speed},"
        f" {reply.get('players_online', 0)} players online, chat "
        f"#{reply.get('chat_seq', 0)}",
        f"seed {reply.get('seed')} deaths {reply.get('deaths')}"
        f" evolution {num(reply.get('evolution'))} pollution here "
        f"{num(reply.get('pollution', 0))}",
    ]
    ch = reply.get("character")
    if ch:
        lines.append(
            f"at ({num(ch['x'])}, {num(ch['y'])}) hp "
            f"{ch['health']}/{ch['max_health']}"
        )
        lines.append(f"inv: {items(ch.get('inventory'))}")
        lines.append(
            f"guns: {items(ch.get('guns'))} | ammo: {items(ch.get('ammo'))} | "
            f"armor: {items(ch.get('armor'))}"
        )
        crafting = seq(ch.get("crafting"))
        if crafting:
            lines.append(
                "crafting: "
                + ", ".join(f"{c['recipe']} {c['count']}" for c in crafting)
            )
    else:
        lines.append("no character (dead or not started)")
    orders = reply.get("orders") or {}
    if orders.get("current") or orders.get("queued"):
        lines.append(
            f"orders: current {orders.get('current')}, {orders.get('queued')} "
            "queued"
        )
    lines.append(research(reply.get("research") or {}))
    return "\n".join(lines)


def research(info):
    queue = seq(info.get("queue"))
    if not info.get("current"):
        return "research: none"
    return (
        f"research: {info['current']} {info.get('progress', 0) * 100:.0f}% "
        f"| queue: {', '.join(queue)}"
    )


def scan(reply):
    lines = [
        f"scan around ({num(reply['x'])}, {num(reply['y'])}) r={reply['r']}"
    ]
    for patch in seq(reply.get("resources")):
        lines.append(
            f"  {patch['name']}: {amount(patch['amount'])} in {patch['tiles']} "
            "tiles,"
            f" x {patch['x1']}..{patch['x2']} y {patch['y1']}..{patch['y2']}, "
            f"dist {patch['dist']}"
        )
    trees = reply.get("trees") or {}
    lines.append(
        f"  trees: {trees.get('count', 0)}"
        + (
            f", nearest {tuple(trees['nearest'])}"
            if trees.get("nearest")
            else ""
        )
    )
    rocks = seq(reply.get("rocks"))
    if rocks:
        lines.append(
            "  rocks: "
            + ", ".join(
                f"{r['name']} ({num(r['x'])}, {num(r['y'])})" for r in rocks
            )
        )
    water = reply.get("water") or {}
    lines.append(
        f"  water: {water.get('tiles', 0)} tiles"
        + (
            f", nearest {tuple(water['nearest'])}"
            if water.get("nearest")
            else ""
        )
    )
    enemy = reply.get("enemy") or {}
    text = (
        f"  enemy: {enemy.get('nests', 0)} nests, {enemy.get('units', 0)} "
        "units in view"
    )
    if enemy.get("nearest_nest"):
        text += (
            f", nearest nest {tuple(enemy['nearest_nest'])} dist "
            f"{enemy['nearest_nest_dist']}"
        )
    lines.append(text)
    if reply.get("own"):
        lines.append(f"  own: {items(reply['own'])}")
    for box in seq(reply.get("containers")):
        lines.append(
            f"  {box['name']} ({num(box['x'])}, {num(box['y'])}): "
            f"{items(box['items'])}"
        )
    return "\n".join(lines)


def entity(e):
    head = f"{e['name']} ({num(e['x'])}, {num(e['y'])})"
    rest = fields(e, skip=("name", "x", "y", "items"))
    for inventory, counts in (e.get("items") or {}).items():
        rest += f" {inventory}[{items(counts)}]"
    return (head + " " + rest).rstrip()


def entities(reply):
    listed = seq(reply.get("entities"))
    lines = [entity(e) for e in listed]
    total = reply.get("total", len(listed))
    if total > len(listed):
        lines.append(f"... {total - len(listed)} more")
    return "\n".join(lines) if lines else "nothing found"


def found(reply):
    lines = []
    for e in seq(reply.get("found")):
        extra = f" amount {amount(e['amount'])}" if "amount" in e else ""
        lines.append(
            f"{e['name']} ({num(e['x'])}, {num(e['y'])}) dist "
            f"{num(e['dist'])}{extra}"
        )
    return "\n".join(lines) if lines else "nothing found"


def tile_map(reply):
    x0, y0, width = reply["x"], reply["y"], reply["w"]
    scale = reply.get("scale", 1)
    ruler = [" "] * width
    for column in range(width):
        x = x0 + column * scale
        if x % (10 * scale) == 0:
            label = str(x)
            if column + len(label) <= width:
                ruler[column : column + len(label)] = label
    lines = ["      " + "".join(ruler)]
    for offset, row in enumerate(seq(reply.get("rows"))):
        lines.append(f"{y0 + offset * scale:5d} {row}")
    return "\n".join(lines)


def recipes(reply):
    lines = []
    for r in seq(reply.get("recipes")):
        flags = []
        if not r.get("enabled"):
            flags.append("LOCKED")
        if r.get("by_hand"):
            flags.append("hand")
        lines.append(
            f"{r['name']}: {items(r['ingredients'])} -> {items(r['products'])} "
            f"in {num(r['seconds'])}s"
            f" [{r['category']}{', ' + ', '.join(flags) if flags else ''}]"
            f" made in: {', '.join(seq(r.get('made_in')))}"
        )
    return "\n".join(lines)


def cost(entry):
    if entry.get("trigger"):
        return "trigger: " + fields(entry["trigger"])
    c = entry.get("cost") or {}
    return (
        f"{c.get('count')} x ({items(c.get('packs'))}) "
        f"{num(c.get('seconds', 0))}s each"
    )


def tech(reply):
    prerequisites = reply.get("prerequisites") or {}
    lines = [
        f"{reply['name']}: "
        f"{'researched' if reply['researched'] else 'not researched'}"
        f"{'' if reply.get('enabled') else ' (disabled)'}",
        f"  cost: {cost(reply)}",
        "  needs: "
        + (
            ", ".join(
                f"{name}{'' if done else ' (missing)'}"
                for name, done in sorted(prerequisites.items())
            )
            or "-"
        ),
        "  unlocks: " + (", ".join(seq(reply.get("unlocks"))) or "-"),
    ]
    effects = seq(reply.get("effects"))
    if effects:
        lines.append("  effects: " + ", ".join(effects))
    return "\n".join(lines)


def techs(reply):
    lines = [research(reply.get("research") or {})]
    for entry in sorted(seq(reply.get("available")), key=lambda e: e["name"]):
        lines.append(f"  {entry['name']}: {cost(entry)}")
    return "\n".join(lines)


def production(reply):
    lines = []
    for kind in ("items", "fluids"):
        for name, row in sorted((reply.get(kind) or {}).items()):
            lines.append(
                f"{name}: made {amount(row['made'])} used {amount(row['used'])}"
                f" | per min, last 1m: +{num(row['made_1m'])} "
                f"-{num(row['used_1m'])}"
                f" | last 10m: +{num(row['made_10m'])} -{num(row['used_10m'])}"
            )
    return "\n".join(lines) if lines else "nothing produced yet"


def enemies(reply):
    lines = [
        f"evolution {num(reply['evolution'])}, pollution here "
        f"{num(reply['pollution'])}, known nests "
        f"{reply.get('total_nests', 0)}"
    ]
    for nest in seq(reply.get("nests")):
        lines.append(
            f"  {nest['name']} ({num(nest['x'])}, {num(nest['y'])}) dist "
            f"{nest['dist']}"
        )
    return "\n".join(lines)


def status(reply):
    groups = sorted(
        seq(reply.get("groups")),
        key=lambda g: (
            g["status"] in ("working", "normal"),
            g["name"],
            g["status"],
        ),
    )
    lines = []
    for group in groups:
        where = (
            " at "
            + " ".join(f"({num(x)},{num(y)})" for x, y in seq(group.get("at")))
            if seq(group.get("at"))
            else ""
        )
        lines.append(
            f"{group['count']:4d} {group['name']} {group['status']}{where}"
        )
    return "\n".join(lines) if lines else "no buildings"


def power(reply):
    top = sorted((reply.get("consumers") or {}).items(), key=lambda kv: -kv[1])[
        :8
    ]
    return (
        f"power: drawing {reply['consumed']} kW, generating "
        f"{reply['produced']} kW, engines can give {reply['capacity']} kW\n"
        "  biggest users (kW): "
        + ", ".join(f"{name} {kw}" for name, kw in top if kw)
    )
