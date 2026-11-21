"""Site search: coordinates (WGS84 or NZTM), Lot/DP appellation, or street address."""
import re
from . import sources as S
from . import config as C

LOT_DP = re.compile(r"\b(lot|pt|part|sec|section|flat|unit)\b.*\b(dp|sp|so|lt|ps|ml|deeds)\s*\d+", re.I)

def search(q: str, limit=10):
    q = q.strip()
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", q)]
    if len(nums) == 2 and not re.search(r"[a-zA-Z]{2,}", q):
        a, b = nums
        if -48 <= a <= -33 and 165 <= b <= 180:
            return [{"kind": "coordinates", "label": f"{a:.6f}, {b:.6f}", "lat": a, "lon": b}]
        if 165 <= a <= 180 and -48 <= b <= -33:
            return [{"kind": "coordinates", "label": f"{b:.6f}, {a:.6f}", "lat": b, "lon": a}]
        if 1_000_000 <= a <= 2_200_000 and 4_700_000 <= b <= 6_300_000:
            lon, lat = S.TO_WGS.transform(a, b)
            return [{"kind": "coordinates", "label": f"NZTM {a:.0f} E, {b:.0f} N", "lat": lat, "lon": lon}]
    safe = q.replace("'", "''")
    if LOT_DP.search(q):
        f = C.LAYERS["parcels"]["field"]
        g = S.wfs("parcels", cql=f"{f} ILIKE '%{safe}%'", count=limit)
        kind = "parcel"
    else:
        f = C.LAYERS["addresses"]["field"]
        g = S.wfs("addresses", cql=f"{f} ILIKE '%{safe}%'", count=limit)
        kind = "address"
    out = []
    for _, row in g.iterrows():
        c = row.geometry.representative_point() if row.geometry is not None else None
        if c is None:
            continue
        lon, lat = S.TO_WGS.transform(c.x, c.y)
        item = {"kind": kind, "label": str(row.get(f, "")), "lat": lat, "lon": lon}
        if kind == "parcel":
            item["parcel"] = [list(S.TO_WGS.transform(x, y)) for x, y in row.geometry.convex_hull.exterior.coords]
        out.append(item)
    return out
