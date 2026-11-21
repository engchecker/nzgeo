"""Jobs: one folder per report, holding the inputs, uploaded files and the saved wind calculation."""
from __future__ import annotations

import base64
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .config import HOME_DIR

JOBS = HOME_DIR / "jobs"
REPORT_TYPES = {
    "wind": "Site wind speed report",
    "desk": "Geotechnical desk study",
    "iga": "Initial geotechnical assessment (desk study + field testing)",
    "combined": "Combined report: wind speed, desk study and field testing",
}


def _dir(job_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{6,40}", job_id or ""):
        raise KeyError("bad job id")
    return JOBS / job_id


def new_id(label: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "site").lower()).strip("-")[:24] or "site"
    return f"{slug}-{secrets.token_hex(3)}"


def create(data: dict) -> dict:
    jid = new_id(data.get("site", {}).get("address") or data.get("project", {}).get("job_no") or "")
    d = _dir(jid)
    (d / "photos").mkdir(parents=True, exist_ok=True)
    job = {"id": jid, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), **data,
           "photos": [], "workbook": None, "wind": None}
    save(job)
    return job


def save(job: dict) -> None:
    d = _dir(job["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps(job, indent=1, default=str))


def load(job_id: str) -> dict:
    p = _dir(job_id) / "job.json"
    if not p.exists():
        raise KeyError(job_id)
    return json.loads(p.read_text())


def add_workbook(job: dict, name: str, data: bytes) -> Path:
    ext = Path(name).suffix.lower() if Path(name).suffix.lower() in (".xlsx", ".xlsm") else ".xlsx"
    p = _dir(job["id"]) / f"fieldsheet{ext}"
    p.write_bytes(data)
    job["workbook"] = {"name": name, "file": p.name}
    return p


def workbook_bytes(job: dict) -> bytes | None:
    if not job.get("workbook"):
        return None
    p = _dir(job["id"]) / job["workbook"]["file"]
    return p.read_bytes() if p.exists() else None


def add_photo(job: dict, processed: dict, *, caption: str = "", kind: str = "overview", include: bool = True) -> dict:
    n = len(job["photos"]) + 1
    f = f"photo{n:02d}.jpg"
    (_dir(job["id"]) / "photos" / f).write_bytes(base64.b64decode(processed["jpeg_b64"]))
    meta = {k: v for k, v in processed.items() if k != "jpeg_b64"}
    meta.update({"file": f, "caption": caption, "kind": kind, "include": include, "no": n})
    job["photos"].append(meta)
    return meta


def photo_b64(job: dict, meta: dict) -> str:
    return base64.b64encode((_dir(job["id"]) / "photos" / meta["file"]).read_bytes()).decode()


def list_jobs(limit: int = 30) -> list[dict]:
    if not JOBS.exists():
        return []
    out = []
    for p in sorted(JOBS.glob("*/job.json"), key=lambda q: q.stat().st_mtime, reverse=True)[:limit]:
        try:
            j = json.loads(p.read_text())
            out.append({"id": j["id"], "created": j.get("created"), "type": j.get("report_type"),
                        "address": (j.get("site") or {}).get("address"), "has_wind": bool(j.get("wind"))})
        except Exception:
            continue
    return out
