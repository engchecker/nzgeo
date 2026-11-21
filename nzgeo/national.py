"""National datasets: QMAP geology, NZ Active Faults Database, landslides, LINZ coastline, NZ SeaRise."""
from __future__ import annotations

import csv
import io
import math
import re
from functools import lru_cache

from shapely.geometry import Point

from . import arcgis
from .config import settings
from .geo import bearing_name, nearest, to_nztm
from .hazards import clean_attributes
from .http import fetch


@lru_cache(maxsize=1)
def gns_services() -> list[str]:
    """Every MapServer/FeatureServer on the GNS (Earth Sciences NZ) server, one folder deep."""
    root = settings.gns_root
    lst = arcgis.listing(root)
    out = [arcgis.service_url(root, s) for s in lst["services"]]
    for f in lst["folders"]:
        try:
            out += [arcgis.service_url(root, s) for s in arcgis.listing(f"{root}/{f}")["services"]]
        except Exception:
            continue
    return [s for s in out if s.endswith(("MapServer", "FeatureServer"))]


def _pick_service(pattern: str, prefer: str = "MapServer") -> str | None:
    hits = [s for s in gns_services() if re.search(pattern, s, re.I)]
    if not hits:
        return None
    def year(s):
        m = re.findall(r"(20\d\d)", s)
        return int(m[-1]) if m else 0
    hits.sort(key=lambda s: (year(s), s.endswith(prefer)), reverse=True)
    return hits[0]


def _layer(service: str, pattern: str, geometry: str | None = None) -> dict | None:
    for lyr in arcgis.layers(service):
        if re.search(pattern, lyr["name"], re.I) and (geometry is None or lyr["geometry"] == geometry):
            return lyr
    return None


_GEO_FIELDS = {"unit_name": r"^(name|unit_name|strat_unit|stratunit|qmap_name)$",
               "unit_code": r"^(unit_code|code|map_unit|mapunit|key_name)$",
               "description": r"^(description|descr|rock_desc|main_rock|lithology|simple_name)$",
               "age": r"^(age|abs_min|stratage|qmap_age|chrono|age_min|age_max|time_unit)$",
               "main_rock": r"^(main_rock|mainrock|rock_group|rock_class)$"}


def _pick_fields(attrs: dict) -> dict:
    out = {}
    for key, pat in _GEO_FIELDS.items():
        for k, v in attrs.items():
            if re.match(pat, k, re.I) and v not in (None, ""):
                out[key] = v
                break
    return out


def geology(lon: float, lat: float) -> dict:
    svc = _pick_service(r"250K_Geology")
    if not svc:
        return {"status": "unavailable", "reason": "1:250,000 geology service not found on the GNS server"}
    lyr = _layer(svc, r"unit", "esriGeometryPolygon") or _layer(svc, r"geolog", "esriGeometryPolygon")
    if not lyr:
        return {"status": "unavailable", "reason": f"no polygon unit layer in {svc}"}
    url = f"{svc}/{lyr['id']}"
    feats, retrieved = arcgis.query_near(url, lon, lat, settings.geology_boundary_flag_m * 2)
    p = Point(to_nztm(lon, lat))
    here = next((f for f in feats if f["geom"].contains(p)), None)
    if not here:
        return {"status": "no_data", "source": url, "retrieved": retrieved,
                "reason": "No mapped unit at the site (offshore, lake or a gap in the map)"}
    dist, vec = nearest(tuple(p.coords[0]), here["geom"].boundary)
    edition = re.search(r"(20\d\d)", svc)
    return {"status": "ok", "source": url, "retrieved": retrieved,
            "edition_year": int(edition.group(1)) if edition else None,
            "copyright": lyr["copyright"], **_pick_fields(here["attributes"]),
            "attributes": clean_attributes(here["attributes"], 20),
            "boundary_distance_m": round(dist), "boundary_direction": bearing_name(*vec),
            "flag_near_boundary": dist < settings.geology_boundary_flag_m}


def rock_strength(lon: float, lat: float) -> dict:
    svc = _pick_service(r"RockStrength")
    if not svc:
        return {"status": "unavailable", "reason": "rock strength view not found"}
    for lyr in arcgis.layers(svc):
        if lyr["geometry"] == "esriGeometryPolygon":
            attrs, retrieved = arcgis.query_point(f"{svc}/{lyr['id']}", lon, lat)
            if attrs:
                return {"status": "ok", "source": f"{svc}/{lyr['id']}", "retrieved": retrieved,
                        "attributes": clean_attributes(attrs[0])}
    return {"status": "no_data"}


_FAULT_SETS = {"af250": r"250", "highres": r"high", "faz": r"avoidance", "faa": r"awareness"}


def faults(lon: float, lat: float) -> dict:
    svc = _pick_service(r"Active_Faults/NZActiveFaultDatasets") or _pick_service(r"NZActiveFaultsDatabase")
    if not svc:
        return {"status": "unavailable", "reason": "NZ Active Faults Database service not found"}
    lyrs = arcgis.layers(svc)
    p = to_nztm(lon, lat)
    out = {"status": "ok", "source": svc, "traces": [], "zones": []}
    for lyr in lyrs:
        name = lyr["name"]
        url = f"{svc}/{lyr['id']}"
        if lyr["geometry"] == "esriGeometryPolyline" and re.search(r"fault", name, re.I):
            feats, retrieved = arcgis.query_near(url, lon, lat, settings.fault_search_m)
            best = None
            for f in feats:
                d, vec = nearest(p, f["geom"])
                if best is None or d < best[0]:
                    best = (d, vec, f["attributes"])
            out["retrieved"] = retrieved
            set_name = next((k for k, pat in _FAULT_SETS.items() if re.search(pat, name, re.I)), name)
            if best:
                a = best[2]
                out["traces"].append({
                    "set": set_name, "layer": name, "distance_m": round(best[0]), "direction": bearing_name(*best[1]),
                    "name": next((a[k] for k in a if re.match(r"^(name|fault_name|faultname)$", k, re.I)), None),
                    "recurrence_interval_class": next((a[k] for k in a if re.search(r"rec.*int.*class|ri_class|recur", k, re.I)), None),
                    "type": next((a[k] for k in a if re.match(r"^(dom_sense|type|fault_type|sense)$", k, re.I)), None),
                    "accuracy": next((a[k] for k in a if re.search(r"accura|locat.*qual", k, re.I)), None),
                    "attributes": clean_attributes(a)})
            else:
                out["traces"].append({"set": set_name, "layer": name, "distance_m": None,
                                      "note": f"none within {settings.fault_search_m / 1000:.0f} km"})
        elif lyr["geometry"] == "esriGeometryPolygon" and re.search(r"avoidance|awareness", name, re.I):
            attrs, _ = arcgis.query_point(url, lon, lat)
            out["zones"].append({"layer": name, "inside": bool(attrs),
                                 "attributes": clean_attributes(attrs[0]) if attrs else {}})
    nearest_trace = [t for t in out["traces"] if t.get("distance_m") is not None]
    out["nearest"] = min(nearest_trace, key=lambda t: t["distance_m"]) if nearest_trace else None
    out["inside_zone"] = any(z["inside"] for z in out["zones"])
    return out


def landslides(lon: float, lat: float) -> dict:
    hits = []
    for svc in [s for s in gns_services() if re.search(r"landslide", s, re.I)]:
        for lyr in arcgis.layers(svc):
            try:
                feats, retrieved = arcgis.query_near(f"{svc}/{lyr['id']}", lon, lat, settings.landslide_search_m)
            except Exception:
                continue
            p = to_nztm(lon, lat)
            for f in feats:
                d, vec = nearest(p, f["geom"])
                if d <= settings.landslide_search_m:
                    hits.append({"layer": f"{svc.split('/rest/services/')[-1]} / {lyr['name']}", "distance_m": round(d),
                                 "direction": bearing_name(*vec), "attributes": clean_attributes(f["attributes"], 6)})
    hits.sort(key=lambda h: h["distance_m"])
    return {"status": "ok", "search_radius_m": settings.landslide_search_m, "features": hits[:20]}


def coast(lon: float, lat: float) -> dict:
    """Distance to the LINZ Topo 1:50k coastline (requires LINZ_API_KEY)."""
    if not settings.linz_api_key:
        return {"status": "unavailable", "reason": "Set LINZ_API_KEY to measure distance to coast"}
    x, y = to_nztm(lon, lat)
    r = settings.coast_search_m
    url = f"https://data.linz.govt.nz/services;key={settings.linz_api_key}/wfs"
    body, retrieved = fetch(url, {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"layer-{settings.linz_coastline_layer}", "outputFormat": "json", "srsName": "EPSG:2193",
        "bbox": f"{x - r},{y - r},{x + r},{y + r},urn:ogc:def:crs:EPSG::2193"})
    from shapely.geometry import shape
    best = None
    for f in body.get("features", []):
        g = shape(f["geometry"])
        d, vec = nearest((x, y), g.boundary if g.geom_type.endswith("Polygon") else g)
        if best is None or d < best[0]:
            best = (d, vec)
    src = f"LINZ Data Service layer {settings.linz_coastline_layer} (NZ Coastlines, Topo 1:50k), CC BY 4.0"
    if best is None:
        return {"status": "ok", "distance_m": None, "beyond_m": r, "source": src, "retrieved": retrieved}
    return {"status": "ok", "distance_m": round(best[0]), "direction": bearing_name(*best[1]), "source": src,
            "retrieved": retrieved}


@lru_cache(maxsize=1)
def _searise_rows() -> list[dict]:
    text, _ = fetch(settings.searise_vlm_csv, as_json=False, ttl_days=365)
    return list(csv.DictReader(io.StringIO(text)))


def vertical_land_movement(lon: float, lat: float, max_km: float = 5.0) -> dict:
    rows = _searise_rows()
    def num(r, *keys):
        for k in r:
            if any(k.lower().strip().startswith(x) for x in keys):
                try:
                    return float(r[k])
                except (TypeError, ValueError):
                    return None
        return None
    best = None
    for r in rows:
        la, lo = num(r, "lat"), num(r, "lon")
        if la is None or lo is None:
            continue
        d = math.hypot((lo - lon) * 111.32 * math.cos(math.radians(lat)), (la - lat) * 110.57)
        if best is None or d < best[0]:
            best = (d, r)
    if not best or best[0] > max_km:
        return {"status": "no_data", "reason": f"no NZ SeaRise site within {max_km} km"}
    r = best[1]
    rate = next((r[k] for k in r if "bop corrected" in k.lower()), None) or next((r[k] for k in r if "vertical rate" in k.lower()), None)
    return {"status": "ok", "site_id": r.get("id") or r.get("Site ID"), "distance_km": round(best[0], 1),
            "vlm_mm_per_yr": float(rate) if rate not in (None, "") else None,
            "quality_factor": next((r[k] for k in r if k.strip().upper() == "QF"), None),
            "source": "NZ SeaRise (Naish et al. 2024), CC BY 4.0"}


def table36_fault_distance(lon: float, lat: float, names: list[str], radius_m: float = 25_000) -> dict:
    """Shortest distance to a mapped trace of a NZS 1170.5 Table 3.6 fault (NZ Active Faults Database)."""
    svc = _pick_service(r"Active_Faults/NZActiveFaultDatasets") or _pick_service(r"NZActiveFaultsDatabase")
    if not svc:
        return {"status": "unavailable"}
    p = to_nztm(lon, lat)
    best = None
    for lyr in arcgis.layers(svc):
        if lyr["geometry"] != "esriGeometryPolyline" or not re.search(r"fault", lyr["name"], re.I):
            continue
        feats, _ = arcgis.query_near(f"{svc}/{lyr['id']}", lon, lat, radius_m, max_records=1000)
        for f in feats:
            a = f["attributes"]
            nm = next((str(a[k]) for k in a if re.match(r"^(name|fault_name|faultname)$", k, re.I) and a[k]), "")
            hit = next((n for n in names if nm.lower().startswith(n.lower())), None)
            if not hit:
                continue
            d, _ = nearest(p, f["geom"])
            if best is None or d < best[0]:
                best = (d, hit, nm)
    if best is None:
        return {"status": "ok", "distance_km": None}
    return {"status": "ok", "distance_km": best[0] / 1000, "name": best[1], "trace": best[2]}
