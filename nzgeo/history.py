"""Plain-English statements on site history (aerial photographs) and contaminated land (HAIL), shared by the reports."""
from __future__ import annotations


def _years(imgs):
    ys = [str(i["year"]) for i in imgs]
    return ys[0] if len(ys) == 1 else ", ".join(ys[:-1]) + " and " + ys[-1]


def aerial_summary(a: dict | None) -> dict:
    ae = (a or {}).get("aerials") or {}
    if ae.get("status") != "ok":
        return {"ok": False}
    imgs = [i for i in ae.get("images", []) if i.get("png")]
    hist = [i for i in imgs if i["cat"] == "scanned-aerial-photos"]
    cur = [i for i in imgs if i["cat"] != "scanned-aerial-photos"]
    frames = [f for f in ae.get("frames", []) if f.get("date")]
    earliest = frames[0] if frames else None
    return {"ok": True, "images": imgs, "hist": hist, "current": cur, "earliest_frame": earliest,
            "surveys": ae.get("surveys", []), "download_failed": bool(ae.get("surveys")) and not imgs,
            "all_years": sorted({s["year"] for s in ae.get("surveys", [])}),
            "historic_range": ae.get("historic_range")}


def aerial_sentence(a: dict | None, ref_imagery: str | None = None, ref_retrolens: str | None = None, appendix="D") -> str | None:
    s = aerial_summary(a)
    if not s["ok"] or s["download_failed"]:
        return None
    r1 = f" [{ref_imagery}]" if ref_imagery else ""
    parts = []
    if s["hist"]:
        parts.append(f"Historic aerial photographs of the site from {_years(s['hist'])}"
                     + (f", and current aerial imagery from {s['current'][-1]['year']}," if s["current"] else "")
                     + f" have been reviewed{r1} and are reproduced in Appendix {appendix}.")
    elif s["current"]:
        parts.append(f"No orthorectified historic aerial survey covers the site; current aerial imagery from "
                     f"{s['current'][-1]['year']} is reproduced in Appendix {appendix}{r1}.")
    ef = s["earliest_frame"]
    r2 = f" [{ref_retrolens}]" if ref_retrolens else ""
    if ef:
        parts.append(f"Earlier unrectified photographs, the oldest dating from {ef['date'][:4]}"
                     + (f" (survey {ef['survey']}, run {ef['run']}, frame {ef['frame']})" if ef.get("survey") else "")
                     + f", are held in the Crown Aerial Film Archive and can be viewed on Retrolens{r2}.")
    elif s["hist"] and s["hist"][0]["year"] > 1960:
        parts.append(f"Earlier photographs in the Crown Aerial Film Archive can be viewed on Retrolens{r2}.")
    return " ".join(parts) if parts else None


def hail_sentence(a: dict | None, ref: str | None = None) -> tuple[str | None, str]:
    """(sentence, level) where level is 'on_site', 'nearby', 'clear', 'not_published' or 'unknown'."""
    h = (a or {}).get("hail") or {}
    st = h.get("status")
    r = f" [{ref}]" if ref else ""
    reg, council = h.get("register") or "contaminated land register", h.get("council") or "the regional council"
    if st == "ok":
        if h.get("on_site"):
            x = h["on_site"][0]
            what = ", ".join(str(v) for v in (x.get("category"), x.get("status")) if v)
            return (f"The site is recorded on {council}’s {reg}{r}" + (f" ({what})" if what else "") + ". The National Environmental "
                    "Standard for Assessing and Managing Contaminants in Soil to Protect Human Health (NESCS) may apply to soil "
                    "disturbance on this land, and a preliminary site investigation by a suitably qualified and experienced "
                    "practitioner is recommended before earthworks.", "on_site")
        if h.get("nearby"):
            x = h["nearby"][0]
            nm = x.get("site") or "a listed site"
            cat = f" ({x['category']})" if x.get("category") else ""
            return (f"The site is not recorded on {council}’s {reg}{r}. The nearest listed site, {nm}{cat}, is approximately "
                    f"{x['distance_m']} m away.", "nearby")
        return (f"The site is not recorded on {council}’s {reg}{r}, and no listed site lies within {h.get('near_m', 100)} m.", "clear")
    if st == "not_published":
        return (None, "not_published")
    return (None, "unknown")
