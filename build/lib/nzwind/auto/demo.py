"""Demonstration data: the synthetic test site placed at the chosen location.
Used only when NZWIND_DEMO=1. Every response is labelled as demonstration data."""
import numpy as np
from .sources import TO_NZTM
from .sitedata import Grid

def demo_site(lon, lat, radius, res):
    from . import synthetic as S
    x, y = TO_NZTM.transform(lon, lat)
    sd = S.build(radius=radius, res=res)
    dx, dy = x - S.SX, y - S.SY
    sd.site_xy = (x, y)
    sd.grid = Grid(sd.grid.x0 + dx, sd.grid.y0 + dy, sd.grid.res, sd.grid.shape)
    sd.buildings = sd.buildings.translate(dx, dy) if len(sd.buildings) else sd.buildings
    import geopandas as gpd
    sd.buildings = gpd.GeoDataFrame(geometry=sd.buildings, crs="EPSG:2193") if not isinstance(sd.buildings, gpd.GeoDataFrame) else sd.buildings
    g, dem = S.escarpment_dem(res=5.0, radius=2600.0)
    sd.topo_grid = Grid(g.x0 + dx, g.y0 + dy, g.res, g.shape)
    sd.topo_dem = dem
    sd.provenance = {"demo": "Synthetic demonstration terrain: not real data for this location"}
    sd.issues = ["DEMONSTRATION DATA: synthetic terrain, not the real site"]
    return sd
