"""Run every check for one site. Each check fails soft: a failure is reported, never hidden."""
from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from shapely.geometry import Point

from . import __version__, arcgis, coast, councils, discover, durability, national, seismic, standards, windzones
from .config import settings
from .geo import bearing_name, nearest, to_nztm
from .hazards import HAZARDS, clean_attributes
from .secure import load_bundle


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "reason": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=2)}


def _in_bbox(b, lon, lat, pad=0.02):
    return b is None or (b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad)


def _check_layer(rec: dict, lon: float, lat: float) -> dict | None:
    url = f"{rec['service']}/{rec['layer_id']}"
    base = {"council": rec["council"], "hazards": rec["hazards"], "layer": rec["layer"], "source": url,
            "service": rec["service"].split("/rest/services/")[-1],
            "found_by": rec.get("found_by", "registry")}
    if rec["geometry"] == "esriGeometryPolygon":
        attrs, retrieved = arcgis.query_point(url, lon, lat)
        if not attrs:
            return None
        return {**base, "relation": "site inside", "distance_m": 0, "retrieved": retrieved,
                "attributes": clean_attributes(attrs[0])}
    if rec["geometry"] in ("esriGeometryPolyline", "esriGeometryPoint", "esriGeometryMultipoint"):
        feats, retrieved = arcgis.query_near(url, lon, lat, settings.line_hazard_search_m)
        if not feats:
            return None
        p = to_nztm(lon, lat)
        d, vec, f = min(((*nearest(p, f["geom"]), f) for f in feats), key=lambda t: t[0])
        return {**base, "relation": "nearby", "distance_m": round(d), "direction": bearing_name(*vec),
                "retrieved": retrieved, "attributes": clean_attributes(f["attributes"])}
    return None


def council_hazards(lon: float, lat: float) -> dict:
    where, cs = councils.councils_for_site(lon, lat)
    findings, layers_checked, notes = [], 0, []
    for c in cs:
        entry = discover.ensure(c)
        recs = [r for r in entry["layers"] if _in_bbox(r["bbox"], lon, lat) and "services" not in r["hazards"]]
        layers_checked += len(recs)
        if not entry["layers"]:
            notes.append(f"{c['name']}: no public hazard layers found ({entry['found_by']}); check the council's own viewer")
        with ThreadPoolExecutor(max_workers=8) as ex:
            for res in ex.map(lambda r: _safe(_check_layer, r, lon, lat), recs):
                if res and res.get("status") != "error":
                    findings.append(res)
                elif res:
                    notes.append(f"query failed: {res['reason']}")
    covered = {h for f in findings for h in f["hazards"]}
    return {"where": where, "councils": [c["name"] for c in cs], "layers_checked": layers_checked,
            "findings": findings, "hazards_found": sorted(covered),
            "hazards_without_finding": [HAZARDS[h] for h in HAZARDS if h not in covered], "notes": notes}


def assess(lon: float, lat: float, *, apoe_n: int | None = 500, vs30: float | None = None,
           site_class: str | None = None, surface_condition: str | None = None,
           offshore_island: bool | None = None, coast_type: str | None = None,
           address: str | None = None, legal: str | None = None,
           job: dict | None = None, parcel=None, imagery: bool = False) -> dict:
    bundle = _safe(load_bundle)
    bundle = bundle if isinstance(bundle, dict) and bundle.get("status") != "error" else None
    tasks = {
        "standards": lambda: standards.check(),
        "geology": lambda: national.geology(lon, lat),
        "rock_strength": lambda: national.rock_strength(lon, lat),
        "faults": lambda: national.faults(lon, lat),
        "landslides": lambda: national.landslides(lon, lat),
        "coast": lambda: national.coast(lon, lat),
        "council": lambda: council_hazards(lon, lat),
        "site_class": lambda: seismic.site_class(lon, lat, vs30_override=vs30, class_override=site_class),
        "ts1170_5": lambda: seismic.ts_parameters(lon, lat, apoe_n=apoe_n),
        "table36": lambda: national.table36_fault_distance(
            lon, lat, ((bundle or {}).get("nzs1170_5_z") or {}).get("near_fault_faults", [])),
        "coast_offline": lambda: coast.distance(lon, lat),
        "wind_region": lambda: windzones.wind_region(lon, lat, bundle),
        "lee_zones": lambda: windzones.lee_zones(lon, lat, bundle),
    }
    if imagery:
        from . import aerials
        tasks["aerials"] = lambda: aerials.site_imagery(lon, lat, parcel=parcel)
        from . import services, topo_site
        tasks["topography"] = lambda: topo_site.site_topography(lon, lat, parcel)
        tasks["services"] = lambda: services.lookup(lon, lat, parcel)
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futs = {k: ex.submit(_safe, fn) for k, fn in tasks.items()}
        r = {k: f.result() for k, f in futs.items()}

    ta = (r["council"].get("where") or {}).get("territorial_authority") if isinstance(r["council"], dict) else None
    region = (r["council"].get("where") or {}).get("region") if isinstance(r["council"], dict) else None
    from . import hail
    cat_layers = []
    try:
        from .councils import councils_for_site
        from .discover import ensure
        for c in councils_for_site(lon, lat)[1]:
            cat_layers += [l for l in ensure(c)["layers"] if "contaminated" in l["hazards"]]
    except Exception:
        pass
    r["hail"] = _safe(hail.lookup, lon, lat, region, cat_layers)
    if imagery and isinstance(r.get("geology"), dict) and r["geology"].get("status") == "ok":
        from . import geomap
        r["geomap"] = _safe(geomap.geology_map, lon, lat, geo=r["geology"], parcel=parcel)
    r["nzs1170_5"] = _safe(seismic.nzs1170_5_z, lon, lat, bundle, apoe_n=apoe_n, territorial_authority=ta,
                           fault_distance=r["table36"] if r["table36"].get("status") == "ok" else None)
    fig = _safe(seismic.nzs1170_5_figure_png, lon, lat, bundle)
    if isinstance(fig, str):
        r["nzs1170_5"]["figure"], r["nzs1170_5"]["figure_png"] = fig.split("|", 1)
    # Distance to coast: live LINZ query when a key is set, otherwise the bundled LINZ 1:50k coastline
    off = r["coast_offline"] if r["coast_offline"].get("status") == "ok" else {}
    if r["coast"].get("status") != "ok" and off:
        r["coast"] = off
    coast_m = r["coast"].get("distance_m") if r["coast"].get("status") == "ok" else None
    beyond_m = r["coast"].get("beyond_m")
    r["vlm"] = _safe(national.vertical_land_movement, lon, lat) if coast_m is not None and coast_m < 2000 else \
        {"status": "not_applicable"}
    r["coast_type"] = coast.coast_type(off) if off else {"type": None}
    isl = (off.get("island") or "") if off else ""
    auto_island = bool(off.get("on_land")) and isl != "" and not any(k in isl for k in ("North Island", "South Island"))
    if offshore_island is None:
        offshore_island = auto_island
        if auto_island:
            r.setdefault("notes", []).append(f"Site is on {isl}: treated as an offshore island for NZS 3604 (confirm)")
    geo_m = min((f["distance_m"] for f in r["council"].get("findings", []) if "geothermal" in f["hazards"]), default=None)

    # TS 1170.5 label follows the standards check
    sc = r["standards"].get("seismic", {}) if isinstance(r["standards"], dict) else {}
    if sc.get("ts1170_5_cited") and isinstance(r["ts1170_5"], dict):
        r["ts1170_5"]["compliance_path"] = "verification_method"
        r["ts1170_5"]["label"] = "TS 1170.5:2025 – cited in B1/VM1 (confirm with the evidence in the standards check)."

    s3604 = r["standards"].get("nzs3604") if isinstance(r["standards"], dict) else None
    r["exposure"] = _safe(durability.nzs3604_exposure, lon, lat, coast_m=coast_m, offshore_island=offshore_island,
                          geothermal_m=geo_m, bundle=bundle, edition=settings.nzs3604_bundle_edition,
                          standards_status=s3604)
    r["corrosivity"] = _safe(durability.nzs3404_3_corrosivity, lon, lat, coast_m=coast_m, coast_type=r["coast_type"],
                             coast_type_override=coast_type, beyond_m=beyond_m, geothermal_m=geo_m,
                             surface_condition=surface_condition, bundle=bundle)

    # Slope and elevation come from the wind tool's LiDAR work when the site is run from a wind job
    terrain = {}
    if job:
        for k in ("ground_elevation_m", "slope_max_deg", "slope_mean_deg", "crest_features"):
            if k in job:
                terrain[k] = job[k]
    tp = r.get("topography") if isinstance(r.get("topography"), dict) else {}
    if not terrain and tp.get("status") == "ok":
        terrain = {"ground_elevation_m": tp["site_elevation_m"], "slope_max_deg": tp["slope_p90_deg"],
                   "slope_mean_deg": tp["slope_mean_deg"]}
    r["terrain"] = terrain or {"status": "not_supplied", "note": "LiDAR topography not retrieved"}

    x, y = to_nztm(lon, lat)
    return {"site": {"lon": lon, "lat": lat, "nztm": [round(x, 1), round(y, 1)], "address": address, "legal": legal,
                     "apoe_n": apoe_n},
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tool_version": __version__,
            "data_bundle": "loaded" if bundle else "not loaded", **r}
