"""V_R, M_c, M_d (AS/NZS 1170.2 Section 3) and annual probability (AS/NZS 1170.0 Cl 3.4)."""
from .data import table, DIRECTIONS

REGIONS = ["NZ1", "NZ2", "NZ3", "NZ4"]
LIVES = {"construction_equipment": "Construction equipment", "lt_6_months": "Less than 6 months",
         "5_years": "5 years", "25_years": "25 years", "50_years": "50 years", "100_years_plus": "100 years or more"}

class HazardAnalysisRequired(ValueError):
    pass

def return_period(life: str, importance_level: int, limit_state: str = "ULS") -> int:
    """Average recurrence interval R (years) for wind, from AS/NZS 1170.0 Table 3.3."""
    rows = table("annual_probability_nz")["rows"]
    if life not in rows:
        raise ValueError(f"Unknown design working life '{life}'")
    by_il = rows[life]
    if str(importance_level) not in by_il:
        raise ValueError(f"Importance level {importance_level} not defined for '{LIVES[life]}'")
    row = by_il[str(importance_level)]
    p = row[0] if limit_state == "ULS" else row[3]
    if p is None:
        raise ValueError(f"No {limit_state} wind event defined for IL{importance_level}, {LIVES[life]}")
    if p == "HAZARD_ANALYSIS":
        raise HazardAnalysisRequired("IL4 with design life of 100 years or more: design event by hazard analysis (Table 3.3 note)")
    return int(p.split("/")[1])

def vr(region: str, R: float) -> float:
    t = table("vr_regional_wind_speed_nz")
    col = t["regions"][region]
    if R in t["R_years"]:
        return float(t["values"][col][t["R_years"].index(R)])
    if R < 5:
        raise ValueError("V_R formula applies only for R >= 5 years")
    f = t["formula_R_ge_5"][col]
    return float(round(f["a"] - f["b"] * R ** -0.1))

def mc(region: str) -> float:
    return float(table("mc_climate_change_multiplier")["values"][region])

def md(region: str, direction: str, circular_section: bool = False) -> float:
    if circular_section:
        return 1.0
    t = table("md_direction_multiplier_nz")
    return float(t["values"][region][DIRECTIONS.index(direction)])
