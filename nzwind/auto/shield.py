"""Shielding buildings (AS/NZS 1170.2:2021 Cl 4.3) suggested from LINZ building outlines and LiDAR.

For each cardinal direction:
  - buildings whose footprint centroid lies within the 45° sector centred on the direction and within 20h
    of the site (Cl 4.3.2); the footprint containing the site itself is the subject and is left out
  - height hs: mean of DSM minus DEM inside the footprint, edge pixels excluded (average roof height)
  - breadth bs: footprint extent normal to the wind (Cl 4.3.3)
  - only buildings at least h tall qualify (Cl 4.3.2)
  - slope exclusion (Cl 4.3.1, Figure 4.2): average ground gradient between the site and the building
    greater than 0.2 excludes the building, unless its top is higher than the subject building's top
Vegetation never shields (Cl 4.3.1): only mapped building outlines are used. Structures missing from the
outlines are reported by the terrain mapping, not added here.
"""
from __future__ import annotations

import math

import numpy as np

from ..data import BEARING, DIRECTIONS

SECTOR_HALF = 22.5
BORDER_DEG = 3.0        # centroid within this of a sector edge -> flagged as borderline [assumption]
MIN_PIXELS = 3          # fewer LiDAR pixels inside the eroded footprint -> height unknown [assumption]


def _sample_dem(dem, grid, x, y):
    c = int((x - grid.x0) / grid.res)
    r = int((grid.y0 - y) / grid.res)
    if 0 <= r < dem.shape[0] and 0 <= c < dem.shape[1]:
        v = dem[r, c]
        return float(v) if np.isfinite(v) else None
    return None


def building_heights(sd):
    """Per footprint: mean nDSM over the interior (edge pixels dropped) and ground level, NZTM coordinates."""
    out = []
    if sd.buildings is None or not len(sd.buildings) or sd.dsm is None or sd.dem is None:
        return out
    from rasterio.features import rasterize
    from scipy import ndimage
    g = sd.grid
    geoms = list(sd.buildings.geometry)
    ids = rasterize([(geom, i + 1) for i, geom in enumerate(geoms) if geom is not None], out_shape=g.shape,
                    transform=g.transform, fill=0, dtype="int32")
    # erode each footprint by one pixel so walls and eaves edges do not pull the mean down
    inner = ids * (ndimage.minimum_filter(ids, size=3) == ids)
    ndsm = sd.dsm - sd.dem
    ok = np.isfinite(ndsm) & (inner > 0)
    n = len(geoms) + 1
    cnt = np.bincount(inner[ok], minlength=n)
    tot = np.bincount(inner[ok], weights=ndsm[ok], minlength=n)
    gtot = np.bincount(inner[ok], weights=sd.dem[ok], minlength=n)
    for i, geom in enumerate(geoms):
        if geom is None or geom.is_empty:
            continue
        k = i + 1
        h = float(tot[k] / cnt[k]) if cnt[k] >= MIN_PIXELS else None
        ground = float(gtot[k] / cnt[k]) if cnt[k] >= MIN_PIXELS else None
        out.append({"id": i, "geom": geom, "height_m": h, "ground_m": ground, "pixels": int(cnt[k])})
    return out


def suggest(sd, h: float) -> dict:
    """Suggested shielding buildings per direction, with the buildings left out and why."""
    res = {d: {"buildings": [], "excluded": [], "borderline": [], "flags": []} for d in DIRECTIONS}
    if h > 25:
        for d in DIRECTIONS:
            res[d]["flags"].append("h > 25 m: shielding does not apply (Cl 4.3.1)")
        return {"directions": res, "status": "not_applicable"}
    blds = building_heights(sd)
    if not blds:
        why = "No building outlines" if sd.buildings is None or not len(sd.buildings) else "No LiDAR DSM/DEM"
        return {"directions": res, "status": "no_data", "reason": f"{why}: enter shielding buildings by hand."}
    sx, sy = sd.site_xy
    from shapely.geometry import Point
    site_pt = Point(sx, sy)
    g_site = _sample_dem(sd.dem, sd.grid, sx, sy) if sd.dem is not None else None
    subject = [b for b in blds if b["geom"].buffer(1.0).contains(site_pt)]
    reach = 20 * h
    for b in blds:
        if b in subject:
            continue
        c = b["geom"].centroid
        dx, dy = c.x - sx, c.y - sy
        dist = math.hypot(dx, dy)
        if dist > reach or dist < 1:
            continue
        brg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        for d in DIRECTIONS:
            off = abs((brg - BEARING[d] + 180) % 360 - 180)
            if off > SECTOR_HALF:
                continue
            u = math.radians(BEARING[d])
            lx, ly = math.cos(u), -math.sin(u)              # lateral axis, normal to the wind
            xs, ys = np.asarray(b["geom"].exterior.coords if b["geom"].geom_type == "Polygon"
                                else max(b["geom"].geoms, key=lambda q: q.area).exterior.coords).T
            lat = xs * lx + ys * ly
            breadth = float(lat.max() - lat.min())
            rec = {"id": b["id"], "height_m": None if b["height_m"] is None else round(b["height_m"], 1),
                   "breadth_m": round(breadth, 1), "distance_m": round(dist, 1), "bearing_deg": round(brg, 1),
                   "ground_m": None if b["ground_m"] is None else round(b["ground_m"], 1)}
            if b["height_m"] is None:
                res[d]["excluded"].append({**rec, "reason": "no LiDAR height inside the footprint"})
                continue
            if b["height_m"] < h:
                res[d]["excluded"].append({**rec, "reason": f"lower than h ({b['height_m']:.1f} m < {h:.1f} m)"})
                continue
            slope_ex = False
            if g_site is not None and b["ground_m"] is not None:
                grad = abs(b["ground_m"] - g_site) / dist
                rec["ground_gradient"] = round(grad, 3)
                if grad > 0.2 and (b["ground_m"] + b["height_m"]) <= (g_site + h):
                    slope_ex = True
            rec["slope_excluded"] = slope_ex
            if SECTOR_HALF - off < BORDER_DEG or reach - dist < 0.05 * reach:
                rec["borderline"] = True
                res[d]["borderline"].append(rec["id"])
            res[d]["buildings"].append(rec)
    for d in DIRECTIONS:
        res[d]["buildings"].sort(key=lambda r: r["distance_m"])
        if subject:
            res[d]["flags"].append("An existing building outline contains the site; it is treated as the subject "
                                   "building and not counted as shielding. Confirm it is being replaced or is the subject.")
        if res[d]["borderline"]:
            res[d]["flags"].append(f"{len(res[d]['borderline'])} building(s) sit near the edge of the 45° sector or the "
                                   "20h radius: confirm whether they count.")
    return {"directions": res, "status": "ok", "h": h, "radius_m": round(reach, 1),
            "method": "LINZ building outlines; heights = mean LiDAR DSM minus DEM inside each footprint"}
