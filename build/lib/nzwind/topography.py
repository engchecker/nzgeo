"""M_h and M_t (AS/NZS 1170.2 Cl 4.4.1-4.4.2)."""
from dataclasses import dataclass

@dataclass
class Feature:
    kind: str           # "none", "hill" (hills and ridges) or "escarpment"
    H: float = 0.0      # height of feature
    Lu: float = 0.0     # upwind horizontal distance from crest to half height
    x: float = 0.0      # site position from crest: negative upwind, positive downwind
    peak_zone: bool = False   # site inside rectangular peak zone (Figure 4.5), slopes > 0.45 only

def mh(f: Feature, z: float, h: float) -> dict:
    if f.kind == "none" or f.H <= 0:
        return {"mh": 1.0, "note": "No topographic feature"}
    if f.H < min(0.4 * h, 5.0):
        return {"mh": 1.0, "note": "H < lesser of 0.4h and 5 m"}
    slope = f.H / (2 * f.Lu)
    if slope < 0.05:
        return {"mh": 1.0, "slope": slope, "note": "H/(2Lu) < 0.05"}
    L1 = max(0.36 * f.Lu, 0.4 * f.H)
    L2 = 10 * L1 if (f.kind == "escarpment" and f.x > 0) else 4 * L1
    out = {"slope": slope, "L1": L1, "L2": L2}
    if abs(f.x) >= L2:
        return {**out, "mh": 1.0, "note": "Outside local topographic zone"}
    if slope > 0.45 and f.peak_zone:
        return {**out, "mh": 1 + 0.71 * (1 - abs(f.x) / L2), "equation": "4.4(4)"}
    return {**out, "mh": 1 + (f.H / (3.5 * (z + L1))) * (1 - abs(f.x) / L2), "equation": "4.4(3)"}

def mt(mh_value: float, mlee: float, elevation_m: float) -> dict:
    """NZ regions: Eq 4.4(1) above 500 m ASL, otherwise the larger of Mh and Mlee."""
    if elevation_m > 500:
        return {"mt": mh_value * mlee * (1 + 0.00015 * elevation_m), "rule": "4.4(1): Mh·Mlee·(1+0.00015E)"}
    return {"mt": max(mh_value, mlee), "rule": "4.4.1(c): max(Mh, Mlee)"}
