"""Crawl council services and build a local catalogue of hazard layers.

Run `python -m nzgeo discover` once (and then monthly). Sites are checked against the
catalogue; a council not yet in it is crawled on demand.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pyproj import Transformer

from . import arcgis
from .config import settings
from .councils import registry
from .hazards import classify, classify_service

SCHEMA = 3          # 2: contaminated-land (HAIL) layers; 3: three-waters pipe layers
CATALOGUE = lambda: settings.cache_dir.parent / "council_catalogue.json"  # noqa: E731

# Folders worth entering on large shared servers (NIWA hosts several councils)
FOLDER_LIMITS = {"https://gis.niwa.co.nz/server/rest/services": r"^WCRC"}
_SKIP_FOLDER = r"basemap|imagery|aerial|transport|roading|internal|test"


def _extent_wgs84(ext: dict | None):
    if not ext or "xmin" not in ext or ext.get("xmin") in (None, "NaN"):
        return None
    wkid = (ext.get("spatialReference") or {}).get("latestWkid") or (ext.get("spatialReference") or {}).get("wkid")
    if not wkid:
        return None
    try:
        t = Transformer.from_crs(int(wkid), 4326, always_xy=True)
        x0, y0 = t.transform(ext["xmin"], ext["ymin"])
        x1, y1 = t.transform(ext["xmax"], ext["ymax"])
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    except Exception:
        return None


def _services_under(root: str, max_services: int) -> list[str]:
    out, todo, seen = [], [root.rstrip("/")], set()
    allow = FOLDER_LIMITS.get(root.rstrip("/"))
    while todo and len(out) < max_services:
        cur = todo.pop()
        if cur in seen:
            continue
        seen.add(cur)
        try:
            lst = arcgis.listing(cur)
        except Exception:
            continue
        for f in lst["folders"]:
            if allow and not re.search(allow, f):
                continue
            if re.search(_SKIP_FOLDER, f, re.I):
                continue
            todo.append(root.rstrip("/") + "/" + f)
        for s in lst["services"]:
            if s.get("type") in ("MapServer", "FeatureServer"):
                out.append(arcgis.service_url(root, s))
    return out


def _layers_for_service(svc: str, council: str, found_by: str = "registry") -> list[dict]:
    try:
        lyrs = arcgis.layers(svc)
    except Exception:
        return []
    svc_name = svc.split("/rest/services/")[-1]
    recs = []
    for lyr in lyrs:
        kinds = classify(svc_name, lyr["name"])
        stype = classify_service(svc_name, lyr["name"]) if lyr["geometry"] == "esriGeometryPolyline" else None
        if stype:
            kinds = ["services"]
        if not kinds:
            continue
        recs.append({"council": council, "service": svc, "layer_id": lyr["id"], "layer": lyr["name"],
                     "hazards": kinds, "service_type": stype, "geometry": lyr["geometry"], "bbox": _extent_wgs84(lyr["extent"]),
                     "copyright": lyr["copyright"], "found_by": found_by})
    return recs


def crawl_council(c: dict, *, max_services: int = 400) -> dict:
    services: list[str] = []
    for root in c["rest_roots"]:
        services += _services_under(root, max_services)
    found_by = "registry"
    # Hubs and ArcGIS Online search fill gaps
    for hub in c.get("hubs", []):
        try:
            for it in arcgis.hub_search(hub, "hazard OR flood OR liquefaction OR tsunami OR coastal OR landslide OR fault"):
                services.append(re.sub(r"/\d+$", "", it["url"]))
        except Exception:
            pass
    if not c["rest_roots"]:
        found_by = "arcgis_online_search"
        name = c["name"].replace("'", "")
        try:
            for it in arcgis.agol_search(f'"{name}" AND (hazard OR flood OR liquefaction OR tsunami OR coastal OR landslide OR fault OR instability)'):
                services.append(re.sub(r"/\d+$", "", it["url"]))
        except Exception:
            pass
    services = list(dict.fromkeys(s for s in services if re.search(r"/(MapServer|FeatureServer)$", s)))
    with ThreadPoolExecutor(max_workers=8) as ex:
        recs = [r for rs in ex.map(lambda s: _layers_for_service(s, c["name"], found_by), services) for r in rs]
    return {"council": c["name"], "found_by": found_by, "services_scanned": len(services), "layers": recs, "schema": SCHEMA,
            "crawled": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def load_catalogue() -> dict:
    p = CATALOGUE()
    return json.loads(p.read_text()) if p.exists() else {"councils": {}}


def save_catalogue(cat: dict) -> None:
    p = CATALOGUE()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cat, indent=1))


def ensure(council: dict, *, refresh: bool = False) -> dict:
    cat = load_catalogue()
    entry = cat["councils"].get(council["name"])
    if entry is None or refresh or entry.get("schema") != SCHEMA:
        entry = crawl_council(council)
        cat["councils"][council["name"]] = entry
        save_catalogue(cat)
    return entry


def discover_all(names: list[str] | None = None, *, refresh: bool = True, progress=None) -> dict:
    cat = load_catalogue()
    todo = [c for c in registry()["councils"] if not names or c["name"] in names]
    for k, c in enumerate(todo, 1):
        if progress:
            progress(k, len(todo), c["name"])
        cat["councils"][c["name"]] = crawl_council(c) if refresh or c["name"] not in cat["councils"] else cat["councils"][c["name"]]
        save_catalogue(cat)
    return cat
