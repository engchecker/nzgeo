"""M_z,cat (AS/NZS 1170.2 Cl 4.2)."""
from dataclasses import dataclass
from .data import table, interp

@dataclass
class Band:
    tc: float        # terrain category, 1 to 4 (decimals allowed)
    start_m: float   # distance upwind of the site where the band starts
    end_m: float     # distance upwind of the site where the band ends

def mz_fully_developed(tc: float, z: float) -> float:
    t = table("mzcat_terrain_height_multiplier")
    if not 1 <= tc <= 4:
        raise ValueError("Terrain category must be between 1 and 4")
    if z > t["z_m"][-1]:
        raise ValueError("Height above 200 m is outside Table 4.1")
    tcs = t["terrain_categories"]
    col = [interp(z, t["z_m"], t["values"][k]) for k in ["1", "2", "2.5", "3", "4"]]
    return interp(tc, tcs, col)

def averaging_window(z: float):
    """(start, end) of the averaging window upwind of the site: lag 20z, then max(500 m, 40z)."""
    lag = 20 * z
    return lag, lag + max(500.0, 40 * z)

def mz_averaged(bands: list[Band], z: float) -> dict:
    """Distance-weighted Mz,cat over the averaging window (Cl 4.2.3, Figure 4.1)."""
    a, b = averaging_window(z)
    total, covered, parts = 0.0, 0.0, []
    for band in sorted(bands, key=lambda x: x.start_m):
        lo, hi = max(a, band.start_m), min(b, band.end_m)
        if hi > lo:
            m = mz_fully_developed(band.tc, z)
            total += m * (hi - lo)
            covered += hi - lo
            parts.append({"tc": band.tc, "from_m": lo, "to_m": hi, "mz": round(m, 4)})
    if covered < (b - a) - 1e-6:
        raise ValueError(f"Terrain bands cover {covered:.0f} m of the {b - a:.0f} m averaging window "
                         f"({a:.0f}-{b:.0f} m upwind)")
    return {"mz_cat": total / covered, "window_m": [a, b], "parts": parts}
