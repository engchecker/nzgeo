"""Council registry and resolution of which councils cover a site."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache

from . import arcgis
from .config import DATA_DIR


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads((DATA_DIR / "councils.json").read_text())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(council|region|regional|district|city|lakes|of|the|area outside.*)\b", " ", s)
    return re.sub(r"[^a-z]+", " ", s).strip()


def by_name(name: str) -> dict | None:
    n = _norm(name)
    for c in registry()["councils"]:
        if _norm(c["name"]) == n:
            return c
    return None


def _first(attrs: dict, prefix: str) -> str | None:
    for k, v in attrs.items():
        if k.upper().startswith(prefix) and k.upper().endswith("_NAME") and "ASCII" not in k.upper():
            return v
    for k, v in attrs.items():
        if k.upper().startswith(prefix) and "NAME" in k.upper():
            return v
    return None


def resolve(lon: float, lat: float) -> dict:
    """Territorial authority and region containing the site, from Stats NZ 2023 boundaries."""
    b = registry()["boundaries"]
    ta_attrs, _ = arcgis.query_point(b["territorial"], lon, lat)
    rc_attrs, _ = arcgis.query_point(b["regional"], lon, lat)
    ta_name = _first(ta_attrs[0], "TA") if ta_attrs else None
    rc_name = _first(rc_attrs[0], "REGC") if rc_attrs else None
    return {"territorial_authority": ta_name, "region": rc_name}


def councils_for_site(lon: float, lat: float) -> tuple[dict, list[dict]]:
    """The site's district council plus every council whose services cover its region."""
    where = resolve(lon, lat)
    out: list[dict] = []
    if where["territorial_authority"]:
        ta = by_name(where["territorial_authority"])
        if ta:
            out.append(ta)
    if where["region"]:
        rn = _norm(where["region"])
        for c in registry()["councils"]:
            if c["type"] in ("regional", "unitary") and _norm(c["region"]) == rn and c not in out:
                out.append(c)
    return where, out
