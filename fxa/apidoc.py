"""Look things up in the Lua API reference shipped with the game (for harness
development).

    fx apidoc LuaEntity.set_recipe event:on_tick concept:Ingredient
    define:inventory class:LuaForce

Full game installs carry doc-html/runtime-api.json; the headless build does not.
"""

import json
import sys


def load():
    from fxa import install

    for role in ("client", "server"):
        try:
            path = install.configured(role).api_doc()
        except install.InstallError:
            continue
        if path:
            return json.loads(path.read_text(encoding="utf-8"))
    raise SystemExit(
        "fx apidoc: no doc-html/runtime-api.json in the configured installs "
        "(headless builds lack it)"
    )


def main(queries):
    api = load()
    cls = {c["name"]: c for c in api["classes"]}

    def ty(t):
        if isinstance(t, str):
            return t
        if t is None:
            return "nil"
        ct = t.get("complex_type")
        if ct == "optional":
            return ty(t["value"]) + "?"
        if ct == "array":
            return "[" + ty(t["value"]) + "]"
        if ct == "dictionary":
            return "{" + ty(t["key"]) + ":" + ty(t["value"]) + "}"
        if ct == "union":
            return "|".join(ty(o) for o in t["options"])
        if ct == "literal":
            return repr(t["value"])
        if ct == "type":
            return ty(t["value"])
        if ct in ("table", "tuple"):
            return (
                "{"
                + ", ".join(
                    p["name"]
                    + ("?" if p.get("optional") else "")
                    + ":"
                    + ty(p["type"])
                    for p in t.get("parameters", [])
                )
                + "}"
            )
        if ct == "LuaStruct":
            return (
                "struct{"
                + ", ".join(a["name"] for a in t.get("attributes", []))
                + "}"
            )
        if ct == "function":
            return "function"
        return ct or str(t)

    def desc(d, n=500):
        return " ".join(d.split())[:n]

    for q in queries:
        print("##", q)
        if q.startswith("event:"):
            for e in api["events"]:
                if q[6:] in e["name"]:
                    print(
                        " ",
                        e["name"],
                        "{"
                        + ", ".join(
                            p["name"]
                            + ("?" if p.get("optional") else "")
                            + ":"
                            + ty(p["type"])
                            for p in e["data"]
                        )
                        + "}",
                    )
                    print("    ", desc(e["description"], 300))
        elif q.startswith("concept:"):
            for c in api["concepts"]:
                if c["name"] == q[8:]:
                    print(" ", ty(c["type"]))
                    print("    ", desc(c["description"]))
        elif q.startswith("define:"):

            def walk(nodes, path):
                for d in nodes:
                    p = path + [d["name"]]
                    if ".".join(p) == q[7:]:
                        print(
                            " ",
                            ", ".join(v["name"] for v in d.get("values", []))
                            or [s["name"] for s in d.get("subkeys", [])],
                        )
                    walk(d.get("subkeys", []), p)

            walk(api["defines"], [])
        elif q.startswith("class:"):
            c = cls[q[6:]]
            print("  methods:", ", ".join(m["name"] for m in c["methods"]))
            print("  attrs:", ", ".join(a["name"] for a in c["attributes"]))
        else:
            cn, mn = q.split(".")
            c = cls[cn]
            found = False
            for m in c["methods"]:
                if m["name"] == mn:
                    found = True
                    print(
                        "  ("
                        + ", ".join(
                            p["name"]
                            + ("?" if p.get("optional") else "")
                            + ":"
                            + ty(p["type"])
                            for p in sorted(
                                m["parameters"], key=lambda p: p["order"]
                            )
                        )
                        + ") ->",
                        ", ".join(
                            ty(r["type"]) for r in m.get("return_values", [])
                        ),
                        "| table"
                        if m.get("format", {}).get("takes_table")
                        else "",
                    )
                    for vg in m.get("variant_parameter_groups", []) or []:
                        print(
                            "    variant",
                            vg["name"],
                            ":",
                            ", ".join(
                                p["name"]
                                + ("?" if p.get("optional") else "")
                                + ":"
                                + ty(p["type"])
                                for p in vg["parameters"]
                            ),
                        )
                    print("    ", desc(m["description"]))
            for a in c["attributes"]:
                if a["name"] == mn:
                    found = True
                    print(
                        "  attr read:",
                        ty(a.get("read_type")),
                        "write:",
                        ty(a.get("write_type")),
                    )
                    print("    ", desc(a["description"]))
            if not found:
                print("  NOT FOUND")


if __name__ == "__main__":
    main(sys.argv[1:])
