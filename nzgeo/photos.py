"""Site photographs: orientation, size reduction, and what the camera recorded (time, GPS, facing)."""
from __future__ import annotations

import base64
import io
import math
from datetime import datetime

from PIL import ExifTags, Image, ImageOps

try:  # iPhone HEIC photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:  # pragma: no cover
    pass

MAX_PX = 1600
KINDS = {"overview": "Site overview", "test": "Test location", "auger": "Hand auger / soil sample",
         "scala": "Scala penetrometer", "feature": "Site feature", "other": "Other"}


def _ratio(v):
    try:
        return float(v)
    except TypeError:
        return v[0] / v[1]


def _gps(ex):
    try:
        g = ex.get_ifd(0x8825)
    except Exception:
        return None
    if not g or 2 not in g or 4 not in g:
        return None
    dms = lambda t: _ratio(t[0]) + _ratio(t[1]) / 60 + _ratio(t[2]) / 3600  # noqa: E731
    lat, lon = dms(g[2]), dms(g[4])
    if str(g.get(1, "N")).upper().startswith("S"):
        lat = -lat
    if str(g.get(3, "E")).upper().startswith("W"):
        lon = -lon
    out = {"lat": round(lat, 6), "lon": round(lon, 6)}
    if 17 in g:
        out["facing_deg"] = round(_ratio(g[17]))
    if 31 in g:
        out["accuracy_m"] = round(_ratio(g[31]))
    return out


def _compass(deg):
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((deg % 360) + 22.5) // 45) % 8]


def process(data: bytes, name: str = "") -> dict:
    im = Image.open(io.BytesIO(data))
    ex = im.getexif()
    tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
    try:
        sub = ex.get_ifd(0x8769)
        taken = sub.get(36867) or tags.get("DateTime")
    except Exception:
        taken = tags.get("DateTime")
    gps = _gps(ex)
    im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    im.thumbnail((MAX_PX, MAX_PX))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80, optimize=True)
    when = None
    if taken:
        try:
            when = datetime.strptime(str(taken)[:19], "%Y:%m:%d %H:%M:%S").isoformat(sep=" ")
        except ValueError:
            when = str(taken)
    return {"name": name, "taken": when, "camera": " ".join(str(tags.get(k, "")) for k in ("Make", "Model")).strip() or None,
            "gps": gps, "facing": _compass(gps["facing_deg"]) if gps and "facing_deg" in gps else None,
            "original_px": [w, h], "jpeg_b64": base64.b64encode(buf.getvalue()).decode(), "size_px": list(im.size)}


def distance_m(lon1, lat1, lon2, lat2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def checks(photos: list[dict], site: dict | None, investigation_date: str | None) -> list[str]:
    notes = []
    no_gps = [p["name"] for p in photos if not p.get("gps")]
    if photos and len(no_gps) == len(photos):
        notes.append("No photo carries a GPS position, so photo locations cannot be checked against the site. "
                     "On iPhone: Settings > Privacy & Security > Location Services > Camera > While Using; "
                     "share photos with 'All Photos Data' (Options) or copy them from the phone by cable.")
    if site:
        for p in photos:
            g = p.get("gps")
            if g:
                d = distance_m(site["lon"], site["lat"], g["lon"], g["lat"])
                p["distance_from_site_m"] = round(d)
                if d > 150:
                    notes.append(f"{p['name']}: taken {d:.0f} m from the site marker. Check it belongs to this site.")
    if investigation_date:
        days = {(p["taken"] or "")[:10] for p in photos if p.get("taken")}
        other = sorted(d for d in days if d and d != investigation_date[:10])
        if other:
            notes.append(f"Photos dated {', '.join(other)}; field sheet dated {investigation_date[:10]}.")
    return notes
