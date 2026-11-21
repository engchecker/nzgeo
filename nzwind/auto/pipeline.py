"""Runs automatic terrain and topography mapping for a site and returns reviewable suggestions."""
import datetime as dt
import math
import os
from .classify import analyse_terrain
from .topo import analyse_topography
from .shield import suggest as suggest_shielding
from .config import P
from . import sources as S
from ..data import DIRECTIONS, BEARING

DEMO = os.environ.get("NZWIND_DEMO") == "1"
_cache = {}

def coverage_needed(z):
    return max(P["min_coverage_m"], 1.25 * (20 * z + max(500.0, 40 * z)))

def auto_map(lon, lat, h, z):
    radius = coverage_needed(z) + 60
    res = 1.0 if radius <= 900 else 2.0
    key = (round(lon, 5), round(lat, 5), round(radius / 100), res, DEMO)
    if key not in _cache:
        if DEMO:
            from .demo import demo_site
            _cache[key] = demo_site(lon, lat, radius, res)
        else:
            _cache[key] = S.gather(lon, lat, radius, res)
    sd = _cache[key]
    terrain = analyse_terrain(sd)
    topo = analyse_topography(sd.topo_dem, sd.topo_grid, sd.site_xy, h, z) if sd.topo_dem is not None else None
    issues = list(sd.issues)
    if topo is None:
        issues.append("No DEM for topography: enter topographic features manually")
    dsm_dates = (sd.provenance.get("dsm") or {}).get("capture") or []
    flags = []
    try:
        yr = int(str(dsm_dates[-1])[:4]) if dsm_dates else None
        if yr and dt.date.today().year - yr > P["dsm_old_years"]:
            flags.append(f"LiDAR DSM captured {yr}: buildings and vegetation may have changed. Check against current imagery.")
    except (ValueError, TypeError):
        pass
    out = {"site": {"lon": lon, "lat": lat, "nztm": [round(v, 1) for v in sd.site_xy],
                    "elevation_m": topo["site_elevation_m"] if topo else None},
           "demo": DEMO, "parameters": P, "provenance": sd.provenance, "issues": issues, "flags": flags,
           "directions": {}}
    try:
        shield = suggest_shielding(sd, h)
    except Exception as e:  # never let shielding stop the terrain suggestions
        shield = {"status": "error", "reason": f"{type(e).__name__}: {e}", "directions": {}}
    out["shielding"] = {k: v for k, v in shield.items() if k != "directions"}
    for d in DIRECTIONS:
        t = terrain[d]
        bands = t["bands"]
        for b in bands:     # street-level evidence point at band mid-distance on the sector centreline
            mid = (b["start_m"] + b["end_m"]) / 2
            x = sd.site_xy[0] + math.sin(math.radians(BEARING[d])) * mid
            y = sd.site_xy[1] + math.cos(math.radians(BEARING[d])) * mid
            blon, blat = S.TO_WGS.transform(x, y)
            b["evidence_point"] = [round(blon, 6), round(blat, 6)]
            b["street_view"] = S.google_pano_url(blon, blat, (BEARING[d] + 180) % 360)
        out["directions"][d] = {"bins": t["bins"], "bands": bands, "coverage_m": t["coverage_m"],
                                "topography": topo["directions"][d] if topo else None,
                                "shielding": (shield.get("directions") or {}).get(d)}
    return out
