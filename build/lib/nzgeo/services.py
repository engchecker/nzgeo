"""Buried services: council three-waters pipes (wastewater, stormwater, water supply) at or near the site."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from shapely.geometry import Point, Polygon

from . import arcgis
from .geo import bearing_name, nearest, to_nztm
from .hazards import clean_attributes

SEARCH_M = 30

_DIAM = re.compile(r"diam|dia$|^dia|size|nominal|^nd$|^dn$|pipe_?size", re.I)
_MAT = re.compile(r"material|^mat$|pipe_?mat", re.I)
_OWN = re.compile(r"owner|asset_?owner|ownership", re.I)


def _pick(attrs, rx):
    return next((v for k, v in attrs.items() if rx.search(k) and v not in (None, "", " ", 0)), None)


def _query(rec, lon, lat, site_geom):
    url = f"{rec['service']}/{rec['layer_id']}"
    feats, retrieved = arcgis.query_near(url, lon, lat, SEARCH_M + 40)
    out = []
    for f in feats:
        d = f["geom"].distance(site_geom)
        if d > SEARCH_M:
            continue
        p = to_nztm(lon, lat)
        _, vec = nearest(p, f["geom"])
        a = f["attributes"]
        out.append({"type": rec.get("service_type") or "service", "layer": rec["layer"], "council": rec["council"],
                    "distance_m": round(d, 1), "crosses_site": d == 0, "direction": bearing_name(*vec) if d > 0 else None,
                    "diameter": _pick(a, _DIAM), "material": _pick(a, _MAT), "owner": _pick(a, _OWN),
                    "attributes": clean_attributes(a), "source": url, "retrieved": retrieved})
    return out


def lookup(lon: float, lat: float, parcel=None) -> dict:
    """Nearest pipe of each type within 30 m of the property boundary (or the site point)."""
    from .councils import councils_for_site
    from .discover import ensure
    recs = []
    for c in councils_for_site(lon, lat)[1]:
        recs += [l for l in ensure(c)["layers"] if "services" in l["hazards"]]
    site_geom = Polygon([to_nztm(lo, la) for lo, la in parcel]) if parcel and len(parcel) >= 3 else Point(to_nztm(lon, lat))
    found, errors = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for rec, res in zip(recs, ex.map(lambda r: _safe(_query, r, lon, lat, site_geom), recs)):
            if isinstance(res, Exception):
                errors.append(f"{rec['layer']}: {type(res).__name__}")
            else:
                found += res
    best = {}
    for f in sorted(found, key=lambda f: f["distance_m"]):
        best.setdefault(f["type"], f)
    return {"status": "ok" if recs else "no_layers", "layers_checked": len(recs), "search_m": SEARCH_M,
            "measured_from": "property boundary" if not isinstance(site_geom, Point) else "site point",
            "nearest": best, "all": found[:30], "errors": errors}


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        return e


def sentence(sv: dict | None) -> str | None:
    if not sv or sv.get("status") != "ok":
        return None
    if not sv["nearest"]:
        return (f"Council asset maps show no public wastewater, stormwater or water supply pipes within {sv['search_m']} m of the "
                f"{sv['measured_from']}.")
    bits = []
    for t, f in sv["nearest"].items():
        spec = " ".join(str(x) for x in (f.get("diameter") and f"{f['diameter']} mm" if str(f.get("diameter")).replace('.', '').isdigit()
                                          else f.get("diameter"), f.get("material")) if x)
        where = "crossing the property" if f["crosses_site"] else f"approximately {f['distance_m']:.0f} m to the {f['direction']}"
        bits.append(f"a {t} pipe{(' (' + spec + ')') if spec else ''} {where}")
    return ("Council asset maps show " + (", ".join(bits[:-1]) + " and " + bits[-1] if len(bits) > 1 else bits[0])
            + f" of the {sv['measured_from']}. Building over or near public pipes requires the network owner's approval, and "
              "locations shall be confirmed on site before excavation.")
