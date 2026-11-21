"""M_s (AS/NZS 1170.2 Cl 4.3)."""
import math
from dataclasses import dataclass
from .data import table, interp

@dataclass
class ShieldBuilding:
    height_m: float
    breadth_m: float      # normal to the wind
    distance_m: float     # from the subject building
    slope_excluded: bool = False   # True where Cl 4.3.1 / Figure 4.2 excludes it

def ms(h: float, buildings: list[ShieldBuilding]) -> dict:
    t = table("ms_shielding_multiplier")
    if h > 25:
        return {"ms": 1.0, "note": "h > 25 m: Ms = 1.0", "ns": 0}
    used = [b for b in buildings if b.height_m >= h and b.distance_m <= 20 * h and not b.slope_excluded]
    if not used:
        return {"ms": 1.0, "note": "No qualifying shielding buildings", "ns": 0}
    ns = len(used)
    hs = sum(b.height_m for b in used) / ns
    bs = sum(b.breadth_m for b in used) / ns
    ls = h * (10 / ns + 5)
    s = ls / math.sqrt(hs * bs)
    return {"ms": interp(s, t["s"], t["Ms"]), "ns": ns, "hs": hs, "bs": bs, "ls": ls, "s": s,
            "ignored": len(buildings) - ns}
