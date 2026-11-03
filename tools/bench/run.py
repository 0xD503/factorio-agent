"""Run one module of the blueprint set in a throwaway game and report it.

    python3 tools/bench/run.py SMELT-iron-steel [--minutes 10] [--keep]

The game runs from a temporary data directory with only the bench mod, which
is never installed anywhere else. The configured headless game is the one
`fx doctor` shows.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from fxa import install  # noqa: E402
from tools.blueprints.layout import POWERED  # noqa: E402
from tools.blueprints.modules import all_modules  # noqa: E402

MOD = Path(__file__).resolve().parent / "mod"
SAMPLE_TICKS = 3600
DEBUG = "FXA_BENCH_DEBUG" in os.environ


def lua_string(text):
    return json.dumps(text)


def lua_value(value):
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(lua_value(v) for v in value) + "}"
    if isinstance(value, dict):
        items = [f"[{lua_string(k)}]={lua_value(v)}" for k, v in value.items()]
        return "{" + ",".join(items) + "}"
    raise TypeError(value)


def payload(module):
    min_x = min(x for x, _ in module._taken)
    min_y = min(y for _, y in module._taken)
    ports = []
    for port in module.ports:
        entry = port.as_dict()
        entry["x"] -= min_x
        entry["y"] -= min_y
        ports.append(entry)
    return (
        "return "
        + lua_value(
            {
                "blueprint": module.string(),
                "ports": ports,
                "sample_every": SAMPLE_TICKS,
                "ore": module.ore,
                "research": module.research,
                "switch_at": module.switch_at,
                "supply": module.supply or None,
                "debug": DEBUG,
                "needs_power": any(
                    e["name"] in POWERED for e in module.entities
                ),
                "power_demand": module.power_demand,
                "width": module.box()[0],
                "height": module.box()[1],
            }
        )
        + "\n"
    )


def run_game(work, module, ticks):
    game = install.configured("server")
    mods = work / "mods"
    mod_dir = mods / "fxa-bench_0.1.0"
    shutil.copytree(MOD, mod_dir)
    (mod_dir / "payload.lua").write_text(payload(module), encoding="utf-8")
    entries = [{"name": name, "enabled": False} for name in game.builtin_mods()]
    for entry in entries:
        entry["enabled"] = entry["name"] == "base"
    entries.append({"name": "fxa-bench", "enabled": True})
    (mods / "mod-list.json").write_text(
        json.dumps({"mods": entries}), encoding="utf-8"
    )
    config = work / "config.ini"
    config.write_text(
        "[path]\n"
        f"read-data={game.data.as_posix()}\n"
        f"write-data={work.as_posix()}\n"
        "[other]\ncheck-updates=false\nenable-crash-log-uploading=false\n",
        encoding="utf-8",
    )
    common = [str(game.binary), "-c", str(config), "--mod-directory", str(mods)]
    save = work / "bench.zip"
    logs = []
    for args in (
        ["--create", str(save)],
        ["--benchmark", str(save), "--benchmark-ticks", str(ticks)],
    ):
        done = subprocess.run(
            common + args, capture_output=True, text=True, timeout=1800
        )
        logs.append(done.stdout)
        if done.returncode:
            raise SystemExit(
                f"game failed ({done.returncode}):\n{done.stdout[-3000:]}"
            )
    reports = [
        line.split("BENCH-REPORT ", 1)[1]
        for line in logs[-1].splitlines()
        if "BENCH-REPORT " in line
    ]
    if not reports:
        raise SystemExit("no report\n" + logs[-1][-3000:])
    report = json.loads(reports[-1])
    report["samples"] = [
        json.loads(line.split("BENCH-SAMPLE ", 1)[1])
        for line in logs[-1].splitlines()
        if "BENCH-SAMPLE " in line
    ]
    return report


def judge(module, report):
    """Problems found: (ok, list of lines to print)."""
    lines, ok = [], True
    for error in report.get("errors", []):
        lines.append(f"ERROR {error}")
        ok = False
    count = len(module.entities)
    lines.append(f"entities {report.get('ghosts')} of {count}")
    if report.get("ghosts") != count:
        ok = False
    samples = report.get("samples") or []
    if len(samples) < 3:
        return False, lines + ["too few samples"]
    # Skip the first samples as warm-up, and take the rate over the rest.
    first, last = samples[len(samples) // 2], samples[-1]
    minutes = (last["tick"] - first["tick"]) / 3600
    for item, wanted in module.targets.items():
        made = last["produced"].get(item, 0) - first["produced"].get(item, 0)
        rate = made / minutes
        met = rate >= wanted * 0.98
        ok = ok and met
        lines.append(
            f"{'ok  ' if met else 'LOW '} {item}: {rate:.0f}/min"
            f" (target {wanted})"
        )
    for item, wanted in module.totals.items():
        made = last["produced"].get(item, 0)
        met = made >= wanted
        ok = ok and met
        lines.append(
            f"{'ok  ' if met else 'LOW '} {item}: {made} in all"
            f" (at least {wanted})"
        )
    if "launches" in report or module.totals:
        lines.append(f"     rockets launched: {report.get('launches', 0)}")
    for item, wanted in module.stock.items():
        held = last.get("stock", {}).get(item, 0)
        met = held >= wanted
        ok = ok and met
        lines.append(f"{'ok  ' if met else 'NONE'} {item}: {held} in chests")
    if module.rocket_parts:
        # Parts reset when a rocket is finished, so take the rate up to the
        # highest count seen.
        best = max(samples, key=lambda s: s.get("parts", 0))
        rate = best.get("parts", 0) / (best["tick"] / 3600)
        met = rate >= module.rocket_parts
        ok = ok and met
        lines.append(
            f"{'ok  ' if met else 'LOW '} rocket parts: {rate:.1f}/min"
            f" (target {module.rocket_parts})"
        )
    if module.research_target:
        rate = (last["research"] - first["research"]) / minutes
        met = rate >= module.research_target * 0.95
        ok = ok and met
        lines.append(
            f"{'ok  ' if met else 'LOW '} research: {rate:.1f} units/min"
            f" (target {module.research_target})"
        )
    if module.power_target:
        made = last.get("generated", 0)
        met = made >= module.power_target
        ok = ok and met
        lines.append(
            f"{'ok  ' if met else 'LOW '} power: {made / 1e6:.1f} MW"
            f" (target {module.power_target / 1e6:.1f})"
        )
    for item, wanted in module.fluid_targets.items():
        made = last.get("fluids", {}).get(item, 0)
        made -= first.get("fluids", {}).get(item, 0)
        rate = made / minutes
        met = rate >= wanted * 0.95
        ok = ok and met
        lines.append(
            f"{'ok  ' if met else 'LOW '} {item}: {rate:.0f}/min"
            f" (target {wanted})"
        )
    if module.stock:
        lines.append("first in chests, minutes:")
        for item in module.stock:
            when = next(
                (
                    s["tick"] / 3600
                    for s in samples
                    if s.get("stock", {}).get(item, 0) > 0
                ),
                None,
            )
            when = "never" if when is None else f"{when:.0f}"
            lines.append(f"     {item}: {when}")
    if last.get("tanks"):
        levels = [round(t) for t in last["tanks"]]
        lines.append(f"     tanks: {levels}")
    if DEBUG and last.get("net"):
        for entry in last["net"]:
            lines.append(f"     {entry}")
        for sample in samples:
            for entry in sample.get("net") or []:
                if entry.get("n") == "rocket-silo":
                    lines.append(
                        f"     minute {sample['tick'] / 3600:.0f}: silo "
                        f"{entry.get('silo')} parts {sample.get('parts')}"
                    )
    if DEBUG and last.get("plants"):
        for plant in last["plants"]:
            lines.append(f"     {plant}")
    bad = {"no_power", "not_plugged_in_anywhere", "not_connected"}
    for name, statuses in sorted(last["machines"].items()):
        lines.append(f"     {name}: {statuses}")
        if bad.intersection(statuses):
            ok = False
    return ok, lines


def check_book(args):
    """Import the book in a throwaway game and count its pages."""
    from tools.blueprints.layout import Module

    string = (REPO / "dist" / "blueprints" / "BOOK.txt").read_text().strip()
    probe = Module("BOOK")
    probe.add("small-electric-pole", 0, 0)
    probe.string = lambda: string
    work = Path(tempfile.mkdtemp(prefix="fxa-bench-"))
    try:
        (work / "mods").mkdir()
        report = run_game(work, probe, 7200)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    errors = report.get("errors", [])
    print(f"book pages: {report.get('book_pages')}, errors: {errors or 'none'}")
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="a module name, or `all`")
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--keep", action="store_true", help="keep the work dir")
    parser.add_argument(
        "--book",
        action="store_true",
        help="only check that dist/blueprints/BOOK.txt imports",
    )
    args = parser.parse_args()
    modules = all_modules()
    if args.book:
        return check_book(args)
    if args.module == "all":
        # Probes and turrets have nothing to measure.
        names = [
            n for n in modules if not n.startswith("PROBE") and n != "TUR"
        ]
    elif args.module in modules:
        names = [args.module]
    else:
        raise SystemExit(f"unknown module; have {', '.join(modules)}")
    failed = []
    for name in names:
        module = modules[name]
        work = Path(tempfile.mkdtemp(prefix="fxa-bench-"))
        try:
            (work / "mods").mkdir()
            report = run_game(work, module, int(args.minutes * 3600) + 60)
            ok, lines = judge(module, report)
            print(f"{module.name}: {'PASS' if ok else 'FAIL'}")
            if not ok or len(names) == 1:
                print("\n".join(lines))
            if not ok:
                failed.append(name)
        finally:
            if args.keep:
                print(f"work dir: {work}")
            else:
                shutil.rmtree(work, ignore_errors=True)
    if len(names) > 1:
        print(f"{len(names) - len(failed)} of {len(names)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
