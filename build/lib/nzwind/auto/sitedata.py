"""Container for the data gathered around a site, on a regular NZTM2000 grid."""
from dataclasses import dataclass, field
import numpy as np

@dataclass
class Grid:
    x0: float          # NZTM easting of the left edge
    y0: float          # NZTM northing of the top edge
    res: float         # metres per pixel
    shape: tuple       # (rows, cols)

    @property
    def transform(self):
        from rasterio.transform import from_origin
        return from_origin(self.x0, self.y0, self.res, self.res)

    def centres(self):
        r, c = self.shape
        xs = self.x0 + (np.arange(c) + 0.5) * self.res
        ys = self.y0 - (np.arange(r) + 0.5) * self.res
        return np.meshgrid(xs, ys)

    @classmethod
    def around(cls, x, y, radius, res):
        n = int(np.ceil(2 * radius / res))
        return cls(x - n * res / 2, y + n * res / 2, res, (n, n))

@dataclass
class SiteData:
    site_xy: tuple                     # NZTM (E, N)
    grid: Grid                         # analysis grid for terrain
    dem: np.ndarray | None = None      # bare-earth elevation (m), NaN = no data
    dsm: np.ndarray | None = None      # surface elevation (m)
    water: np.ndarray | None = None    # bool: water surface (lakes, rivers, sea)
    lcdb: np.ndarray | None = None     # int LCDB class, 0 = none
    exg: np.ndarray | None = None      # excess-green index from aerial imagery
    buildings: object = None           # GeoDataFrame of footprints (NZTM)
    topo_grid: Grid | None = None      # coarser, wider grid for topographic profiles
    topo_dem: np.ndarray | None = None
    provenance: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
