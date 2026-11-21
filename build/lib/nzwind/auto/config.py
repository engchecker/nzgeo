"""Configuration for automatic terrain mapping.

Data-service identifiers are set here so they can be corrected without code changes.
Run `python -m nzwind.auto.check_sources` on first use to confirm each one responds.
"""
import os

LINZ_KEY = os.environ.get("LINZ_LDS_KEY", "")            # LINZ Data Service API key
LRIS_KEY = os.environ.get("LRIS_KEY", "")                 # LRIS (Manaaki Whenua) API key
BASEMAPS_KEY = os.environ.get("LINZ_BASEMAPS_KEY", "")    # LINZ Basemaps key (imagery)
MAPILLARY_TOKEN = os.environ.get("MAPILLARY_TOKEN", "")   # Mapillary client token (viewer only)
CACHE_DIR = os.environ.get("NZWIND_CACHE", os.path.expanduser("~/.nzwind-cache"))

ELEVATION = {
    "dem": "https://nz-elevation.s3.ap-southeast-2.amazonaws.com/new-zealand/new-zealand/dem_1m/2193/collection.json",
    "dsm": "https://nz-elevation.s3.ap-southeast-2.amazonaws.com/new-zealand/new-zealand/dsm_1m/2193/collection.json",
}
LDS_WFS = "https://data.linz.govt.nz/services;key={key}/wfs"
LRIS_WFS = "https://lris.scinfo.org.nz/services;key={key}/wfs"
LAYERS = {
    "buildings": {"service": "lds", "id": "layer-101290"},                  # NZ Building Outlines
    "parcels": {"service": "lds", "id": "layer-50772", "field": "appellation"},   # NZ Primary Parcels
    "addresses": {"service": "lds", "id": "layer-105689", "field": "full_address"},  # NZ Addresses
    "lcdb": {"service": "lris", "id": "layer-104400", "field": "Class_2018"},     # LCDB v5.0
}
BASEMAPS_TILES = "https://basemaps.linz.govt.nz/v1/tiles/aerial/WebMercatorQuad/{z}/{x}/{y}.webp?api={key}"
MAPILLARY_GRAPH = "https://graph.mapillary.com/images"

# ---- Classification parameters (AS/NZS 1170.2:2021 Cl 4.2.1) ----
# Values marked [standard] come straight from the clause text; [assumption] are assumptions to
# confirm in validation and record in the calculation basis.
P = {
    "bin_m": 50,                    # radial bin length along each sector [assumption]
    "min_coverage_m": 1200,         # bins are computed at least this far upwind [assumption]
    "obstruction_min_h": 1.5,       # lowest obstruction height in TC2 [standard]
    "tall_obstruction_h": 5.0,      # TC2 obstructions are 1.5-5 m [standard]
    "tc3_min_h": 3.0,               # TC3 obstructions 3-10 m [standard]
    "tc4_min_h": 10.0,              # TC4 constructions 10-30 m [standard]
    "tc2_max_per_ha": 2.0,          # TC2: no more than two obstructions per hectare [standard]
    "tc25_max_bldg_per_ha": 10.0,   # TC2.5: more than 2 and less than 10 buildings per ha [standard]
    "tc3_house_eq_per_ha": 10.0,    # TC3: at least 10 house-size obstructions per ha [standard]
    "house_area_m2": 200.0,         # one house-size equivalent of plan area [assumption]
    "min_building_m2": 20.0,        # smaller footprints ignored as obstructions [assumption]
    "dense_forest_cover": 0.5,      # tall vegetation cover treated as dense forest (TC3) [assumption]
    "some_trees_cover": 0.05,       # tall vegetation cover treated as 'some trees' (TC2.5) [assumption]
    "tall_isolated_per_ha": 1.0,    # isolated obstructions > 5 m per ha that make TC2.5 [assumption]
    "water_frac": 0.5,              # bin treated as water surface (TC1) [assumption]
    "open_max_per_ha": 0.2,         # 'very few or no obstructions' (TC1 on land) [assumption]
    "exg_veg": 0.05,                # excess-green index above which a pixel is vegetation [assumption]
    "near_threshold": 0.25,         # within 25 % of a threshold -> neighbouring TC in range [assumption]
    "z0_disagree_tc": 0.75,         # z0 cross-check differs by more than this -> lower confidence [assumption]
    "dsm_old_years": 5,             # LiDAR older than this flagged [assumption]
}

# LCDB v5 classes -> fallback TC (used when no DSM) and permanence flags
LCDB = {
    "water": {20, 21, 22},
    "bare": {10, 12, 14, 16},
    "open": {2, 5, 6, 15, 30, 40, 41, 43, 44, 45, 46, 47},
    "shrub": {33, 50, 51, 52, 55, 56, 58},
    "forest": {54, 68, 69, 70, 71},
    "urban": {1},
    "plantation": {71},
    "harvested": {64},
}
LCDB_FALLBACK_TC = [("water", 1), ("bare", 1), ("open", 2), ("harvested", 2), ("shrub", 2.5),
                    ("forest", 3), ("urban", 3)]
