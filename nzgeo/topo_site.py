"""Site topography from the LINZ national 1 m LiDAR DEM: elevations, slopes and fall across the property and
its surroundings, with a contour and slope figure for the report."""
from __future__ import annotations

import io
import math

import numpy as np

from .geo import to_nztm

RADIUS = 120.0     # m around the site analysed and drawn


def _compass(deg):
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int(((deg % 360) + 22.5) // 45) % 8]


def site_topography(lon: float, lat: float, parcel=None, *, radius=RADIUS) -> dict:
    from nzwind.auto.sitedata import Grid
    from nzwind.auto.sources import read_elevation
    x, y = to_nztm(lon, lat)
    grid = Grid.around(x, y, radius, 1.0)
    dem, prov = read_elevation("dem", grid)
    if not np.isfinite(dem).any():
        return {"status": "no_data", "reason": "No LiDAR DEM covers the site"}
    return analyse(dem, grid, x, y, parcel, prov)


def analyse(dem, grid, x, y, parcel=None, prov=None) -> dict:
    gy, gx = np.gradient(dem, grid.res)              # rows run south (y decreases), so dz/dnorth = -gy
    dzde, dzdn = gx, -gy
    slope = np.degrees(np.arctan(np.hypot(dzde, dzdn)))
    X, Y = grid.centres()
    if parcel and len(parcel) >= 3:
        from matplotlib.path import Path
        poly = [to_nztm(lo, la) for lo, la in parcel]
        mask = Path(poly).contains_points(np.c_[X.ravel(), Y.ravel()]).reshape(X.shape)
        where = "property"
    else:
        mask = np.hypot(X - x, Y - y) <= 15
        where = "area within 15 m of the site"
    mask &= np.isfinite(dem) & np.isfinite(slope)
    if mask.sum() < 10:
        return {"status": "no_data", "reason": "LiDAR DEM has no values over the site"}
    near = np.isfinite(slope) & (np.hypot(X - x, Y - y) <= 50)
    z = dem[mask]
    s = slope[mask]
    ge, gn = float(np.nanmean(dzde[mask])), float(np.nanmean(dzdn[mask]))
    fall_deg = (math.degrees(math.atan2(-ge, -gn)) + 360) % 360          # direction the ground falls towards
    r, c = int((grid.y0 - y) / grid.res), int((x - grid.x0) / grid.res)
    site_z = float(dem[r, c]) if 0 <= r < dem.shape[0] and 0 <= c < dem.shape[1] and np.isfinite(dem[r, c]) else float(np.nanmedian(z))
    out = {"status": "ok", "where": where, "site_elevation_m": round(site_z, 1),
           "elev_min_m": round(float(np.nanmin(z)), 1), "elev_max_m": round(float(np.nanmax(z)), 1),
           "slope_mean_deg": round(float(np.nanmean(s)), 1), "slope_p90_deg": round(float(np.nanpercentile(s, 90)), 1),
           "slope_max_deg": round(float(np.nanpercentile(s, 99)), 1),
           "falls_to": _compass(fall_deg), "overall_gradient": round(math.hypot(ge, gn), 3),
           "steep_within_50m_deg": round(float(np.nanpercentile(slope[near], 98)), 1) if near.any() else None,
           "relief_100m_m": round(float(np.nanmax(dem) - np.nanmin(dem)), 1),
           "frac_over_20deg": round(float((s > 20).mean()), 2), "frac_over_30deg": round(float((s > 30).mean()), 2),
           "provenance": prov or {}}
    out["figure_png"] = figure(dem, slope, grid, x, y, parcel)
    return out


def figure(dem, slope, grid, x, y, parcel=None) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    ext = [grid.x0 - x, grid.x0 + dem.shape[1] * grid.res - x, grid.y0 - dem.shape[0] * grid.res - y, grid.y0 - y]
    fig, ax = plt.subplots(figsize=(6.4, 5.4), dpi=160)
    filled = np.where(np.isfinite(dem), dem, np.nanmean(dem))
    hs = LightSource(azdeg=315, altdeg=45).hillshade(filled, vert_exag=2, dx=grid.res, dy=grid.res)
    ax.imshow(hs, cmap="gray", extent=ext, origin="upper", alpha=0.9)
    im = ax.imshow(np.clip(slope, 0, 45), cmap="RdYlGn_r", vmin=0, vmax=45, extent=ext, origin="upper", alpha=0.45)
    zr = np.nanmax(dem) - np.nanmin(dem)
    step = 0.5 if zr < 8 else 1 if zr < 20 else 2 if zr < 50 else 5
    Xc = np.linspace(ext[0], ext[1], dem.shape[1])
    Yc = np.linspace(ext[3], ext[2], dem.shape[0])
    cs = ax.contour(Xc, Yc, filled, levels=np.arange(math.floor(np.nanmin(dem)), math.ceil(np.nanmax(dem)) + step, step),
                    colors="k", linewidths=0.4, alpha=0.7)
    ax.clabel(cs, cs.levels[::max(1, len(cs.levels) // 8)], fontsize=6, fmt="%g")
    if parcel and len(parcel) >= 3:
        pts = [to_nztm(lo, la) for lo, la in parcel]
        ax.plot([p[0] - x for p in pts] + [pts[0][0] - x], [p[1] - y for p in pts] + [pts[0][1] - y], color="#0050c8", lw=2)
    ax.plot(0, 0, marker="o", ms=8, mfc="none", mec="red", mew=2)
    ax.set_xlabel("Metres east of site", fontsize=8)
    ax.set_ylabel("Metres north of site", fontsize=8)
    ax.tick_params(labelsize=7)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Ground slope (degrees)", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    ax.set_aspect("equal")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def sentence(t: dict | None) -> str | None:
    if not t or t.get("status") != "ok":
        return None
    ratio = lambda deg: f"about 1V:{1 / math.tan(math.radians(deg)):.0f}H" if deg >= 2 else "near level"  # noqa: E731
    s = (f"LiDAR survey data indicates that the {t['where']} lies between RL {t['elev_min_m']:.1f} m and RL {t['elev_max_m']:.1f} m "
         f"(NZVD2016) and falls generally to the {t['falls_to']}, with an average slope of {t['slope_mean_deg']:.0f}° "
         f"({ratio(t['slope_mean_deg'])}) and local slopes of up to about {t['slope_p90_deg']:.0f}°.")
    if t.get("steep_within_50m_deg") and t["steep_within_50m_deg"] >= 30:
        s += f" Slopes of about {t['steep_within_50m_deg']:.0f}° occur within 50 m of the site."
    return s
