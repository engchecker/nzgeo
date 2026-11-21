"""Validation harness: compares suggested terrain categories with engineer-assigned ones.

Input CSV (one row per site, direction and band), e.g. from past jobs:
    job,lon,lat,h,z,direction,start_m,end_m,tc
    24-118,174.7762,-41.2865,6,6,N,0,300,3
Run: python -m nzwind.auto.validate benchmarks.csv report.csv

Reports, for every direction, the engineer and suggested Mz,cat over the Cl 4.2.3 averaging
window, the difference, and category agreement weighted by distance inside the window.
"""
import csv, sys
from collections import defaultdict
from .pipeline import auto_map
from ..terrain import Band, mz_averaged, averaging_window

def tc_at(bands, m):
    for b in bands:
        if b.start_m <= m < b.end_m:
            return b.tc
    return None

def main(src, dst):
    rows = list(csv.DictReader(open(src)))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["job"], float(r["lon"]), float(r["lat"]), float(r["h"]), float(r["z"]), r["direction"])].append(
            Band(float(r["tc"]), float(r["start_m"]), float(r["end_m"])))
    out, cache = [], {}
    for (job, lon, lat, h, z, d), eng in groups.items():
        key = (job, lon, lat, h, z)
        if key not in cache:
            cache[key] = auto_map(lon, lat, h, z)
        sug = [Band(b["tc"], b["start_m"], b["end_m"]) for b in cache[key]["directions"][d]["bands"]]
        a, b = averaging_window(z)
        agree = sum(1 for m in range(int(a), int(b), 10) if tc_at(eng, m + 5) == tc_at(sug, m + 5)) / len(range(int(a), int(b), 10))
        me, ms = mz_averaged(eng, z)["mz_cat"], mz_averaged(sug, z)["mz_cat"]
        out.append({"job": job, "direction": d, "mz_engineer": round(me, 3), "mz_suggested": round(ms, 3),
                    "mz_diff": round(ms - me, 3), "category_agreement": round(agree, 2),
                    "unconservative": ms < me - 0.005})
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    n = len(out)
    print(f"{n} site-directions. Mean category agreement {sum(o['category_agreement'] for o in out) / n:.0%}. "
          f"Suggested Mz,cat lower than engineer (unconservative) in {sum(o['unconservative'] for o in out)} cases.")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
