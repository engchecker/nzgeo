"""Hazard types and classification of council layer names."""
from __future__ import annotations

import re

HAZARDS = {
    "flood": "Flooding",
    "coastal": "Coastal erosion and inundation",
    "tsunami": "Tsunami",
    "liquefaction": "Liquefaction",
    "slope": "Slope instability and landslides",
    "fault": "Active faults and fault rupture",
    "volcanic": "Volcanic",
    "geothermal": "Geothermal",
    "expansive": "Expansive soils",
    "subsidence": "Subsidence, mine workings and soft ground",
    "rockfall": "Rockfall",
    "erosion": "River and land erosion",
    "contaminated": "Contaminated land (HAIL)",
}

_PATTERNS = {
    "flood": r"flood|inundat(?!.*(coast|sea|tsunami|storm surge))|overland flow|ponding|stopbank|floodplain|flood ?plain|stormwater (hazard|risk)|wet extent",
    "coastal": r"coast|storm surge|sea[- ]level|shoreline|chas|coastal hazard|erosion hazard zone",
    "tsunami": r"tsunami|evacuation zone",
    "liquefaction": r"liquef|lateral spread",
    "slope": r"slope|landslide|land ?slip|instabilit|mass movement|debris flow|geotech.*(hazard|constraint)",
    "fault": r"fault|rupture|fault avoidance|fault awareness|deformation overlay",
    "volcanic": r"volcan|lahar|ashfall|tephra",
    "geothermal": r"geotherm|hydrothermal|hot ?spot",
    "expansive": r"expansive|shrink|swell|reactive soil",
    "subsidence": r"subsid|mine|peat|soft ground|sinkhole|tomo",
    "rockfall": r"rockfall|rock fall|boulder roll|cliff collapse",
    "erosion": r"river erosion|bank erosion|erosion prone|highly erodible",
    "contaminated": r"\bhail\b|\bslu\b|selected land ?use|\bslur\b|\bllur\b|listed land ?use|contaminat|land ?use register|hazardous activit",
}
_EXCLUDE = r"contour|survey mark|monitoring site|rain gauge|gauge|consent|bore|well log|culvert|pipe|asset|cadastr|parcel|label|anno"


def classify(*texts: str) -> list[str]:
    t = " ".join(x for x in texts if x).lower().replace("_", " ")
    if re.search(_EXCLUDE, t):
        return []
    return [k for k, p in _PATTERNS.items() if re.search(p, t)]


# Attribute fields that are noise in a report
_NOISE = re.compile(r"^(objectid|fid|shape|globalid|st_area|st_length|shape_(area|length|leng)|created_|last_edited|"
                    r"creator|editor|gdb_|se_anno|oid)", re.I)


def clean_attributes(attrs: dict, limit: int = 12) -> dict:
    out = {}
    for k, v in attrs.items():
        if _NOISE.match(k) or v in (None, "", " "):
            continue
        out[k] = v
        if len(out) >= limit:
            break
    return out


# Buried services (three waters) layers in council asset services
_SERVICE_PATTERNS = {
    "wastewater": r"waste ?water|sewer|foul|\bww\b|sanitary",
    "stormwater": r"storm ?water|\bsw\b|drainage (pipe|main)|stormwater",
    "water supply": r"water ?(supply|main|pipe|reticulation)|potable|\bws\b|drinking water",
}
_SERVICE_EXCLUDE = r"catchment|overland|flood|ponding|consent|zone|area|abandon|proposed|future|node|valve|hydrant|manhole|fitting|meter|lateral connection point"


def classify_service(*texts: str) -> str | None:
    t = " ".join(x for x in texts if x).lower().replace("_", " ")
    if re.search(_SERVICE_EXCLUDE, t) or not re.search(r"pipe|main|line|reticulation|gravity|rising|network|sewer|drain", t):
        return None
    return next((k for k, p in _SERVICE_PATTERNS.items() if re.search(p, t)), None)
