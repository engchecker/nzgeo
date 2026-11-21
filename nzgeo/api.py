"""FastAPI router. In the wind tool: `app.include_router(nzgeo.api.router)`."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from . import councils, discover, standards
from .report import render_html
from .site import assess

router = APIRouter(prefix="/api/geotech", tags=["geotechnical"])


@router.get("/site")
def site(lat: float, lon: float, apoe_n: int = 500, vs30: float | None = None, site_class: str | None = None,
         surface_condition: str | None = Query(None, description="exposed, sheltered or interior")):
    return assess(lon, lat, apoe_n=apoe_n, vs30=vs30, site_class=site_class, surface_condition=surface_condition)


@router.get("/report", response_class=HTMLResponse)
def report(lat: float, lon: float, apoe_n: int = 500, vs30: float | None = None, site_class: str | None = None,
           address: str | None = None, legal: str | None = None, surface_condition: str | None = None,
           coast_type: str | None = None):
    return render_html(assess(lon, lat, apoe_n=apoe_n, vs30=vs30, site_class=site_class, address=address, legal=legal,
                              surface_condition=surface_condition, coast_type=coast_type))


@router.get("/standards")
def standards_status():
    return standards.check()


@router.get("/councils")
def council_list():
    reg = councils.registry()
    cat = discover.load_catalogue()["councils"]
    return [{"name": c["name"], "type": c["type"], "status": c["status"], "roots": c["rest_roots"],
             "layers_catalogued": len(cat.get(c["name"], {}).get("layers", [])),
             "crawled": cat.get(c["name"], {}).get("crawled")} for c in reg["councils"]]


@router.post("/discover")
def run_discover(council: str | None = None):
    cat = discover.discover_all([council] if council else None)
    return {k: len(v["layers"]) for k, v in cat["councils"].items()}
