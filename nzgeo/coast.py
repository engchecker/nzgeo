"""Offline coastline (LINZ NZ Coastlines and Islands Polygons, Topo 1:50k, CC BY 4.0; simplified 5 m)
and the NZS 3404.3 coast type of the nearest coast."""
from __future__ import annotations

import gzip
import json
import struct
from functools import lru_cache

import numpy as np
from shapely import STRtree, wkb
from shapely.geometry import Point

from .config import DATA_DIR
from .geo import bearing_name, nearest, to_nztm, to_wgs84

SOURCE = ("LINZ NZ Coastlines and Islands Polygons (Topo 1:50k), CC BY 4.0, via GNS-Science/nzgeom 1.0.1; "
          "simplified to 5 m")


@lru_cache(maxsize=1)
def _polys():
    recs = []
    with gzip.open(DATA_DIR / "nz_coast_topo50k.wkb.gz", "rb") as f:
        while hdr := f.read(8):
            lm, lb = struct.unpack("<II", hdr)
            meta = json.loads(f.read(lm))
            recs.append((meta, wkb.loads(f.read(lb))))
    geoms = [g for _, g in recs]
    return recs, STRtree(geoms), STRtree([g.boundary for g in geoms])


def distance(lon: float, lat: float, search_m: float = 25_000) -> dict:
    """Distance from the site to the nearest coastline, and the island it is on."""
    recs, tree, btree = _polys()
    x, y = to_nztm(lon, lat)
    p = Point(x, y)
    on = [recs[int(i)][0]["name"] for i in tree.query(p, predicate="intersects")]
    idx = btree.query(p.buffer(search_m))
    if len(idx) == 0:
        return {"status": "ok", "distance_m": None, "beyond_m": search_m, "on_land": bool(on), "island": on[0] if on else None,
                "source": SOURCE}
    best = min(((nearest((x, y), recs[int(i)][1].boundary), int(i)) for i in idx), key=lambda t: t[0][0])
    (d, vec), i = best
    qx, qy = x + vec[0], y + vec[1]
    qlon, qlat = to_wgs84(qx, qy)
    return {"status": "ok", "distance_m": round(d), "direction": bearing_name(*vec), "on_land": bool(on),
            "island": on[0] if on else None, "nearest_coast_island": recs[i][0]["name"],
            "nearest_coast_point": [round(qlon, 5), round(qlat, 5)], "source": SOURCE}


# --- NZS 3404.3 Table 2 coast type, from the nearest coast point ---
# Coarse dividing lines down the spine of each main island (lon, lat). West of the line = west coast.
_NI_DIVIDE = [(172.68, -34.43), (173.2, -35.0), (174.0, -36.0), (174.75, -36.9), (175.2, -37.4), (175.55, -38.2),
              (175.7, -39.0), (175.6, -39.8), (175.45, -40.5), (175.2, -41.2), (175.3, -41.7)]
_SI_DIVIDE = [(172.7, -40.5), (172.6, -41.0), (172.2, -41.8), (171.6, -42.6), (170.9, -43.3), (170.0, -44.0),
              (168.9, -44.7), (168.3, -45.3), (168.1, -45.9), (168.4, -46.6)]


def _divide_lon(line, lat):
    pts = sorted(line, key=lambda t: -t[1])
    for (lo1, la1), (lo2, la2) in zip(pts, pts[1:]):
        if la2 <= lat <= la1:
            return lo1 + (lat - la1) / (la2 - la1) * (lo2 - lo1)
    return pts[0][0] if lat > pts[0][1] else pts[-1][0]


def coast_type(coast: dict) -> dict:
    """Classify the nearest coast as si_ws, ni_ws, east or chatham. Harbours are not detected (engineer input)."""
    if not coast or not coast.get("nearest_coast_point"):
        return {"type": None, "reason": "no coast within the search distance"}
    lon, lat = coast["nearest_coast_point"]
    isl = (coast.get("nearest_coast_island") or "").lower()
    note = "Coarse sector map; confirm the coast type, and select 'harbour' for harbour or calm saltwater frontages."
    if lon < 0 or lon > 182 or "chatham" in isl or "pitt" in isl:
        return {"type": "chatham", "note": note}
    if "north island" in isl:
        ni = True
    elif "south island" in isl or "stewart" in isl:
        ni = False
    else:  # offshore islands: by position (Cook Strait islands east of 174.4 E belong with the North Island)
        ni = lat > -40.4 or (lat > -41.7 and lon > 174.4)
    if ni:
        west = lon < _divide_lon(_NI_DIVIDE, lat)
        south = lat < -41.2 and lon < 175.35
        return {"type": "ni_ws" if (west or south) else "east", "note": note,
                "near_transition": abs(lat - (-34.43)) < 0.1 or abs(lon - _divide_lon(_NI_DIVIDE, lat)) < 0.05}
    if "stewart" in isl or lat < -46.3:
        return {"type": "si_ws", "note": note}
    if lat > -41.0 and lon > 172.7:  # Golden Bay, Tasman Bay, Marlborough Sounds: north coast, not listed in Table 2
        return {"type": "east", "note": note + " North coast of the South Island is not listed in Table 2; treated with the east coast."}
    west = lon < _divide_lon(_SI_DIVIDE, lat)
    return {"type": "si_ws" if west else "east", "note": note,
            "near_transition": abs(lon - _divide_lon(_SI_DIVIDE, lat)) < 0.05}
