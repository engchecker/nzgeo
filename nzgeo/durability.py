"""Durability exposure: NZS 3604 exposure zone and NZS 3404.3:2026 atmospheric corrosivity.

Bundle keys (digitised from licensed copies of the standards):
  nzs3604_<edition>_exposure_grid  : georeferenced Figure 4.2 (classes B, C, D)
  nzs3604_<edition>_exposure        : alternative GeoJSON polygons, property 'zone'
  nzs3404_3_2026_table2             : Table 2 distance rules and surface-specific categories
  nzs3404_3_2026_corrosivity_grid   : georeferenced Figures 1 to 7 (indicative macroclimate)
NZS 3604 Zone D distance rules are applied in code. For NZS 3404.3, Table 2 governs; the figures are design
aids and are reported alongside, with any disagreement flagged.
"""
from __future__ import annotations

from shapely.geometry import Point, shape

from . import zonegrid

SURFACES = ("exposed", "sheltered", "wet", "dry", "damp")
_ORDER = ["C1", "C2", "C3", "C4", "C5", "CX"]


def _zone_from_polygons(fc: dict, lon: float, lat: float, prop: str):
    p = Point(lon, lat)
    for f in fc.get("features", []):
        if shape(f["geometry"]).contains(p):
            return f["properties"].get(prop)
    return None


def nzs3604_exposure(lon: float, lat: float, *, coast_m: float | None, offshore_island: bool,
                     geothermal_m: float | None, bundle: dict | None, edition: int, standards_status: dict | None) -> dict:
    std = f"NZS 3604:{edition}"
    out = {"standard": std, "flags": []}
    if standards_status and standards_status.get("status") == "newer_cited_update_required":
        out.update(status="blocked", zone=None,
                   reason=f"{standards_status['newest_cited_label']} is now cited. Digitise its exposure zone map "
                          f"into the bundle as nzs3604_{standards_status['newest_cited']}_exposure_grid before issue.")
        return out
    rules = []
    if offshore_island:
        rules.append("offshore island")
    if coast_m is not None and coast_m <= 500:
        rules.append(f"within 500 m of the coastline ({coast_m} m), which includes harbours")
    if geothermal_m is not None and geothermal_m <= 50:
        rules.append(f"within 50 m of a geothermal hot spot ({geothermal_m} m)")
    grid = (bundle or {}).get(f"nzs3604_{edition}_exposure_grid")
    mapped = zonegrid.lookup(grid, lon, lat) if grid else None
    if mapped:
        out["map"] = mapped
    if rules:
        out.update(status="ok", zone="D", basis="Clause 4.2.2 distance rules: " + "; ".join(rules))
    elif mapped and mapped["status"] == "ok":
        out.update(status="ok", zone=mapped["class"],
                   basis=f"{std} {mapped['figure']} ({mapped['map']}), digitised; map fit {mapped['fit']['median_m']} m median")
        if mapped["class"] == "D":
            out["basis"] += ". Shown white on the map (Zone D)"
        if mapped["near_boundary"]:
            out["flags"].append(f"Within {mapped['nearest_other_class_m']} m of a zone boundary on Figure 4.2; "
                                "at map scale the boundary may be several hundred metres out. Confirm the zone.")
    else:
        fc = (bundle or {}).get(f"nzs3604_{edition}_exposure")
        z = _zone_from_polygons(fc, lon, lat, "zone") if fc else None
        if z:
            out.update(status="ok", zone=z, basis=f"{std} exposure zone map (digitised polygons)")
        else:
            out.update(status="partial", zone="B or C",
                       basis="Outside the Zone D distance rules; the zone map is not in the data bundle",
                       reason=f"Add nzs3604_{edition}_exposure_grid to the bundle to resolve B or C")
    if coast_m is None:
        out["flags"].append("Distance to coast not measured; Zone D rule not checked")
    if coast_m is not None and coast_m <= 500:
        out["flags"].append("Check for Zone E (E2/AS1): beachfront with rough seas or surf. "
                            "NZS 3604 treats D and E alike for structural fixings.")
    if coast_m is not None and 500 < coast_m <= 1000:
        out["flags"].append("Within 100 m of a tidal estuary or sheltered inlet is also Zone D; check aerial imagery")
    if geothermal_m is not None and 50 < geothermal_m <= 500:
        out["flags"].append(f"Geothermal feature {geothermal_m} m away; BRANZ SR458 recommends treating 500 m as the "
                            "boundary, consistent with NZS 3404.3")
    return out


def _table2_row(t2: dict, coast_type: str, coast_m: float | None) -> str | None:
    rules = t2["distance_rules_m"].get(coast_type)
    if not rules:
        return None
    d = float("inf") if coast_m is None else coast_m
    for row, limit in rules:
        if limit is None or d <= limit:
            return row
    return None


def nzs3404_3_corrosivity(lon: float, lat: float, *, coast_m: float | None, coast_type: dict | None,
                          coast_type_override: str | None, beyond_m: float | None, geothermal_m: float | None,
                          surface_condition: str | None, bundle: dict | None) -> dict:
    out = {"standard": "NZS 3404.3:2026", "flags": []}
    t2 = (bundle or {}).get("nzs3404_3_2026_table2")
    grid = (bundle or {}).get("nzs3404_3_2026_corrosivity_grid")
    if not t2:
        out.update(status="unavailable", macro_category=None,
                   reason="NZS 3404.3 Table 2 is not in the data bundle (key 'nzs3404_3_2026_table2')")
        return out
    ctype = coast_type_override or (coast_type or {}).get("type")
    out["coast_type"] = ctype
    out["coast_type_label"] = t2["coast_types"].get(ctype or "", None)
    out["coast_type_source"] = "engineer" if coast_type_override else "sector map"
    if coast_m is None and beyond_m:
        coast_m = beyond_m + 1  # beyond the search radius
    row = None
    if geothermal_m is not None and geothermal_m <= t2["geothermal_m"]["near"]:
        row = "GEO_NEAR"
    elif ctype:
        row = _table2_row(t2, ctype, coast_m)
    if row is None:
        out.update(status="partial", macro_category=None, reason="Coast type or distance to coast unknown")
    else:
        r = t2["rows"][row]
        out.update(status="ok", row=row, macro_category=r["macro"], characterised_by=r["characterised_by"],
                   surface_specific={s: r[s] for s in SURFACES},
                   basis=f"Table 2: {out['coast_type_label'] or 'geothermal zone'}, "
                         f"{'%d m' % coast_m if coast_m is not None and coast_m < 1e7 else 'distance unknown'} from the coast")
        if surface_condition in SURFACES:
            out["surface_condition"] = surface_condition
            out["surface_category"] = r[surface_condition]
        if row == "GEO_NEAR":
            out["flags"].append(f"Within 500 m of a geothermal source ({geothermal_m} m): external categories "
                                "need a corrosivity assessment (C2.2.2); can range up to CX")
    if geothermal_m is not None and 500 < geothermal_m <= 1500:
        out["flags"].append(f"Geothermal feature {geothermal_m} m away: mild geothermal influence possible; apply the "
                            "smell test (C2.1.2a) before using the distance-from-sea category")
    if not coast_type_override and coast_m is not None and coast_m <= 5000:
        out["flags"].append((coast_type or {}).get("note") or "Confirm the coast type")
    if (coast_type or {}).get("near_transition"):
        out["flags"].append("Near the change between west/south and east coast types; confirm which applies")
    if ctype not in (None, "harbour") and coast_m is not None and 50 < coast_m <= 1000:
        out["flags"].append("If the nearest water is a sheltered harbour, the harbour row may give a lower category")
    if coast_m is not None and coast_m <= 500:
        out["flags"].append("The C4 and C5 environments may extend further inland with prevailing winds and local conditions")
    # Indicative maps (Figures 1 to 7)
    mapped = zonegrid.lookup(grid, lon, lat) if grid else None
    if mapped and mapped["status"] == "ok":
        cls = mapped["class"]
        if cls == "band500":
            cls = "C4 (500 m from sea band)"
        out["map"] = {**mapped, "class": cls}
        mc = "C4" if cls.startswith("C4") else cls
        tc = out.get("macro_category")
        if tc in _ORDER and mc in _ORDER and mc != tc:
            higher = _ORDER.index(mc) > _ORDER.index(tc)
            out["flags"].append(f"{mapped['figure']} ({mapped['map']}) shows {cls}, Table 2 gives {tc}. "
                                + ("The map is more severe; consider adopting it or obtaining specialist advice (C2.1.2a)."
                                   if higher else "Table 2 governs; the map is a design aid."))
        if mapped["near_boundary"]:
            out["flags"].append(f"Within {mapped['nearest_other_class_m']} m of a zone boundary on {mapped['figure']}")
    out["flags"].append("Check for industrial emission sources within 1.5 km (AS/NZS 2312.1)")
    return out
