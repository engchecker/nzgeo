"""Synthetic sites with known answers, one terrain type per upwind sector."""
import math
import numpy as np
import geopandas as gpd
from shapely.geometry import box, Point
from nzwind.auto.sitedata import Grid, SiteData

SX, SY = 1_500_000.0, 5_200_000.0

def sector_of(x, y):
    brg = (math.degrees(math.atan2(x - SX, y - SY)) + 360) % 360
    return int(((brg + 22.5) // 45) % 8)

def lattice(pitch, radius, offset=0.0):
    k = int(radius // pitch) + 1
    for i in range(-k, k + 1):
        for j in range(-k, k + 1):
            yield SX + i * pitch + offset, SY + j * pitch + offset

# sector index: 0 N, 1 NE, 2 E, 3 SE, 4 S, 5 SW, 6 W, 7 NW
PLAN = {0: "suburb", 1: "cbd", 2: "sea", 3: "farm", 4: "lifestyle", 5: "forest", 6: "suburb_then_sea", 7: "scattered_trees"}
EXPECT = {"N": 3, "NE": 4, "E": 1, "SE": 2, "S": 2.5, "SW": 3, "NW": 2.5}

def build(radius=1300.0, res=2.0, ground=100.0):
    g = Grid.around(SX, SY, radius, res)
    X, Y = g.centres()
    sec = (np.floor((((np.degrees(np.arctan2(X - SX, Y - SY)) + 360) % 360) + 22.5) / 45) % 8).astype(int)
    dist = np.hypot(X - SX, Y - SY)
    dem = np.full(g.shape, ground)
    add = np.zeros(g.shape)
    water = np.zeros(g.shape, bool)
    lcdb = np.full(g.shape, 40, np.int32)
    polys, heights = [], []

    def put_building(cx, cy, w, l, h, want):
        if sector_of(cx, cy) != want or math.hypot(cx - SX, cy - SY) < 30:
            return
        polys.append(box(cx - w / 2, cy - l / 2, cx + w / 2, cy + l / 2)); heights.append(h)

    def put_tree(cx, cy, r, h, want):
        if sector_of(cx, cy) != want or math.hypot(cx - SX, cy - SY) < 30:
            return
        m = np.hypot(X - cx, Y - cy) <= r
        np.maximum(add, np.where(m, h, 0), out=add)

    for x, y in lattice(28, radius):           # N suburb: 168 m2 houses on 28 m lots, 6 m
        put_building(x, y, 12, 14, 6, 0)
    for x, y in lattice(45, radius):           # NE CBD: 30 x 30 m blocks, 25 m
        put_building(x, y, 30, 30, 25, 1)
    water |= (sec == 2)                        # E sea
    lcdb[sec == 2] = 0
    for x, y in lattice(100, radius, 13):      # SE farm: one 6 x 10 m shed per ha, 4 m
        put_building(x, y, 6, 10, 4, 3)
    for x, y in lattice(45, radius, 7):        # S lifestyle: ~4.9 houses/ha
        put_building(x, y, 15, 12, 6, 4)
    add[sec == 5] = np.maximum(add[sec == 5], 15.0)   # SW plantation forest, 15 m
    lcdb[sec == 5] = 71
    for x, y in lattice(28, radius):           # W suburb to 400 m, then sea
        if math.hypot(x - SX, y - SY) < 400:
            put_building(x, y, 12, 14, 6, 6)
    sea_w = (sec == 6) & (dist >= 400)
    water |= sea_w; lcdb[sea_w] = 0
    for x, y in lattice(58, radius, 11):       # NW pasture with ~3 large trees/ha, 8 m
        put_tree(x, y, 3, 8, 7)

    bl = gpd.GeoDataFrame({"h": heights}, geometry=polys, crs="EPSG:2193")
    from rasterio.features import rasterize
    if len(bl):
        hb = rasterize([(p, h) for p, h in zip(bl.geometry, bl.h)], out_shape=g.shape, transform=g.transform, fill=0, dtype="float32")
        add = np.maximum(add, hb)
    dsm = dem + add
    dsm[water] = dem[water]
    return SiteData((SX, SY), g, dem=dem, dsm=dsm, water=water, lcdb=lcdb, buildings=bl,
                    provenance={"source": "synthetic"})

def escarpment_dem(res=5.0, radius=3000.0):
    """Escarpment facing west: 100 m plain rising to 130 m between 360 m and 200 m west of the site."""
    g = Grid.around(SX, SY, radius, res)
    X, _ = g.centres()
    dx = X - SX
    z = np.where(dx <= -360, 100.0, np.where(dx >= -200, 130.0, 100 + 30 * (dx + 360) / 160))
    return g, z

def ridge_dem(res=5.0, radius=3000.0):
    """North-south ridge 40 m high, crest 100 m east of the site, flanks 200 m wide each side."""
    g = Grid.around(SX, SY, radius, res)
    X, _ = g.centres()
    dx = X - (SX + 100)
    z = 100 + np.clip(40 * (1 - np.abs(dx) / 200), 0, None)
    return g, z
