"""NZ Site Hazards local web app: one menu for desk study and field-testing reports.

Start with:  python -m nzgeo serve      (the desktop icon does this)
"""
from __future__ import annotations

import json
import re
import os
import threading
import webbrowser
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import __version__, iga, jobs, locate
from .api import router
from .config import HOME_DIR, settings

# Keys for the wind calculator, from the same places setup saved them
if settings.linz_api_key and not os.environ.get("LINZ_LDS_KEY"):
    os.environ["LINZ_LDS_KEY"] = settings.linz_api_key
_WIND_KEY_FILE = HOME_DIR / ".nzwind-data-key"
if _WIND_KEY_FILE.exists() and not os.environ.get("NZWIND_DATA_KEY"):
    os.environ.setdefault("NZWIND_DATA_KEY_FILE", str(_WIND_KEY_FILE))

app = FastAPI(title="NZ Site Hazards", version=__version__)
app.include_router(router)
from pathlib import Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

WIND, WIND_ERR = False, "wind calculator disabled"
if os.environ.get("NZGEO_ENABLE_WIND") == "1":   # wind calculator is hidden unless explicitly enabled
    try:
        from nzwind.api import app as wind_app
        app.mount("/wind", wind_app)
        WIND, WIND_ERR = True, ""
    except Exception as e:  # pragma: no cover
        WIND, WIND_ERR = False, f"{type(e).__name__}: {e}"


@app.get("/wind", include_in_schema=False)
def _wind_slash():
    return RedirectResponse("/wind/")


# ---------------------------------------------------------------- lookups
@app.get("/api/search")
def search(q: str):
    return locate.search(q)


@app.get("/api/legal")
def legal(lat: float, lon: float):
    return locate.legal_at(lon, lat)


@app.get("/api/prefill")
def prefill(lat: float, lon: float):
    from .windzones import wind_region
    try:
        w = wind_region(lon, lat)
    except Exception as e:
        w = {"status": "error", "reason": str(e)}
    return {"wind_region": w, "wind_available": WIND}


@app.post("/api/parse-workbook")
async def parse_workbook(file: UploadFile = File(...)):
    from .fieldsheet import read_workbook, template_value
    from .goodground import assess as gg_assess
    data = await file.read()
    try:
        f = read_workbook(data, file.filename)
    except Exception as e:
        raise HTTPException(422, f"Could not read the spreadsheet ({type(e).__name__}). Save it as .xlsx or .xlsm and try again.")
    t = f["template"]
    proj = {k: template_value(t, lab, nth=n) for k, lab, n in (
        ("client", "Client Details", 0), ("job_no", "Job number", 0), ("revision", "Revision", 0),
        ("company", "Engineering Company", 0), ("prepared_by", "Prepared by", 0), ("prepared_quals", "Qualifications", 0),
        ("reviewed_by", "Reviewed by", 0), ("reviewed_quals", "Qualifications", 1), ("structure", "Structure type", 0),
        ("levels", "Levels above ground", 0), ("design_life", "Design Life", 0), ("importance_level", "Importance level", 0))}
    if not proj.get("job_no"):
        proj["job_no"] = f["header"].get("job_no")
    gg = gg_assess(f) if f["scala"] else None
    return {"address": f["header"].get("address") or template_value(t, "Project Street Address"),
            "date": f["header"].get("date"), "technician": f["header"].get("technician"), "project": proj,
            "scala_tests": len(f["scala"]), "auger_tests": len(f["auger"]), "issues": f["issues"],
            "photo_descriptions": t.get("photo_descriptions", []), "verdict": gg["verdict"] if gg else None,
            "findings": gg["findings"] if gg else []}


# ---------------------------------------------------------------- jobs
@app.get("/api/jobs")
def list_jobs():
    return jobs.list_jobs()


@app.post("/api/jobs")
async def save_job(meta: str = Form(...), workbook: UploadFile | None = File(None),
                   photos: list[UploadFile] | None = File(None), photo_meta: str = Form("[]")):
    from .photos import process
    m = json.loads(meta)
    if not m.get("site") or m["site"].get("lat") is None:
        raise HTTPException(422, "Choose the site first (step 1).")
    jid = m.pop("job_id", None)
    if jid:
        try:
            job = jobs.load(jid)
        except KeyError:
            raise HTTPException(404, "Job not found")
        job.update({k: v for k, v in m.items() if k in ("site", "report_type", "project", "field_inputs", "options")})
    else:
        job = jobs.create(m)
    if workbook is not None and workbook.filename:
        jobs.add_workbook(job, workbook.filename, await workbook.read())
    pm = json.loads(photo_meta or "[]")
    if photos:
        job["photos"] = []
        for i, up in enumerate(photos):
            if not up.filename:
                continue
            meta_i = pm[i] if i < len(pm) else {}
            try:
                p = process(await up.read(), up.filename)
            except Exception:
                raise HTTPException(422, f"{up.filename}: not a readable photo (use JPEG, PNG or HEIC).")
            jobs.add_photo(job, p, caption=meta_i.get("caption", ""), kind=meta_i.get("kind", "overview"),
                           include=meta_i.get("include", True))
    elif pm and job.get("photos"):
        for i, ph in enumerate(job["photos"]):
            if i < len(pm):
                ph.update({k: pm[i][k] for k in ("caption", "kind", "include") if k in pm[i]})
    jobs.save(job)
    return {"id": job["id"], "photos": len(job["photos"]), "workbook": bool(job.get("workbook")), "has_wind": bool(job.get("wind"))}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    try:
        j = jobs.load(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")
    return {**{k: v for k, v in j.items() if k != "wind"}, "has_wind": bool(j.get("wind")),
            "wind_saved": (j.get("wind") or {}).get("saved")}


@app.post("/api/jobs/{job_id}/wind")
def save_wind(job_id: str, body: dict):
    try:
        j = jobs.load(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")
    if not isinstance(body.get("result"), dict) or "directions" not in body["result"]:
        raise HTTPException(422, "No wind result in the request")
    j["wind"] = {"result": body["result"], "summary": [r for r in body.get("summary", []) if len(r) == 2],
                 "saved": datetime.now().strftime("%d %b %Y %H:%M")}
    jobs.save(j)
    return {"ok": True}


def _assessment(job):
    from .report import render_html
    from .site import assess
    s, o = job["site"], job.get("options") or {}
    num = lambda k: float(o[k]) if o.get(k) not in (None, "") else None  # noqa: E731
    a = assess(s["lon"], s["lat"], apoe_n=int(o.get("apoe_n") or 500), vs30=num("vs30"), site_class=o.get("site_class") or None,
               surface_condition=o.get("surface_condition") or None, coast_type=o.get("coast_type") or None,
               address=s.get("address"), legal=s.get("legal"), parcel=s.get("parcel"), imagery=True)
    return a, iga.desk_body(render_html(a))


def _client_doc(job_id: str):
    from . import clientreport
    try:
        job = jobs.load(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")
    a = None
    if job.get("report_type") != "wind":
        a, _ = _assessment(job)
    return job, clientreport.build(job, a)


@app.get("/api/jobs/{job_id}/report", response_class=HTMLResponse)
def job_report(job_id: str):
    """Client report preview, with a Word download button."""
    from . import clientreport
    job, d = _client_doc(job_id)
    title = next((b["text"] for b in d.blocks if b["t"] == "title"), "Report")
    html = clientreport.to_html(d, job_id, f"{title} – {(job.get('site') or {}).get('address') or ''}")
    html = html.replace("</small></div>", "</small><a class='ghost' href='/api/jobs/" + job_id + "/checks' target='_blank'>Engineer's check sheet</a></div>", 1)
    return html


@app.get("/api/jobs/{job_id}/report.docx")
def job_report_docx(job_id: str):
    from . import clientreport
    job, d = _client_doc(job_id)
    data = clientreport.to_docx(d, clientreport.footer_text(job))
    proj, site = job.get("project") or {}, job.get("site") or {}
    stem = " ".join(x for x in (proj.get("job_no"), (site.get("address") or "").split(",")[0], "Geotechnical Assessment"
                                if job.get("report_type") != "wind" else "Wind Assessment") if x)
    fn = re.sub(r'[\\/:*?"<>|]+', "", stem).strip() or "Report"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{fn}.docx"'})


@app.get("/api/jobs/{job_id}/checks", response_class=HTMLResponse)
def job_checks(job_id: str):
    """Engineer's check sheet: every tool result, NZS 3604 checks and spreadsheet checks (not for the client)."""
    try:
        job = jobs.load(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")
    if job.get("report_type") == "wind":
        from .windzones import lee_zones, wind_region
        try:
            a, desk = {"wind_region": wind_region(job["site"]["lon"], job["site"]["lat"]),
                       "lee_zones": lee_zones(job["site"]["lon"], job["site"]["lat"])}, None
        except Exception:
            a, desk = None, None
    else:
        a, desk = _assessment(job)
    return iga.build(job, assessment=a, desk_html=desk)


@app.get("/api/jobs/{job_id}/workbook")
def job_workbook(job_id: str):
    try:
        job = jobs.load(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found")
    a, _ = _assessment(job)
    data, cells = iga.completed_workbook(job, a)
    if data is None:
        raise HTTPException(404, "No spreadsheet was uploaded for this job")
    name = job["workbook"]["name"].rsplit(".", 1)
    fn = f"{name[0]} - desk study filled.{name[1] if len(name) > 1 else 'xlsx'}"
    return Response(data, media_type="application/vnd.ms-excel.sheet.macroEnabled.12" if fn.endswith("xlsm") else
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"', "X-Filled-Cells": ",".join(cells)})


# ---------------------------------------------------------------- page
@app.get("/", response_class=HTMLResponse)
def home():
    from .menu_page import PAGE
    return PAGE.replace("__VERSION__", __version__).replace("__WIND__", "true" if WIND else "false")


def serve(port: int = 8765, open_browser: bool = True):
    import uvicorn
    url = f"http://127.0.0.1:{port}/"
    print("\n  NZ Site Hazards is running.")
    print(f"  Your browser should open at {url}")
    print("  If it does not, open your web browser and type that address.")
    print("  KEEP THIS WINDOW OPEN while you use the tool. Close it to stop.\n")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
