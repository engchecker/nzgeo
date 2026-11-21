"""AS/NZS 1170.2:2021 wind region (Figure 3.1(B)) and North Island lee zones (Figure 4.6), digitised.

For the wind tool: `wind_region(lon, lat)` and `lee_zones(lon, lat)`. Data comes from the encrypted bundle.
Figure 3.1(B) is small scale (about 3.6 km per point, boundary lines about 7 km wide), so sites within
10 km of a boundary are flagged for the engineer.
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point, shape

from .secure import load_bundle


def _side(line, p):
    L = np.array(line)
    best = None
    for u, v in zip(L[:-1], L[1:]):
        d = v - u
        t = np.clip(np.dot(np.array(p) - u, d) / np.dot(d, d), 0, 1)
        q = u + t * d
        dist_km = math.hypot((p[0] - q[0]) * 111.32 * math.cos(math.radians(p[1])), (p[1] - q[1]) * 110.57)
        if best is None or dist_km < best[0]:
            best = (dist_km, u, d)
    dist, u, d = best
    w = np.array(p) - u
    return float(np.sign(d[0] * w[1] - d[1] * w[0])), dist


def wind_region(lon: float, lat: float, bundle: dict | None = None) -> dict:
    b = bundle or load_bundle() or {}
    lines = b.get("asnzs1170_2_wind_region_lines")
    if not lines:
        return {"status": "unavailable", "reason": "Wind region lines not in the data bundle"}
    p = (lon % 360, lat)
    s1, d1 = _side(lines["NZ1_NZ2"], p)
    s2, d2 = _side(lines["NZ3_east"], p)
    s3, d3 = _side(lines["NZ3_west"], p)
    s4, d4 = _side(lines["NZ4"], p)
    sg = lines["_sign"]
    d = min(d1, d2, d3, d4)
    if p[1] < -47.5 or p[0] > 179.0 or p[0] < 166.0:
        r, note = "NZ4", "Chatham or Auckland Islands (Figure 3.1(B) note)"
    elif p[1] > -39.6 and s1 == sg["NZ1"]:
        r, note = "NZ1", None
    elif -42.4 < p[1] < -40.5 and s2 == sg["NZ3_e"] and s3 == sg["NZ3_w"]:
        r, note = "NZ3", None
    elif p[1] < -45.2 and s4 == sg["NZ4"]:
        r, note = "NZ4", None
    else:
        r, note = "NZ2", None
    return {"status": "ok", "region": r, "distance_to_boundary_km": round(d, 1), "near_boundary": d <= 10,
            "note": note, "source": lines.get("source"), "fit_median_km": round(lines["_fit"]["median_km"], 1)}


def lee_zones(lon: float, lat: float, bundle: dict | None = None) -> dict:
    """North Island lee zones containing the site (zones 1–6). South Island zones come from Table 4.5 crests."""
    b = bundle or load_bundle() or {}
    fc = b.get("asnzs1170_2_lee_zones_ni")
    if not fc:
        return {"status": "unavailable", "reason": "Lee zone polygons not in the data bundle"}
    p = Point(lon, lat)
    hits = []
    for f in fc["features"]:
        g = shape(f["geometry"])
        if g.contains(p):
            hits.append(dict(f["properties"]))
        elif g.distance(p) * 111 < 3:
            hits.append({**f["properties"], "part": f["properties"]["part"] + " (within 3 km of edge)"})
    return {"status": "ok", "zones": hits, "fit_median_km": round(fc["fit"]["median_km"], 1),
            "note": "Digitised from Figure 4.6 (about 1 km fit; zone edges ±2–4 km at this scale). "
                    "Lateral transition zones are indicative; compute them from Clause 4.4.3(c)."}
