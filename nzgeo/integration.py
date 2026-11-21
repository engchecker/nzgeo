"""Attach the geotechnical section to a saved wind job.

The wind job supplies the site and, where it has computed them, ground elevation, LiDAR slope and
crest features from the M_t profiles. Key names are mapped here so the two tools stay independent.
"""
from __future__ import annotations

from .report import render_html
from .site import assess

# wind job key -> nzgeo key
JOB_KEYS = {"ground_elevation": "ground_elevation_m", "elevation_m": "ground_elevation_m",
            "slope_max_deg": "slope_max_deg", "slope_mean_deg": "slope_mean_deg", "crest_features": "crest_features"}


def attach_to_job(job: dict, *, apoe_n: int | None = None) -> dict:
    site = job.get("site", job)
    lat, lon = float(site["lat"]), float(site["lon"])
    terrain = {v: site[k] for k, v in JOB_KEYS.items() if k in site}
    a = assess(lon, lat, apoe_n=apoe_n or job.get("apoe_n") or 500, address=site.get("address"),
               legal=site.get("legal"), job=terrain)
    job["geotech"] = a
    job["geotech_report_html"] = render_html(a)
    return job
