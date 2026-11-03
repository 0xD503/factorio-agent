"""Write every module's blueprint string to dist/blueprints/.

    python3 tools/blueprints/build.py

Paste a string with the game's "Import string" button in the blueprint library.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tools.blueprints import codec  # noqa: E402
from tools.blueprints.layout import GAME_VERSION  # noqa: E402
from tools.blueprints.modules import all_modules  # noqa: E402
from tools.blueprints.plan import AFTER, RUN  # noqa: E402


def book(modules):
    """One book with every module of the run in stage order, then those only
    needed after the launch."""
    names = sorted(RUN, key=lambda n: RUN[n][1])
    names += [n for n in AFTER if n not in RUN]
    pages = [
        {"index": i, "blueprint": modules[n].blueprint()["blueprint"]}
        for i, n in enumerate(names)
    ]
    return {
        "blueprint_book": {
            "item": "blueprint-book",
            "label": "6-hour rocket",
            "description": "Modules in build order. See tools/blueprints/"
            "README.md in factorio-agent.",
            "blueprints": pages,
            "active_index": 0,
            "version": GAME_VERSION,
        }
    }


def main():
    out = REPO / "dist" / "blueprints"
    out.mkdir(parents=True, exist_ok=True)
    for name, module in all_modules().items():
        (out / f"{name}.txt").write_text(module.string() + "\n", "utf-8")
        width, height = module.box()
        print(f"{name}: {width}x{height}, {module.bill()}")
    (out / "BOOK.txt").write_text(codec.encode(book(all_modules())) + "\n")
    print(f"written to {out}, with BOOK.txt holding the run's modules")


if __name__ == "__main__":
    main()
