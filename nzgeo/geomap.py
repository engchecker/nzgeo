"""Geological map extract for reports: QMAP 1:250,000 geology with NZ Active Faults Database traces, the site
marked, a scale bar and a legend of the mapped units in view. Images come from the Earth Sciences New Zealand
(GNS Science) map services; nothing is redrawn from the data."""
from __future__ import annotations

import base64
import io
import re

from . import arcgis
from .geo import to_nztm
from .http import fetch, fetch_bytes

W, H = 1200, 800


def _export(service: str, bbox, layer_ids, transparent: bool) -> bytes:
    return fetch_bytes(f"{service}/export", {
        "bbox": ",".join(f"{v:.1f}" for v in bbox), "bboxSR": 2193, "imageSR": 2193, "size": f"{W},{H}", "dpi": 96,
        "format": "png32", "transparent": "true" if transparent else "false",
        "layers": "show:" + ",".join(str(i) for i in layer_ids), "f": "image"}, ttl_days=90)


def _legend(service: str, layer_id: int) -> dict:
    """label -> PNG swatch bytes, from the service legend."""
    body, _ = fetch(f"{service}/legend", {"f": "json"}, ttl_days=90)
    out = {}
    for l in body.get("layers", []):
        if l.get("layerId") != layer_id:
            continue
        for it in l.get("legend", []):
            if it.get("imageData"):
                sw = base64.b64decode(it["imageData"])
                for key in [it.get("label") or ""] + list(it.get("values") or []):
                    if key:
                        out[str(key).strip().lower()] = sw
    return out


def units_in_view(unit_layer_url: str, bbox) -> list[dict]:
    body, _ = fetch(f"{unit_layer_url}/query", {
        "geometry": ",".join(f"{v:.1f}" for v in bbox), "geometryType": "esriGeometryEnvelope", "inSR": 2193,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "f": "json"}, ttl_days=90)
    from .national import _pick_fields
    seen, out = set(), []
    for f in body.get("features", []):
        a = f.get("attributes", {})
        p = _pick_fields(a)
        key = (p.get("unit_code") or "", p.get("unit_name") or p.get("description") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({**p, "raw": a})
    return out


def geology_map(lon: float, lat: float, *, half_w=3000.0, fault_svc=None, geo=None, parcel=None) -> dict:
    """Map extract around the site. `geo` is the national.geology() result (for the service and layer)."""
    from PIL import Image, ImageDraw, ImageFont
    from . import national
    x, y = to_nztm(lon, lat)
    half_h = half_w * H / W
    bbox = (x - half_w, y - half_h, x + half_w, y + half_h)
    src = (geo or {}).get("source")
    if not src:
        return {"status": "unavailable", "reason": "geology service not available"}
    gsvc, gid = src.rsplit("/", 1)
    base = Image.open(io.BytesIO(_export(gsvc, bbox, [int(gid)], False))).convert("RGBA")
    fsvc = fault_svc or national._pick_service(r"Active_Faults/NZActiveFaultDatasets") or national._pick_service(r"NZActiveFaultsDatabase")
    fault_note = None
    if fsvc:
        try:
            ids = [l["id"] for l in arcgis.layers(fsvc) if l["geometry"] == "esriGeometryPolyline" and re.search(r"fault", l["name"], re.I)]
            if ids:
                ov = Image.open(io.BytesIO(_export(fsvc, bbox, ids, True))).convert("RGBA")
                base = Image.alpha_composite(base, ov)
                fault_note = "Active fault traces (NZ Active Faults Database) overlaid."
        except Exception:
            fault_note = None
    im = base.convert("RGB")
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
        small = ImageFont.truetype("DejaVuSans.ttf", 15)
    except Exception:
        font = small = ImageFont.load_default()
    to_px = lambda px, py: ((px - bbox[0]) / (2 * half_w) * W, (bbox[3] - py) / (2 * half_h) * H)  # noqa: E731
    cx, cy = to_px(x, y)
    dr.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], outline=(255, 0, 0), width=4)
    dr.line([cx - 18, cy, cx + 18, cy], fill=(255, 0, 0), width=2)
    dr.line([cx, cy - 18, cx, cy + 18], fill=(255, 0, 0), width=2)
    dr.text((cx + 16, cy - 30), "Site", fill=(200, 0, 0), font=font, stroke_width=3, stroke_fill=(255, 255, 255))
    km = 1000 / (2 * half_w) * W
    dr.rectangle([20, H - 40, 20 + km, H - 30], fill=(0, 0, 0))
    dr.rectangle([20, H - 40, 20 + km / 2, H - 30], fill=(255, 255, 255), outline=(0, 0, 0))
    dr.text((24 + km, H - 46), "1 km", fill=(0, 0, 0), font=font, stroke_width=3, stroke_fill=(255, 255, 255))
    dr.polygon([(W - 40, 20), (W - 52, 52), (W - 28, 52)], fill=(0, 0, 0))
    dr.text((W - 46, 56), "N", fill=(0, 0, 0), font=font, stroke_width=3, stroke_fill=(255, 255, 255))
    # legend of units in view
    units = []
    try:
        units = units_in_view(src, bbox)
        sw = _legend(gsvc, int(gid))
    except Exception:
        sw = {}
    rows = []
    for u in units[:10]:
        label = " – ".join(str(x) for x in (u.get("unit_code"), u.get("unit_name") or u.get("description")) if x)
        swatch = next((sw[k] for k in (str(u.get("unit_code") or "").lower(), str(u.get("unit_name") or "").lower(),
                                       str(u.get("description") or "").lower()) if k and k in sw), None)
        rows.append((label, swatch))
    if rows:
        lh = 28
        leg = Image.new("RGB", (W, 20 + lh * len(rows)), "white")
        ld = ImageDraw.Draw(leg)
        for i, (label, swatch) in enumerate(rows):
            yy = 10 + i * lh
            if swatch:
                leg.paste(Image.open(io.BytesIO(swatch)).convert("RGB").resize((30, 20)), (20, yy))
            else:
                ld.rectangle([20, yy, 50, yy + 20], outline=(120, 120, 120))
            ld.text((62, yy), label[:120], fill=(0, 0, 0), font=small)
        full = Image.new("RGB", (W, H + leg.height), "white")
        full.paste(im, (0, 0))
        full.paste(leg, (0, H))
        im = full
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return {"status": "ok", "png": out.getvalue(), "units": [{k: v for k, v in u.items() if k != "raw"} for u in units],
            "width_km": round(2 * half_w / 1000, 1), "fault_note": fault_note,
            "source": f"{gsvc} (QMAP 1:250,000); {fsvc or ''}"}
