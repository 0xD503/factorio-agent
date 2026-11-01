"""One-line order syntax for the CLI.

    walk X Y
    mine X Y                      the building, tree or rock at that spot
    mine NAME X Y [xN] [rR]       N units of ore (or N entities) of that name
                                  within R
    mine tree|rock X Y [xN] [rR]
    craft RECIPE [N] [wait]
    wait N | wait craft | wait have ITEM N | wait item X Y ITEM N
    place ITEM X Y [n|e|s|w] [recipe=NAME] [ug=input|output]
    put X Y ITEM [N]
    take X Y [ITEM] [N]
    recipe X Y NAME
    rotate X Y [n|e|s|w]
    filter X Y [ITEM...]          inserter moves only these items; none clears
                                  it
    mirror X Y                    flip a machine so its fluid inlets swap sides
    launch X Y
    pickup [X Y]
    equip ITEM [SLOT]             gun, armour or ammunition into its slot

Several orders are separated by ';'.
"""

from fxa import game

DIRECTIONS = {"n", "e", "s", "w", "ne", "se", "sw", "nw"}
KINDS = {"tree", "rock"}


class ParseError(ValueError):
    pass


def _number(text):
    try:
        value = float(text)
    except ValueError:
        raise ParseError(f"expected a number, got {text!r}") from None
    return int(value) if value.is_integer() else value


def _is_number(text):
    try:
        float(text)
    except ValueError:
        return False
    return True


def _count(text):
    value = _number(text)
    if not isinstance(value, int) or value < 1:
        raise ParseError(f"expected a positive whole number, got {text!r}")
    return value


def _take(words, n, what):
    if len(words) < n:
        raise ParseError(f"{what}: missing arguments")
    return words[:n], words[n:]


def _parse_one(text):
    words = text.split()
    verb, rest = words[0], words[1:]

    if verb == "walk":
        (x, y), rest = _take(rest, 2, text)
        order = game.walk(_number(x), _number(y))

    elif verb == "mine":
        name = kind = None
        if rest and not _is_number(rest[0]):
            if rest[0] in KINDS:
                kind = rest[0]
            else:
                name = rest[0]
            rest = rest[1:]
        (x, y), rest = _take(rest, 2, text)
        count = radius = None
        while rest and rest[0][:1] in ("x", "r") and _is_number(rest[0][1:]):
            if rest[0][0] == "x":
                count = _count(rest[0][1:])
            else:
                radius = _number(rest[0][1:])
            rest = rest[1:]
        order = game.mine(
            _number(x),
            _number(y),
            name=name,
            kind=kind,
            count=count,
            radius=radius,
        )

    elif verb == "craft":
        (recipe,), rest = _take(rest, 1, text)
        count, wait = 1, False
        if rest and _is_number(rest[0]):
            count, rest = _count(rest[0]), rest[1:]
        if rest and rest[0] == "wait":
            wait, rest = True, rest[1:]
        order = game.craft(recipe, count, wait=wait)

    elif verb == "uncraft":
        (recipe,), rest = _take(rest, 1, text)
        count = None
        if rest and _is_number(rest[0]):
            count, rest = _count(rest[0]), rest[1:]
        order = game.uncraft(recipe, count)

    elif verb == "wait":
        (first,), rest = _take(rest, 1, text)
        if first == "craft":
            order = game.wait(craft=True)
        elif first == "have":
            (item, count), rest = _take(rest, 2, text)
            order = game.wait(have=item, count=_count(count))
        elif first == "item":
            (x, y, item, count), rest = _take(rest, 4, text)
            order = game.wait(
                item=item, count=_count(count), x=_number(x), y=_number(y)
            )
        else:
            order = game.wait(ticks=_count(first))

    elif verb == "place":
        (item, x, y), rest = _take(rest, 3, text)
        direction = recipe = ug_type = None
        while rest:
            word = rest[0]
            if word in DIRECTIONS:
                direction = word
            elif word.startswith("recipe="):
                recipe = word[7:]
            elif word.startswith("ug="):
                ug_type = word[3:]
            else:
                break
            rest = rest[1:]
        order = game.place(
            item,
            _number(x),
            _number(y),
            dir=direction,
            recipe=recipe,
            ug_type=ug_type,
        )

    elif verb == "put":
        (x, y, item), rest = _take(rest, 3, text)
        count = None
        if rest:
            count, rest = _count(rest[0]), rest[1:]
        order = game.put(_number(x), _number(y), item, count)

    elif verb == "take":
        (x, y), rest = _take(rest, 2, text)
        item = count = None
        if rest and not _is_number(rest[0]):
            item, rest = rest[0], rest[1:]
        if rest:
            count, rest = _count(rest[0]), rest[1:]
        order = game.take(_number(x), _number(y), item, count)

    elif verb == "recipe":
        (x, y, name), rest = _take(rest, 3, text)
        order = game.recipe(_number(x), _number(y), name)

    elif verb == "rotate":
        (x, y), rest = _take(rest, 2, text)
        direction = None
        if rest and rest[0] in DIRECTIONS:
            direction, rest = rest[0], rest[1:]
        order = game.rotate(_number(x), _number(y), direction)

    elif verb == "filter":
        (x, y), rest = _take(rest, 2, text)
        order, rest = game.filter(_number(x), _number(y), *rest), []

    elif verb == "mirror":
        (x, y), rest = _take(rest, 2, text)
        order = game.mirror(_number(x), _number(y))

    elif verb == "launch":
        (x, y), rest = _take(rest, 2, text)
        order = game.launch(_number(x), _number(y))

    elif verb == "pickup":
        if rest:
            (x, y), rest = _take(rest, 2, text)
            order = game.pickup(_number(x), _number(y))
        else:
            order = game.pickup()

    elif verb == "equip":
        (item,), rest = _take(rest, 1, text)
        slot = None
        if rest:
            slot, rest = _count(rest[0]), rest[1:]
        order = game.equip(item, slot)

    else:
        raise ParseError(f"unknown order {verb!r}")

    if rest:
        raise ParseError(f"{text.strip()!r}: unexpected {' '.join(rest)!r}")
    return order


def parse(text):
    """Turn 'walk 3 4; craft iron-gear-wheel 2' into a list of orders."""
    return [_parse_one(part) for part in text.split(";") if part.strip()]
