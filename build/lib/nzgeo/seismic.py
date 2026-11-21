"""Seismic site parameters.

TS 1170.5:2025 (alternative solution) from the published Tables 3.1 and 3.2 (GNS-Science/TS1170.5-SDP,
deliverables/v2): a site inside a Figure 3.2 settlement polygon takes that settlement's row; any other
site takes the nearest 0.1 degree grid point. NZS 1170.5:2004 Z comes from the digitised data bundle.
"""
from __future__ import annotations

import csv
import json
import math
from functools import lru_cache

import numpy as np
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from .config import DATA_DIR, settings
from .geo import bearing_name, nearest, to_nztm

TS_DIR = DATA_DIR / "ts1170_5"
APOES = (25, 50, 100, 250, 500, 1000, 2500)
SITE_CLASSES = ("I", "II", "III", "IV", "V", "VI")
TS_LABEL = ("TS 1170.5:2025 – alternative solution. B1/VM1 cites NZS 1170.5:2004; use of TS 1170.5 "
            "requires acceptance by the building consent authority as an alternative solution.")


@lru_cache(maxsize=1)
def _polygons():
    d = json.loads((TS_DIR / "TS1170-5_Figure3-2_2025.geojson").read_text())
    geoms = [shape(f["geometry"]) for f in d["features"]]
    names = [f["properties"]["Name"] for f in d["features"]]
    return STRtree(geoms), geoms, names


@lru_cache(maxsize=1)
def _grid():
    d = json.loads((TS_DIR / "TS1170-5_GridPoints_2025.geojson").read_text())
    names = [f["properties"]["Name"] for f in d["features"]]
    xy = np.array([to_nztm(*f["geometry"]["coordinates"][:2]) for f in d["features"]])
    return names, xy


@lru_cache(maxsize=2)
def _table(which: str) -> dict:
    fn = "TS1170-5_Table3-1_2025.csv" if which == "3.1" else "TS1170-5_Table3-2_2025.csv"
    rows = {}
    with open(TS_DIR / fn, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            apoe = int(r["apoe"].strip().split("/")[1])
            rows[(r["location"], apoe)] = r
    return rows


@lru_cache(maxsize=1)
def _faults():
    d = json.loads((TS_DIR / "TS1170-5_MajorFaults_2025.geojson").read_text())
    out = []
    for f in d["features"]:
        g = shape(f["geometry"])
        coords = [to_nztm(x, y) for x, y, *_ in g.coords]
        from shapely.geometry import LineString
        out.append((f["properties"]["Name"], LineString(coords)))
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v.strip() if isinstance(v, str) else v


def ts_location(lon: float, lat: float) -> tuple[str, str]:
    """(table, location id) for a site."""
    tree, geoms, names = _polygons()
    p = Point(lon, lat)
    for i in tree.query(p, predicate="intersects"):
        return "3.1", names[int(i)]
    gnames, xy = _grid()
    x, y = to_nztm(lon, lat)
    i = int(np.argmin((xy[:, 0] - x) ** 2 + (xy[:, 1] - y) ** 2))
    return "3.2", gnames[i]


def ts_parameters(lon: float, lat: float, *, apoe_n: int | None = None,
                  site_classes: tuple[str, ...] = SITE_CLASSES) -> dict:
    table, loc = ts_location(lon, lat)
    rows = _table(table)
    by_apoe = {}
    for a in APOES:
        r = rows.get((loc, a))
        if not r:
            continue
        by_apoe[a] = {"M": _num(r["M"]), "D": _num(r["D"]),
                      "classes": {sc: {"PGA": _num(r[f"{sc}-PGA"]), "Sas": _num(r[f"{sc}-Sas"]),
                                       "Tc": _num(r[f"{sc}-Tc"]), "Td": _num(r[f"{sc}-Td"])}
                                  for sc in site_classes}}
    x, y = to_nztm(lon, lat)
    best = None
    for name, line in _faults():
        d, vec = nearest((x, y), line)
        if best is None or d < best[0]:
            best = (d, vec, name)
    prov = json.loads((TS_DIR / "provenance.json").read_text())
    out = {"standard": "TS 1170.5:2025", "compliance_path": "alternative_solution", "label": TS_LABEL,
           "table": table, "location": loc, "parameters": by_apoe,
           "major_fault_reference": {"name": best[2], "distance_km": round(best[0] / 1000, 1),
                                     "direction": bearing_name(*best[1]),
                                     "note": "For reference only; TS 1170.5 requires the tabulated D for the location."},
           "source": f"{prov['source']} @ {prov['commit'][:10]} ({prov['folder']})"}
    if apoe_n is not None:
        if apoe_n not in by_apoe:
            out["selected"] = {"apoe_n": apoe_n, "error": f"1/{apoe_n} is not tabulated; tabulated: {', '.join('1/%d' % a for a in APOES)}"}
        else:
            out["selected"] = {"apoe_n": apoe_n, **by_apoe[apoe_n]}
    return out


# --- Site class from Vs30 (TS 1170.5 Table 3.x ranges; secondary criteria need investigation data) ---
_BOUNDS = [(750, "I"), (450, "II"), (300, "III"), (250, "IV"), (200, "V"), (150, "VI")]


def site_class_from_vs30(vs30: float) -> str:
    for lower, sc in _BOUNDS:
        if vs30 > lower:
            return sc
    return "VII"


def site_class_range(vs30: float, rel_uncertainty: float = 0.2) -> list[str]:
    hi, lo = site_class_from_vs30(vs30 * (1 + rel_uncertainty)), site_class_from_vs30(vs30 * (1 - rel_uncertainty))
    order = ["I", "II", "III", "IV", "V", "VI", "VII"]
    return order[order.index(hi): order.index(lo) + 1]


def vs30_at(lon: float, lat: float) -> dict:
    path = settings.vs30_h5
    if not path:
        return {"status": "unavailable",
                "reason": "Vs30 model not installed (run the setup wizard, step 4)"}
    import h5py
    with h5py.File(path, "r") as f:
        lats, lons = f["latitude"][:], f["longitude"][:]
        name = next(k for k in f.keys() if k not in ("latitude", "longitude") and f[k].ndim == 2)
        i = int(np.abs(lats - lat).argmin())
        j = int(np.abs(lons - lon).argmin())
        v = float(f[name][i, j])
    if not math.isfinite(v) or v <= 60:  # offshore cells are set to 50
        return {"status": "no_data", "source": path}
    return {"status": "ok", "vs30": round(v), "source": "NZ Vs30 model, NZ Community Velocity Model data (ucgmsim/nzcvm_data, NZ_Vs30_HD_With_Offshore, MIT)",
            "grid_point": [float(lons[j]), float(lats[i])]}


def site_class(lon: float, lat: float, *, vs30_override: float | None = None, class_override: str | None = None) -> dict:
    if class_override:
        return {"status": "ok", "site_class": class_override, "basis": "engineer input", "confidence": "engineer"}
    if vs30_override:
        return {"status": "ok", "vs30": vs30_override, "site_class": site_class_from_vs30(vs30_override),
                "range": site_class_range(vs30_override, 0.1), "basis": "engineer-supplied Vs30", "confidence": "medium"}
    v = vs30_at(lon, lat)
    if v["status"] != "ok":
        return {"status": v["status"], "reason": v.get("reason"), "site_class": None}
    return {"status": "ok", "vs30": v["vs30"], "site_class": site_class_from_vs30(v["vs30"]),
            "range": site_class_range(v["vs30"]), "basis": v["source"], "confidence": "low",
            "note": "Regional model only. Confirm by investigation (TS 1170.5 Section 3.1.3)."}


# --- NZS 1170.5:2004 hazard factor (from the digitised bundle) ---
def _r_factor(table: dict, apoe_n: int | None):
    if apoe_n is None:
        return None
    return table["R"].get(str(int(apoe_n)))


def _nmax(table: dict, T: float) -> float:
    pts = table["Nmax"]
    if T <= pts[0][0]:
        return pts[0][1]
    for (t0, n0), (t1, n1) in zip(pts, pts[1:]):
        if t0 <= T <= t1:
            return n0 + (n1 - n0) * (T - t0) / (t1 - t0)
    return pts[-1][1]


def _parse_d(d: str):
    """'-' -> None; '8–16' -> (8, 16); '2' -> (2, 2)."""
    d = (d or "").replace("-", "–").strip()
    if d in ("", "–"):
        return None
    parts = [float(x) for x in d.split("–") if x.strip()]
    return (min(parts), max(parts))


@lru_cache(maxsize=1)
def _z_interp_cache():
    return {}


def _interp(towns, x, y):
    from scipy.interpolate import RBFInterpolator
    key = id(towns)
    cache = _z_interp_cache()
    if key not in cache:
        seen = {}
        for t in towns:
            seen.setdefault((t["lon"], t["lat"]), t)
        pts = list(seen.values())
        X = np.array([to_nztm(t["lon"], t["lat"]) for t in pts])
        cache[key] = RBFInterpolator(X, np.array([t["Z"] for t in pts]), kernel="thin_plate_spline")
    return float(cache[key](np.array([[x, y]]))[0])


def nzs1170_5_z(lon: float, lat: float, bundle: dict | None, *, apoe_n: int | None = None,
                territorial_authority: str | None = None, fault_distance: dict | None = None) -> dict:
    data = (bundle or {}).get("nzs1170_5_z")
    std = "NZS 1170.5:2004 as modified by B1/VM1 (2nd ed.)"
    if not data:
        return {"status": "unavailable", "standard": std,
                "reason": "NZS 1170.5 Table 3.3 is not in the data bundle (key 'nzs1170_5_z')"}
    towns = data["towns"]
    x, y = to_nztm(lon, lat)
    out = {"status": "ok", "standard": std, "flags": []}
    # 1. Listed locality (Table 3.3 values govern, clause 3.1.4)
    listed = None
    tree, geoms, names = _polygons()
    poly_name = next((names[int(i)] for i in tree.query(Point(lon, lat), predicate="intersects")), None)
    if poly_name:
        cands = [t for t in towns if t.get("ts_polygon") == poly_name]
        if cands:
            listed = min(cands, key=lambda t: len(t["name"]))  # 'Wellington' before 'Wellington CBD (...)'
    if listed is None:
        for t in towns:  # localities without a TS polygon: within 3 km of the point
            if not t.get("ts_polygon") and math.dist((x, y), to_nztm(t["lon"], t["lat"])) <= 3000:
                listed = t
                break
    near = min(towns, key=lambda t: math.dist((x, y), to_nztm(t["lon"], t["lat"])))
    near_km = math.dist((x, y), to_nztm(near["lon"], near["lat"])) / 1000
    if listed:
        z = listed["Z"]
        out.update(basis=f"Table 3.3 location {listed['no']} {listed['name']}", listed=listed["name"], confidence="table")
        if listed["name"].startswith("Wellington"):
            out["flags"].append("Wellington CBD (north of the Basin Reserve) has D = 2 km; the rest of Wellington 0–8 km. "
                                "Confirm which applies.")
    else:
        z = round(_interp(towns, x, y), 2)
        conf = "medium" if near_km <= 15 else "low"
        out.update(basis=f"Interpolated from Table 3.3 locations (nearest: {near['name']}, {near_km:.0f} km, Z = {near['Z']})",
                   confidence=conf)
        out["flags"].append("Unlisted location: confirm Z by interpolating from "
                            + ("Figure 3.3" if lat > -41.7 and lon > 172.5 else "Figure 3.4")
                            + " (site marked on the figure extract below).")
        if conf == "low":
            out["flags"].append(f"More than 15 km from any listed location; the interpolated value may be out by 0.05 or more "
                                "where contours are tight (Fiordland, the Alpine Fault zone, Marlborough).")
    z = max(z, data["zmin"])
    # 2. B1/VM1 modifications
    mods = data["b1vm1"]
    if listed and listed["name"] in mods["table_overrides"]:
        z = max(z, mods["table_overrides"][listed["name"]])
        out["flags"].append(f"B1/VM1 {mods['edition'].split('(')[0].strip()} replaces the Table 3.3 value for "
                            f"{listed['name']} with {mods['table_overrides'][listed['name']]}.")
    ta = (territorial_authority or "").replace("ā", "a")
    in_canty = any(c.split()[0].lower() in ta.lower() for c in mods["canterbury_tas"]) if ta else None
    if in_canty:
        if z < mods["canterbury_min_z"]:
            out["flags"].append(f"Canterbury earthquake region ({ta}): B1/VM1 sets a minimum Z of {mods['canterbury_min_z']}.")
        z = max(z, mods["canterbury_min_z"])
    elif in_canty is None and -44.2 < lat < -42.8 and 171.4 < lon < 173.2:
        out["flags"].append("District not resolved: if the site is in Christchurch City, Selwyn or Waimakariri District, "
                            "B1/VM1 sets a minimum Z of 0.3.")
    out["Z"] = round(z, 2)
    # 3. Return period factor and the 0.7 cap
    R = _r_factor(data, apoe_n)
    if R is not None:
        zr = z * R
        out.update(R=R, apoe_n=apoe_n, ZR=round(min(zr, data["zr_max"]), 3))
        if zr > data["zr_max"]:
            out["flags"].append(f"Z·R = {zr:.3f} is limited to {data['zr_max']} (clause 3.1.1).")
    elif apoe_n is not None:
        out["flags"].append(f"Return period factor not tabulated for 1/{apoe_n} (Table 3.5).")
    # 4. Near-fault distance D (clause 3.1.6)
    nf = {"faults": data["near_fault_faults"]}
    if listed:
        d = _parse_d(listed["D_km"])
        if d is None:
            nf.update(D_km=None, basis="Table 3.3 gives no distance: N(T,D) = 1.0", applies=False)
        else:
            nf.update(D_km=d[0], D_range=list(d), basis="Table 3.3 (shortest listed distance by default)", applies=d[0] < 20)
            if d[0] != d[1]:
                nf["note"] = f"Table 3.3 range {d[0]:g}–{d[1]:g} km; a larger D may be justified by detailed geological information."
    elif fault_distance and fault_distance.get("distance_km") is not None:
        dk = fault_distance["distance_km"]
        nf.update(D_km=round(dk, 1), basis=f"Indicative: distance to the mapped trace of the {fault_distance['name']} "
                  f"(NZ Active Faults Database), not the fault plane", applies=dk < 20)
        if dk < 20:
            out["flags"].append("Unlisted location within 20 km of a Table 3.6 fault: determine D to the fault plane from "
                                "detailed geological information (clause 3.1.6).")
    else:
        nf.update(D_km=None, basis="No Table 3.6 fault trace found within 25 km, or fault data unavailable", applies=False)
    if nf.get("applies"):
        D = nf["D_km"]
        nf["Nmax"] = {str(t): n for t, n in data["Nmax"]}
        nf["N_at_T"] = {str(T): round(_nmax(data, T) if D <= 2 else 1 + (_nmax(data, T) - 1) * (20 - D) / 18, 3)
                        for T in (1.5, 2.0, 3.0, 4.0, 5.0)}
        nf["note_apoe"] = "N(T,D) = 1.0 for annual probability of exceedance of 1/250 or more frequent (clause 3.1.6.1)."
    out["near_fault"] = nf
    return out


def nzs1170_5_figure_png(lon: float, lat: float, bundle: dict | None, half_km: float = 60) -> str | None:
    """A crop of Figure 3.3 or 3.4 around the site with the site marked, as a base64 PNG."""
    figs = (bundle or {}).get("nzs1170_5_figures")
    if not figs:
        return None
    import base64
    import io
    from PIL import Image, ImageDraw
    from pyproj import Transformer
    tmg = Transformer.from_crs(4326, 27200, always_xy=True)
    e, n = tmg.transform(lon, lat)
    for m in figs["maps"]:
        A = np.vstack([np.array(m["A"]), [0, 0, 1]])
        px, py, _ = np.linalg.inv(A) @ np.array([e, n, 1.0])
        im = Image.open(io.BytesIO(base64.b64decode(m["jpeg_b64"]))).convert("RGB")
        if not (0 <= px < im.width and 0 <= py < im.height - 70):
            continue
        r = half_km * 1000 / abs(A[0, 0])
        box = (int(max(0, px - r)), int(max(0, py - r)), int(min(im.width, px + r)), int(min(im.height, py + r)))
        crop = im.crop(box).resize(((box[2] - box[0]) * 3, (box[3] - box[1]) * 3), Image.LANCZOS)
        d = ImageDraw.Draw(crop)
        cx, cy = (px - box[0]) * 3, (py - box[1]) * 3
        d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), outline=(220, 0, 0), width=4)
        d.line((cx - 16, cy, cx + 16, cy), fill=(220, 0, 0), width=2)
        d.line((cx, cy - 16, cx, cy + 16), fill=(220, 0, 0), width=2)
        buf = io.BytesIO(); crop.save(buf, "PNG")
        return m["figure"] + "|" + base64.b64encode(buf.getvalue()).decode()
    return None
