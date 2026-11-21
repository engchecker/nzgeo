"""Proposes terrain categories along each 45° upwind sector (AS/NZS 1170.2:2021 Cl 4.2.1).

Method
1. Split the area around the site into 8 sectors (cardinal direction ±22.5°) and 50 m radial bins.
2. Measure in each bin, from LiDAR (DSM - DEM), building outlines, land cover and imagery:
   water fraction, buildings and house-size equivalents per hectare, mean building height,
   obstructions >= 1.5 m per hectare, isolated obstructions > 5 m per hectare, tall-vegetation cover.
3. Apply the Cl 4.2.1 category definitions as ordered rules (see `_rules`).
4. Cross-check with roughness length z0 (Macdonald et al. 1998) and the standard's relation
   z0 = 2 x 10^(TC - 4) (Note to Cl 4.2.1). Disagreement lowers confidence.
5. Report a TC range where a measure sits near a threshold, or the cross-check disagrees.
DEM alone is never used to classify; it only removes ground height from the DSM.
"""
import math
import numpy as np
from scipy import ndimage
from .config import P, LCDB, LCDB_FALLBACK_TC
from ..data import DIRECTIONS

TCS = [1, 2, 2.5, 3, 4]

def _neighbour(tc, step):
    i = TCS.index(tc) + step
    return TCS[min(max(i, 0), len(TCS) - 1)]

def tc_from_z0(z0):
    """Inverse of z0 = 2 x 10^(TC - 4), clamped to 1-4."""
    return float(min(4.0, max(1.0, 4 + math.log10(max(z0, 1e-6) / 2))))

def z0_macdonald(h, lp, lf):
    """Macdonald, Griffiths & Hall (1998), alpha 4.43, beta 1.0, Cd 1.2, kappa 0.4."""
    if h <= 0 or lp <= 0 or lf <= 0:
        return None
    lp, lf = min(lp, 0.9), min(lf, 0.9)
    d = 1 + 4.43 ** (-lp) * (lp - 1)
    z0 = (1 - d) * math.exp(-(0.5 * 1.0 * 1.2 / 0.16 * (1 - d) * lf) ** -0.5)
    return z0 * h

# ---------------------------------------------------------------- pixel-level layers

def _layers(sd):
    g = sd.grid
    X, Y = g.centres()
    sx, sy = sd.site_xy
    dx, dy = X - sx, Y - sy
    dist = np.hypot(dx, dy)
    bearing = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    sector = (np.floor((bearing + 22.5) / 45) % 8).astype(int)
    nbins = int(np.ceil(dist.max() / P["bin_m"]))
    binidx = np.minimum((dist // P["bin_m"]).astype(int), nbins - 1)

    have_dsm = sd.dsm is not None and sd.dem is not None
    if have_dsm:
        ndsm = np.where(np.isfinite(sd.dsm - sd.dem), sd.dsm - sd.dem, np.nan)
        ndsm = np.clip(ndsm, 0, 300)
    else:
        ndsm = None
    water = sd.water if sd.water is not None else np.zeros(g.shape, bool)

    bmask = np.zeros(g.shape, bool)
    bid = np.zeros(g.shape, np.int32)
    if sd.buildings is not None and len(sd.buildings):
        from rasterio.features import rasterize
        shapes = [(geom, i + 1) for i, geom in enumerate(sd.buildings.geometry) if geom is not None]
        bid = rasterize(shapes, out_shape=g.shape, transform=g.transform, fill=0, dtype="int32")
        bmask = bid > 0
    return dict(X=X, Y=Y, dist=dist, bearing=bearing, sector=sector, binidx=binidx, nbins=nbins,
                ndsm=ndsm, water=water, bmask=bmask, bid=bid, have_dsm=have_dsm)

def _building_table(sd, L):
    """Per-building: area, height (mean nDSM inside footprint), centroid sector/bin."""
    rows = []
    if sd.buildings is None or not len(sd.buildings):
        return rows
    sx, sy = sd.site_xy
    hmean = None
    if L["ndsm"] is not None:
        ids = L["bid"].ravel()
        vals = np.nan_to_num(L["ndsm"].ravel())
        n = len(sd.buildings) + 1
        cnt = np.bincount(ids, minlength=n)
        tot = np.bincount(ids, weights=vals, minlength=n)
        hmean = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
    for i, geom in enumerate(sd.buildings.geometry):
        if geom is None or geom.area < P["min_building_m2"]:
            continue
        c = geom.centroid
        dx, dy = c.x - sx, c.y - sy
        d = math.hypot(dx, dy)
        if d < 1:          # the subject site itself
            continue
        brg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        h = float(hmean[i + 1]) if hmean is not None and np.isfinite(hmean[i + 1]) else None
        rows.append({"area": geom.area, "h": h, "sector": int(((brg + 22.5) // 45) % 8),
                     "bin": int(d // P["bin_m"])})
    return rows

def _clumps(sd, L):
    """Non-building obstructions >= 1.5 m (trees, shelterbelts, unmapped structures)."""
    if L["ndsm"] is None:
        return None, []
    obs = (np.nan_to_num(L["ndsm"]) >= P["obstruction_min_h"]) & ~L["bmask"] & ~L["water"]
    lab, n = ndimage.label(obs)
    if n == 0:
        return obs, []
    idx = np.arange(1, n + 1)
    px = sd.grid.res ** 2
    area = ndimage.sum(obs, lab, idx) * px
    hmax = ndimage.maximum(np.nan_to_num(L["ndsm"]), lab, idx)
    com = ndimage.center_of_mass(obs, lab, idx)
    green = ndimage.mean(sd.exg, lab, idx) if sd.exg is not None else np.full(n, np.nan)
    rows = []
    sx, sy = sd.site_xy
    for k in range(n):
        if area[k] < 4:
            continue
        r, c = com[k]
        x = sd.grid.x0 + (c + 0.5) * sd.grid.res
        y = sd.grid.y0 - (r + 0.5) * sd.grid.res
        dx, dy = x - sx, y - sy
        brg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        unmapped = (np.isfinite(green[k]) and green[k] < P["exg_veg"] and area[k] >= 40 and hmax[k] >= 2.5)
        rows.append({"area": float(area[k]), "hmax": float(hmax[k]), "sector": int(((brg + 22.5) // 45) % 8),
                     "bin": int(math.hypot(dx, dy) // P["bin_m"]), "unmapped_structure": bool(unmapped)})
    return obs, rows

def _frontal_rise(ndsm, sector_i, res):
    """Positive height step met by wind from this sector, per pixel (frontal area / res)."""
    if ndsm is None:
        return None
    h = np.nan_to_num(ndsm)
    h = np.where(h >= P["obstruction_min_h"], h, 0)
    b = math.radians(sector_i * 45)
    # wind comes FROM bearing b, so the upwind neighbour is one step towards b
    dc, dr = int(round(math.sin(b))), -int(round(math.cos(b)))
    up = np.roll(np.roll(h, -dr, axis=0), -dc, axis=1)
    rise = np.clip(h - up, 0, None)
    return rise * (res if (dc == 0 or dr == 0) else res / math.sqrt(2))

# ---------------------------------------------------------------- rules

def _rules(m):
    """Cl 4.2.1 definitions as ordered rules. Returns (tc, rule text, deciding ratios)."""
    near = []
    if m["water_frac"] >= P["water_frac"]:
        return 1, "TC1: water surface (Cl 4.2.1(a): all water surfaces)", near
    eq, hb = m["house_eq_per_ha"], m["bldg_h_mean"]
    if eq >= P["tc3_house_eq_per_ha"] and hb is not None and hb >= P["tc4_min_h"]:
        near += [("house_eq", eq / P["tc3_house_eq_per_ha"], -1), ("bldg_h", hb / P["tc4_min_h"], -1)]
        return 4, f"TC4: {eq:.0f} house-size equivalents/ha with mean height {hb:.0f} m (Cl 4.2.1(e): 10-30 m, closely spaced)", near
    mix = eq / P["tc3_house_eq_per_ha"] + m["tall_veg_cover"] / P["dense_forest_cover"]
    if mix >= 1:
        if hb is not None and hb >= 0.75 * P["tc4_min_h"] and eq >= P["tc3_house_eq_per_ha"]:
            near.append(("bldg_h", hb / P["tc4_min_h"], +1))
        near.append(("mix", mix, -1))
        what = (f"{eq:.0f} house-size equivalents/ha" if eq / P["tc3_house_eq_per_ha"] >= m["tall_veg_cover"] / P["dense_forest_cover"]
                else f"tall vegetation over {m['tall_veg_cover']:.0%} of the bin (dense forest)")
        return 3, f"TC3: {what} (Cl 4.2.1(d): >= 10 house-size obstructions/ha, or dense forest)", near
    near.append(("mix", mix, +1))
    if (m["bldg_per_ha"] > P["tc2_max_per_ha"] or m["obstructions_per_ha"] > P["tc2_max_per_ha"]
            or m["tall_isolated_per_ha"] >= P["tall_isolated_per_ha"] or m["tall_veg_cover"] >= P["some_trees_cover"]):
        near.append(("obs", m["obstructions_per_ha"] / P["tc2_max_per_ha"], -1))
        return 2.5, (f"TC2.5: {m['obstructions_per_ha']:.1f} obstructions/ha ({m['bldg_per_ha']:.1f} buildings), "
                     f"tall vegetation {m['tall_veg_cover']:.0%} (Cl 4.2.1(c): some trees or 2-10 buildings/ha)"), near
    near.append(("obs", m["obstructions_per_ha"] / P["tc2_max_per_ha"], +1))
    if m["obstructions_per_ha"] <= P["open_max_per_ha"] and (m["water_frac"] >= 0.2 or m["bare_frac"] >= 0.5):
        return 1, "TC1: open water or bare ground with no obstructions (Cl 4.2.1(a))", near
    return 2, f"TC2: {m['obstructions_per_ha']:.1f} obstructions/ha of 1.5-5 m (Cl 4.2.1(b): no more than 2/ha)", near

def _fallback(m):
    """Land-cover-only proposal where no LiDAR DSM is available."""
    if m["water_frac"] >= P["water_frac"]:
        return 1, "TC1: water surface (Cl 4.2.1(a)); no LiDAR DSM"
    shares = m["lcdb_share"]
    if not shares:
        return 2, "TC2 assumed: no LiDAR DSM or land cover for this bin"
    top = max(shares, key=shares.get)
    for group, tc in LCDB_FALLBACK_TC:
        if top in LCDB[group]:
            return tc, f"TC{tc}: land cover class {top} ({group}); no LiDAR DSM, so obstruction density not measured"
    return 2, f"TC2 assumed: land cover class {top}"

# ---------------------------------------------------------------- main

def analyse_terrain(sd):
    L = _layers(sd)
    blds = _building_table(sd, L)
    _, clumps = _clumps(sd, L)
    px_ha = sd.grid.res ** 2 / 10000
    end_cov = (min(sd.grid.shape) * sd.grid.res) / 2     # inscribed radius = full sector coverage
    nb = int(end_cov // P["bin_m"])
    out = {}
    for si, d in enumerate(DIRECTIONS):
        insec = L["sector"] == si
        rise = _frontal_rise(L["ndsm"], si, sd.grid.res)
        bins = []
        for b in range(nb):
            mask = insec & (L["binidx"] == b)
            npx = int(mask.sum())
            if npx == 0:
                continue
            area_ha = npx * px_ha
            water_frac = float(L["water"][mask].mean())
            bb = [r for r in blds if r["sector"] == si and r["bin"] == b]
            cc = [r for r in clumps if r["sector"] == si and r["bin"] == b]
            unm = [r for r in cc if r["unmapped_structure"]]
            trees = [r for r in cc if not r["unmapped_structure"]]
            bplan = sum(r["area"] for r in bb) + sum(r["area"] for r in unm)
            nb_ = len(bb) + len(unm)
            hs = [r["h"] for r in bb if r["h"] is not None] + [r["hmax"] * 0.8 for r in unm]
            hb = float(np.average(hs, weights=[r["area"] for r in bb if r["h"] is not None] + [r["area"] for r in unm])) if hs else None
            if L["ndsm"] is not None:
                nd = np.nan_to_num(L["ndsm"][mask])
                tall_veg = (nd >= P["tc3_min_h"]) & ~L["bmask"][mask] & ~L["water"][mask]
                if sd.exg is not None:
                    tall_veg &= sd.exg[mask] >= P["exg_veg"]
                tall_veg_cover = float(tall_veg.mean())
                obs_px = nd >= P["obstruction_min_h"]
                lp = float(obs_px.mean())
                hob = float(nd[obs_px].mean()) if obs_px.any() else 0.0
                lf = float(rise[mask].sum() / (area_ha * 10000))
            else:
                tall_veg_cover, lp, hob, lf = 0.0, 0.0, 0.0, 0.0
            lc = sd.lcdb[mask] if sd.lcdb is not None else np.array([], int)
            lc = lc[lc > 0]
            shares = {int(k): float(v) / len(lc) for k, v in zip(*np.unique(lc, return_counts=True))} if len(lc) else {}
            bare_frac = sum(v for k, v in shares.items() if k in LCDB["bare"])
            m = {
                "water_frac": water_frac, "bare_frac": bare_frac,
                "bldg_per_ha": nb_ / area_ha,
                "house_eq_per_ha": max(nb_, bplan / P["house_area_m2"]) / area_ha,
                "bldg_h_mean": hb, "plan_frac_bldg": bplan / (area_ha * 10000),
                "obstructions_per_ha": (nb_ + len(trees)) / area_ha,
                "tall_isolated_per_ha": (sum(1 for r in trees if r["hmax"] > P["tall_obstruction_h"])
                                          + sum(1 for r in bb if (r["h"] or 0) > P["tall_obstruction_h"])) / area_ha
                                         if L["have_dsm"] else 0.0,
                "tall_veg_cover": tall_veg_cover, "lcdb_share": shares,
                "unmapped_structures": len(unm),
            }
            flags = []
            if L["have_dsm"] and np.isfinite(sd.dsm[mask]).mean() > 0.5:
                tc, rule, near = _rules(m)
                conf = "high"
            else:
                tc, rule = _fallback(m)
                near, conf = [], "low"
                flags.append("No LiDAR DSM: proposed from land cover only")
            lo, hi = tc, tc
            for _, ratio, step in near:
                if abs(ratio - 1) <= P["near_threshold"]:
                    alt = _neighbour(tc, step)
                    lo, hi = min(lo, alt), max(hi, alt)
            if lo != hi and conf == "high":
                conf = "medium"
            # z0 cross-check
            if water_frac >= P["water_frac"]:
                z0 = 0.0002
            elif lp < 0.01:
                z0 = 0.002 if bare_frac >= 0.5 else 0.02
            else:
                z0 = z0_macdonald(hob, lp, lf) or 0.02
            tcz = tc_from_z0(z0)
            veg_dominated = tall_veg_cover > m["plan_frac_bldg"] and tall_veg_cover >= P["some_trees_cover"]
            if veg_dominated:
                tcz_used = None
                flags.append("Roughness cross-check not applied: vegetation canopy (Macdonald method is for building arrays)")
            else:
                tcz_used = tcz
            if L["have_dsm"] and tcz_used is not None and abs(tcz - tc) > P["z0_disagree_tc"]:
                alt = min(TCS, key=lambda t: abs(t - tcz))
                lo, hi = min(lo, alt), max(hi, alt)
                conf = "low" if conf != "high" else "medium"
                flags.append(f"Roughness cross-check suggests TC{tcz:.1f}")
            if any(k in LCDB["plantation"] for k, v in shares.items() if v >= 0.3):
                flags.append("Plantation forest: may be harvested during the design life (Cl 4.2.1 permanence). Consider TC2.")
                lo = min(lo, 2)
                conf = "medium" if conf == "high" else conf
            if any(k in LCDB["harvested"] for k, v in shares.items() if v >= 0.3):
                flags.append("Harvested forest: regrowth expected; check the design life")
            if m["unmapped_structures"]:
                flags.append(f"{m['unmapped_structures']} structure(s) in LiDAR not in building outlines")
            bins.append({"start_m": b * P["bin_m"], "end_m": (b + 1) * P["bin_m"], "tc": tc, "tc_low": lo, "tc_high": hi,
                         "confidence": conf, "rule": rule, "flags": flags, "z0": round(z0, 4), "tc_z0": None if tcz_used is None else round(tcz, 2),
                         "metrics": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items() if k != "lcdb_share"}
                                    | {"lcdb": {str(k): round(v, 2) for k, v in shares.items() if v >= 0.05},
                                       "lambda_p": round(lp, 3), "lambda_f": round(lf, 3), "obstacle_h": round(hob, 1),
                                       "area_ha": round(area_ha, 2)}})
        out[d] = {"bins": bins, "bands": merge_bins(bins), "coverage_m": nb * P["bin_m"]}
    return out

def merge_bins(bins, key="tc"):
    bands = []
    for b in bins:
        if bands and bands[-1]["tc"] == b[key] and bands[-1]["end_m"] == b["start_m"]:
            bands[-1]["end_m"] = b["end_m"]
            bands[-1]["confidence"] = min(bands[-1]["confidence"], b["confidence"], key=["low", "medium", "high"].index)
        else:
            bands.append({"tc": b[key], "start_m": b["start_m"], "end_m": b["end_m"], "confidence": b["confidence"]})
    return bands
