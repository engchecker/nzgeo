"""Coordinate helpers. Analysis is in NZTM2000 (EPSG:2193)."""
from __future__ import annotations

import math

from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, shape

_to_nztm = Transformer.from_crs(4326, 2193, always_xy=True)
_to_wgs = Transformer.from_crs(2193, 4326, always_xy=True)


def to_nztm(lon: float, lat: float) -> tuple[float, float]:
    return _to_nztm.transform(lon, lat)


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    return _to_wgs.transform(x, y)


def bearing_name(dx: float, dy: float) -> str:
    """Compass direction of a vector in NZTM (grid north, close enough for a desk study)."""
    ang = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int((ang + 22.5) // 45) % 8]


def esri_to_shapely(geom: dict):
    """Convert an Esri JSON geometry to shapely (coordinates kept as given)."""
    if not geom:
        return None
    if "x" in geom:
        return Point(geom["x"], geom["y"])
    if "points" in geom:
        return MultiPoint(geom["points"])
    if "paths" in geom:
        paths = [p for p in geom["paths"] if len(p) >= 2]
        return LineString(paths[0]) if len(paths) == 1 else MultiLineString(paths)
    if "rings" in geom:
        # Esri rings: outer rings clockwise, holes anticlockwise. Union of rings by even-odd is
        # adequate for point-in-polygon and boundary distance at desk study precision.
        polys = []
        for ring in geom["rings"]:
            if len(ring) >= 4:
                polys.append(Polygon(ring))
        if not polys:
            return None
        outer = [p for p in polys if not _ccw(p)] or polys
        holes = [p for p in polys if _ccw(p)] if len(outer) < len(polys) else []
        g = MultiPolygon(outer).buffer(0) if len(outer) > 1 else outer[0].buffer(0)
        for h in holes:
            g = g.difference(h)
        return g
    if "type" in geom:  # GeoJSON
        return shape(geom)
    return None


def _ccw(p: Polygon) -> bool:
    return p.exterior.is_ccw


def nearest(point_xy: tuple[float, float], geom) -> tuple[float, tuple[float, float]]:
    """Distance (m) and the vector from the site to the nearest point on geom (both in NZTM)."""
    from shapely.ops import nearest_points
    p = Point(point_xy)
    if geom.geom_type in ("Polygon", "MultiPolygon") and geom.contains(p):
        return 0.0, (0.0, 0.0)
    _, q = nearest_points(p, geom)
    return p.distance(geom), (q.x - p.x, q.y - p.y)
