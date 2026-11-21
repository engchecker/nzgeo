"""FastAPI service: serves the web page and the calculation endpoint."""
import os
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi import Request
from .secure import DataKeyError
from pydantic import BaseModel, Field, model_validator
from pyproj import Transformer
from . import regional, lee
from .data import DIRECTIONS, data_version
from .terrain import Band
from .shielding import ShieldBuilding
from .topography import Feature
from .site import Site, Building, DirectionInput, site_wind_speeds

WEB = Path(__file__).resolve().parent / "web"
app = FastAPI(title="NZ site wind speed", version="0.2.0")

@app.exception_handler(DataKeyError)
def _no_key(request: Request, exc: DataKeyError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})
_nztm = Transformer.from_crs("EPSG:4326", "EPSG:2193", always_xy=True)

class BandIn(BaseModel):
    tc: float = Field(ge=1, le=4)
    to_m: float = Field(gt=0, description="Upwind distance where this band ends; starts where the previous ends")

class ShieldIn(BaseModel):
    height_m: float = Field(gt=0)
    breadth_m: float = Field(gt=0)
    distance_m: float = Field(ge=0)
    slope_excluded: bool = False

class TopoIn(BaseModel):
    kind: Literal["none", "hill", "escarpment"] = "none"
    H: float = Field(0, ge=0)
    Lu: float = Field(0, ge=0)
    x: float = 0
    peak_zone: bool = False

    @model_validator(mode="after")
    def _lu(self):
        if self.kind != "none" and self.H > 0 and self.Lu <= 0:
            raise ValueError("Lu must be greater than 0 when a feature is entered")
        return self

class DirIn(BaseModel):
    bands: list[BandIn] = []
    shielding: list[ShieldIn] = []
    topo: TopoIn = TopoIn()
    mzcat_override: float | None = Field(None, gt=0)
    ms_override: float | None = Field(None, gt=0, le=1)
    mh_override: float | None = Field(None, ge=1)
    mlee_override: float | None = Field(None, ge=1)
    suggested_bands: list[BandIn] | None = None
    suggested_topo: TopoIn | None = None
    suggested_shielding: list[ShieldIn] | None = None
    bands_low: list[BandIn] | None = None
    bands_high: list[BandIn] | None = None

class BuildingIn(BaseModel):
    name: str = ""
    eaves_height_m: float = Field(gt=0)
    ridge_height_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    orientation_deg: float = Field(ge=0, lt=360)
    reference_height_m: float | None = Field(None, gt=0)
    circular_section: bool = False

class CalcIn(BaseModel):
    lon: float = Field(ge=165, le=180)
    lat: float = Field(ge=-48, le=-33)
    region: Literal["NZ1", "NZ2", "NZ3", "NZ4"]
    elevation_m: float = Field(ge=0)
    importance_level: int = Field(ge=1, le=4)
    design_life: str
    limit_state: Literal["ULS", "SLS1"] = "ULS"
    building: BuildingIn
    directions: dict[str, DirIn]

def _bands(items):
    out, start = [], 0.0
    for b in items:
        if b.to_m <= start:
            raise ValueError(f"Terrain band ends must increase (band ending {b.to_m} m)")
        out.append(Band(b.tc, start, b.to_m)); start = b.to_m
    return out

def _safe(fn, default):
    try:
        return fn()
    except DataKeyError:
        return default

def _version_or_none():
    return _safe(data_version, None)

@app.get("/api/meta")
def meta():
    return {"regions": regional.REGIONS, "lives": regional.LIVES, "directions": DIRECTIONS,
            "data_version": _version_or_none(), "undigitised_lee_ranges": _safe(lee.undigitised_ranges, []),
            "basemaps_key": os.environ.get("LINZ_BASEMAPS_KEY", ""),
            "mapillary_token": os.environ.get("MAPILLARY_TOKEN", ""),
            "demo": os.environ.get("NZWIND_DEMO") == "1"}

@app.get("/api/locate")
def locate(lon: float, lat: float):
    e, n = _nztm.transform(lon, lat)
    return {"nztm_e": round(e, 1), "nztm_n": round(n, 1)}

@app.post("/api/calc")
def calc(body: CalcIn):
    try:
        missing = [d for d in DIRECTIONS if d not in body.directions]
        if missing:
            raise ValueError("Missing inputs for " + ", ".join(missing))
        b = body.building
        bldg = Building(b.eaves_height_m, b.ridge_height_m, b.length_m, b.width_m, b.orientation_deg,
                        b.reference_height_m, b.circular_section)
        dirs = {}
        for d in DIRECTIONS:
            x = body.directions[d]
            dirs[d] = DirectionInput(
                terrain_bands=_bands(x.bands),
                shielding=[ShieldBuilding(s.height_m, s.breadth_m, s.distance_m, s.slope_excluded) for s in x.shielding],
                feature=Feature(x.topo.kind, x.topo.H, x.topo.Lu, x.topo.x, x.topo.peak_zone),
                mlee_override=x.mlee_override, mzcat_override=x.mzcat_override,
                ms_override=x.ms_override, mh_override=x.mh_override,
                suggested_bands=_bands(x.suggested_bands) if x.suggested_bands else None,
                suggested_feature=Feature(x.suggested_topo.kind, x.suggested_topo.H, x.suggested_topo.Lu,
                                          x.suggested_topo.x, x.suggested_topo.peak_zone) if x.suggested_topo else None,
                suggested_shielding=[ShieldBuilding(s.height_m, s.breadth_m, s.distance_m, s.slope_excluded)
                                     for s in x.suggested_shielding] if x.suggested_shielding is not None else None,
                bands_low=_bands(x.bands_low) if x.bands_low else None,
                bands_high=_bands(x.bands_high) if x.bands_high else None)
        site = Site(body.lon, body.lat, body.region, body.elevation_m, body.importance_level, body.design_life)
        res = site_wind_speeds(site, bldg, dirs, body.limit_state)
        res["inputs"].update(locate(body.lon, body.lat))
        return res
    except (ValueError, regional.HazardAnalysisRequired) as e:
        raise HTTPException(status_code=422, detail=str(e))

class AutoIn(BaseModel):
    lon: float = Field(ge=165, le=180)
    lat: float = Field(ge=-48, le=-33)
    h: float = Field(gt=0)
    z: float = Field(gt=0)

@app.post("/api/auto")
def auto(body: AutoIn):
    from .auto.pipeline import auto_map
    try:
        return auto_map(body.lon, body.lat, body.h, body.z)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Automatic mapping failed: {type(e).__name__}: {e}")

@app.get("/api/search")
def search(q: str):
    """Address first, then Lot/DP (LINZ, no key needed), then coordinates; map click otherwise."""
    try:
        from nzgeo.locate import search as nz_search
        r = nz_search(q)
        if r["results"] or not os.environ.get("LINZ_LDS_KEY"):
            if not r["results"]:
                raise HTTPException(status_code=404, detail=r.get("message") or "No match")
            return {"results": [{**x, "kind": {"legal": "parcel"}.get(x["kind"], x["kind"])} for x in r["results"]]}
    except HTTPException:
        raise
    except Exception:
        pass
    from .auto.search import search as do_search
    try:
        return {"results": do_search(q)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

@app.get("/api/streetlevel")
def streetlevel(lon: float, lat: float, heading: float = 0):
    from .auto import sources as S
    try:
        m = S.mapillary_nearest(lon, lat)
    except Exception as e:
        m = {"error": str(e)}
    return {"mapillary": m, "google_street_view": S.google_pano_url(lon, lat, heading)}

app.mount("/static", StaticFiles(directory=WEB), name="static")

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
