"""Look up a site on a georeferenced, classified map grid held in the data bundle.

Each grid has an affine A (pixel -> NZTM), a class table and fit statistics from matching the map's
coastline to the LINZ 1:50k coastline. The answer carries the map's accuracy so the report can say how
far to trust it.
"""
from __future__ import annotations

import base64
import io
from functools import lru_cache

import numpy as np
from PIL import Image

from .geo import to_nztm

LAND_SKIP = {"sea", "water", "lake"}


@lru_cache(maxsize=32)
def _decode(b64: str) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(base64.b64decode(b64))))


def _pixel(m: dict, lon: float, lat: float) -> tuple[float, float]:
    A = np.vstack([np.array(m["A"]), [0, 0, 1]])
    x, y = to_nztm(lon, lat)
    px, py, _ = np.linalg.inv(A) @ np.array([x, y, 1.0])
    return px, py


def lookup(grid: dict, lon: float, lat: float, *, land_search_m: float = 1500) -> dict | None:
    """Class at the site from the highest-priority map that covers it."""
    for m in sorted(grid["maps"], key=lambda m: -m["priority"]):
        h, w = m["shape"]
        px, py = _pixel(m, lon, lat)
        if not (2 <= px < w - 2 and 2 <= py < h - 2):
            continue
        arr = _decode(m["png_b64"])
        mpp = m["fit"]["m_per_px"]
        i, j = int(py), int(px)
        cls = m["classes"].get(str(int(arr[i, j])))
        moved = None
        if cls in LAND_SKIP or cls is None:
            r = max(int(land_search_m / mpp), 1)
            win = arr[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]
            land_codes = [int(k) for k, v in m["classes"].items() if v not in LAND_SKIP]
            yy, xx = np.nonzero(np.isin(win, land_codes))
            if len(yy) == 0:
                return {"map": m["name"], "figure": m["figure"], "class": cls, "status": "no_land_class_nearby", "fit": m["fit"]}
            k = np.argmin((yy - (i - max(0, i - r))) ** 2 + (xx - (j - max(0, j - r))) ** 2)
            ii, jj = yy[k] + max(0, i - r), xx[k] + max(0, j - r)
            moved = round(float(np.hypot(ii - i, jj - j)) * mpp)
            i, j = ii, jj
            cls = m["classes"][str(int(arr[i, j]))]
        # distance to the nearest pixel of a different land class
        r = int(3000 / mpp)
        win = arr[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1]
        here = int(arr[i, j])
        other = [int(k) for k, v in m["classes"].items() if v not in LAND_SKIP and int(k) != here]
        yy, xx = np.nonzero(np.isin(win, other))
        boundary_m = None
        if len(yy):
            boundary_m = round(float(np.min(np.hypot(yy - (i - max(0, i - r)), xx - (j - max(0, j - r))))) * mpp)
        return {"map": m["name"], "figure": m["figure"], "class": cls, "status": "ok",
                "site_mapped_as_water_moved_m": moved, "nearest_other_class_m": boundary_m, "fit": m["fit"],
                "near_boundary": boundary_m is not None and boundary_m <= max(2 * m["fit"]["median_m"], 250)}
    return None
