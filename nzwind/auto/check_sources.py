"""First-run check of every data source: `python -m nzwind.auto.check_sources`."""
from . import config as C
from . import sources as S
from .sitedata import Grid

def main(lon=174.7762, lat=-41.2865):
    x, y = S.TO_NZTM.transform(lon, lat)
    g = Grid.around(x, y, 150, 2.0)
    b = S._bounds(g)
    checks = [
        ("LiDAR DEM index + read", lambda: f"{S.read_elevation('dem', g)[1]['tiles']} tile(s)"),
        ("LiDAR DSM index + read", lambda: f"{S.read_elevation('dsm', g)[1]['tiles']} tile(s)"),
        ("Building outlines (LDS)", lambda: f"{len(S.wfs('buildings', b))} buildings"),
        ("Land cover LCDB (LRIS)", lambda: f"{len(S.wfs('lcdb', b))} polygons, field {C.LAYERS['lcdb']['field']}"),
        ("Addresses (LDS)", lambda: f"{len(S.wfs('addresses', cql=C.LAYERS['addresses']['field'] + ' ILIKE ' + chr(39) + '%Lambton Quay%' + chr(39), count=3))} matches"),
        ("Parcels (LDS)", lambda: f"{len(S.wfs('parcels', b))} parcels"),
        ("Aerial imagery (Basemaps)", lambda: "ok" if S.read_exg(g)[0] is not None else "none"),
        ("Mapillary (optional)", lambda: str(S.mapillary_nearest(lon, lat)) if C.MAPILLARY_TOKEN else "no token set"),
    ]
    for name, fn in checks:
        try:
            print(f"OK    {name}: {fn()}")
        except Exception as e:
            print(f"FAIL  {name}: {type(e).__name__}: {e}"[:300])

if __name__ == "__main__":
    main()
