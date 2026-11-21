"""ArcGIS REST, ArcGIS Online and ArcGIS Hub queries."""
from __future__ import annotations

from .config import settings
from .geo import esri_to_shapely, to_nztm
from .http import fetch


def listing(root: str) -> dict:
    """Folders and services under a REST root or folder."""
    body, _ = fetch(root.rstrip("/"), {"f": "json"}, ttl_days=7)
    return {"folders": body.get("folders", []), "services": body.get("services", [])}


def service_url(root: str, svc: dict) -> str:
    base = root.rstrip("/").split("/rest/services")[0] + "/rest/services"
    return f"{base}/{svc['name']}/{svc['type']}"


def layers(service: str) -> list[dict]:
    """Layers of a MapServer or FeatureServer with name, id, geometry type and extent."""
    body, _ = fetch(service.rstrip("/") + "/layers", {"f": "json"}, ttl_days=7)
    out = []
    for lyr in body.get("layers", []):
        if lyr.get("type") not in (None, "Feature Layer"):
            continue
        out.append({"id": lyr["id"], "name": lyr.get("name", ""), "geometry": lyr.get("geometryType"),
                    "extent": lyr.get("extent"), "fields": [f["name"] for f in lyr.get("fields") or []],
                    "description": (lyr.get("description") or "")[:500],
                    "copyright": lyr.get("copyrightText") or ""})
    return out


def query_point(layer_url: str, lon: float, lat: float, *, out_fields: str = "*") -> tuple[list[dict], str]:
    """Features intersecting the site. Returns (attribute dicts, retrieved)."""
    body, retrieved = fetch(layer_url.rstrip("/") + "/query", {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": out_fields, "returnGeometry": "false",
        "f": "json"})
    return [f.get("attributes", {}) for f in body.get("features", [])], retrieved


def query_near(layer_url: str, lon: float, lat: float, radius_m: float, *, out_fields: str = "*",
               max_records: int = 200) -> tuple[list[dict], str]:
    """Features within radius_m, each with 'attributes' and 'geom' (shapely, NZTM)."""
    x, y = to_nztm(lon, lat)
    env = f"{x - radius_m},{y - radius_m},{x + radius_m},{y + radius_m}"
    body, retrieved = fetch(layer_url.rstrip("/") + "/query", {
        "geometry": env, "geometryType": "esriGeometryEnvelope", "inSR": 2193,
        "spatialRel": "esriSpatialRelIntersects", "outFields": out_fields, "returnGeometry": "true",
        "outSR": 2193, "resultRecordCount": max_records, "f": "json"})
    feats = []
    for f in body.get("features", []):
        g = esri_to_shapely(f.get("geometry"))
        if g is not None and not g.is_empty:
            feats.append({"attributes": f.get("attributes", {}), "geom": g})
    return feats, retrieved


NZ_BBOX = "166,-48,179,-34"


def agol_search(text: str, *, num: int = 100) -> list[dict]:
    """Public ArcGIS Online map and feature services matching text, limited to the NZ area."""
    q = f'({text}) AND (type:"Feature Service" OR type:"Map Service")'
    body, _ = fetch(settings.agol_search, {"q": q, "bbox": NZ_BBOX, "num": num, "f": "json"}, ttl_days=7)
    return [{"title": r.get("title"), "owner": r.get("owner"), "url": r.get("url"),
             "org": r.get("orgId"), "snippet": r.get("snippet")} for r in body.get("results", []) if r.get("url")]


def hub_search(hub: str, text: str, *, limit: int = 100) -> list[dict]:
    """Datasets on an ArcGIS Hub open data site (OGC records API)."""
    body, _ = fetch(hub.rstrip("/") + "/api/search/v1/collections/dataset/items",
                    {"q": text, "limit": limit}, ttl_days=7)
    out = []
    for f in body.get("features", []):
        p = f.get("properties", {})
        if p.get("url"):
            out.append({"title": p.get("title"), "url": p.get("url"), "owner": p.get("owner")})
    return out
