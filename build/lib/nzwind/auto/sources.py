"""Live data connectors. Each returns data on the analysis grid (NZTM2000) plus provenance.

Requires network access to LINZ (S3, Data Service, Basemaps), LRIS and optionally Mapillary.
Any source that fails is recorded in SiteData.issues and the analysis continues with what is
available; the classifier lowers confidence where data is missing.
"""
import io, json, math, os, re, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from pyproj import Transformer
from . import config as C
from .sitedata import Grid, SiteData

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff")

TO_NZTM = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:2193", "EPSG:4326", always_xy=True)
UA = {"User-Agent": "nzwind-site-wind-tool/0.2"}

def _get(url, timeout=60, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else json.loads(data)

def _bounds(grid):
    r, c = grid.shape
    return grid.x0, grid.y0 - r * grid.res, grid.x0 + c * grid.res, grid.y0

def _wgs_bbox(b):
    xs, ys = TO_WGS.transform([b[0], b[2], b[0], b[2]], [b[1], b[1], b[3], b[3]])
    return min(xs), min(ys), max(xs), max(ys)

# ------------------------------------------------------------------ elevation (STAC + COG)

def stac_index(kind):
    """Item bbox + COG href for the national 1 m DEM or DSM, cached on disk."""
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    path = os.path.join(C.CACHE_DIR, f"stac_{kind}.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 30 * 86400:
        return json.load(open(path))
    url = C.ELEVATION[kind]
    col = _get(url)
    base = url.rsplit("/", 1)[0] + "/"
    hrefs = [urllib.parse.urljoin(base, l["href"]) for l in col.get("links", []) if l.get("rel") == "item"]

    def item(h):
        it = _get(h)
        asset = next((a for a in it.get("assets", {}).values() if "tif" in (a.get("type", "") + a.get("href", ""))), None)
        if not asset:
            return None
        p = it.get("properties", {})
        return {"bbox": it["bbox"], "href": urllib.parse.urljoin(h, asset["href"]),
                "start": p.get("start_datetime") or p.get("datetime"), "end": p.get("end_datetime")}
    with ThreadPoolExecutor(16) as ex:
        items = [i for i in ex.map(item, hrefs) if i]
    idx = {"title": col.get("title"), "description": col.get("description", "")[:300],
           "temporal": col.get("extent", {}).get("temporal", {}).get("interval"),
           "providers": [p.get("name") for p in col.get("providers", [])], "items": items, "collection": url}
    json.dump(idx, open(path, "w"))
    return idx

def read_elevation(kind, grid):
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import reproject, Resampling
    from affine import Affine
    idx = stac_index(kind)
    b = _bounds(grid)
    wb = _wgs_bbox(b)
    hits = [i for i in idx["items"] if not (i["bbox"][2] < wb[0] or i["bbox"][0] > wb[2] or i["bbox"][3] < wb[1] or i["bbox"][1] > wb[3])]
    out = np.full(grid.shape, np.nan, np.float32)
    dates = []
    for it in hits:
        path = "/vsicurl/" + it["href"] if it["href"].startswith("http") else it["href"]
        with rasterio.open(path) as src:
            win = from_bounds(*b, transform=src.transform).intersection(
                rasterio.windows.Window(0, 0, src.width, src.height))
            if win.width < 1 or win.height < 1:
                continue
            oh = max(1, int(round(win.height * src.res[1] / grid.res)))
            ow = max(1, int(round(win.width * src.res[0] / grid.res)))
            arr = src.read(1, window=win, out_shape=(oh, ow), resampling=Resampling.bilinear, masked=True)
            data = arr.filled(np.nan).astype(np.float32)
            t = src.window_transform(win) @ Affine.scale(win.width / ow, win.height / oh)
            reproject(data, out, src_transform=t, src_crs="EPSG:2193", dst_transform=grid.transform,
                      dst_crs="EPSG:2193", src_nodata=np.nan, dst_nodata=np.nan, init_dest_nodata=False,
                      resampling=Resampling.bilinear)
            dates.append(it.get("end") or it.get("start"))
    prov = {"dataset": idx["title"], "collection": idx["collection"], "tiles": len(hits),
            "capture": sorted(d for d in dates if d)[-1:] or idx["temporal"], "licence": "CC BY 4.0 (see STAC licensors)"}
    return out, prov

# ------------------------------------------------------------------ WFS vectors

def wfs(layer_key, bbox=None, cql=None, count=20000):
    import geopandas as gpd
    L = C.LAYERS[layer_key]
    key = C.LINZ_KEY if L["service"] == "lds" else C.LRIS_KEY
    if not key:
        raise RuntimeError(f"No API key for {L['service'].upper()} (set {'LINZ_LDS_KEY' if L['service'] == 'lds' else 'LRIS_KEY'})")
    base = (C.LDS_WFS if L["service"] == "lds" else C.LRIS_WFS).format(key=key)
    q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": L["id"],
         "outputFormat": "application/json", "srsName": "EPSG:2193", "count": str(count)}
    if bbox is not None and cql is None:
        q["bbox"] = ",".join(f"{v:.1f}" for v in bbox) + ",EPSG:2193"
    if cql:
        q["cql_filter"] = cql
    gj = _get(base + "?" + urllib.parse.urlencode(q), timeout=120)
    feats = gj.get("features", [])
    if not feats:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2193")
    return gpd.GeoDataFrame.from_features(feats, crs="EPSG:2193")

def _rasterize(gdf, grid, value=None, field=None, dtype="uint8"):
    from rasterio.features import rasterize
    if gdf is None or not len(gdf):
        return np.zeros(grid.shape, dtype)
    if field:
        shapes = [(g, int(v)) for g, v in zip(gdf.geometry, gdf[field]) if g is not None and v is not None and str(v).isdigit()]
    else:
        shapes = [(g, value) for g in gdf.geometry if g is not None]
    return rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=0, dtype=dtype) if shapes else np.zeros(grid.shape, dtype)

# ------------------------------------------------------------------ imagery (excess-green)

def read_exg(grid, zoom=16):
    """Excess-green index from LINZ Basemaps aerial tiles, resampled to the grid."""
    if not C.BASEMAPS_KEY:
        raise RuntimeError("No LINZ Basemaps key (set LINZ_BASEMAPS_KEY)")
    from PIL import Image
    from rasterio.warp import reproject, Resampling
    from affine import Affine
    lon0, lat0, lon1, lat1 = _wgs_bbox(_bounds(grid))
    n = 2 ** zoom
    tx = lambda lon: int((lon + 180) / 360 * n)
    ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    xs, ys = range(tx(lon0), tx(lon1) + 1), range(ty(lat1), ty(lat0) + 1)
    mosaic = np.zeros((len(ys) * 256, len(xs) * 256, 3), np.float32)

    def fetch(xy):
        x, y = xy
        url = C.BASEMAPS_TILES.format(z=zoom, x=x, y=y, key=C.BASEMAPS_KEY)
        try:
            return xy, np.asarray(Image.open(io.BytesIO(_get(url, binary=True))).convert("RGB"), np.float32)
        except Exception:
            return xy, None
    with ThreadPoolExecutor(12) as ex:
        for (x, y), img in ex.map(fetch, [(x, y) for y in ys for x in xs]):
            if img is not None:
                mosaic[(y - ys[0]) * 256:(y - ys[0] + 1) * 256, (x - xs[0]) * 256:(x - xs[0] + 1) * 256] = img
    r, g, b = mosaic[..., 0], mosaic[..., 1], mosaic[..., 2]
    s = r + g + b + 1e-6
    exg = (2 * g - r - b) / s
    exg[s < 3] = np.nan
    size = 2 * 20037508.342789244 / n
    t = Affine(size / 256, 0, -20037508.342789244 + xs[0] * size, 0, -size / 256, 20037508.342789244 - ys[0] * size)
    out = np.full(grid.shape, np.nan, np.float32)
    reproject(exg.astype(np.float32), out, src_transform=t, src_crs="EPSG:3857", dst_transform=grid.transform,
              dst_crs="EPSG:2193", src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
    return out, {"dataset": "LINZ Basemaps aerial imagery", "zoom": zoom, "licence": "CC BY 4.0"}

# ------------------------------------------------------------------ assemble

def gather(lon, lat, radius, res, topo_radius=2600.0, topo_res=5.0):
    x, y = TO_NZTM.transform(lon, lat)
    grid = Grid.around(x, y, radius, res)
    sd = SiteData((x, y), grid)
    b = _bounds(grid)

    def attempt(name, fn):
        try:
            return fn()
        except Exception as e:                    # recorded, not fatal
            sd.issues.append(f"{name}: {type(e).__name__}: {e}"[:300])
            return None

    r = attempt("LiDAR DEM", lambda: read_elevation("dem", grid))
    if r: sd.dem, sd.provenance["dem"] = r
    r = attempt("LiDAR DSM", lambda: read_elevation("dsm", grid))
    if r: sd.dsm, sd.provenance["dsm"] = r
    tg = Grid.around(x, y, topo_radius, topo_res)
    r = attempt("LiDAR DEM (topography)", lambda: read_elevation("dem", tg))
    if r: sd.topo_grid, sd.topo_dem = tg, r[0]
    bl = attempt("Building outlines", lambda: wfs("buildings", b))
    if bl is not None:
        sd.buildings = bl
        sd.provenance["buildings"] = {"dataset": "NZ Building Outlines (LINZ)", "count": len(bl), "licence": "CC BY 4.0"}
    lc = attempt("Land cover (LCDB)", lambda: wfs("lcdb", b))
    if lc is not None:
        sd.lcdb = _rasterize(lc, grid, field=C.LAYERS["lcdb"]["field"], dtype="int32")
        sd.provenance["lcdb"] = {"dataset": "LCDB v5.0 (Manaaki Whenua)", "polygons": len(lc), "licence": "CC BY 4.0"}
    # Water: LCDB water classes, plus sea = no land-cover polygon where LiDAR ground is absent or
    # below 1 m. (The Topo50 coastline polygons are whole islands, too large to fetch per site.)
    water = np.zeros(grid.shape, bool)
    if sd.lcdb is not None:
        water |= np.isin(sd.lcdb, list(C.LCDB["water"]))
        if sd.dem is not None:
            water |= (sd.lcdb == 0) & (~np.isfinite(sd.dem) | (sd.dem < 1.0))
        sd.provenance["water"] = {"method": "LCDB water classes + sea (no LCDB polygon, LiDAR ground absent or < 1 m)"}
    else:
        sd.issues.append("Water surfaces not identified: no land cover data")
    sd.water = water
    r = attempt("Aerial imagery", lambda: read_exg(grid))
    if r: sd.exg, sd.provenance["imagery"] = r
    return sd

# ------------------------------------------------------------------ street level (evidence only)

def mapillary_nearest(lon, lat, radius_deg=0.002):
    if not C.MAPILLARY_TOKEN:
        return None
    q = {"access_token": C.MAPILLARY_TOKEN, "fields": "id,computed_geometry,captured_at,compass_angle",
         "bbox": f"{lon - radius_deg},{lat - radius_deg},{lon + radius_deg},{lat + radius_deg}", "limit": "50"}
    data = _get(C.MAPILLARY_GRAPH + "?" + urllib.parse.urlencode(q)).get("data", [])
    if not data:
        return None
    def d2(i):
        c = i.get("computed_geometry", {}).get("coordinates", [999, 999])
        return (c[0] - lon) ** 2 + (c[1] - lat) ** 2
    best = min(data, key=d2)
    return {"id": best["id"], "captured_at": best.get("captured_at"), "coordinates": best.get("computed_geometry", {}).get("coordinates")}

def google_pano_url(lon, lat, heading):
    """Opens Google Street View for the engineer to look at. Display only: Google's terms do not
    permit analysing Street View imagery, so it is never used in the classification."""
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat:.6f},{lon:.6f}&heading={heading:.0f}"
