"""Reports built from a job: wind, desk study, Initial Geotechnical Assessment, or all three.

The Initial Geotechnical Assessment follows the structure of the 'Civil and Structural Engineer Initial
Geotechnical Assessment Report' template used in a soil suitability workbook (sections 1 to 8 and
Appendices One and Two), with the desk study filled from national and council data and the field
results checked against NZS 3604:2011 clause 3.3.
"""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime

from jinja2 import Environment, select_autoescape

from . import __version__, goodground, jobs, photos as photo_mod
from .fieldsheet import read_workbook, template_value

_ENV = Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
COLOURS = ["#2a6fdb", "#d1495b", "#2e9e6b", "#e08a00", "#7a4fd1", "#00838f"]


def _m(v):
    if v is None:
        return "not measured"
    return f"{v / 1000:.1f} km" if v >= 1000 else f"{v:.0f} m"


_ENV.filters["m"] = _m


def _get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def _hits(a, kind):
    return [f for f in (_get(a, "council", "findings") or []) if kind in f.get("hazards", [])]


def _hit_text(h):
    t = f"{h['council']} – {h['layer']}: {h['relation']}"
    if h.get("distance_m"):
        t += f", {_m(h['distance_m'])} {h.get('direction', '')}".rstrip()
    return t


# ---------------------------------------------------------------- field interpretation
def ground_model(field: dict | None, gg: dict | None) -> str | None:
    if not field or not (field.get("auger") or field.get("scala")):
        return None
    parts = []
    for t in field.get("auger", [])[:1]:
        layers = t["layers"]
        org = [L for L in layers if re.search(r"organic|top\s*soil", L["description"], re.I)]
        if org:
            parts.append(f"topsoil to about {org[-1]['depth_m'] + 0.1:.1f} m")
        below = [L for L in layers if L not in org]
        if below:
            mats = []
            for L in below:
                m = L["fields"].get("material") or L["description"]
                if not mats or mats[-1][0] != m:
                    mats.append([m, L["depth_m"], L["depth_m"] + 0.1])
                else:
                    mats[-1][2] = L["depth_m"] + 0.1
            parts += [f"{m.lower()} from {a:.1f} m to {b:.1f} m" for m, a, b in mats]
        parts[-1] += f" (hand auger {t['test']} terminated at {t['max_depth_m']:.1f} m)"
    if gg and gg["tests"]:
        reached = [s["reached_m"] for s in gg["tests"]]
        refusal = [s for s in gg["tests"] if s["refusal"]]
        if refusal:
            parts.append(f"Scala refusal at {min(reached):.1f}–{max(reached):.1f} m in {len(refusal)} of {len(gg['tests'])} tests "
                         "(cause not identified)")
    return ("; ".join(parts) + ".").capitalize() if parts else None


def desk_answers(a: dict | None, field: dict | None, gg: dict | None, job: dict) -> dict[str, str]:
    """Answers for the desktop assessment items of the Engineering NZ template, as full sentences."""
    from .history import aerial_sentence, hail_sentence
    from .profile import geology_text, subsoil_class_evidence
    from .services import sentence as services_sentence
    from .topo_site import sentence as topo_sentence
    if not a:
        return {}
    out = {}
    g = a.get("geology") or {}
    gm_ = a.get("geomap") or {}
    if g.get("status") == "ok":
        txt = ("Geological Map of New Zealand 1:250,000 (QMAP, Earth Sciences New Zealand, 2023) maps the site as "
               + geology_text(a) + ".")
        if g.get("flag_near_boundary"):
            txt += (f" A mapped geological boundary lies about {_m(g.get('boundary_distance_m'))} to the "
                    f"{g.get('boundary_direction')}; at this scale either unit may be present.")
        others = [u for u in gm_.get("units", []) if (u.get("unit_name") or u.get("description")) not in
                  (g.get("unit_name"), g.get("description"))]
        if others:
            txt += " Other units within the map extract: " + "; ".join(
                " ".join(str(x) for x in (u.get("unit_code"), u.get("unit_name") or u.get("description")) if x) for u in others[:5]) + "."
        if gm_.get("status") == "ok":
            txt += " A map extract is included in the appendices."
        rs = (a.get("rock_strength") or {}).get("attributes") or {}
        if rs:
            txt += " Rock strength grouping: " + "; ".join(f"{k}: {v}" for k, v in list(rs.items())[:3]) + "."
        out["Geological maps available"] = txt
    ch = _get(a, "council", "findings") or []
    geo_kinds = ("liquefaction", "slope", "rockfall", "fault", "subsidence", "expansive", "erosion", "coastal", "tsunami", "volcanic")
    if _get(a, "council", "status") == "error":
        out["Geotechnical hazards from council"] = None
    else:
        rel = [h for h in ch if any(k in h["hazards"] for k in geo_kinds)]
        ls = _get(a, "landslides", "features") or []
        t = ("; ".join(_hit_text(h) for h in rel[:6]) + "." if rel else
             f"No geotechnical hazard is mapped at the site in the {_get(a, 'council', 'layers_checked', default=0)} hazard "
             f"layers published by {', '.join(_get(a, 'council', 'councils', default=[]) or ['the councils'])}.")
        if ls:
            t += f" National landslide data records {len(ls)} landslide(s) nearby, the closest {ls[0]['layer']} about {_m(ls[0]['distance_m'])} {ls[0]['direction']}."
        out["Geotechnical hazards from council"] = t
    inside = [h for h in ch if h.get("relation") == "site inside" and any(k in h["hazards"] for k in geo_kinds)]
    known = [_hit_text(h) for h in inside]
    if gg:
        known += [t for lvl, t in gg["findings"] if t.startswith("Technician recorded signs of fill")][:1]
    out["Known geotechnical hazards on the site"] = "; ".join(known) if known else "None recorded in council hazard layers or during the site investigation."
    fl = _hits(a, "flood")
    tp = a.get("topography") or {}
    t = ("; ".join(_hit_text(h) for h in fl[:4]) + "." if fl else "No council flood hazard layer identifies the site.")
    if tp.get("status") == "ok":
        t += f" Ground level at the site is about RL {tp['site_elevation_m']:.1f} m (NZVD2016, LiDAR)."
    cst = a.get("coast") or {}
    if cst.get("status") == "ok" and cst.get("distance_m") is not None and cst["distance_m"] < 2000:
        t += f" The coast is about {_m(cst['distance_m'])} away."
    t += " Any minimum floor level shall be confirmed with the territorial authority."
    out["Minimum floor level and flooding"] = t
    hs, _ = hail_sentence(a)
    hl = a.get("hail") or {}
    if not hs and hl.get("status") == "not_published":
        hs = (f"{hl.get('council') or 'The regional council'} does not publish its {hl.get('register')} online; a property "
              "search has to be requested" + (f" ({hl['request']})" if hl.get("request") else "") + ".")
    out["Review of historic aerial photographs"] = " ".join(x for x in (aerial_sentence(a, appendix="(see appendix)"), hs) if x) or None
    f = a.get("faults") or {}
    if f.get("status") == "ok":
        n = f.get("nearest")
        t = (f"The nearest active fault in the New Zealand Active Faults Database is the {n.get('name') or 'unnamed'} fault, about "
             f"{_m(n.get('distance_m'))} to the {n.get('direction')}"
             + (f" (recurrence interval class {n['recurrence_interval_class']})" if n.get("recurrence_interval_class") else "") + "."
             if n else "No active fault is mapped within 10 km in the New Zealand Active Faults Database.")
        t += " The site is " + ("within" if f.get("inside_zone") else "not within") + " a mapped fault avoidance or awareness area."
        faz = [h for h in _hits(a, "fault")]
        if faz:
            t += " Council layers: " + "; ".join(_hit_text(h) for h in faz[:2]) + "."
        out["Close-proximity active faults"] = t
    sub = (job.get("project") or {}).get("subsoil_class")
    ev = subsoil_class_evidence(a, field, gg)
    z = a.get("nzs1170_5") or {}
    t = (f"Subsoil Class {sub} to NZS 1170.5 is adopted." if sub else "Subsoil class to NZS 1170.5 to be confirmed by the engineer.")
    if ev:
        t += " Basis: " + ev[0].upper() + ev[1:]
    if z.get("status") == "ok":
        t += f" Hazard factor Z = {z['Z']:.2f}."
    out["Subsoil class"] = t
    ts = topo_sentence(tp)
    if ts:
        out["Topographical assessment"] = ts
    else:
        terr = a.get("terrain") or {}
        out["Topographical assessment"] = (f"Ground slopes up to {terr['slope_max_deg']}° across the site (LiDAR)."
                                           if terr.get("slope_max_deg") is not None else None)
    sv = services_sentence(a.get("services"))
    t = sv or ""
    if field:
        it = next((i for i in field.get("checklist", []) if re.search(r"locate services", i["prompt"], re.I)), None)
        if it and it["answer"] == "Y":
            t += " Services were located before testing."
    if gg and any(s["refusal"] for s in gg["tests"]):
        t += " Scala refusal may indicate a buried obstruction."
    t += " Obtain BeforeUDig plans before excavation."
    out["Buried services and structures"] = t.strip()
    gm = ground_model(field, gg)
    if gm or g.get("status") == "ok":
        unc = ("Uncertainty is moderate to high because the investigation did not reach the required depth." if gg and not all(
            s["depth_ok"] for s in gg["tests"]) else "Uncertainty is low to moderate." if gg else
               "Uncertainty is high until site investigation is undertaken.")
        out["Anticipated engineering geological model"] = " ".join(x for x in [
            f"Regional geology: {geology_text(a)}." if g.get("status") == "ok" else "", f"Site: {gm}" if gm else "", unc] if x)
    return out


def findings_table(a, field, gg):
    rows = []

    def add(item, yes, comment, source="tool"):
        rows.append({"item": item, "yes": yes, "comment": comment, "source": source})
    add("Hazard check", "Yes", "National and council hazard layers checked by the tool (see section 3 and Appendix Three)." if a else "Not run.")
    add("Desktop study", "Yes" if a else "No", "Summarised in section 3." if a else "")
    add("Ground investigations", "Yes" if field and field.get("scala") else "No",
        f"{len((field or {}).get('scala', []))} Scala, {len((field or {}).get('auger', []))} hand auger." if field else "")
    liq = _hits(a, "liquefaction") if a else []
    add("Liquefaction risk", "Yes" if any(h["relation"] == "site inside" for h in liq) else "No",
        "; ".join(_hit_text(h) for h in liq[:3]) or "Not identified in council mapping; clay soils recorded." if field else
        "; ".join(_hit_text(h) for h in liq[:3]) or "Not identified in council mapping.")
    add("Lateral spread risk", "No" if not liq else "Check", "No free face or liquefiable soils identified." if not liq else
        "Liquefaction mapped nearby: assess proximity to free faces.")
    sl = (_hits(a, "slope") + _hits(a, "rockfall")) if a else []
    ls = _get(a, "landslides", "features") or [] if a else []
    add("Slope stability risk", "Yes" if any(h["relation"] == "site inside" for h in sl) else ("Check" if sl or ls else "No"),
        "; ".join([_hit_text(h) for h in sl[:3]] + [f"{l['layer']} {_m(l['distance_m'])} {l['direction']}" for l in ls[:2]])
        or "No mapped instability within the search radius.")
    clay = bool(field) and any(re.search(r"clay", L["description"], re.I) for t in field.get("auger", []) for L in t["layers"])
    ex = _hits(a, "expansive") if a else []
    add("Expansive soils", "Check" if clay or ex else "No",
        ("Clay recorded in the auger log. NZS 3604 excludes expansive clay (liquid limit > 50 % and linear shrinkage > 15 %, "
         "NZS 4402 Tests 2.2 and 2.6); classify or test." if clay else "") + (" " + "; ".join(_hit_text(h) for h in ex[:2]) if ex else ""))
    age = str(_get(a, "geology", "age", default="") or "").lower() if a else ""
    org_deep = bool(gg) and any(e["found"] in ("organic topsoil", "peat") for e in gg["exclusions"])
    add("Potentially compressible soils", "Yes" if org_deep or "holocene" in age else "No",
        ("Organic soil below footing depth. " if org_deep else "") + ("Holocene unit mapped." if "holocene" in age else ""))
    if gg:
        add("Minimum 300 kPa ultimate bearing strength established", "Yes" if gg["good_ground"] else "No", gg["verdict"])
        add("Probable maximum settlement met under NZ Building Code", "Not demonstrated" if not gg["good_ground"] else "Yes",
            "Depends on the obstruction and fill being resolved." if not gg["good_ground"] else "")
        add("‘Good ground’ per NZS 3604 (latest edition)", "Yes" if gg["good_ground"] else "No",
            "; ".join(t for _, t in gg["findings"][:3]))
    fl = _hits(a, "flood") if a else []
    add("Flooding risk", "Yes" if any(h["relation"] == "site inside" for h in fl) else "No",
        "; ".join(_hit_text(h) for h in fl[:3]) or "Not identified in council mapping.")
    f = (a or {}).get("faults") or {}
    n = f.get("nearest") or {}
    add("Close-proximity active fault risk", "Yes" if f.get("inside_zone") else "No",
        (f"{n.get('name') or 'Nearest fault'} {_m(n.get('distance_m'))} {n.get('direction')}." if n else "") +
        (" Site within a fault avoidance/awareness zone." if f.get("inside_zone") else ""))
    return rows


def spreadsheet_findings(field):
    """The engineer's own Yes/No entries in the workbook (template section 5.2), for comparison."""
    out = {}
    if not field:
        return out
    for r in field.get("template", {}).get("rows", []):
        if r["value"] and r["value"].upper() in ("YES", "NO", "Y", "N"):
            out[r["label"][:40].lower()] = r["value"]
    return out


def risks(a, gg, field):
    out = []
    if gg:
        if any(s["refusal"] for s in gg["tests"]):
            out.append(("Unidentified obstruction or buried fill at about 0.9–1.3 m (Scala refusal)",
                        "Foundations bear on variable material; differential settlement", "H",
                        "Dig a test pit or machine-auger to identify the obstruction; extend testing to 2 m below footing level."))
        if any("fill" in t.lower() for _, t in gg["findings"]):
            out.append(("Fill recorded by the technician", "Settlement of uncertified fill", "H",
                        "Establish fill extent and depth; found below the fill on good ground or obtain specific design."))
        if any(s["zone5"]["fails"] for s in gg["tests"]):
            out.append(("Low blow counts below standard footing depth", "Bearing capacity below 300 kPa ultimate", "M",
                        "Deepen footings to competent ground or use specifically designed foundations."))
        if any(e["found"] == "organic topsoil" for e in gg["exclusions"]):
            out.append(("Topsoil below footing depth", "Compressible bearing stratum", "M", "Strip topsoil; found below organic soils."))
    if a and any(h["relation"] == "site inside" for h in _hits(a, "slope")):
        out.append(("Mapped slope instability", "Ground movement", "H", "Consult a CPEng (Geotechnical) or PEngGeol."))
    if a and any(h["relation"] == "site inside" for h in _hits(a, "liquefaction")):
        out.append(("Mapped liquefaction susceptibility", "Foundation damage in earthquakes", "H", "Consult a geotechnical engineer."))
    return out


def recommendations(gg, a):
    rec = []
    if not gg:
        return rec
    if not gg["good_ground"]:
        rec.append(("Further investigation/assessments", "Yes",
                    "Identify the cause of Scala refusal (test pit or machine auger), confirm fill extent, and extend Scala testing "
                    f"and hand augers to {gg['footing_depth_m'] + 2.0:.1f} m (2 m below footing) at a minimum of {gg['min_tests']} locations, "
                    "or engage a CPEng (Geotechnical)."))
        rec.append(("Foundation recommendations", "Yes",
                    "Good ground is not demonstrated: NZS 3604 foundations cannot be used without further investigation. "
                    "Specific engineering design of foundations is likely to be required."))
    else:
        rec.append(("Foundation recommendations", "Yes", "NZS 3604 foundations bearing in the tested strata, subject to inspection of "
                                                         "footing excavations."))
    if gg.get("exclusions"):
        rec.append(("Ground improvement/remediation", "Check", "Remove organic or unsuitable soils beneath footings."))
    return rec


# ---------------------------------------------------------------- chart
def scala_svg(field, gg) -> str:
    tests = [t for t in (field or {}).get("scala", []) if t["readings"]]
    if not tests:
        return ""
    W, H, L, T, B, R = 640, 420, 56, 30, 40, 150
    dmax = max(2.6, (gg or {}).get("footing_depth_m", 0.45) + 2.1, max(t["readings"][-1]["depth_m"] + 0.2 for t in tests))
    bmax = max(20, max((r["blows"] or 0) for t in tests for r in t["readings"]) + 2)
    sx = lambda b: L + (W - L - R) * b / bmax  # noqa: E731
    sy = lambda d: T + (H - T - B) * d / dmax  # noqa: E731
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Scala penetrometer blows per 100 mm against depth" '
         f'style="width:100%;max-width:{W}px;font:12px system-ui,sans-serif">']
    if gg:
        fd, fw = gg["footing_depth_m"], gg["footing_width_m"]
        s.append(f'<rect x="{sx(5):.1f}" y="{sy(fd):.1f}" width="{sx(bmax) - sx(5):.1f}" height="{sy(fd + 2 * fw) - sy(fd):.1f}" fill="#2e9e6b" opacity=".10"/>')
        s.append(f'<rect x="{sx(3):.1f}" y="{sy(fd + 2 * fw):.1f}" width="{sx(bmax) - sx(3):.1f}" height="{sy(fd + 2) - sy(fd + 2 * fw):.1f}" fill="#2e9e6b" opacity=".06"/>')
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{sy(fd):.1f}" y2="{sy(fd):.1f}" stroke="#555" stroke-dasharray="6 4"/>'
                 f'<text x="{W - R + 4}" y="{sy(fd) + 4:.1f}" fill="#555">Footing {fd:.2f} m</text>')
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{sy(fd + 2):.1f}" y2="{sy(fd + 2):.1f}" stroke="#9b1c1c" stroke-dasharray="2 3"/>'
                 f'<text x="{W - R + 4}" y="{sy(fd + 2) + 4:.1f}" fill="#9b1c1c">Required depth {fd + 2:.2f} m</text>')
    for k in range(0, int(bmax) + 1, 5):
        s.append(f'<line x1="{sx(k):.1f}" x2="{sx(k):.1f}" y1="{T}" y2="{H - B}" stroke="#ccc" stroke-width=".6"/>'
                 f'<text x="{sx(k):.1f}" y="{T - 8}" text-anchor="middle" fill="#555">{k}</text>')
    for v, lab in ((3, "3"), (5, "5")):
        s.append(f'<line x1="{sx(v):.1f}" x2="{sx(v):.1f}" y1="{T}" y2="{H - B}" stroke="#2e9e6b" stroke-width="1.2" stroke-dasharray="4 3"/>')
    d = 0.0
    while d <= dmax + 1e-9:
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{sy(d):.1f}" y2="{sy(d):.1f}" stroke="#eee" stroke-width=".6"/>'
                 f'<text x="{L - 6}" y="{sy(d) + 4:.1f}" text-anchor="end" fill="#555">{d:.1f}</text>')
        d += 0.5
    s.append(f'<text x="{(L + W - R) / 2:.0f}" y="12" text-anchor="middle" fill="#333">Blows per 100 mm</text>'
             f'<text x="14" y="{(T + H - B) / 2:.0f}" transform="rotate(-90 14 {(T + H - B) / 2:.0f})" text-anchor="middle" fill="#333">Depth below ground (m)</text>')
    for i, t in enumerate(tests):
        c = COLOURS[i % len(COLOURS)]
        pts = []
        for r in t["readings"]:
            if r["blows"] is None:
                continue
            pts += [(sx(r["blows"]), sy(r["depth_m"])), (sx(r["blows"]), sy(r["depth_m"] + 0.1))]
        s.append(f'<polyline fill="none" stroke="{c}" stroke-width="2" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>')
        y0 = T + 10 + i * 18
        s.append(f'<line x1="{W - R + 6}" x2="{W - R + 26}" y1="{H - B - 90 + i * 18}" y2="{H - B - 90 + i * 18}" stroke="{c}" stroke-width="3"/>'
                 f'<text x="{W - R + 30}" y="{H - B - 86 + i * 18}" fill="#333">Test {html.escape(str(t["test"]))}</text>')
        del y0
    s.append(f'<rect x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" fill="none" stroke="#999"/>')
    s.append("</svg>")
    return "".join(s)


# ---------------------------------------------------------------- assemble
def build(job: dict, *, assessment: dict | None, desk_html: str | None) -> str:
    rt = job.get("report_type", "iga")
    field = None
    wbytes = jobs.workbook_bytes(job)
    if wbytes:
        field = read_workbook(wbytes, job["workbook"]["name"])
    p = job.get("field_inputs", {}) or {}
    gg = goodground.assess(field, footing_depth_m=float(p.get("footing_depth_m") or 0.45),
                           footing_width_m=float(p.get("footing_width_m") or 0.3),
                           floor_area_m2=float(p["floor_area_m2"]) if p.get("floor_area_m2") else None,
                           strict=p.get("criterion", "exceeds") != "at_least",
                           rock_at_refusal=bool(p.get("rock_at_refusal"))) if field and field.get("scala") else None
    ph = [dict(x, b64=jobs.photo_b64(job, x)) for x in job.get("photos", []) if x.get("include", True)]
    ph_notes = photo_mod.checks(ph, job.get("site"), (field or {}).get("header", {}).get("date"))
    answers = desk_answers(assessment, field, gg, job)
    tmpl = (field or {}).get("template", {})
    proj = dict(job.get("project") or {})
    for key, label, nth in (("client", "Client Details", 0), ("job_no", "Job number", 0), ("revision", "Revision", 0),
                            ("company", "Engineering Company", 0), ("prepared_by", "Prepared by", 0),
                            ("prepared_quals", "Qualifications", 0), ("reviewed_by", "Reviewed by", 0),
                            ("reviewed_quals", "Qualifications", 1), ("date", "Date", 0), ("structure", "Structure type", 0),
                            ("levels", "Levels above ground", 0), ("design_life", "Design Life", 0),
                            ("importance_level", "Importance level", 0)):
        if not proj.get(key) and tmpl:
            proj[key] = template_value(tmpl, label, nth=nth)
    logos = [base64.b64encode(im["bytes"]).decode() for im in (field or {}).get("images", []) if im.get("note") == "Logo"]
    ctx = {
        "job": job, "rt": rt, "rt_label": jobs.REPORT_TYPES.get(rt, rt), "a": assessment or {}, "field": field, "gg": gg,
        "photos": ph, "photo_notes": ph_notes, "answers": answers, "proj": proj, "tmpl_vals": tmpl,
        "findings": findings_table(assessment, field, gg) if (field or assessment) else [],
        "sheet_findings": spreadsheet_findings(field), "risks": risks(assessment, gg, field),
        "recs": recommendations(gg, assessment), "svg": scala_svg(field, gg), "desk_html": desk_html,
        "wind": job.get("wind"), "logos": logos, "version": __version__,
        "now": datetime.now().strftime("%d %B %Y"), "site": job.get("site") or {},
        "include_field": rt in ("iga", "combined"), "include_desk": rt in ("desk", "iga", "combined"),
        "include_wind": rt in ("wind", "combined"),
        "template_labels": [
            ("List of previous geotechnical reports", "List  of previous geotechnical reports available"),
            ("Findings of previous geotechnical reports", None), ("Geological maps available", None),
            ("Geotechnical hazards from council", None),
            ("Known geotechnical hazards on the site", None), ("Minimum floor level and flooding", None),
            ("Review of historic aerial photographs", None), ("Close-proximity active faults", None),
            ("Subsoil class", None), ("Topographical assessment", None), ("Buried services and structures", None),
            ("Anticipated engineering geological model", None)],
    }
    grid = []
    if field:
        depths = sorted({r["depth_m"] for t in field["scala"] for r in t["readings"]} |
                        {L["depth_m"] for t in field["auger"] for L in t["layers"]})
        for d in depths:
            sv = [next(("" if r["blows"] is None else f"{r['blows']:.0f}" for r in t["readings"] if r["depth_m"] == d), "")
                  for t in field["scala"]]
            av = [next((L["description"] for L in t["layers"] if L["depth_m"] == d), "") for t in field["auger"]]
            grid.append((d, sv, av))
    ctx["grid"] = grid
    ctx["engineer"] = {lab: template_value(tmpl, lab) if tmpl else None for lab, _ in ctx["template_labels"]}
    return _ENV.from_string(TEMPLATE).render(**ctx)


def desk_body(full_html: str) -> str:
    """Body of the desk study report, without its own title, for use as an appendix."""
    m = re.search(r"<body>([\s\S]*)</body>", full_html)
    body = m.group(1) if m else full_html
    body = re.sub(r"<h1>[\s\S]*?</h1>", "", body, count=1)
    return body.replace("<h2>", "<h3>").replace("</h2>", "</h3>")


def completed_workbook(job: dict, assessment: dict | None) -> tuple[bytes | None, list[str]]:
    from .fieldsheet import fill_template
    wbytes = jobs.workbook_bytes(job)
    if not wbytes:
        return None, []
    field = read_workbook(wbytes)
    p = job.get("field_inputs", {}) or {}
    gg = goodground.assess(field, footing_depth_m=float(p.get("footing_depth_m") or 0.45),
                           footing_width_m=float(p.get("footing_width_m") or 0.3)) if field.get("scala") else None
    ans = desk_answers(assessment, field, gg, job)
    labels = {"Geological maps available": "Geological maps available",
              "Geotechnical hazards from council": "Geotechnical hazards from council",
              "Known geotechnical hazards on the site": "Known geotechnical hazards on the site",
              "Minimum floor level and flooding": "Minimum floor level and flooding",
              "Review of historic aerial photographs": "Review of historic aerial photographs",
              "Close-proximity active faults": "Close-proximity active faults", "Subsoil class": "Subsoil class",
              "Topographical assessment": "Topographical assessment", "Buried services and structures": "Buried services and structures",
              "Anticipated engineering geological model": "Anticipated engineering geological model"}
    site = job.get("site") or {}
    fill = {lab: ans[k] for k, lab in labels.items() if ans.get(k)}
    if site.get("address"):
        fill["Project Street Address"] = site["address"] + (f" ({site['legal']})" if site.get("legal") else "")
    return fill_template(wbytes, fill)


TEMPLATE = r"""<!doctype html><html lang="en-NZ"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ rt_label }} – {{ site.address or "site" }}</title>
<link rel="stylesheet" href="/static/leaflet/leaflet.css">
<script src="/static/leaflet/leaflet.js"></script>
<style>
:root{--ink:#1d2329;--muted:#5b6670;--line:#d7dde2;--warn:#8a5a00;--warnbg:#fff6e0;--stop:#9b1c1c;--stopbg:#fdecec;--ok:#1f6b3a;--okbg:#e9f6ee;--bg:#fff;--head:#0b2a4a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#e8ecef;--muted:#a3adb5;--line:#3a434b;--warnbg:#3a2f12;--warn:#f2c46b;--stopbg:#3d1d1d;--stop:#ff9b9b;--ok:#7fd49c;--okbg:#17301f;--bg:#15191d;--head:#9cc3ff}}
*{box-sizing:border-box}body{font:14.5px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg);max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:1.45rem;margin:4px 0;color:var(--head)}h2{font-size:1.1rem;margin:30px 0 8px;padding-bottom:4px;border-bottom:2px solid var(--head);color:var(--head);break-after:avoid}
h3{font-size:1rem;margin:18px 0 6px}.meta,small{color:var(--muted)}.logos{display:flex;gap:18px;align-items:center;justify-content:flex-end}.logos img{max-height:56px}
table{border-collapse:collapse;width:100%;font-size:.88rem;margin:8px 0}th,td{border:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top}th{background:color-mix(in srgb,var(--head) 8%,transparent)}
td.k{width:34%;font-weight:600}.box{border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:12px 0}
.stop{background:var(--stopbg);border-color:var(--stop)}.warn{background:var(--warnbg);border-color:var(--warn)}.ok{background:var(--okbg);border-color:var(--ok)}
.yes{color:var(--stop);font-weight:600}.no{color:var(--ok)}.chk{color:var(--warn);font-weight:600}.edit{color:var(--muted);font-style:italic}
.src{font-size:.75rem;color:var(--muted)}.photos{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
figure{margin:0;border:1px solid var(--line);border-radius:6px;padding:8px;break-inside:avoid}figure img{width:100%;height:auto;display:block}figcaption{font-size:.85rem;margin-top:6px}
#map{height:340px;border:1px solid var(--line);border-radius:6px}.scroll{overflow-x:auto}ul.f{padding-left:18px}ul.f li{margin:4px 0}
.vd{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.vd div{border:1px solid var(--line);border-radius:6px;padding:8px}.vd b{font-size:1.4rem}
@media print{body{max-width:none;padding:0}h2{break-before:auto}.noprint{display:none}a{color:inherit}}
</style></head><body>
<div class="logos">{% for l in logos %}<img alt="Logo" src="data:image/png;base64,{{ l }}">{% endfor %}</div>
<p class="meta">{{ proj.company or "" }}{% if proj.job_no %} · Job {{ proj.job_no }}{% endif %} · Revision {{ proj.revision or "0" }} · {{ now }}</p>
<h1>{{ "Civil and Structural Engineer Initial Geotechnical Assessment Report" if include_field else rt_label }}</h1>
<p class="meta">{{ site.address or "Site" }}{% if site.legal %} · {{ site.legal }}{% endif %}{% if site.titles %} · Title {{ site.titles }}{% endif %} · {{ "%.6f"|format(site.lat) }}, {{ "%.6f"|format(site.lon) }}</p>
<p class="noprint box"><b>Draft for engineer review.</b> Every value the tool supplied is marked “tool”. Use your browser's Print → Save as PDF to file it.</p>

{% if include_field %}
<p>This report identifies soil suitability for the project below and provides justification for the engineer's assumptions where a geotechnical report by a Chartered Professional Engineer (Geotechnical) or Professional Engineering Geologist is unlikely to be required. It is not to be used for projects with geotechnical risks outside the competence of a structural engineer.</p>
{% endif %}

<h2>1. Project details</h2>
<table>
<tr><td class="k">Project street address and legal description</td><td>{{ site.address or "–" }}{% if site.legal %}; {{ site.legal }}{% endif %}{% if site.titles %} (Record of Title {{ site.titles }}){% endif %}{% if site.area_m2 %}; parcel area {{ site.area_m2 }} m²{% endif %} <span class="src">{{ site.source or "" }}</span></td></tr>
<tr><td class="k">Client</td><td>{{ proj.client or "" }}{% if not proj.client %}<span class="edit">[enter]</span>{% endif %}</td></tr>
<tr><td class="k">Project and site testing locations</td><td>Site plan in Appendix One.</td></tr>
<tr><td class="k">Revision</td><td>{{ proj.revision or "0" }}</td></tr>
<tr><td class="k">Engineering company</td><td>{{ proj.company or "" }}</td></tr>
<tr><td class="k">Prepared by</td><td>{{ proj.prepared_by or "" }}{% if proj.prepared_quals %} ({{ proj.prepared_quals }}){% endif %}{% if not proj.prepared_by %}<span class="edit">[enter]</span>{% endif %}</td></tr>
<tr><td class="k">Reviewed by</td><td>{{ proj.reviewed_by or "" }}{% if proj.reviewed_quals %} ({{ proj.reviewed_quals }}){% endif %}</td></tr>
<tr><td class="k">Date</td><td>{{ proj.date or now }}</td></tr>
<tr><td class="k">Job number</td><td>{{ proj.job_no or "" }}{% if not proj.job_no %}<span class="edit">[enter]</span>{% endif %}</td></tr>
</table>

{% if include_field or include_desk %}
<h2>2. Summary of proposed development</h2>
<table><tr><td class="k">Structure type</td><td>{{ proj.structure or "" }}</td></tr><tr><td class="k">Levels above ground</td><td>{{ proj.levels or "" }}</td></tr>
<tr><td class="k">Design life</td><td>{{ proj.design_life or "" }}</td></tr><tr><td class="k">Importance level</td><td>{{ proj.importance_level or "" }}</td></tr></table>
{% endif %}

{% if include_desk %}
<h2>3. Summary of desktop assessment</h2>
<table><tr><th>Item</th><th>Comments</th></tr>
{% for lab, _ in template_labels %}
{% set mine = engineer[lab] %}
<tr><td class="k">{{ lab }}</td><td>{% if mine %}{{ mine }} <span class="src">(engineer)</span>{% if answers[lab] %}<br>{% endif %}{% endif %}{% if answers[lab] %}{{ answers[lab] }} <span class="src">(tool)</span>{% elif not mine %}<span class="edit">[engineer to complete]</span>{% endif %}</td></tr>
{% endfor %}</table>
<p><small>Detailed desk study, seismic parameters, durability zones and sources: Appendix Three.</small></p>
<h2>4. Resources</h2>
<ul class="f"><li>NZS 3604:2011 Timber-framed buildings, Section 3</li><li>NZS 4431 Engineered fill construction for lightweight structures</li><li>NZGS Field description of soil and rock (2005)</li><li>MBIE / Engineering New Zealand Geotechnical Input Flowchart</li></ul>
{% endif %}

{% if include_field and field %}
<h2>5. Ground investigations</h2>
<h3>5.1 Ground testing</h3>
<p>{{ field.header.technician or "The technician" }} undertook the following investigations on {{ field.header.date or "[date]" }} to evaluate the subsurface conditions. Site plan and photos are in Appendix One; test data, the Scala plot and soil photos are in Appendix Two.</p>
<table><tr><th>Test type</th><th>Number</th><th>Maximum depth (m bgl)</th><th>Average depth (m bgl)</th><th>Standard</th></tr>
{% if gg %}{% set rs = gg.tests|map(attribute="reached_m")|list %}
<tr><td>Scala penetrometer (minimum 2 m below footing or justifiable refusal)</td><td>{{ rs|length }}</td><td>{{ "%.1f"|format(rs|max) }}</td><td>{{ "%.1f"|format((rs|sum)/(rs|length)) }}</td><td>NZS 3604:2011 cl. 3.3; NZS 4402 Test 6.5.2</td></tr>{% endif %}
{% if field.auger %}{% set ad = field.auger|map(attribute="max_depth_m")|list %}
<tr><td>Hand auger / test pit</td><td>{{ ad|length }}</td><td>{{ "%.1f"|format(ad|max) }}</td><td>{{ "%.1f"|format((ad|sum)/(ad|length)) }}</td><td>NZGS field description guideline</td></tr>{% endif %}
{% if field.groundwater.shear_vane_kpa %}<tr><td>Shear vane</td><td>–</td><td>–</td><td>Average {{ field.groundwater.shear_vane_kpa }} kPa</td><td>NZGS 2001</td></tr>{% endif %}
</table>
<p>Groundwater: {% if field.groundwater.depth_m %}encountered at {{ field.groundwater.depth_m }} m bgl{% else %}not encountered{% endif %} at the time of the investigation.
{% if field.technician_summary %}Technician's summary: “{{ field.technician_summary }}”{% endif %}</p>

<h3>5.2 Investigation findings</h3>
<div class="box {{ 'ok' if gg and gg.good_ground else 'stop' }}"><b>{{ gg.verdict if gg else "No Scala results found in the spreadsheet." }}</b>
{% if gg %}<br><small>Checked for footings {{ gg.footing_depth_m }} m deep and {{ gg.footing_width_m }} m wide; blow counts must {{ gg.criterion }} 5 and 3 (clause 3.3.7.1(b)).{% if gg.all_tests_meet_b_from_m %} All tests meet the blow-count criteria from {{ gg.all_tests_meet_b_from_m }} m.{% endif %}</small>{% endif %}</div>
{% if gg %}<ul class="f">{% for lvl, t in gg.findings %}<li class="{{ 'yes' if lvl == 'stop' else ('chk' if lvl == 'warn' else '') }}">{{ t }}</li>{% endfor %}</ul>{% endif %}
<table><tr><th>Item</th><th>Yes/No</th><th>Comments</th></tr>
{% for r in findings %}{% set eng = sheet_findings.get(r.item[:40]|lower) %}
<tr><td class="k">{{ r.item }}</td><td class="{{ 'yes' if r.yes == 'Yes' and r.item not in ['Hazard check','Desktop study','Ground investigations','Minimum 300 kPa ultimate bearing strength established','‘Good ground’ per NZS 3604 (latest edition)','Probable maximum settlement met under NZ Building Code'] else ('chk' if r.yes in ['Check','Not demonstrated'] else '') }}">{{ r.yes }}{% if eng and eng|lower != r.yes|lower %}<br><small>engineer entered {{ eng }}</small>{% endif %}</td><td>{{ r.comment }} <span class="src">(tool)</span></td></tr>
{% endfor %}</table>

<h2>6. Geotechnical risk assessment</h2>
<table><tr><th>Risk</th><th>Consequence</th><th>L/M/H</th><th>Proposed mitigation</th></tr>
{% for r in risks %}<tr><td>{{ r[0] }}</td><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }} <span class="src">(tool – confirm)</span></td></tr>{% else %}<tr><td colspan="4" class="edit">[Engineer to complete]</td></tr>{% endfor %}</table>

<h2>7. Recommendations</h2>
<table><tr><th>Item</th><th>Yes/No</th><th>Comments</th></tr>
{% for r in recs %}<tr><td class="k">{{ r[0] }}</td><td>{{ r[1] }}</td><td>{{ r[2] }} <span class="src">(tool – confirm)</span></td></tr>{% endfor %}
{% for x in ["Planned earthworks","Cut and fill","Building restriction zone (BRZ)","Preliminary SW design / control of surface water / groundwater","On-site wastewater design required?"] %}<tr><td class="k">{{ x }}</td><td></td><td class="edit">[engineer]</td></tr>{% endfor %}
</table>
<p><small>This report has been prepared for the client's exclusive use for the project described. It may not be relied on by others or for another purpose without written agreement.</small></p>
{% endif %}

{% if include_wind %}
<h2>{{ "8" if include_field else "4" }}. Site wind speeds (AS/NZS 1170.2:2021)</h2>
{% if wind %}{% set r = wind.result %}{% set I = r.inputs %}
<p>{{ I.limit_state }}, R = {{ I.R }} years, wind region {{ I.region }}: V<sub>R</sub> = {{ I.VR }} m/s, M<sub>c</sub> = {{ I.Mc }}, h = {{ I.h }} m, z = {{ I.z }} m.
{% if a.wind_region and a.wind_region.region and a.wind_region.region != I.region %}<b class="yes">Region used ({{ I.region }}) differs from the digitised Figure 3.1(B) result ({{ a.wind_region.region }}); confirm.</b>{% endif %}</p>
<div class="scroll"><table><tr><th>Direction</th><th>M<sub>d</sub></th><th>M<sub>z,cat</sub></th><th>M<sub>s</sub></th><th>M<sub>h</sub></th><th>M<sub>lee</sub></th><th>M<sub>t</sub></th><th>V<sub>sit,β</sub> (m/s)</th><th>Source</th></tr>
{% set vmax = r.directions|map(attribute="Vsit")|max %}
{% for x in r.directions %}<tr{% if x.Vsit == vmax %} style="font-weight:600"{% endif %}><td>{{ x.direction }}</td><td>{{ "%.2f"|format(x.Md) }}</td><td>{{ "%.2f"|format(x.Mzcat) }}</td><td>{{ "%.2f"|format(x.Ms) }}</td><td>{{ "%.2f"|format(x.Mh) }}</td><td>{{ "%.2f"|format(x.Mlee) }}</td><td>{{ "%.2f"|format(x.Mt) }}</td><td>{{ "%.1f"|format(x.Vsit) }}{% if x.Vsit_range %} <small>({{ "%.1f"|format(x.Vsit_range[0]) }}–{{ "%.1f"|format(x.Vsit_range[1]) }})</small>{% endif %}</td><td><small>terrain {{ x.source.terrain }}, topography {{ x.source.topography }}</small></td></tr>{% endfor %}</table></div>
<h3>Building design wind speeds</h3>
<div class="vd">{% for v in r.design %}<div>θ = {{ v.theta }}°<br><b>{{ "%.1f"|format(v.Vdes) }}</b> m/s<br><small>{{ "30 m/s ULS minimum" if v.min_applied else "governs at " ~ v.governing_bearing ~ "°" }}</small></div>{% endfor %}</div>
{% if r.overrides %}<p><small>Engineer changes: {% for o in r.overrides %}{{ o.direction }} {{ o.factor }}{{ "; " if not loop.last }}{% endfor %}</small></p>{% endif %}
{% if r.warnings %}<ul class="f">{% for w in r.warnings %}<li>{{ w }}</li>{% endfor %}</ul>{% endif %}
{% if a.lee_zones and a.lee_zones.status == "ok" %}<p><small>Cross-check against the digitised North Island lee zones (Figure 4.6): {% if a.lee_zones.zones %}{% for z in a.lee_zones.zones %}{{ z.zone }} {{ z.range }} ({{ z.part }}){{ "; " if not loop.last }}{% endfor %} – confirm M<sub>lee</sub> for those directions.{% else %}site is not within lee zones 1–6.{% endif %}</small></p>{% endif %}
{% if wind.summary %}<table>{% for k, v in wind.summary %}<tr><td class="k">{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}</table>{% endif %}
<p><small>Calculated {{ wind.saved }} with the site wind speed calculator; AS/NZS 1170 data v{{ r.data_version }}.</small></p>
{% else %}<p class="box warn">No wind calculation saved for this job. Open the wind calculator from the menu, calculate, then press <b>Save to report</b>.</p>{% endif %}
{% endif %}

{% if include_field %}
<h2>Appendix One – Site plan and site photos</h2>
<div id="map"></div><p><small>Site marker and parcel boundary (LINZ). Mark the test locations on the site plan before issue.</small></p>
{% set site_ph = photos|rejectattr("kind", "in", ["auger","scala"])|list %}
{% if photo_notes %}<ul class="f">{% for n in photo_notes %}<li class="chk">{{ n }}</li>{% endfor %}</ul>{% endif %}
<div class="photos">{% for p in site_ph %}<figure><img alt="{{ p.caption or p.name }}" src="data:image/jpeg;base64,{{ p.b64 }}"><figcaption><b>Photo {{ loop.index }}.</b> {{ p.caption or "[caption: view, slope of ground and direction]" }}<br><small>{{ p.taken or "" }}{% if p.facing %} · facing {{ p.facing }}{% endif %}{% if p.distance_from_site_m is defined %} · {{ p.distance_from_site_m }} m from site marker{% endif %}</small></figcaption></figure>{% else %}<p class="edit">[No site photos uploaded]</p>{% endfor %}</div>

<h2>Appendix Two – Scala penetrometer and hand auger results</h2>
<p class="meta">Date {{ field.header.date or "" }} · Completed by {{ field.header.technician or "" }}</p>
{{ svg|safe }}
<p><small>Dashed green lines: 3 and 5 blows per 100 mm. Darker shading: more than 5 blows needed (footing level to twice the footing width below); lighter shading: more than 3 blows needed (to 2 m below the footing); NZS 3604 clause 3.3.7.1(b).</small></p>
{% if gg %}<div class="scroll"><table><tr><th>Test</th><th>Reached (m)</th><th>Required (m)</th><th>Final blows</th><th>Below 5 blows in footing zone</th><th>Criteria first met from</th><th>Result</th></tr>
{% for s in gg.tests %}<tr><td>{{ s.test }}</td><td>{{ s.reached_m }}</td><td>{{ s.required_m }}</td><td>{{ s.final_blows|int }}{{ " (refusal)" if s.refusal else "" }}</td><td>{{ s.fails_txt or "none" }}{% if s.zone5.averaged %}<br><small>averaged at {{ s.zone5.averaged|join(", ") }} m</small>{% endif %}</td><td>{{ (s.first_depth_meeting_b_m ~ " m") if s.first_depth_meeting_b_m else "not within depth tested" }}</td><td class="{{ 'no' if s.status == 'pass' else 'yes' }}">{{ s.status }}</td></tr>{% endfor %}</table></div>{% endif %}
<div class="scroll"><table><tr><th>Depth (m)</th>{% for t in field.scala %}<th>Scala {{ t.test }}</th>{% endfor %}{% for t in field.auger %}<th>Auger {{ t.test }} (NZGS description)</th>{% endfor %}</tr>
{% for d, sv, av in grid %}<tr><td>{{ "%.1f"|format(d) }}</td>{% for v in sv %}<td>{{ v }}</td>{% endfor %}{% for v in av %}<td>{{ v }}</td>{% endfor %}</tr>{% endfor %}
</table></div>
{% if field.issues %}<h3>Spreadsheet checks</h3><ul class="f">{% for i in field.issues %}<li class="chk">{{ i }}</li>{% endfor %}</ul>{% endif %}
{% set soil_ph = photos|selectattr("kind", "in", ["auger","scala"])|list %}
{% if soil_ph %}<h3>Hand auger and Scala photos</h3><div class="photos">{% for p in soil_ph %}<figure><img alt="{{ p.caption or p.name }}" src="data:image/jpeg;base64,{{ p.b64 }}"><figcaption>{{ p.caption or "[caption: test number and depth]" }}<br><small>{{ p.taken or "" }}</small></figcaption></figure>{% endfor %}</div>{% endif %}
{% if field.checklist %}<h3>Technician field checklist</h3><table><tr><th>No.</th><th>Prompt</th><th>Answer</th><th>Notes</th></tr>{% for c in field.checklist %}<tr><td>{{ c.no }}</td><td>{{ c.prompt }}</td><td>{{ c.answer }}</td><td>{{ c.notes }}</td></tr>{% endfor %}</table>{% endif %}
{% endif %}

{% if desk_html %}
<h2>Appendix {{ "Three" if include_field else "One" }} – Desk study detail</h2>
<div class="desk">{{ desk_html|safe }}</div>
{% endif %}
<p><small>Prepared with NZ Site Hazards {{ version }}. Regional data cannot characterise a specific site; all tool values are for engineer confirmation.</small></p>
{% if include_field %}
<script>
(function(){try{var m=L.map('map',{scrollWheelZoom:false}).setView([{{ site.lat }},{{ site.lon }}],19);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:20,maxNativeZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(m);
L.marker([{{ site.lat }},{{ site.lon }}]).addTo(m);
{% if site.parcel %}var p=L.polygon({{ site.parcel|tojson }}.map(function(c){return [c[1],c[0]]}),{color:'#d1495b',weight:2,fill:false}).addTo(m);m.fitBounds(p.getBounds(),{padding:[20,20]});{% endif %}
}catch(e){document.getElementById('map').textContent='Map not available offline.';}})();
</script>{% endif %}
</body></html>"""
