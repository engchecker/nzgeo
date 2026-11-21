"""Find a site: street address first, then Lot/DP (legal description), then coordinates.

Sources, in order of preference:
  Address  1. LINZ NZ Addresses on LINZ's public ArcGIS Online services (no key)
           2. LINZ Data Service WFS, layer 105689 (LINZ key)
           3. OpenStreetMap Nominatim (no key; flagged "check location")
  Lot/DP   1. LINZ NZ Primary Parcels on ArcGIS Online (no key)
           2. LINZ Data Service WFS, layer 50772 (LINZ key)
The map click in the web page is the final fallback.
"""
from __future__ import annotations

import re

from .config import settings
from .http import fetch

LINZ_AGOL = "https://services.arcgis.com/xdsHIIxuCWByZiCB/ArcGIS/rest/services"
AGOL_ADDRESSES = f"{LINZ_AGOL}/LINZ_NZ_Addresses/FeatureServer/0"
AGOL_PARCELS = f"{LINZ_AGOL}/LINZ_NZ_Primary_Parcels/FeatureServer/0"
AGOL_TITLES = f"{LINZ_AGOL}/LINZ_NZ_Property_Titles/FeatureServer/0"
LDS_WFS = "https://data.linz.govt.nz/services;key={key}/wfs"
LDS_ADDRESSES, LDS_PARCELS = "layer-105689", "layer-50772"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

STREET_TYPES = {
    "rd": "road", "st": "street", "ave": "avenue", "av": "avenue", "cres": "crescent", "cr": "crescent",
    "dr": "drive", "pl": "place", "tce": "terrace", "ter": "terrace", "hwy": "highway", "ln": "lane",
    "gr": "grove", "cl": "close", "ct": "court", "pde": "parade", "sq": "square", "esp": "esplanade",
    "blvd": "boulevard", "hts": "heights", "mt": "mount", "rdge": "ridge", "wy": "way",
}
APPELLATION = re.compile(
    r"\b(?P<pre>(?:pt|part)\s+)?(?P<kind>lot|lt|section|sec|sect|flat|unit|accessory\s+unit|au)\s*(?P<num>[0-9A-Z]+)\s*,?\s*"
    r"(?:(?:on|of)\s+)?(?P<plan>d\.?\s?p\.?|s\.?\s?o\.?|l\.?\s?t\.?|d\.?\s?p\.?\s?s|ps|ml|deeds|unit\s+plan|up)\s*(?P<pnum>\d+)\b",
    re.I)
COORD = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$")


# ---------------------------------------------------------------- parsing
def normalise_appellation(text: str) -> str | None:
    """'lot 2 dp12345' -> 'Lot 2 DP 12345'; returns None when the text is not a legal description."""
    m = APPELLATION.search(text or "")
    if not m:
        return None
    kind = m.group("kind").lower()
    kind = {"lt": "Lot", "lot": "Lot", "sec": "Section", "sect": "Section", "section": "Section", "flat": "Flat",
            "unit": "Unit", "au": "Accessory Unit"}.get(kind, kind.title())
    plan = re.sub(r"[.\s]", "", m.group("plan")).upper()
    plan = {"UNITPLAN": "UP"}.get(plan, plan)
    pre = "Part " if m.group("pre") else ""
    return f"{pre}{kind} {m.group('num').upper()} {plan} {m.group('pnum')}"


def parse_address(text: str) -> dict | None:
    """Split '2/1 Lambton Quay, Wellington' into unit, number, street (types expanded) and locality."""
    t = re.sub(r"\s+", " ", (text or "").strip().rstrip("."))
    m = re.match(r"^(?:(?:unit|flat|apt)\s*)?(?:(?P<unit>[0-9A-Za-z]+)\s*/\s*)?(?P<num>\d+[A-Za-z]?)\s+(?P<street>[^,]+?)"
                 r"(?:\s*,\s*(?P<rest>.*))?$", t, re.I)
    if not m:
        return None
    words = m.group("street").split(" ")
    if words and words[-1].lower().rstrip(".") in STREET_TYPES:
        words[-1] = STREET_TYPES[words[-1].lower().rstrip(".")]
    street = " ".join(words)
    rest = [p.strip() for p in (m.group("rest") or "").split(",") if p.strip()]
    return {"unit": m.group("unit"), "number": m.group("num").upper(), "street": street.title(), "locality": rest}


def classify(q: str) -> str:
    if COORD.match(q or ""):
        return "coordinates"
    if normalise_appellation(q):
        return "legal"
    if parse_address(q):
        return "address"
    return "unknown"


# ---------------------------------------------------------------- sources
_FIELD_CACHE: dict[str, list[str]] = {}


def _fields(layer: str) -> list[str]:
    if layer not in _FIELD_CACHE:
        body, _ = fetch(layer, {"f": "json"}, ttl_days=30)
        _FIELD_CACHE[layer] = [f["name"] for f in body.get("fields", [])]
    return _FIELD_CACHE[layer]


def _pick(fields: list[str], *names: str) -> str | None:
    low = {f.lower(): f for f in fields}
    for n in names:
        if n in low:
            return low[n]
    return None


def _agol_query(layer: str, where: str, *, n: int = 20, geometry: str = "point") -> list[dict]:
    body, _ = fetch(f"{layer}/query", {"where": where, "outFields": "*", "returnGeometry": "true", "outSR": 4326,
                                       "resultRecordCount": n, "f": "json"}, ttl_days=7)
    out = []
    for f in body.get("features", []):
        g = f.get("geometry") or {}
        if "x" in g:
            lon, lat = g["x"], g["y"]
            ring = None
        elif g.get("rings"):
            ring = g["rings"][0]
            from shapely.geometry import Polygon
            p = Polygon(ring).representative_point()
            lon, lat = p.x, p.y
        else:
            continue
        out.append({"attributes": f.get("attributes", {}), "lon": lon, "lat": lat, "ring": ring})
    return out


def _lds_query(layer: str, cql: str, *, n: int = 20) -> list[dict]:
    if not settings.linz_api_key:
        raise RuntimeError("no LINZ key")
    body, _ = fetch(LDS_WFS.format(key=settings.linz_api_key),
                    {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": layer,
                     "outputFormat": "json", "srsName": "EPSG:4326", "count": n, "cql_filter": cql}, ttl_days=7)
    from shapely.geometry import shape
    out = []
    for f in body.get("features", []):
        g = shape(f["geometry"]) if f.get("geometry") else None
        if g is None:
            continue
        p = g.representative_point()
        ring = list(g.geoms[0].exterior.coords) if g.geom_type == "MultiPolygon" else \
            (list(g.exterior.coords) if g.geom_type == "Polygon" else None)
        out.append({"attributes": f.get("properties", {}), "lon": p.x, "lat": p.y, "ring": ring})
    return out


def _sql(s: str) -> str:
    return s.replace("'", "''").upper()


def _address_ok(full: str, a: dict) -> bool:
    """Exact house number (and unit) match; locality words must appear when given."""
    f = (full or "").upper()
    pre = rf"(?:^|[ /]){re.escape(a['unit'].upper())}/" if a.get("unit") else r"(?:^|[ /])"
    if not re.search(pre + re.escape(a["number"]) + r" " + re.escape(a["street"].upper()) + r"\b", f):
        return False
    return all(loc.upper() in f for loc in a["locality"])


def search_address(q: str, n: int = 10) -> tuple[list[dict], list[str]]:
    a = parse_address(q)
    tried: list[str] = []
    like = f"%{a['number']} {a['street']}%" if a else ""
    # 1. LINZ on ArcGIS Online
    try:
        if not a:
            raise LookupError("not a street address")
        tried.append("LINZ NZ Addresses (ArcGIS Online)")
        fld = _pick(_fields(AGOL_ADDRESSES), "full_address", "full_address_ascii", "address") or "full_address"
        rows = _agol_query(AGOL_ADDRESSES, f"UPPER({fld}) LIKE '{_sql(like)}'", n=50)
        res = [{"kind": "address", "label": r["attributes"].get(fld), "lon": r["lon"], "lat": r["lat"],
                "source": "LINZ NZ Addresses"} for r in rows if _address_ok(r["attributes"].get(fld), a)]
        if res:
            return res[:n], tried
    except Exception as e:
        tried[-1] += " – no match" if isinstance(e, LookupError) else f" – not reached ({type(e).__name__})"
    # 2. LINZ Data Service (key)
    if settings.linz_api_key and a:
        try:
            tried.append("LINZ Data Service NZ Addresses")
            rows = _lds_query(LDS_ADDRESSES, f"full_address ILIKE '{like.replace(chr(39), chr(39) * 2)}'", n=50)
            res = [{"kind": "address", "label": r["attributes"].get("full_address"), "lon": r["lon"], "lat": r["lat"],
                    "source": "LINZ NZ Addresses"} for r in rows if _address_ok(r["attributes"].get("full_address"), a)]
            if res:
                return res[:n], tried
        except Exception as e:
            tried[-1] += f" – not reached ({type(e).__name__})"
    # 3. OpenStreetMap
    try:
        tried.append("OpenStreetMap Nominatim")
        body, _ = fetch(NOMINATIM, {"q": q, "countrycodes": "nz", "format": "jsonv2", "limit": n}, ttl_days=7)
        res = [{"kind": "address", "label": r.get("display_name"), "lon": float(r["lon"]), "lat": float(r["lat"]),
                "source": "OpenStreetMap (check the marker is on the right property)"}
               for r in body if r.get("lat")]
        return res, tried
    except Exception as e:
        tried[-1] += f" – not reached ({type(e).__name__})"
    return [], tried


def _appellation_ok(app: str, target: str) -> bool:
    return bool(re.search(r"(?:^|[ ,])" + re.escape(target.upper()) + r"(?:$|[ ,])", (app or "").upper()))


def _parcel_item(r: dict, src: str) -> dict:
    at = r["attributes"]
    area = at.get("calc_area") or at.get("survey_area")
    return {"kind": "legal", "label": at.get("appellation"), "lon": r["lon"], "lat": r["lat"], "source": src,
            "legal": at.get("appellation"), "titles": at.get("titles"), "area_m2": round(area) if area else None,
            "parcel": r.get("ring")}


def search_legal(q: str, n: int = 10) -> tuple[list[dict], list[str]]:
    target = normalise_appellation(q)
    tried: list[str] = []
    if not target:
        return [], tried
    num_plan = target.replace("Part ", "")
    try:
        tried.append("LINZ NZ Primary Parcels (ArcGIS Online)")
        rows = _agol_query(AGOL_PARCELS, f"UPPER(appellation) LIKE '%{_sql(num_plan)}%'", n=50, geometry="polygon")
        res = [_parcel_item(r, "LINZ NZ Primary Parcels") for r in rows
               if _appellation_ok(r["attributes"].get("appellation"), num_plan)]
        if res:
            return res[:n], tried
    except Exception as e:
        tried[-1] += f" – not reached ({type(e).__name__})"
    if settings.linz_api_key:
        try:
            tried.append("LINZ Data Service NZ Primary Parcels")
            rows = _lds_query(LDS_PARCELS, f"appellation ILIKE '%{num_plan}%'", n=50)
            res = [_parcel_item(r, "LINZ NZ Primary Parcels") for r in rows
                   if _appellation_ok(r["attributes"].get("appellation"), num_plan)]
            return res[:n], tried
        except Exception as e:
            tried[-1] += f" – not reached ({type(e).__name__})"
    return [], tried


def legal_at(lon: float, lat: float) -> dict:
    """Legal description (appellation and titles) of the parcel containing the point."""
    try:
        body, _ = fetch(f"{AGOL_PARCELS}/query", {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "appellation,titles,calc_area,parcel_intent",
            "returnGeometry": "true", "outSR": 4326, "f": "json"}, ttl_days=7)
        feats = [f for f in body.get("features", []) if (f.get("attributes") or {}).get("parcel_intent") != "Road"] \
            or body.get("features", [])
        if feats:
            at, g = feats[0]["attributes"], feats[0].get("geometry") or {}
            return {"status": "ok", "legal": at.get("appellation"), "titles": at.get("titles"),
                    "area_m2": round(at["calc_area"]) if at.get("calc_area") else None,
                    "parcel": (g.get("rings") or [None])[0], "source": "LINZ NZ Primary Parcels"}
    except Exception:
        pass
    if settings.linz_api_key:
        try:
            rows = _lds_query(LDS_PARCELS, f"INTERSECTS(shape, POINT({lat} {lon}))", n=5)
            if rows:
                it = _parcel_item(rows[0], "LINZ NZ Primary Parcels")
                return {"status": "ok", **{k: it[k] for k in ("legal", "titles", "area_m2", "parcel", "source")}}
        except Exception:
            pass
    return {"status": "not_found", "note": "Legal description not found. Enter it from the Record of Title."}


def search(q: str, n: int = 10) -> dict:
    """Address first; then Lot/DP; otherwise ask for a map click."""
    q = (q or "").strip()
    m = COORD.match(q)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        lat, lon = (a, b) if a < 0 else (b, a)
        if 1_000_000 <= a <= 2_200_000 and 4_700_000 <= b <= 6_300_000:
            from .geo import to_wgs84
            lon, lat = to_wgs84(a, b)
        if -48.5 <= lat <= -33 and (165 <= lon <= 180 or lon <= -175):
            return {"query": q, "kind": "coordinates", "tried": [],
                    "results": [{"kind": "coordinates", "label": f"{lat:.6f}, {lon:.6f}", "lat": lat, "lon": lon,
                                 "source": "typed coordinates"}]}
    kind = classify(q)
    tried: list[str] = []
    res: list[dict] = []
    order = ("legal", "address") if kind == "legal" else ("address", "legal")
    for k in order:
        r, t = (search_legal if k == "legal" else search_address)(q, n)
        tried += t
        if r:
            res = r
            break
    msg = None
    if not res:
        msg = ("No match found. Check the spelling, try the street number and name (e.g. 1 Lambton Quay), "
               "or the legal description (e.g. Lot 2 DP 12345). Otherwise click the site on the map.")
    return {"query": q, "kind": kind, "results": res, "tried": tried, "message": msg}
