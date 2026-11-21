"""Site and design wind speeds (AS/NZS 1170.2 Cl 2.2, 2.3)."""
from dataclasses import dataclass, field
from .data import DIRECTIONS, BEARING, data_version
from . import regional, terrain, shielding, topography, lee

@dataclass
class Building:
    eaves_height_m: float
    ridge_height_m: float
    length_m: float            # along the building's long axis
    width_m: float
    orientation_deg: float     # bearing of the long axis, clockwise from true north
    reference_height_m: float | None = None   # z; defaults to average roof height h
    circular_section: bool = False

    @property
    def h(self):
        return (self.eaves_height_m + self.ridge_height_m) / 2

    @property
    def z(self):
        return self.reference_height_m if self.reference_height_m else self.h

@dataclass
class DirectionInput:
    terrain_bands: list = field(default_factory=list)       # list[terrain.Band]
    shielding: list = field(default_factory=list)           # list[shielding.ShieldBuilding]
    feature: topography.Feature = field(default_factory=lambda: topography.Feature("none"))
    mlee_override: float | None = None
    mzcat_override: float | None = None
    ms_override: float | None = None
    mh_override: float | None = None
    suggested_bands: list | None = None      # terrain bands proposed by automatic mapping
    suggested_feature: topography.Feature | None = None
    suggested_shielding: list | None = None   # shielding buildings proposed by automatic mapping
    bands_low: list | None = None            # lower / upper TC bands from mapping uncertainty
    bands_high: list | None = None

@dataclass
class Site:
    lon: float
    lat: float
    region: str
    elevation_m: float
    importance_level: int
    design_life: str

def _bands_key(bands):
    return [(float(b.tc), round(b.start_m, 1), round(b.end_m, 1)) for b in bands]

def _bands_text(bands):
    return ", ".join(f"TC{b.tc:g} {b.start_m:.0f}-{b.end_m:.0f} m" for b in bands)

def _feat_text(f):
    return "none" if f.kind == "none" else f"{f.kind}, H {f.H:g} m, Lu {f.Lu:g} m, x {f.x:g} m"

def _r(x, n=3):
    return round(x, n)

def site_wind_speeds(site: Site, bldg: Building, dirs: dict, limit_state: str = "ULS") -> dict:
    if bldg.ridge_height_m < bldg.eaves_height_m:
        raise ValueError("Ridge height must not be less than eaves height")
    R = regional.return_period(site.design_life, site.importance_level, limit_state)
    VR = regional.vr(site.region, R)
    Mc = regional.mc(site.region)
    h, z = bldg.h, bldg.z
    rows, warnings, overrides = [], [], []
    for d in DIRECTIONS:
        di = dirs[d]
        Md = regional.md(site.region, d, bldg.circular_section)
        tz = terrain.mz_averaged(di.terrain_bands, z) if di.terrain_bands else None
        Mz = tz["mz_cat"] if tz else None
        if di.mzcat_override is not None:
            overrides.append({"direction": d, "factor": "Mz,cat", "computed": Mz, "used": di.mzcat_override}); Mz = di.mzcat_override
        if Mz is None:
            raise ValueError(f"{d}: enter terrain bands or an Mz,cat value")
        s = shielding.ms(h, di.shielding)
        Ms = s["ms"]
        if di.ms_override is not None:
            overrides.append({"direction": d, "factor": "Ms", "computed": Ms, "used": di.ms_override}); Ms = di.ms_override
        t = topography.mh(di.feature, z, h)
        Mh = t["mh"]
        if di.mh_override is not None:
            overrides.append({"direction": d, "factor": "Mh", "computed": Mh, "used": di.mh_override}); Mh = di.mh_override
        L = lee.mlee(site.lon, site.lat, d)
        Mlee = L["mlee"]
        if di.mlee_override is not None:
            overrides.append({"direction": d, "factor": "Mlee", "computed": Mlee, "used": di.mlee_override}); Mlee = di.mlee_override
        T = topography.mt(Mh, Mlee, site.elevation_m)
        V = VR * Mc * Md * (Mz * Ms * T["mt"])
        src = {"terrain": "manual", "topography": "manual", "shielding": "manual"}
        if di.suggested_shielding is not None:
            key = lambda bs: sorted((round(b.height_m, 1), round(b.breadth_m, 1), round(b.distance_m, 1), b.slope_excluded) for b in bs)  # noqa: E731
            same = key(di.suggested_shielding) == key(di.shielding)
            src["shielding"] = "suggested" if same else "edited"
            if not same and di.ms_override is None:
                sug = shielding.ms(h, di.suggested_shielding)["ms"]
                overrides.append({"direction": d, "factor": "Shielding buildings", "computed": sug, "used": Ms,
                                  "suggested": f"{len(di.suggested_shielding)} building(s), Ms {sug:.2f}",
                                  "entered": f"{len(di.shielding)} building(s), Ms {Ms:.2f}"})
        if di.suggested_bands is not None:
            same = _bands_key(di.suggested_bands) == _bands_key(di.terrain_bands)
            src["terrain"] = "suggested" if same else "edited"
            if not same:
                sug = terrain.mz_averaged(di.suggested_bands, z)["mz_cat"]
                overrides.append({"direction": d, "factor": "Terrain bands", "computed": sug, "used": Mz,
                                  "suggested": _bands_text(di.suggested_bands), "entered": _bands_text(di.terrain_bands)})
        if di.suggested_feature is not None:
            same = di.suggested_feature == di.feature
            src["topography"] = "suggested" if same else "edited"
            if not same:
                sug = topography.mh(di.suggested_feature, z, h)["mh"]
                overrides.append({"direction": d, "factor": "Topography", "computed": sug, "used": t["mh"],
                                  "suggested": _feat_text(di.suggested_feature), "entered": _feat_text(di.feature)})
        rng = None
        if di.bands_low and di.bands_high and src["terrain"] == "suggested" and di.mzcat_override is None:
            m_lo = terrain.mz_averaged(di.bands_low, z)["mz_cat"]
            m_hi = terrain.mz_averaged(di.bands_high, z)["mz_cat"]
            k = VR * Mc * Md * Ms * T["mt"]
            rng = [_r(k * min(m_lo, m_hi), 2), _r(k * max(m_lo, m_hi), 2)]
        rows.append({"direction": d, "bearing": BEARING[d], "Md": Md, "Mzcat": _r(Mz), "Ms": _r(Ms), "Mh": _r(Mh),
                     "Mlee": _r(Mlee), "Mt": _r(T["mt"]), "Vsit": _r(V, 2), "Vsit_range": rng, "source": src,
                     "detail": {"terrain": tz, "shielding": s, "topography": t, "lee": L, "mt_rule": T["rule"]}})
    if h > 25:
        warnings.append("h > 25 m: shielding not applied (Cl 4.3.1)")
    if z > 25 and z == h:
        warnings.append("z > 25 m: confirm reference height for the terrain averaging distance")
    und = lee.undigitised_ranges()
    if und:
        warnings.append("Not yet digitised - check Figure 4.6 manually for lee zones: " + "; ".join(und))
    derived = sorted({(r["detail"]["lee"]["range"], r["detail"]["lee"].get("crest_basis")) for r in rows
                      if r["detail"]["lee"].get("range") and "derived" in str(r["detail"]["lee"].get("crest_basis"))})
    for name, _ in derived:
        dirs = [r["direction"] for r in rows if r["detail"]["lee"].get("range") == name]
        warnings.append(f"{name} lee zone ({', '.join(dirs)}): the standard gives no crest coordinates; the crest is taken from "
                        "Figure 4.6 (digitised, about ±1–2 km). Check the site's position against the figure, "
                        "especially near zone edges.")
    near = [r["direction"] for r in rows if r["detail"]["lee"].get("range") and r["detail"]["lee"].get("zone") == "outer"
            and r["detail"]["lee"].get("distance_km") is not None]
    del near
    return {"inputs": {"R": R, "VR": VR, "Mc": Mc, "h": _r(h), "z": _r(z), "limit_state": limit_state,
                       "region": site.region, "elevation_m": site.elevation_m},
            "directions": rows, "design": design_wind_speeds(rows, bldg.orientation_deg, limit_state),
            "overrides": overrides, "warnings": warnings, "data_version": data_version()}

def _vsit_at(rows, bearing):
    """Linear interpolation of Vsit between cardinal points (bearing in degrees)."""
    b = bearing % 360
    i = int(b // 45)
    f = (b - 45 * i) / 45
    v0, v1 = rows[i % 8]["Vsit"], rows[(i + 1) % 8]["Vsit"]
    return v0 + f * (v1 - v0)

def design_wind_speeds(rows, orientation_deg, limit_state="ULS"):
    """Vdes,theta for the four building orthogonal directions (Cl 2.3)."""
    out = []
    for k, face in enumerate(["Axis +0°", "Axis +90°", "Axis +180°", "Axis +270°"]):
        theta = (orientation_deg + 90 * k) % 360
        cands = [theta - 45, theta + 45] + [c for c in range(0, 720, 45) if theta - 45 < c < theta + 45]
        vals = [(_vsit_at(rows, c), c % 360) for c in cands]
        v, at = max(vals)
        governing = v
        if limit_state == "ULS" and v < 30:
            v = 30.0
        out.append({"theta": _r(theta, 1), "label": face, "Vdes": _r(v, 2), "governing_bearing": _r(at, 1),
                    "min_applied": governing < 30 and limit_state == "ULS"})
    return out
