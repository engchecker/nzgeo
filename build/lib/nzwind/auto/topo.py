"""Automatic hill, ridge and escarpment detection from LiDAR DEM profiles (AS/NZS 1170.2 Cl 4.4.2).

For each cardinal direction, profiles are cut through the site at the cardinal bearing and at
±11.25° and ±22.5° (the clause asks for the most adverse cross-section within ±22.5°).
On each profile every crest within reach is tested:
  H  = crest elevation minus the lowest ground upwind before the profile climbs back above the crest
  Lu = horizontal distance upwind from the crest to the level H/2 below it
  type = escarpment if the average downwind slope from the crest over max(3.6 Lu, 4H) is <= 0.05,
         otherwise hill or ridge
  x  = horizontal distance from the crest to the site (positive downwind)
The candidate giving the highest Mh at the site governs.
"""
import math
import numpy as np
from scipy.ndimage import map_coordinates, uniform_filter1d
from ..data import DIRECTIONS, BEARING
from ..topography import Feature, mh

STEP = 5.0          # profile sample spacing (m)
OFFSETS = [-22.5, -11.25, 0.0, 11.25, 22.5]

def sample_profile(dem, grid, site_xy, bearing_deg, reach):
    """Elevations along the line through the site; s is positive DOWNWIND (wind from bearing)."""
    s = np.arange(-reach, reach + STEP, STEP)
    b = math.radians(bearing_deg)
    ux, uy = -math.sin(b), -math.cos(b)                 # downwind unit vector
    x = site_xy[0] + s * ux
    y = site_xy[1] + s * uy
    col = (x - grid.x0) / grid.res - 0.5
    row = (grid.y0 - y) / grid.res - 0.5
    z = map_coordinates(dem, [row, col], order=1, mode="constant", cval=np.nan)
    return s, z

def _candidates(s, z, reach_up):
    """Crest candidates. Smoothing (15 m) only locates candidates; H, Lu and the crest
    position are measured on the raw LiDAR profile."""
    finite = np.isfinite(z)
    if not finite.any():
        return []
    zr = np.where(finite, z, np.nanmin(z))
    zs = uniform_filter1d(zr, 3)
    zs[~finite] = np.nan
    n = len(s)
    # crest: ground rising into the point (gradient > 0.02) and not rising beyond it
    # (gradient <= 0.01), each measured over two samples
    peaks = [i for i in range(2, n - 2) if finite[i - 2:i + 3].all()
             and (zs[i] - zs[i - 2]) / (2 * STEP) > 0.02 and (zs[i + 2] - zs[i]) / (2 * STEP) <= 0.01]
    out, seen = [], set()
    for i0 in peaks:
        # refine on raw profile: largest drop in gradient within +/- 3 samples
        lo, hi = max(1, i0 - 3), min(n - 2, i0 + 3)
        i = max(range(lo, hi + 1), key=lambda k: (zr[k] - zr[k - 1]) - (zr[k + 1] - zr[k]))
        if i in seen:
            continue
        seen.add(i)
        Ec = zr[i]
        j, base, ibase = i, Ec, i
        while j > 0 and finite[j - 1] and zr[j - 1] <= Ec + 0.5:          # walk upwind
            j -= 1
            if zr[j] < base - 0.5:
                base, ibase = zr[j], j
            elif (s[ibase] - s[j]) > max(300.0, s[i] - s[ibase]):
                break                                                   # flat ground upwind: base found
        H = Ec - base
        if H < 1:
            continue
        half = Ec - H / 2
        k = i
        while k > ibase and zr[k] > half:
            k -= 1
        # interpolate the half-height crossing between k and k+1
        sk = s[k] + (half - zr[k]) / (zr[k + 1] - zr[k]) * STEP if zr[k + 1] != zr[k] else s[k]
        Lu = max(s[i] - sk, STEP)
        Ld = max(3.6 * Lu, 4 * H)
        kd = min(n - 1, i + int(round(Ld / STEP)))
        if not finite[kd]:
            continue
        down_slope = (Ec - zr[kd]) / max(s[kd] - s[i], STEP)
        kind = "escarpment" if down_slope <= 0.05 and s[kd] - s[i] >= Ld * 0.95 else "hill"
        out.append({"i": i, "s_crest": float(s[i]), "E_crest": float(Ec), "H": float(H), "Lu": float(Lu),
                    "kind": kind, "down_slope": float(down_slope), "base_s": float(s[ibase])})
    return out

def analyse_topography(dem, grid, site_xy, h, z, reach=2500.0):
    """Returns per-direction suggested Feature, governing profile and candidates."""
    zsite = sample_profile(dem, grid, site_xy, 0, 0)[1][0]
    out = {"site_elevation_m": None if not np.isfinite(zsite) else round(float(zsite), 1), "directions": {}}
    for d in DIRECTIONS:
        best = None
        for off in OFFSETS:
            brg = (BEARING[d] + off) % 360
            s, zz = sample_profile(dem, grid, site_xy, brg, reach)
            if not np.isfinite(zz).any():
                continue
            for c in _candidates(s, zz, reach):
                x = -c["s_crest"]                        # crest upwind (s<0) -> site downwind, x > 0
                slope = c["H"] / (2 * c["Lu"])
                f = Feature(c["kind"], round(c["H"], 1), round(c["Lu"], 1), round(x, 1), False)
                r = mh(f, z, h)
                cand = {**c, "x": x, "slope": slope, "bearing": brg, "mh": r["mh"], "detail": r}
                if best is None or r["mh"] > best["mh"]:
                    best = {**cand, "profile": (s, zz)}
        if best is None or best["mh"] <= 1.0:
            s, zz = sample_profile(dem, grid, site_xy, BEARING[d], reach)
            out["directions"][d] = {"feature": {"kind": "none", "H": 0, "Lu": 0, "x": 0, "peak_zone": False},
                                    "mh": 1.0, "bearing": BEARING[d], "profile": _thin(s, zz), "flags": [],
                                    "note": "No crest within reach gives Mh above 1.0"}
            continue
        s, zz = best.pop("profile")
        flags = []
        if best["slope"] > 0.45:
            flags.append("Upwind slope over 0.45: confirm whether the site is in the peak zone (Figure 4.5)")
        if best["kind"] == "escarpment" and best["down_slope"] > 0.03:
            flags.append(f"Downwind slope {best['down_slope']:.3f} is close to the 0.05 escarpment limit")
        if abs(best["bearing"] - BEARING[d]) % 360 > 1e-6:
            flags.append(f"Most adverse section at {best['bearing']:.1f}°, within ±22.5° of {d}")
        out["directions"][d] = {
            "feature": {"kind": best["kind"], "H": round(best["H"], 1), "Lu": round(best["Lu"], 1),
                        "x": round(best["x"], 1), "peak_zone": False},
            "mh": round(best["mh"], 3), "bearing": best["bearing"], "slope": round(best["slope"], 3),
            "crest_s": best["s_crest"], "crest_E": round(best["E_crest"], 1), "base_s": best["base_s"],
            "profile": _thin(s, zz), "flags": flags}
    return out

def _thin(s, z, n=400):
    k = max(1, len(s) // n)
    return {"s": [round(float(v), 1) for v in s[::k]],
            "z": [None if not np.isfinite(v) else round(float(v), 2) for v in z[::k]]}
