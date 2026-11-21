"""Settings. Everything can be overridden with environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
HOME_DIR = Path(os.environ.get("NZGEO_HOME", Path.home() / ".nzgeo"))
CONFIG_FILE = HOME_DIR / "config.json"


def _cfg() -> dict:
    try:
        import json
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def _secret(name: str) -> str | None:
    """Environment variable first, then the OS keychain (service 'nzgeo')."""
    env = {"linz-api-key": "LINZ_API_KEY", "data-key": "NZGEO_DATA_KEY"}[name]
    if os.environ.get(env):
        return os.environ[env]
    try:
        import keyring
        v = keyring.get_password("nzgeo", name)
        if v:
            return v
    except Exception:
        pass
    p = HOME_DIR / f".{name}"  # fallback used by setup when no keychain is available
    try:
        return p.read_text().strip() if p.exists() else None
    except Exception:
        return None


_C = _cfg()


@dataclass
class Settings:
    cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("NZGEO_CACHE", HOME_DIR / "cache")))
    cache_ttl_days: float = float(os.environ.get("NZGEO_CACHE_TTL_DAYS", "30"))
    timeout_s: float = float(os.environ.get("NZGEO_TIMEOUT_S", "20"))
    user_agent: str = "nzgeo/0.5 (open-source desk study tool)"
    linz_api_key: str | None = field(default_factory=lambda: _secret("linz-api-key"))

    # National services
    gns_root: str = "https://gis.gns.cri.nz/server/rest/services"
    agol_search: str = "https://www.arcgis.com/sharing/rest/search"
    # LINZ Data Service layer for the coastline (Topo 1:50k). Confirm the id in the LDS catalogue on first use.
    linz_coastline_layer: int = int(os.environ.get("NZGEO_LINZ_COASTLINE_LAYER", "50258"))
    searise_vlm_csv: str = os.environ.get(
        "NZGEO_SEARISE_CSV", "https://zenodo.org/records/11398538/files/NZ_VLM_final_May24.csv?download=1")
    vs30_h5: str | None = os.environ.get("NZGEO_VS30_H5") or _C.get("vs30_h5")  # ucgmsim/nzcvm_data vs30/NZ_Vs30.h5 (git lfs pull)

    # Screening distances (m)
    fault_search_m: float = 10_000
    landslide_search_m: float = 1_000
    line_hazard_search_m: float = 500
    geology_boundary_flag_m: float = 500
    coast_search_m: float = 2_000

    # Standards currency check sources (pages are scanned for edition strings)
    standards_sources: dict = field(default_factory=lambda: {
        "published": [
            "https://www.standards.govt.nz/shop/nzs-36042011",
            "https://www.standards.govt.nz/search?q=NZS%203604",
            "https://www.standards.govt.nz/search?q=1170.5",
            "https://www.standards.govt.nz/search?q=NZS%203404.3",
        ],
        "cited": [
            "https://www.building.govt.nz/building-code-compliance/b-stability/b1-structure/b1-acceptable-solutions-and-verification-methods",
            "https://codehub.building.govt.nz/resources/nzs-36042011",
            "https://codehub.building.govt.nz/resources/b1vm1-second-edition",
            "https://www.building.govt.nz/building-code-compliance/b-stability/b2-durability/",
        ],
    })

    # Durability data bundle (digitised from licensed copies of the standards)
    bundle_path: Path = field(default_factory=lambda: Path(os.environ.get("NZGEO_BUNDLE", DATA_DIR / "standards_geo.enc")))
    nzs3604_bundle_edition: int = int(os.environ.get("NZGEO_NZS3604_EDITION", "2011"))
    nzs3404_3_bundle_edition: int = int(os.environ.get("NZGEO_NZS3404_3_EDITION", "2026"))


settings = Settings()
