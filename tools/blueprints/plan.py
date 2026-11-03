"""The run base: how many of each module, and what that adds up to.

    python3 tools/blueprints/plan.py

Copies come from the sizing in the plan: 60 red, green and blue science a
minute, 30 purple and yellow, about 15 military, and a rocket's parts in about
30 minutes once research is done. Power is the machines' rated draw, plus an
average for inserters; it is an estimate, not a measurement.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tools.blueprints.modules import all_modules  # noqa: E402

# Module -> (copies, stage, why that many)
RUN = {
    "PWR": (5, 1, "18 MW each against about 70-85 MW"),
    "MINE-iron": (8, 1, "per patch; iron ore about 64/s"),
    "TUR": (1, 1, "first defence"),
    "MALL-1": (1, 2, ""),
    "SMELT-iron-steel": (3, 3, "64 iron plates/s; built as stone first"),
    "SMELT-copper-steel": (2, 3, "45 copper plates/s"),
    "STEEL-steel": (2, 3, "6.6 steel/s"),
    "BRICK-steel": (1, 3, "3 bricks/s"),
    "SCI-RG": (1, 3, "60 + 60"),
    "SCI-M": (1, 3, "about 15"),
    "LAB": (1, 3, "30 labs"),
    "MALL-2": (1, 3, ""),
    "OIL": (1, 4, "7 refineries; basic first"),
    "CHEM": (1, 4, "plastic 15/s, sulfur, acid"),
    "GREEN": (1, 4, "18/s against 17"),
    "RED": (2, 4, "4/s against 3.8"),
    "ENGINE": (1, 4, "81/min against 74"),
    "SCI-B": (1, 4, "60"),
    "FRAME": (1, 5, "13.5/min: yellow and robots"),
    "BOTS": (1, 5, ""),
    "SCI-P": (1, 6, "30"),
    "LDS": (1, 6, "30/min: yellow, then the rocket"),
    "BLUE": (1, 6, "27/min: yellow, then the rocket"),
    "SCI-Y": (1, 6, "30"),
    "MOD": (1, 7, "silo productivity 3s"),
    "RF": (1, 7, "24/min"),
    "CONCRETE": (1, 7, "1000 for the silo"),
    "SILO": (1, 7, ""),
}

# After the launch: module -> (copies, why). Not part of the 6-hour run.
AFTER = {
    "SAT": (1, "satellites: 1000 space science a launch, one every ~25 min"),
    "SCI-P": (1, "a second copy: purple to 60"),
    "SCI-Y": (1, "a second copy: yellow to 60"),
    "LDS": (1, "yellow at 60 and rockets together"),
    "BLUE": (1, "yellow at 60 and rockets together"),
    "OIL": (1, "a second block: about 2,800% yield in all"),
    "SMELT-iron-steel": (1, "iron to about 120/s"),
    "SMELT-copper-steel": (1, "copper to about 100/s"),
}

# Rated draw in kW (2.1.24 data); inserters are an average of use.
POWER_KW = {
    "assembling-machine-1": 75,
    "assembling-machine-2": 150,
    "chemical-plant": 210,
    "oil-refinery": 420,
    "lab": 60,
    "electric-mining-drill": 90,
    "rocket-silo": 250,
    "roboport": 50,
    "pump": 29,
    "inserter": 8,
    "long-handed-inserter": 10,
    "fast-inserter": 20,
}


def main():
    modules = all_modules()
    total_bill, total_area, total_kw = {}, 0, 0
    print(f"{'module':22} {'copies':>6} {'size':>8} {'stage':>5}  why")
    for name, (copies, stage, why) in RUN.items():
        module = modules[name]
        width, height = module.box()
        total_area += width * height * copies
        for item, count in module.bill().items():
            total_bill[item] = total_bill.get(item, 0) + count * copies
            total_kw += POWER_KW.get(item, 0) * count * copies
        print(
            f"{name:22} {copies:6} {width:>3}x{height:<4} {stage:5}  {why}"
        )
    print(f"\narea of all module copies: {total_area} tiles", end="")
    print(f" (a {int(total_area**0.5)}-tile square, before any belts between)")
    print("excluding PWR and MINE, which stand at water and ore:", end=" ")
    core = sum(
        modules[n].box()[0] * modules[n].box()[1] * c
        for n, (c, _, _) in RUN.items()
        if n not in ("PWR", "MINE-iron")
    )
    print(f"{core} tiles ({int(core**0.5)} square)")
    print(f"rated power of the machines: about {total_kw / 1000:.0f} MW")
    print("\nafter the launch:")
    for name, (copies, why) in AFTER.items():
        print(f"  {copies} x {name:20} {why}")
    print("\nto build it all:")
    for item, count in sorted(total_bill.items(), key=lambda kv: -kv[1]):
        print(f"  {count:6}  {item}")


if __name__ == "__main__":
    main()
