"""Historic and current aerial photographs of the site, from LINZ's open imagery archive.

LINZ publishes orthorectified scans of the Crown Aerial Film Archive (the surveys also browsable on Retrolens)
and its modern aerial surveys as cloud-optimised GeoTIFFs in the public `nz-imagery` bucket (CC BY 4.0).
Each survey is cut into tiles named by the LINZ Topo50 map sheet grid, e.g. BQ31_5000_0710, so the tile
holding a site can be worked out from its NZTM coordinates and only a small window of that file is read.

The index of surveys (data/linz_imagery_index.json.gz) is built from LINZ's published STAC metadata
(github.com/linz/imagery) and can be refreshed with:  python -m nzgeo.aerials refresh
Unrectified Retrolens frames are listed from the LINZ aerial photo footprint layer when a LINZ key is set.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import HOME_DIR, settings
from .geo import to_nztm

BUCKET = "https://nz-imagery.s3-ap-southeast-2.amazonaws.com"
BUNDLED = Path(__file__).resolve().parent / "data" / "linz_imagery_index.json.gz"
LOCAL = HOME_DIR / "data" / "linz_imagery_index.json.gz"
GITHUB_ZIP = "https://codeload.github.com/linz/imagery/zip/refs/heads/master"
FOOTPRINTS = "layer-51002"      # NZ Aerial Photo Footprints, Mainland NZ (LINZ Data Service)
RETROLENS = "https://retrolens.co.nz"
CATEGORIES = ("scanned-aerial-photos", "urban-aerial-photos", "rural-aerial-photos")

# ---------------------------------------------------------------- LINZ Topo50 tile grid (after linz/argo-tasks mapsheet.ts)
_ORIGIN_X, _ORIGIN_Y, _W, _H = 988000, 6234000, 24000, 36000


def sheet_code(x: float, y: float) -> str:
    ox = math.floor((x - _ORIGIN_X) / _W)
    oy = math.floor((_ORIGIN_Y - y) / _H)
    c = oy
    if c >= 16:
        c += 1          # BI does not exist
    if c >= 22:
        c += 1          # BO does not exist
    if c >= 42:
        c += 1          # CI does not exist
    c += ord("S") - ord("A")
    return f"{chr(c // 26 + 65)}{chr(c % 26 + 65)}{ox:02d}"


def sheet_origin(code: str) -> tuple[float, float]:
    a, b, n = code[0], code[1], int(code[2:])
    y = (ord(a) - 65) * 26 + (ord(b) - 65) - (ord("S") - ord("A"))
    ms = code[:2]
    if ms > "CI":
        y -= 3
    elif ms > "BO":
        y -= 2
    elif ms > "BI":
        y -= 1
    return _W * n + _ORIGIN_X, _ORIGIN_Y - _H * y


def tile_name(x: float, y: float, grid: int) -> str:
    sc = sheet_code(x, y)
    ox, oy = sheet_origin(sc)
    s = grid / 50000
    col = math.floor((x - ox) / (_W * s)) + 1
    row = math.floor((oy - y) / (_H * s)) + 1
    w = 3 if grid == 500 else 2
    return f"{sc}_{grid}_{row:0{w}d}{col:0{w}d}"


def tile_bbox(name: str) -> tuple[float, float, float, float]:
    sc, g, rc = name.split("_")
    g = int(g)
    w = 3 if g == 500 else 2
    row, col = int(rc[:w]), int(rc[w:])
    ox, oy = sheet_origin(sc)
    s = g / 50000
    x0 = ox + (col - 1) * _W * s
    y1 = oy - (row - 1) * _H * s
    return x0, y1 - _H * s, x0 + _W * s, y1


# ---------------------------------------------------------------- index
def build_index(stac_root: Path) -> list[dict]:
    out = []
    for f in stac_root.glob("**/collection.json"):
        parts = f.parts
        if parts[-3] != "rgb" or parts[-2] != "2193":
            continue
        c = json.loads(f.read_text())
        cat = c.get("linz:geospatial_category")
        if cat not in CATEGORIES:
            continue
        tiles = [l["href"][2:-5] for l in c.get("links", []) if l.get("rel") == "item"]
        grids = sorted({int(t.split("_")[1]) for t in tiles if t.count("_") == 2})
        if len(grids) != 1:
            continue
        t0, t1 = c["extent"]["temporal"]["interval"][0]
        i = parts.index("stac")
        out.append({"path": "/".join(parts[i + 1:i + 5]), "title": c["title"], "cat": cat,
                    "sn": c.get("linz:historic_survey_number"), "from": t0[:10], "to": (t1 or t0)[:10],
                    "gsd": c.get("gsd"), "bbox": c["extent"]["spatial"]["bbox"][0], "grid": grids[0],
                    "tiles": sorted(t.split("_")[0] + "_" + t.split("_")[2] for t in tiles)})
    return out


def refresh() -> int:
    """Rebuild the index from LINZ's published metadata on GitHub."""
    import tempfile
    import zipfile

    import httpx
    with tempfile.TemporaryDirectory() as td:
        r = httpx.get(GITHUB_ZIP, follow_redirects=True, timeout=120)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(td)
        root = next(Path(td).glob("*/stac"))
        idx = build_index(root)
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_bytes(gzip.compress(json.dumps(idx, separators=(",", ":")).encode()))
    return len(idx)


_IDX = None


def index() -> list[dict]:
    global _IDX
    if _IDX is None:
        src = LOCAL if LOCAL.exists() and LOCAL.stat().st_mtime > BUNDLED.stat().st_mtime else BUNDLED
        _IDX = json.loads(gzip.decompress(src.read_bytes()))
    return _IDX


def index_age_days() -> float:
    src = LOCAL if LOCAL.exists() else BUNDLED
    return (time.time() - src.stat().st_mtime) / 86400


def surveys_at(lon: float, lat: float) -> list[dict]:
    """Every survey with a tile at the site, oldest first."""
    x, y = to_nztm(lon, lat)
    out = []
    for c in index():
        b = c["bbox"]
        if not (b[0] <= lon <= b[2] and b[1] <= lat <= b[3]):
            continue
        t = tile_name(x, y, c["grid"])
        short = t.split("_")[0] + "_" + t.split("_")[2]
        if short in c["tiles"]:
            out.append({**{k: v for k, v in c.items() if k != "tiles"}, "tile": t, "year": int(c["from"][:4]),
                        "year_to": int(c["to"][:4])})
    return sorted(out, key=lambda s: (s["year"], -(s["gsd"] or 1)))


def choose(surveys: list[dict], n_hist: int = 4) -> list[dict]:
    """Up to n_hist historic surveys spread across the decades, plus the most recent modern survey."""
    hist = [s for s in surveys if s["cat"] == "scanned-aerial-photos"]
    modern = [s for s in surveys if s["cat"] != "scanned-aerial-photos"]
    pick = []
    if hist:
        pick.append(hist[0])
        targets = [1950, 1960, 1970, 1980, 1990, 2000]
        for t in targets:
            if len(pick) >= n_hist:
                break
            cand = [s for s in hist if s not in pick and abs(s["year"] - t) <= 5 and all(abs(s["year"] - p["year"]) >= 8 for p in pick)]
            if cand:
                pick.append(min(cand, key=lambda s: (abs(s["year"] - t), s["gsd"] or 1)))
    if modern:
        latest = max(m["year"] for m in modern)
        pick.append(min([m for m in modern if m["year"] == latest], key=lambda s: s["gsd"] or 1))
    return sorted(pick, key=lambda s: s["year"])


# ---------------------------------------------------------------- image windows
def crop(survey: dict, lon: float, lat: float, *, half_w=120.0, half_h=90.0, parcel=None, max_px=1100) -> bytes | None:
    """A site-centred PNG from the survey's cloud-optimised GeoTIFF(s), with the site and parcel marked."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    from PIL import Image, ImageDraw
    x, y = to_nztm(lon, lat)
    bx0, by0, bx1, by1 = x - half_w, y - half_h, x + half_w, y + half_h
    res = max(survey.get("gsd") or 0.5, 2 * half_w / max_px)
    W, H = int(round(2 * half_w / res)), int(round(2 * half_h / res))
    canvas = np.zeros((H, W, 3), dtype=np.uint8)
    filled = np.zeros((H, W), dtype=bool)
    tiles = {tile_name(px, py, survey["grid"]) for px in (bx0, x, bx1) for py in (by0, y, by1)}
    base = f"{BUCKET}/{survey['path']}"
    env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MAX_RETRY": "2", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tiff"}
    for t in tiles:
        tb = tile_bbox(t)
        ix0, iy0, ix1, iy1 = max(bx0, tb[0]), max(by0, tb[1]), min(bx1, tb[2]), min(by1, tb[3])
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        try:
            src_path = f"/vsicurl/{base}/{t}.tiff" if base.startswith("http") else f"{base}/{t}.tiff"
            with rasterio.Env(**env), rasterio.open(src_path) as src:
                win = from_bounds(ix0, iy0, ix1, iy1, src.transform)
                c0, r0 = int((ix0 - bx0) / res), int((by1 - iy1) / res)
                cw, ch = max(1, int(round((ix1 - ix0) / res))), max(1, int(round((iy1 - iy0) / res)))
                bands = [1, 2, 3] if src.count >= 3 else [1]
                arr = src.read(bands, window=win, out_shape=(len(bands), ch, cw), boundless=True, fill_value=0)
                if arr.shape[0] == 1:
                    arr = np.repeat(arr, 3, axis=0)
                arr = np.moveaxis(arr, 0, -1)
                if arr.dtype != np.uint8:
                    arr = np.clip(arr / max(1, arr.max()) * 255, 0, 255).astype(np.uint8)
                canvas[r0:r0 + ch, c0:c0 + cw] = arr[:H - r0, :W - c0]
                filled[r0:r0 + ch, c0:c0 + cw] = arr[:H - r0, :W - c0].any(axis=-1)
        except Exception:
            continue
    if filled.mean() < 0.25:
        return None
    im = Image.fromarray(canvas)
    dr = ImageDraw.Draw(im)
    to_px = lambda px, py: ((px - bx0) / res, (by1 - py) / res)  # noqa: E731
    if parcel:
        pts = [to_px(*to_nztm(lo, la)) for lo, la in parcel]
        dr.line(pts + pts[:1], fill=(255, 210, 0), width=max(2, W // 300))
    cx, cy = to_px(x, y)
    r = max(6, W // 120)
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 40, 40), width=max(2, r // 3))
    # 50 m scale bar
    sb = 50 / res
    dr.rectangle([12, H - 26, 12 + sb, H - 18], fill=(255, 255, 255), outline=(0, 0, 0))
    dr.text((16 + sb, H - 30), "50 m", fill=(255, 255, 255))
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


def retrolens_frames(lon: float, lat: float, limit: int = 40) -> list[dict]:
    """Unrectified survey frames over the site (LINZ footprint layer; needs a LINZ key)."""
    if not settings.linz_api_key:
        return []
    from .http import fetch
    x, y = to_nztm(lon, lat)
    body, _ = fetch(f"https://data.linz.govt.nz/services;key={settings.linz_api_key}/wfs",
                    {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": FOOTPRINTS,
                     "outputFormat": "json", "count": limit, "srsName": "EPSG:2193",
                     "cql_filter": f"INTERSECTS(shape, POINT({x} {y}))"}, ttl_days=90)
    rows = []
    for f in body.get("features", []):
        p = {k.lower(): v for k, v in (f.get("properties") or {}).items()}
        pick = lambda *ks: next((p[k] for k in ks if p.get(k) not in (None, "")), None)  # noqa: E731
        rows.append({"survey": pick("survey", "sufi", "survey_number", "survey_no"), "run": pick("run", "run_no"),
                     "frame": pick("photo_no", "frame", "photo", "frame_no"),
                     "date": str(pick("flown", "date_flown", "date", "photo_date", "flying_date") or "")[:10],
                     "scale": pick("scale", "photo_scale"), "raw": p})
    return sorted(rows, key=lambda r: r["date"] or "9999")


def site_imagery(lon: float, lat: float, *, parcel=None, n_hist: int = 4) -> dict:
    """Historic and current aerial photographs over the site, with images, for the report."""
    if index_age_days() > 120:
        try:
            refresh()
            global _IDX
            _IDX = None
        except Exception:
            pass
    allv = surveys_at(lon, lat)
    picks = choose(allv, n_hist)

    def one(s):
        try:
            png = crop(s, lon, lat, parcel=parcel)
        except Exception:
            png = None
        return {**s, "png": png}
    with ThreadPoolExecutor(max_workers=5) as ex:
        imgs = list(ex.map(one, picks))
    frames = []
    try:
        frames = retrolens_frames(lon, lat)
    except Exception:
        pass
    hist = [s for s in allv if s["cat"] == "scanned-aerial-photos"]
    return {"status": "ok", "surveys": [{k: v for k, v in s.items()} for s in allv], "images": imgs,
            "historic_range": [hist[0]["year"], hist[-1]["year_to"]] if hist else None,
            "frames": frames, "source": "Toitū Te Whenua LINZ, NZ Imagery (nz-imagery), CC BY 4.0"}


if __name__ == "__main__":
    if sys.argv[1:2] == ["refresh"]:
        print(f"Imagery index refreshed: {refresh()} surveys")
    elif sys.argv[1:2] == ["build"]:
        idx = build_index(Path(sys.argv[2]))
        Path(sys.argv[3]).write_bytes(gzip.compress(json.dumps(idx, separators=(",", ":")).encode()))
        print(len(idx), "surveys")
    else:
        print(__doc__)
