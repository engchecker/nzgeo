"""Loads the AS/NZS 1170 data tables from the encrypted bundle. This module holds no standard values."""
import json, os
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(os.environ.get("NZWIND_DATA", Path(__file__).resolve().parent / "data"))
DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
BEARING = {d: i * 45.0 for i, d in enumerate(DIRECTIONS)}

@lru_cache(maxsize=1)
def _tables() -> dict:
    from .secure import decrypt          # decrypted in memory only
    return decrypt()

def table(name: str) -> dict:
    return _tables()[name]

def data_version() -> str:
    return table("general_rules")["_meta"]["version"]

def interp(x, xs, ys):
    """Linear interpolation on ascending xs; clamps at the ends."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
