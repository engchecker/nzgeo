"""Ground model helpers shared by the reports: subsoil profile, geology description and subsoil class evidence."""
from __future__ import annotations

import re

CONSISTENCY = r"very soft|soft|firm|very stiff|stiff|hard|very loose|loose|medium dense|very dense|dense"


def _layers(auger):
    """Merge 0.1 m auger readings into layers of the same material/condition."""
    out = []
    for L in auger["layers"]:
        f = L["fields"]
        mat = (f.get("material") or L["description"]).strip()
        cond = (f.get("condition") or "").strip()
        withs = (f.get("with") or "").strip()
        key = (mat.lower(), cond.lower(), withs.lower())
        if out and out[-1]["key"] == key:
            out[-1]["to"] = round(L["depth_m"] + 0.1, 2)
        else:
            out.append({"key": key, "soil": mat + (f" with {withs}" if withs else ""), "moisture": cond,
                        "from": L["depth_m"], "to": round(L["depth_m"] + 0.1, 2), "desc": L["description"]})
    return out


def _scala_range(field, a, b):
    vals = [r["blows"] for t in field.get("scala", []) for r in t["readings"]
            if r["blows"] is not None and a - 1e-9 <= r["depth_m"] < b - 1e-9]
    if not vals:
        return None
    lo, hi = int(min(vals)), int(max(vals))
    return f"{lo}" if lo == hi else f"{lo}–{hi}"


def subsoil_profile(field: dict | None) -> list[dict]:
    if not field:
        return []
    rows = []
    sv = (field.get("groundwater") or {}).get("shear_vane_kpa")
    auger = (field.get("auger") or [None])[0]
    end = 0.0
    if auger:
        for L in _layers(auger):
            m = re.search(CONSISTENCY, L["desc"], re.I)
            soil = L["soil"]
            if L["moisture"]:
                soil = f"{soil} ({L['moisture'].lower()})"
            rows.append({"soil": soil, "from": L["from"], "to": L["to"], "consistency": m.group(0) if m else None,
                         "scala": _scala_range(field, L["from"], L["to"]), "shear": f"{sv:g} kPa (average)" if sv else None})
            end = L["to"]
    scala_end = max((r["depth_m"] + 0.1 for t in field.get("scala", []) for r in t["readings"] if r["blows"] is not None), default=0)
    if scala_end > end + 0.05:
        rows.append({"soil": "Not logged (Scala penetrometer only)", "from": round(end, 2), "to": round(scala_end, 2),
                     "consistency": None, "scala": _scala_range(field, end, scala_end), "shear": None})
    return rows


def geology_text(a: dict | None) -> str | None:
    g = (a or {}).get("geology") or {}
    if g.get("status") != "ok":
        return None
    attrs = {k.lower(): v for k, v in (g.get("attributes") or {}).items()}
    bits = [g.get("unit_name") or g.get("description") or "an unnamed unit"]
    if g.get("unit_code"):
        bits[0] += f" ({g['unit_code']})"
    rock = g.get("main_rock") or attrs.get("main_rock") or attrs.get("mainrock")
    desc = g.get("description") if g.get("unit_name") else None
    terr = attrs.get("terrane") or attrs.get("terrane_name")
    sub = attrs.get("sub_rocks") or attrs.get("subrocks")
    t = "the " + bits[0]
    if desc:
        t += f", described as {str(desc).rstrip('.').lower()}"
    if rock and (not desc or str(rock).lower() not in str(desc).lower()):
        t += f"; main rock type {str(rock).lower()}"
    if sub:
        t += f" with {str(sub).lower()}"
    if g.get("age"):
        t += f", of {g['age']} age"
    if terr:
        t += f" ({terr} terrane)"
    return t


def subsoil_class_evidence(a: dict | None, field: dict | None, gg: dict | None) -> str:
    """Indicative NZS 1170.5 subsoil class reasoning for the engineer to confirm."""
    g = (a or {}).get("geology") or {}
    txt = " ".join(str(x) for x in (g.get("unit_name"), g.get("description"), g.get("main_rock"), g.get("age")) if x).lower()
    parts = []
    if re.search(r"greywacke|sandstone|mudstone|argillite|schist|basalt|andesite|granite|limestone|ignimbrite|rock", txt) and \
            not re.search(r"holocene|alluvi|gravel|sand\b|silt|peat|estuarine|swamp|dune", txt):
        parts.append("the mapped unit is rock, so rock or weathered rock is expected at shallow depth (Class B or C depending on "
                     "the depth of soil over rock)")
    elif re.search(r"holocene|alluvi|estuarine|swamp|peat|dune|beach", txt):
        parts.append("the mapped unit is recent sediment, which may be deep or soft (Class D, or E where very soft soils are present)")
    elif re.search(r"pleistocene|gravel|loess|terrace", txt):
        parts.append("the mapped unit is older sediment (typically Class C or D depending on depth)")
    if gg and gg["tests"]:
        ref = [s["reached_m"] for s in gg["tests"] if s["refusal"]]
        if ref:
            parts.append(f"Scala refusal at {min(ref):.1f}–{max(ref):.1f} m may indicate shallow rock, but this is unconfirmed")
    sc = (a or {}).get("site_class") or {}
    if sc.get("vs30"):
        parts.append(f"the regional Vs30 model gives about {sc['vs30']} m/s")
    return ("; ".join(parts) + ".") if parts else ""
