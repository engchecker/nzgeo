"""Contaminated land: regional council registers of HAIL sites (Hazardous Activities and Industries List).

Each region keeps its own register under its own name (Selected Land Use Register, Listed Land Use Register,
HAIL database …). Public map layers are queried directly; for every region the council's property search
service is also given, because the published layers are not always complete and some councils only release
records on request.

Sources, in order:
  1. The register layers listed in REGISTERS (or found in a council's ArcGIS services by name)
  2. Layers in the council catalogue classified as 'contaminated' during council discovery
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import arcgis
from .geo import to_nztm
from .hazards import clean_attributes

NAME_RX = re.compile(r"\bhail\b|selected land ?use|\bslur\b|\bllur\b|listed land ?use|contaminat|land ?use register|"
                     r"hazardous activit|\bslu (points|polygons)\b", re.I)
NEAR_M = 100

# region (Stats NZ 2023 regional council name) -> register name, services to search for register layers, and how to request a search
REGISTERS = {
    "Northland Region": {"name": "Selected Land-use Register", "council": "Northland Regional Council",
                         "services": ["https://services2.arcgis.com/J8errK5dyxu7Xjf7/ArcGIS/rest/services/IRIS_SLUs/FeatureServer"]},
    "Wellington Region": {"name": "Selected Land Use Register (SLUR)", "council": "Greater Wellington Regional Council",
                          "services": ["https://mapping1.gw.govt.nz/arcgis/rest/services/GW/Environment_TA/MapServer",
                                       "https://mapping.gw.govt.nz/arcgis/rest/services/GW/Environment_TA/MapServer"],
                          "request": "https://archive.gw.govt.nz/environment/land-use/contaminated-land-slur"},
    "Canterbury Region": {"name": "Listed Land Use Register (LLUR)", "council": "Environment Canterbury",
                          "webmaps": ["4e2002e69399460f96d3ac5a94dfb131"],
                          "request": "https://canterburymaps.govt.nz/map?webmap=4e2002e69399460f96d3ac5a94dfb131"},
    "Bay of Plenty Region": {"name": "HAIL register", "council": "Bay of Plenty Regional Council",
                             "request": "https://boprc.govt.nz/do-it-online/request-or-enquire/hail-request"},
}
GENERIC = {"name": "HAIL / contaminated land register", "council": None}


def _layers_in(service: str) -> list[dict]:
    try:
        return [dict(l, url=f"{service.rstrip('/')}/{l['id']}") for l in arcgis.layers(service)
                if NAME_RX.search(l["name"] or "") or NAME_RX.search(l.get("description") or "")]
    except Exception:
        return []


def _webmap_layers(item_id: str) -> list[dict]:
    """Operational layers of a public ArcGIS Online web map whose names look like a register."""
    from .http import fetch
    try:
        body, _ = fetch(f"https://www.arcgis.com/sharing/rest/content/items/{item_id}/data", {"f": "json"}, ttl_days=30)
    except Exception:
        return []
    out = []

    def walk(layers):
        for l in layers or []:
            if l.get("layers"):
                walk(l["layers"])
            url = l.get("url")
            if url and (NAME_RX.search(l.get("title") or "") or NAME_RX.search(url)):
                if re.search(r"/\d+$", url):
                    out.append({"url": url, "name": l.get("title") or url})
                else:
                    out.extend(_layers_in(url))
    walk(body.get("operationalLayers"))
    return out


def _query(layer: dict, lon: float, lat: float) -> list[dict]:
    feats, _ = arcgis.query_near(layer["url"], lon, lat, NEAR_M)
    if not feats:
        return []
    from shapely.geometry import Point
    x, y = to_nztm(lon, lat)
    p = Point(x, y)
    out = []
    for f in feats:
        d = f["geom"].distance(p)
        a = f["attributes"]
        low = {k.lower(): v for k, v in a.items()}
        pick = lambda *ks: next((low[k] for k in ks if low.get(k) not in (None, "", " ")), None)  # noqa: E731
        out.append({"layer": layer["name"], "distance_m": round(d), "inside": d == 0,
                    "site": pick("sitename", "site_name", "slu_sitename", "name", "site", "address"),
                    "category": pick("category", "hailcategories", "hail_category", "hail", "anzecc", "activity",
                                     "land_use", "hailactivity"),
                    "status": pick("classification", "currentstatus", "status", "site_status", "investigation_status"),
                    "id": pick("site_id", "siteid", "irisid", "id"), "attributes": clean_attributes(a)})
    return sorted(out, key=lambda r: r["distance_m"])


def lookup(lon: float, lat: float, region: str | None, catalogue_layers: list[dict] | None = None) -> dict:
    key = next((k for k in REGISTERS if region and k.split()[0].lower() in region.lower()), None)
    reg = REGISTERS[key] if key else dict(GENERIC, council=f"{region} council" if region else None)
    layers = []
    for s in reg.get("services", []):
        layers += _layers_in(s)
    for w in reg.get("webmaps", []):
        layers += _webmap_layers(w)
    for c in catalogue_layers or []:
        layers.append({"url": f"{c['service']}/{c['layer_id']}", "name": c["layer"]})
    seen, uniq = set(), []
    for l in layers:
        if l["url"] not in seen:
            seen.add(l["url"])
            uniq.append(l)
    hits, errors = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for l, res in zip(uniq, ex.map(lambda l: _safe_q(l, lon, lat), uniq)):
            if isinstance(res, Exception):
                errors.append(f"{l['name']}: {type(res).__name__}")
            else:
                hits += res
    hits.sort(key=lambda r: r["distance_m"])
    status = "ok" if uniq and len(errors) < len(uniq) else ("not_published" if not uniq else "error")
    return {"status": status, "register": reg["name"], "council": reg.get("council"), "request": reg.get("request"),
            "layers_checked": [l["name"] for l in uniq], "on_site": [h for h in hits if h["inside"]],
            "nearby": [h for h in hits if not h["inside"]], "near_m": NEAR_M, "errors": errors}


def _safe_q(layer, lon, lat):
    try:
        return _query(layer, lon, lat)
    except Exception as e:  # noqa: BLE001
        return e
