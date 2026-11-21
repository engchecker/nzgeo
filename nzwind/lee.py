"""M_lee for NZ lee zones (AS/NZS 1170.2 Cl 4.4.3, Tables 4.4 and 4.5).

Geometry, per wind direction beta (the direction the wind comes FROM):
- cast a ray from the site upwind; where it meets an initiating crest, the distance t is the
  downwind distance from the crest to the site
- shadow zone: Mlee from Table 4.4; outer zone: linear to 1.0 at its downwind edge
- beyond the crest's lateral ends: lateral transition zone x/4 wide beside the shadow zone and
  R/4 beside the outer zone, linear to 1.0 at its far edge
Crests: Table 4.5 coordinates where tabulated. Kaimai, Ruapehu, Tararua (SE) and Coastal Wairarapa have no
Table 4.5 coordinates; their crests are the upwind edges of the Figure 4.6 shadow zones (digitised) and the
result is flagged for checking. Taranaki uses the Table 4.4 rule: the 90-degree sector downwind of the summit,
distance measured from the mountain top.
"""
import math
from pyproj import Transformer
from .data import table, BEARING

_to_nztm = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)

def _nztm(lon, lat):
    return _to_nztm.transform(lon, lat)

def _along_profile(range_, t_km):
    """Mlee along the zone centreline at downwind distance t_km (None if outside)."""
    s0, s1 = range_["shadow_km"]
    m = range_["Mlee"]
    if t_km <= s1:
        return m
    if range_["outer_km"]:
        o0, o1 = range_["outer_km"]
        if t_km <= o1:
            return m + (1.0 - m) * (t_km - o0) / (o1 - o0)
    return None

def _ray_hit(px, py, ux, uy, ax, ay, bx, by):
    """Distance t >= 0 along ray P + t*u to segment AB, or None."""
    ex, ey = bx - ax, by - ay
    den = ux * ey - uy * ex
    if abs(den) < 1e-12:
        return None
    wx, wy = ax - px, ay - py
    t = (wx * ey - wy * ex) / den
    s = (wx * uy - wy * ux) / den
    return t if t >= 0 and 0 <= s <= 1 else None

def _crest(range_, direction):
    by = range_.get("crest_by_direction") or {}
    return by.get(direction) or range_.get("crest_wgs84")


def mlee_summit(range_, site_lon, site_lat, direction):
    """Table 4.4, Taranaki: any direction, within the 90-degree sector from the mountain top downwind to the site."""
    sx, sy = _nztm(*range_["summit_wgs84"])
    px, py = _nztm(site_lon, site_lat)
    dx, dy = px - sx, py - sy
    t_km = math.hypot(dx, dy) / 1000
    if t_km == 0:
        return None
    to_site = math.degrees(math.atan2(dx, dy)) % 360
    downwind = (BEARING[direction] + 180) % 360
    off = abs((to_site - downwind + 180) % 360 - 180)
    if off > 45:
        return None
    v = _along_profile(range_, t_km)
    return None if v is None else {"mlee": v, "zone": "shadow" if t_km <= range_["shadow_km"][1] else "outer",
                                    "distance_km": round(t_km, 2), "sector_offset_deg": round(off)}


def mlee_for_range(range_, site_lon, site_lat, direction):
    px, py = _nztm(site_lon, site_lat)
    b = math.radians(BEARING[direction])
    ux, uy = math.sin(b), math.cos(b)            # unit vector pointing upwind
    pts = [_nztm(lon, lat) for lon, lat in _crest(range_, direction)]
    hits = [t for a, c in zip(pts, pts[1:]) if (t := _ray_hit(px, py, ux, uy, *a, *c)) is not None]
    if hits:
        t_km = min(hits) / 1000
        v = _along_profile(range_, t_km)
        return None if v is None else {"mlee": v, "zone": "shadow" if t_km <= range_["shadow_km"][1] else "outer",
                                        "distance_km": round(t_km, 2)}
    # lateral transition: lateral axis l = (uy, -ux); along-wind downwind distance = -(dot with u)
    lx, ly = uy, -ux
    lat_coords = [((x - px) * lx + (y - py) * ly, x, y) for x, y in pts]
    best = None
    for end in (min(lat_coords), max(lat_coords)):
        l_off, ex, ey = end
        gap = abs(l_off) / 1000                     # lateral distance beyond the crest end
        t_km = ((ex - px) * ux + (ey - py) * uy) / 1000   # downwind distance from the end point
        if t_km < 0:
            continue
        edge = _along_profile(range_, t_km)
        if edge is None:
            continue
        R = range_["shadow_km"][1]
        width = t_km / 4 if t_km <= R else R / 4
        if width > 0 and gap < width:
            v = edge + (1.0 - edge) * gap / width
            if best is None or v > best["mlee"]:
                best = {"mlee": v, "zone": "lateral transition", "distance_km": round(t_km, 2),
                        "lateral_km": round(gap, 2)}
    return best

def mlee(site_lon, site_lat, direction):
    """Returns the governing Mlee for one wind direction, with the zone it came from and the crest basis."""
    t = table("mlee_lee_zones_nz")
    best = {"mlee": 1.0, "range": None}
    for r in t["ranges"]:
        if r["directions"] == "ANY_90DEG_FROM_SUMMIT":
            if not r.get("summit_wgs84"):
                continue
            res = mlee_summit(r, site_lon, site_lat, direction)
        else:
            if direction not in r["directions"] or not _crest(r, direction):
                continue
            res = mlee_for_range(r, site_lon, site_lat, direction)
        if res and res["mlee"] > best["mlee"]:
            best = {**res, "range": r["name"], "crest_basis": r.get("crest_status"), "crest_note": r.get("crest_note")}
    return best

def undigitised_ranges():
    t = table("mlee_lee_zones_nz")
    return [f'{r["no"]}. {r["name"]} ({", ".join(r["directions"]) if isinstance(r["directions"], list) else "any direction"})'
            for r in t["ranges"] if not (r.get("crest_wgs84") or r.get("crest_by_direction") or r.get("summit_wgs84"))]
