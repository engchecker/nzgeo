"""Client-facing geotechnical report  .

One content model is built from the job, the desk study and the field data, then rendered two ways:
  * Word (.docx) from an optional house-style template (NZGEO_DOCX_TEMPLATE), otherwise python-docx defaults
  * HTML for the in-browser preview, styled to match
Text the engineer must supply or confirm is written as ⟦…⟧ and shown highlighted yellow in both outputs.
"""
from __future__ import annotations

import base64
import os
import html as _html
import io
import re
from datetime import date, datetime
from pathlib import Path

from . import goodground, jobs
from .fieldsheet import read_workbook

TEMPLATE = Path(os.environ["NZGEO_DOCX_TEMPLATE"]) if os.environ.get("NZGEO_DOCX_TEMPLATE") else None  # optional house-style .docx
LOGO = Path(os.environ["NZGEO_LOGO"]) if os.environ.get("NZGEO_LOGO") else None  # optional logo image
NAVY, HEADFILL = "003164", "A2BADC"
PH = re.compile(r"⟦(.*?)⟧")
TITLES = {"desk": "GEOTECHNICAL DESK STUDY", "iga": "INITIAL GEOTECHNICAL ASSESSMENT",
          "combined": "INITIAL GEOTECHNICAL ASSESSMENT", "wind": "SITE WIND SPEED ASSESSMENT"}


# ---------------------------------------------------------------- small text helpers
def ph(text: str) -> str:
    return f"⟦{text}⟧"


def m(v, nd=1) -> str:
    return f"{v:.{nd}f} m"


def rng(a, b, unit="m", nd=1) -> str:
    return f"{a:.{nd}f} {unit}" if abs(a - b) < 10 ** -nd / 2 else f"{a:.{nd}f}–{b:.{nd}f} {unit}"


def nice_date(s) -> str:
    if not s:
        return ph("date")
    try:
        d = s if isinstance(s, (date, datetime)) else datetime.fromisoformat(str(s)[:10])
        return f"{d.day} {d.strftime('%B %Y')}"
    except ValueError:
        return str(s)


def km(v) -> str:
    return f"{v / 1000:.1f} km" if v >= 1000 else f"{v:.0f} m"


def words(n: int) -> str:
    return ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"][n] if 0 <= n <= 10 else str(n)


def join_and(items):
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def compass_word(c: str | None) -> str:
    names = {"N": "north", "NE": "north-east", "E": "east", "SE": "south-east", "S": "south", "SW": "south-west",
             "W": "west", "NW": "north-west", "NNE": "north-north-east", "ENE": "east-north-east", "ESE": "east-south-east",
             "SSE": "south-south-east", "SSW": "south-south-west", "WSW": "west-south-west", "WNW": "west-north-west",
             "NNW": "north-north-west"}
    return names.get((c or "").upper(), (c or "").lower())


def address_parts(addr: str | None):
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    street = re.sub(r"^[\d/A-Za-z-]*\d[\dA-Za-z]*\s+", "", parts[0]) if parts else ""
    return {"full": addr or "", "first": parts[0] if parts else "", "street": street,
            "suburb": parts[1] if len(parts) > 1 else "", "city": parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")}


def _hits(a, kind):
    return [f for f in ((a or {}).get("council") or {}).get("findings", []) or [] if kind in f.get("hazards", [])]


# ---------------------------------------------------------------- field interpretation
def auger_story(auger: list) -> tuple[str | None, float | None]:
    """'moist organic topsoil near surface, moist clay from approximately 0.2–0.3 m and dry clay at approximately 0.3–1.0 m'"""
    if not auger:
        return None, None
    t = auger[0]
    groups = []
    for L in t["layers"]:
        f = L["fields"]
        cond = (f.get("condition") or "").lower()
        mat = (f.get("material") or L["description"]).lower()
        size = (f.get("size") or "").lower()
        if size in ("medium",):
            size = ""
        withs = (f.get("with") or "").lower()
        label = " ".join(x for x in (cond, size, mat) if x) + (f" with {withs}" if withs else "")
        if groups and groups[-1][0] == label:
            groups[-1][2] = L["depth_m"] + 0.1
        else:
            groups.append([label, L["depth_m"], L["depth_m"] + 0.1])
    bits = []
    for i, (label, a, b) in enumerate(groups):
        if i == 0 and a == 0:
            bits.append(f"{label} near surface" if b <= 0.3 else f"{label} from the surface to approximately {m(b)}")
        else:
            bits.append(f"{label} from approximately {rng(a, b)}")
    return join_and(bits), t["max_depth_m"]


def scala_story(field: dict, gg: dict | None) -> list[str]:
    tests = [t for t in field.get("scala", []) if t["readings"]]
    if not tests:
        return []
    out = []
    first5 = {}
    means = {}
    for t in tests:
        vals = [(r["depth_m"], r["blows"]) for r in t["readings"] if r["blows"] is not None]
        means[t["test"]] = sum(v for _, v in vals) / len(vals)
        run = None
        for i, (d, v) in enumerate(vals):
            if v >= 5 and all(x >= 3 for _, x in vals[i:i + 3]):
                run = d
                break
        first5[t["test"]] = run
    weak_top = [d for d in first5.values() if d is not None]
    upper = max(weak_top) if weak_top else None
    lowest_upper = min(weak_top) if weak_top else None
    if upper is not None:
        out.append(f"Penetration resistance is relatively low in the upper approximately "
                   f"{rng(lowest_upper, upper)} and increases with depth"
                   + (f" in Tests {join_and([t for t, d in first5.items() if d is not None])}" if None in first5.values() else "")
                   + ".")
    weakest = min(means, key=means.get)
    if len(tests) > 2 and means[weakest] < 0.7 * (sum(means.values()) - means[weakest]) / (len(means) - 1):
        out.append(f"Test {weakest} is weaker across much of the investigated depth, indicating local variability.")
    if gg:
        ref = [s for s in gg["tests"] if s["refusal"]]
        if ref:
            depths = [s["reached_m"] for s in ref]
            blows = [int(s["final_blows"]) for s in ref]
            n = len(ref)
            out.append(f"{'All ' + words(n) if n == len(gg['tests']) else words(n).capitalize() + ' of the'} tests met refusal at "
                       f"approximately {rng(min(depths), max(depths))} ({rng(min(blows), max(blows), 'blows', 0)} per 100 mm), "
                       f"short of the {gg['footing_depth_m'] + 2.0:.1f} m depth required by NZS 3604 clause 3.3.4. "
                       "Refusal does not alone establish competent rock; the obstruction has not been identified.")
    return out


# ---------------------------------------------------------------- content model
class Doc:
    def __init__(self):
        self.blocks = []
        self.fig = {"A": 0, "B": 0, "C": 0, "": 0}
        self.tab = 0

    def add(self, t, **kw):
        self.blocks.append({"t": t, **kw})

    def h1(self, text): self.add("h1", text=text)
    def h2(self, text): self.add("h2", text=text)
    def p(self, text): self.add("p", text=text)

    def table(self, header, rows, widths, caption=None):
        self.add("table", header=header, rows=rows, widths=widths, caption=caption)

    def figure(self, png: bytes, caption: str, width_in=5.8, kind="png"):
        self.add("figure", data=png, caption=caption, width_in=width_in, kind=kind)


def build(job: dict, assessment: dict | None) -> Doc:
    rt = job.get("report_type", "iga")
    a = assessment or {}
    site = job.get("site") or {}
    proj = dict(job.get("project") or {})
    addr = address_parts(site.get("address"))
    field, gg = None, None
    wb = jobs.workbook_bytes(job)
    if wb:
        field = read_workbook(wb, job["workbook"]["name"])
        fi = job.get("field_inputs") or {}
        if field.get("scala"):
            gg = goodground.assess(field, footing_depth_m=float(fi.get("footing_depth_m") or 0.45),
                                   footing_width_m=float(fi.get("footing_width_m") or 0.3),
                                   floor_area_m2=float(fi["floor_area_m2"]) if fi.get("floor_area_m2") else None,
                                   strict=fi.get("criterion", "exceeds") != "at_least",
                                   rock_at_refusal=bool(fi.get("rock_at_refusal")))
    has_field = bool(field and (field.get("scala") or field.get("auger"))) and rt in ("iga", "combined")
    excav = bool(proj.get("excavation"))
    retaining = bool(proj.get("retaining"))
    job_no = proj.get("job_no") or ph("job no.")
    rdate = nice_date(proj.get("date") or date.today())
    status = (proj.get("status") or "Draft").upper() + " REPORT"
    name = proj.get("project_name") or ""
    refs = References()
    d = Doc()

    if rt == "wind":
        return _wind_only(job, refs, d, name, job_no, rdate, status)

    # ---- cover
    d.add("logo")
    d.add("title", text=TITLES.get(rt, "GEOTECHNICAL ASSESSMENT"))
    d.add("center", text="  |  ".join(x for x in (name, site.get("address") or ph("address")) if x))
    d.add("center", text=f"{proj.get('company') or ''}  |  Job {job_no}  |  {rdate}")
    d.add("subtitle", text=status)
    auth = proj.get("authorisation") or (f"{proj['reviewed_by']} – {proj['reviewed_quals']}" if proj.get("reviewed_by") and proj.get("reviewed_quals")
                                         else ph("name – CPEng number"))
    d.table(["Document detail", "Information"], [
        ["Project", proj.get("structure_desc") or proj.get("structure") or ph("project, e.g. New two storey dwelling")],
        ["Client", proj.get("client") or ph("client")],
        ["Project reference", job_no],
        ["Report date", rdate],
        ["Address", site.get("address") or ph("address")],
        ["Legal description", site.get("legal") or ph("legal description")],
        ["Prepared by", proj.get("company") or "Your company"],
        ["Professional authorisation", auth]], [0.5, 0.5])
    d.add("toc")
    d.add("pagebreak")

    # ---- gather the findings used in several places
    fd = gg["footing_depth_m"] if gg else None
    fill_seen = bool(field) and any(it["answer"] == "Y" and re.search(r"signs of fill|pushover fill", it["prompt"], re.I)
                                    for it in field.get("checklist", []))
    refusal = [s for s in gg["tests"] if s["refusal"]] if gg else []
    good = bool(gg and gg["good_ground"])
    pos = proj.get("bearing_position") or "tested"
    verify = has_field and not good and pos == "verify_after_excavation"
    specific = has_field and not good and pos == "specific_design"
    sub_class = proj.get("subsoil_class")
    sub_txt = f"Class {sub_class}" if sub_class else ph("Class C – engineer to confirm")
    council_ok = (a.get("council") or {}).get("status") == "ok" or bool((a.get("council") or {}).get("councils"))
    fault = (a.get("faults") or {}) if (a.get("faults") or {}).get("status") == "ok" else None
    nf = (fault or {}).get("nearest") or {}

    # ---- executive summary
    d.h1("Executive summary")
    es = []
    if rt == "desk" or not has_field:
        es.append("This desk study summarises published geological, seismic and natural hazard information for the site. "
                  "No site-specific ground investigation has been undertaken, and the findings shall be confirmed by "
                  "investigation before foundation design.")
    elif verify:
        es.append("The proposed development will result in an excavation. That excavation is expected to remove weaker "
                  "near-surface soil and expose competent natural ground. A minimum ultimate bearing resistance of 300 kPa is "
                  "expected at the cleared founding level and may be used as the structural design assumption, subject to "
                  "engineer inspection and testing after bulk excavation and before foundation construction.")
    elif specific:
        es.append("The site testing has not demonstrated ‘good ground’ as defined in NZS 3604:2011. Foundations shall be "
                  "specifically designed by the engineer for the ground conditions encountered, and NZS 3604 foundations shall "
                  "not be assumed.")
    elif good:
        es.append(f"Scala penetrometer testing indicates ground meeting the NZS 3604:2011 definition of good ground below "
                  f"approximately {m(fd, 2)}. A minimum ultimate bearing resistance of 300 kPa may be adopted as the structural "
                  "design assumption, subject to engineer inspection of the foundation excavations before concrete is placed.")
    else:
        why = []
        if refusal:
            why.append(f"the Scala penetrometer tests met refusal at approximately "
                       f"{rng(min(s['reached_m'] for s in refusal), max(s['reached_m'] for s in refusal))} on an unidentified obstruction")
        if gg and any(s["zone5"]["fails"] for s in gg["tests"]):
            why.append("penetration resistance below the founding level is lower than the NZS 3604 criteria in places")
        if fill_seen:
            why.append("signs of fill were observed")
        es.append("The site testing has not demonstrated ‘good ground’ as defined in NZS 3604:2011"
                  + (": " + join_and(why) if why else "") + ". "
                  "Further investigation is required before the foundations can be designed, and a bearing resistance of "
                  "300 kPa shall not be assumed until it has been verified.")
    es.append(f"Seismic subsoil {sub_txt} is adopted for initial structural design.")
    risk = ("temporary excavation stability" if excav else
            "the unidentified obstruction and possible fill below the building area" if (refusal or fill_seen) else None)
    if risk:
        es.append(f"The main construction risk is {risk}.")
    d.p(" ".join(es))

    # ---- 1 Introduction
    d.h1("1. Introduction")
    d.h2("1.1 Project and scope")
    dev = proj.get("development") or ph("describe the proposed development, e.g. a new single storey timber-framed dwelling on concrete foundations")
    s1 = f"The proposed development comprises {dev.rstrip('.')}."
    if site.get("legal"):
        s1 += f" The property is identified as {site['legal']}."
    d.p(s1)
    if has_field:
        inv = []
        na, ns = len(field.get("auger", [])), len(field.get("scala", []))
        if na:
            inv.append(f"{'a' if na == 1 else words(na)} hand auger{'s' if na > 1 else ''}")
        if ns:
            inv.append(f"{words(ns)} Scala penetrometer test{'s' if ns > 1 else ''}")
        scope = f"This initial geotechnical assessment includes desktop review, site observations, {join_and(inv)} to inform the foundations"
    else:
        scope = "This desk study includes a review of published geological, seismic and natural hazard information to inform the foundations"
    scope += (", earthworks and retaining walls." if (excav or retaining) else ".")
    life = proj.get("design_life") or ph("50 years")
    il = proj.get("importance_level") or ph("IL2")
    scope += f" The design working life is {life} and importance level is {il}."
    if proj.get("documents"):
        scope += f" The report considers {proj['documents'].rstrip('.')}."
    d.p(scope)

    # ---- 2 Site description
    d.h1("2. Site description and topography")
    loc = f"The site lies in {addr['suburb'] + ', ' if addr['suburb'] else ''}{addr['city'] or ph('town')}"
    loc += f", accessed from {addr['street']}." if addr["street"] else "."
    terr = a.get("terrain") or {}
    from .topo_site import sentence as topo_sentence
    from .services import sentence as services_sentence
    tp = a.get("topography") or {}
    ts = topo_sentence(tp)
    fig_no = [0]
    def body_fig(png, cap, w=5.6):
        fig_no[0] += 1
        d.figure(png, f"Figure {fig_no[0]}. {cap}", w)
    if ts:
        rl = refs.add("lidar", "Toitū Te Whenua Land Information New Zealand, NZ elevation: 1 m LiDAR digital elevation model "
                      "(NZVD2016), CC BY 4.0. https://registry.opendata.aws/nz-elevation/")
        loc += " " + ts.replace("LiDAR survey data", f"LiDAR survey data [{rl}]", 1)
    elif terr.get("slope_max_deg") is not None:
        loc += f" LiDAR survey data indicates ground slopes of up to approximately {terr['slope_max_deg']:.0f}° across the site."
    if proj.get("site_notes"):
        loc += " " + proj["site_notes"].strip().rstrip(".") + "."
    d.p(loc)
    if tp.get("status") == "ok" and tp.get("figure_png"):
        body_fig(tp["figure_png"], "Ground slope and contours from the LINZ 1 m LiDAR elevation model (NZVD2016). "
                 "Property boundary in blue; site circled in red.", 4.8)
    svs = services_sentence(a.get("services"))
    if svs:
        d.p(svs + " Services shall be located before excavation and the BeforeUDig service plans obtained.")
    if field and field.get("checklist"):
        obs, notes = [], []
        ck = {i["prompt"].lower(): i for i in field["checklist"]}
        def ans(rx):
            return next((i for k, i in ck.items() if re.search(rx, k)), None)
        neg = [("ponding or flowing water", ans(r"wet areas")), ("retaining walls", ans(r"retaining walls")),
               ("surface features suggesting instability", ans(r"instability")),
               ("signs of subsidence in the ground or nearby foundations", ans(r"subsidence"))]
        absent = [t for t, i in neg if i and i["answer"] == "N"]
        present = [(t, i) for t, i in neg if i and i["answer"] == "Y"]
        if absent:
            obs.append(f"No {join_and(absent)} were observed during the site investigation.")
        for t, i in present:
            obs.append(f"{t[0].upper() + t[1:]} were noted during the site investigation{': ' + i['notes'] if i['notes'] else ''}.")
        if fill_seen:
            obs.append("Signs of fill were noted. These observations do not establish the extent or depth of any fill, "
                       "which shall be confirmed before foundation design.")
        if obs:
            d.p(" ".join(obs))
    if excav:
        d.p("The structural drawings shall establish the permanent excavation geometry, wall positions, cut depths and "
            "boundary setbacks. Where works cross a legal boundary, permission from the affected neighbouring owner and any "
            "necessary approvals shall be obtained before work begins. Where permission is not obtained, temporary shoring or "
            "revised construction sequencing shall retain the excavation within the site.")
        d.p("The contractor’s methodology shall address temporary excavation support, stormwater diversion, rainfall "
            "protection, construction sequencing and protection of adjoining land and services.")

    # ---- 2.1 Site history and contaminated land
    from .history import aerial_summary, aerial_sentence, hail_sentence
    plans_ = [x for x in job.get("photos", []) if x.get("include", True) and x.get("kind") == "plan"]
    photos_ = [x for x in job.get("photos", []) if x.get("include", True) and x.get("kind") != "plan"]
    letters = iter("ABCDEFG")
    apx = {"layout": next(letters)}
    if has_field and field.get("scala"):
        apx["scala"] = next(letters)
    if photos_:
        apx["photos"] = next(letters)
    aer = aerial_summary(a)
    if aer["ok"] and aer["images"]:
        apx["aerials"] = next(letters)
    hist_txt = []
    if aer["ok"]:
        t = None
        if not aer["download_failed"]:
            ri = refs.add("imagery", "Toitū Te Whenua Land Information New Zealand, NZ Imagery: historic (Crown Aerial Film Archive) and "
                          "current orthorectified aerial photography, CC BY 4.0. https://registry.opendata.aws/nz-imagery/")
            rr = refs.add("retrolens", "Retrolens – historical image resource (LINZ Crown Aerial Film Archive). https://retrolens.co.nz")
            t = aerial_sentence(a, ri, rr, apx.get("aerials", "D"))
        if aer["download_failed"]:
            yrs = sorted({x["year"] for x in aer["surveys"]})
            hist_txt.append(ph(f"LINZ holds aerial photographs of the site from {yrs[0]} to {yrs[-1]}, but they could not be downloaded "
                               "– check the internet connection and create the report again"))
        elif t:
            hist_txt.append(t)
            hist_txt.append(ph("Describe what the photographs show, e.g. earlier buildings, earthworks, filling, drainage changes or vegetation clearance"))
    else:
        hist_txt.append(ph("Historic aerial photographs could not be retrieved; review Retrolens and describe the site history"))
    hl = a.get("hail") or {}
    rh = None
    if hl.get("status") == "ok":
        rh = refs.add("hail", f"{hl.get('council')}, {hl.get('register')}, accessed {nice_date(date.today())}.")
    hs, hlevel = hail_sentence(a, rh)
    if hs:
        hist_txt.append(hs)
    elif hlevel == "not_published":
        hist_txt.append(ph(f"{hl.get('council') or 'The regional council'} does not publish its {hl.get('register')} online – "
                           "record the result of the property search"))
    else:
        hist_txt.append(ph("Record the regional council contaminated land (HAIL) register search result"))
    d.h2("2.1 Site history and contaminated land")
    d.p(" ".join(hist_txt))

    # ---- 3 Geology
    d.h1("3. Geology and ground model")
    g = a.get("geology") or {}
    gtxt = []
    if g.get("status") == "ok":
        r1 = refs.add("geology", "Heron, D.W. (custodian) (2023). Geological Map of New Zealand 1:250,000, 4th edition (QMAP). "
                      "GNS Science / Earth Sciences New Zealand. https://doi.org/10.21420/5XTJ-5718")
        unit = g.get("unit_name") or g.get("description")
        desc = g.get("description") if g.get("unit_name") else None
        gtxt.append(f"Published geological mapping [{r1}] indicates {('the ' + unit) if unit else 'a regional geological unit'}"
                    + (f" ({g['unit_code']})" if g.get("unit_code") else "")
                    + (f", described as {desc.rstrip('.').lower()}" if desc else "")
                    + (f", of {g['age']} age" if g.get("age") else "") + ".")
        if g.get("flag_near_boundary"):
            gtxt.append(f"A mapped geological boundary lies approximately {km(g['boundary_distance_m'])} to the "
                        f"{compass_word(g.get('boundary_direction'))}; at the map scale either unit may be present at the site.")
        from .profile import geology_text
        rich = geology_text(a)
        if rich and (g.get("main_rock") or (g.get("attributes") or {})):
            extra = rich.split(";", 1)[1].strip() if ";" in rich else ""
            if extra:
                gtxt.append(f"The main rock type is {extra.replace('main rock type ', '').rstrip('.')}.")
    else:
        gtxt.append("Published geological mapping " + ph("describe the mapped geology and reference the map") + ".")
    gm = a.get("geomap") or {}
    if gm.get("status") == "ok":
        others = [u for u in gm.get("units", []) if (u.get("unit_name") or u.get("description")) not in (g.get("unit_name"), g.get("description"))]
        if others:
            names = [str(u.get("unit_name") or u.get("description")) for u in others[:4]]
            gtxt.append(f"Other units mapped within about {gm['width_km'] / 2:.0f} km of the site include {join_and(names)}.")
    story, adepth = auger_story(field.get("auger", []) if field else [])
    if has_field and story:
        model = f"The anticipated site model is {story}"
        model += f" (the hand auger terminated at approximately {m(adepth)})." if adepth else "."
        if refusal:
            model += " The material causing Scala refusal has not been identified, and the depth to rock is unconfirmed."
        gtxt.append(model)
    d.p(" ".join(gtxt))
    if gm.get("status") == "ok":
        rf = refs.add("faults", "GNS Science / Earth Sciences New Zealand, New Zealand Active Faults Database. https://data.gns.cri.nz/af/")
        body_fig(gm["png"], f"Geological map extract, about {gm['width_km']:g} km wide, from the Geological Map of New Zealand "
                 f"1:250,000 (QMAP), with active fault traces from the New Zealand Active Faults Database [{rf}]. Site circled in red.", 6.0)
    if has_field:
        from .profile import subsoil_profile
        prof = subsoil_profile(field)
        if prof:
            d.table(["Soil type", "Depth (m)", "Consistency", "Scala (blows/100 mm)"],
                    [[r["soil"], f"{r['from']:.1f} – {r['to']:.1f}", r["consistency"] or "–", r["scala"] or "–"] for r in prof],
                    [0.42, 0.18, 0.18, 0.22], caption="Table 1. Geotechnical model subsoil profile from the hand auger and Scala tests.")
    if has_field:
        if verify:
            d.p("The proposed bulk excavation is expected to remove the weaker surface soil and expose competent founding "
                "material providing at least 300 kPa ultimate bearing resistance. The structural engineer may adopt 300 kPa for "
                "design, but the value shall be verified by inspection and appropriate testing of the exposed founding surfaces "
                "following excavation, before foundation construction. Local unsuitable material shall be removed and remediated "
                "as directed by the engineer.")
        elif good:
            d.p(f"The natural ground below approximately {m(fd, 2)} is expected to provide at least 300 kPa ultimate bearing "
                "resistance. The structural engineer may adopt 300 kPa for design, but the value shall be verified by inspection "
                "of the foundation excavations before foundation construction. Local unsuitable material shall be removed and "
                "remediated as directed by the engineer.")
        else:
            d.p("A bearing resistance of 300 kPa has not been demonstrated by the testing. The founding stratum, its depth "
                "and its bearing resistance shall be confirmed by further investigation before foundation design.")
    d.h2("3.1 Seismic subsoil classification")
    seis = [f"Subsoil {sub_txt} to NZS 1170.5 is adopted for initial structural design."]
    z = a.get("nzs1170_5") or {}
    if z.get("status") == "ok":
        refs.add("nzs1170_5", "Standards New Zealand, NZS 1170.5:2004 Structural design actions – Part 5: Earthquake actions, "
                 "as modified by MBIE Acceptable Solution and Verification Method B1/VM1.")
        seis.append(f"The hazard factor Z for the site is {z['Z']:.2f}.")
        if (z.get("near_fault") or {}).get("applies"):
            seis.append(f"The site is within {z['near_fault']['D_km']} km of a fault listed in Table 3.6 of NZS 1170.5, "
                        "so near-fault effects shall be included for annual probabilities of exceedance below 1/250.")
    if not sub_class:
        sc = a.get("site_class") or {}
        from .profile import subsoil_class_evidence
        ev = subsoil_class_evidence(a, field, gg)
        if ev:
            seis.append(ph("Engineer to confirm the class. Indicators: " + ev))
        elif sc.get("vs30"):
            seis.append(ph(f"Engineer to confirm. Regional Vs30 model suggests about {sc['vs30']} m/s; "
                           "Scala refusal depth and local geology should inform the class."))
    d.p(" ".join(seis))

    # ---- 4 Site investigation
    if has_field:
        d.h1("4. Site investigation and test results")
        h = field.get("header") or {}
        tech = h.get("technician") or ph("technician")
        work = []
        if field.get("auger"):
            ad = [t["max_depth_m"] for t in field["auger"]]
            work.append(f"{'one hand auger' if len(ad) == 1 else words(len(ad)) + ' hand augers'} to approximately {rng(min(ad), max(ad))}")
        if gg:
            rs = [s["reached_m"] for s in gg["tests"]]
            work.append(f"{words(len(rs))} Scala penetrometer test{'s' if len(rs) > 1 else ''} to approximately {rng(min(rs), max(rs))}")
        p4 = f"{tech} (soil technician) undertook the soil testing on {nice_date(h.get('date'))}. The work comprised {join_and(work)}."
        if story:
            p4 += f" The hand auger described {story}"
            summ = (field.get("technician_summary") or "").lower()
            p4 += ("; augering was reportedly obstructed." if re.search(r"block|obstruct|refus|couldn|could not|hard", summ) else ".")
        p4 += " The full Scala data table and penetration-resistance plot are provided in Appendix B."
        d.p(p4)
        sc_lines = scala_story(field, gg)
        if gg:
            if good:
                sc_lines.append(f"Below approximately {m(fd, 2)}, every test exceeds the NZS 3604:2011 clause 3.3.7 criteria "
                                "of more than five blows per 100 mm to twice the footing width and more than three blows per "
                                "100 mm below that.")
            elif verify:
                sc_lines = [x for x in sc_lines if not x.startswith(("All ", "One ", "Two ", "Three ", "Four ", "Five "))]
                sc_lines.append("The proposed excavation is expected to remove weaker shallow soil, subject to the required "
                                "post-excavation verification.")
            else:
                sc_lines.append(f"For footings founded at approximately {m(fd, 2)}, the results do not meet the NZS 3604:2011 "
                                "clause 3.3.7 criteria for good ground.")
            if len(gg["tests"]) < gg["min_tests"] and not verify:
                sc_lines.append(f"NZS 3604 requires at least {gg['min_tests']} test sites for the building footprint; "
                                f"{words(len(gg['tests']))} were undertaken.")
        if sc_lines:
            d.p(" ".join(sc_lines))
        d.h2("4.1 Groundwater and surface-water control")
        gw = (field.get("groundwater") or {}).get("depth_m")
        clay = any(re.search(r"clay", L["description"], re.I) for t in field.get("auger", []) for L in t["layers"])
        g41 = (f"Groundwater was encountered at approximately {m(gw)} below ground level." if gw else
               "No groundwater or seepage was recorded.")
        if clay:
            g41 += (" The predominantly clay soils are expected to have low permeability; significant groundwater inflow is not "
                    "anticipated, although local seepage remains possible.")
        g41 += " Surface water is a greater construction concern: rainfall and runoff may soften "
        g41 += "and erode exposed clay. " if clay else "exposed ground. "
        g41 += "The contractor shall divert runoff, prevent ponding and protect exposed ground"
        g41 += (", and communicate these requirements in the excavation methodology." if excav else ".")
        d.p(g41)

    # ---- 5 Hazards
    sec = 5 if has_field else 4
    d.h1(f"{sec}. Geotechnical hazards")
    rows = []
    if excav:
        rows.append(["Temporary cut instability", "Principal construction risk; temporary works and rainfall protection required."])
    if has_field:
        rows.append(["Surface water", "Rainfall runoff can soften clay and undermine excavations; divert and protect."])
        if verify:
            rows.append(["Settlement", "Low after weaker soils are removed and 300 kPa founding is verified."])
        elif good:
            rows.append(["Settlement", "Low where foundations bear on the verified natural ground."])
        else:
            rows.append(["Settlement", "Not yet assessed: good ground has not been demonstrated" + (" and fill may be present" if fill_seen else "") + "."])
    if fill_seen:
        rows.append(["Uncontrolled fill", "Signs of fill observed; extent and depth to be established. Fill is not suitable founding material unless certified under NZS 4431."])
    liq = _hits(a, "liquefaction")
    if liq:
        inside = [h for h in liq if h["relation"] == "site inside"]
        rows.append(["Liquefaction / lateral spreading", ("Council mapping identifies " + _hit_short(inside[0]) if inside else
                                                          "Council mapping identifies nearby areas; the site itself is outside them") + "."])
    elif council_ok:
        rows.append(["Liquefaction / lateral spreading", "Low anticipated susceptibility" +
                     (" under the clay profile encountered" if has_field else "") + "; not identified in council hazard mapping."])
    else:
        rows.append(["Liquefaction / lateral spreading", ph("council liquefaction mapping not checked – assess")])
    clay = has_field and any(re.search(r"clay", L["description"], re.I) for t in field.get("auger", []) for L in t["layers"])
    ex = _hits(a, "expansive")
    rows.append(["Expansive soils", "Clay soils encountered; expansivity shall be assessed in accordance with NZS 3604 / B1 before foundation design."
                 if clay else ("Council mapping identifies expansive soils." if ex else "Not identified.")])
    sl = _hits(a, "slope") + _hits(a, "rockfall")
    lsl = ((a.get("landslides") or {}).get("features") or [])
    if any(h["relation"] == "site inside" for h in sl):
        rows.append(["Natural slope instability", "Council mapping identifies a slope hazard at the site; specialist assessment required."])
    elif sl or lsl:
        rows.append(["Natural slope instability", f"Mapped landslide or slope hazard features nearby ({_nearest_txt(sl, lsl)}); none observed on site."])
    elif council_ok:
        rows.append(["Natural slope instability", "Low on available mapping and site observations."])
    else:
        rows.append(["Natural slope instability", ph("council slope hazard mapping not checked – assess")])
    fl = _hits(a, "flood")
    rows.append(["Flooding", ("Council flood mapping identifies " + _hit_short([h for h in fl if h['relation'] == 'site inside'][0]) + "."
                              if any(h["relation"] == "site inside" for h in fl) else
                              "Not identified in council flood mapping." if council_ok else ph("council flood mapping not checked – assess"))])
    for kind, label in (("tsunami", "Tsunami"), ("coastal", "Coastal inundation and erosion")):
        hk = [h for h in _hits(a, kind) if h["relation"] == "site inside"]
        if hk:
            rows.append([label, "Council mapping identifies " + _hit_short(hk[0]) + "."])
    if hlevel == "on_site":
        rows.append(["Contaminated land (HAIL)", "Site recorded on the regional register; NESCS may apply to soil disturbance. "
                     "Preliminary site investigation recommended."])
    elif hlevel in ("nearby", "clear"):
        rows.append(["Contaminated land (HAIL)", "Not recorded on the regional register" +
                     (f"; nearest listed site approximately {hl['nearby'][0]['distance_m']} m away." if hlevel == "nearby" else ".")])
    else:
        rows.append(["Contaminated land (HAIL)", ph("register search result")])
    if retaining:
        rows.append(["Permanent retaining walls", "Designed for earth pressures, surcharge and seismic actions with permanent drainage."])
    if fault and nf:
        r7 = refs.add("faults", "GNS Science / Earth Sciences New Zealand, New Zealand Active Faults Database. "
                      "https://data.gns.cri.nz/af/")
        within = "within" if fault.get("inside_zone") else "not within"
        rows.append(["Active fault rupture", f"Approximately {km(nf['distance_m'])} from the {nf.get('name') or 'nearest mapped'} "
                     f"Fault [{r7}]; {within} a mapped fault avoidance or awareness area."])
    else:
        rows.append(["Active fault rupture", ph("distance to nearest active fault")])
    d.table(["Hazard", "Assessment"], rows, [0.3, 0.7])
    d.h2(f"{sec}.1 Active faults")
    if fault and nf:
        txt = (f"The {nf.get('name') or 'nearest'} Fault is mapped approximately {km(nf['distance_m'])} "
               f"{compass_word(nf.get('direction'))} of the site in the New Zealand Active Faults Database [{refs.key('faults')}]. ")
        if fault.get("inside_zone"):
            txt += ("The property lies within a mapped fault avoidance or awareness area, and fault rupture hazard shall be "
                    "assessed by a suitably qualified engineering geologist.")
        else:
            txt += (f"The property is therefore beyond {'1 km' if nf['distance_m'] > 1000 else 'the mapped trace'} from the identified "
                    "fault, and is not within a mapped fault avoidance or awareness area.")
        txt += (" This distance is measured from the national database at its published accuracy"
                + (f" ({nf['accuracy']})" if nf.get("accuracy") else "") + "; it is not a surveyed fault location.")
        d.p(txt)
    else:
        d.p(ph("Active fault data was not retrieved. Describe the nearest active fault and its distance from the site."))

    # ---- 6 Foundations
    sec += 1
    found_sec = sec
    d.h1(f"{sec}. Foundations" + (", excavations and retaining walls" if (excav or retaining) else ""))
    if not has_field:
        d.p("Foundation recommendations require site-specific investigation. As a minimum, Scala penetrometer testing and hand "
            "augers in accordance with NZS 3604:2011 Section 3 shall be undertaken across the building footprint.")
    elif verify:
        d.p("Conventional shallow reinforced concrete foundations may be adopted on competent natural soil, using an anticipated "
            "minimum ultimate bearing resistance of 300 kPa, subject to engineer verification after bulk excavation and before "
            "foundation construction. Foundations shall not bear on topsoil, uncontrolled fill or softened or disturbed clay. "
            "Where unsuitable ground remains, the engineer shall specify removal, engineered replacement or modified foundations.")
    elif specific:
        d.p("Foundations shall be specifically designed by the engineer for the ground conditions encountered. "
            + ph("describe the foundation type and founding level") + " Foundations shall not bear on topsoil, uncontrolled "
            "fill or softened or disturbed clay.")
    elif good:
        d.p(f"Conventional shallow reinforced concrete foundations may be adopted on competent natural soil below approximately "
            f"{m(fd, 2)}, using an anticipated minimum ultimate bearing resistance of 300 kPa, subject to engineer verification "
            "before foundation construction. Foundations shall not bear on topsoil, uncontrolled fill or softened or disturbed "
            "clay. Where unsuitable ground remains, the engineer shall specify removal, engineered replacement or modified foundations.")
    else:
        steps = []
        if refusal:
            steps.append("excavate a test pit or machine auger at the refusal locations to identify the obstruction")
        if fill_seen:
            steps.append("establish the extent and depth of any fill")
        steps.append(f"extend the Scala tests and hand augers to at least {m(fd + 2.0)} below ground level or to confirmed rock")
        if gg and len(gg["tests"]) < gg["min_tests"]:
            steps.append(f"test at a minimum of {gg['min_tests']} locations across the building footprint")
        d.p("Foundations cannot be designed on the basis of the current testing. Before foundation design, the following "
            "further investigation shall be undertaken: " + join_and(steps) + ".")
        d.p("If competent natural ground is confirmed at a practical depth, conventional shallow foundations founded on it may be "
            "suitable. Otherwise, specifically designed foundations, such as deepened pads or piles taken through the unsuitable "
            "material, will be required. Foundations shall not bear on topsoil, uncontrolled fill or softened or disturbed clay.")
    if excav:
        d.p("Temporary batters shall be formed only where the engineer confirms their suitability for the exposed ground, "
            "excavation height, surcharge, water conditions and exposure duration. Temporary shoring or staged cuts shall be "
            "provided where necessary. The contractor shall protect cut surfaces against rainfall, divert runoff away from crests, "
            "prevent ponding, and cease affected works upon cracking, slumping, seepage or movement pending assessment.")
    if retaining:
        d.p("Permanent drainage shall be installed behind all retaining walls: free-draining granular material, appropriate "
            "filtration and collector drains discharging to an approved outlet. Drainage shall be inspected before backfilling.")

    # ---- 7 Retaining parameters (only when walls are proposed)
    if retaining:
        sec += 1
        d.h1(f"{sec}. Retaining-wall geotechnical parameters")
        P = proj.get("retaining_params") or {}
        d.table(["Parameter", "Adopted value", "Basis"], [
            ["Bulk unit weight γ", P.get("gamma") or ph("kN/m³"), P.get("gamma_basis") or ph("basis")],
            ["Effective friction angle φ′", P.get("phi") or ph("°"), P.get("phi_basis") or ph("basis")],
            ["Effective cohesion c′", P.get("c") or ph("kPa"), P.get("c_basis") or ph("basis")],
            ["Active coefficient Ka", P.get("ka") or ph("value"), "Calculated for level backfill; ignore cohesion"],
            ["At-rest coefficient K₀", P.get("k0") or ph("value"), "Restrained walls"],
            ["Passive coefficient Kp", P.get("kp") or ph("value"), "Calculated; apply appropriate resistance reductions"],
            ["Ultimate bearing resistance", "300 kPa" if (good or verify) else ph("to be confirmed by investigation"),
             "Project expectation; testing and inspection required" if verify else "Testing and inspection required"],
            ["Seismic subsoil", sub_txt, "Section 3.1; NZS 1170.5"]], [0.34, 0.26, 0.40])
        refs.add("retaining", "MBIE / NZGS, Earthquake geotechnical engineering practice, Module 6: Earthquake resistant "
                 "retaining wall design. https://www.building.govt.nz/assets/Uploads/building-code-compliance/b-stability/"
                 "b1-structure/geotechnical-guidelines/module6.pdf")
        d.p("The adopted parameters are engineering assumptions, not laboratory-measured site properties. Permanent walls shall "
            "be designed for long-term drained conditions, applicable static and seismic earth pressures, surcharge and restraint. "
            f"Effective cohesion shall be ignored in active pressure calculations. Seismic actions shall be assessed in accordance "
            f"with appropriate New Zealand guidance [{refs.key('retaining')}].")

    # ---- wind (combined report)
    w = job.get("wind") if rt in ("combined", "wind") else None
    if w:
        sec += 1
        d.h1(f"{sec}. Design wind speeds")
        r = w["result"]
        I = r["inputs"]
        refs.add("wind", "Standards Australia / Standards New Zealand, AS/NZS 1170.2:2021 Structural design actions – Part 2: Wind actions.")
        vmax = max(x["Vsit"] for x in r["directions"])
        gov = [x["direction"] for x in r["directions"] if x["Vsit"] == vmax]
        d.p(f"Site wind speeds have been calculated in accordance with AS/NZS 1170.2:2021 [{refs.key('wind')}] for wind region "
            f"{I['region']} and an annual probability of exceedance of 1/{I['R']} ({I['limit_state']}). The regional wind speed "
            f"V_R is {I['VR']} m/s. The highest site wind speed is {vmax:.1f} m/s, from the {join_and([compass_word(g) for g in gov])}.")
        d.table(["Direction", "Mz,cat", "Ms", "Mt", "Vsit,β (m/s)"],
                [[x["direction"], f"{x['Mzcat']:.2f}", f"{x['Ms']:.2f}", f"{x['Mt']:.2f}", f"{x['Vsit']:.1f}"] for x in r["directions"]],
                [0.2, 0.2, 0.2, 0.2, 0.2])
        d.p("Building design wind speeds: " + "; ".join(f"θ = {v['theta']:.0f}°: {v['Vdes']:.1f} m/s" +
                                                       (" (30 m/s minimum)" if v["min_applied"] else "") for v in r["design"]) + ".")

    # ---- construction monitoring
    sec += 1
    d.h1(f"{sec}. Construction monitoring and verification")
    if excav:
        d.p("The contractor is responsible for temporary excavation stability, sequencing, runoff diversion, surface protection, "
            "safe equipment setbacks and maintaining protective measures during and after significant rainfall.")
    hold = []
    if has_field and not good and not verify and not specific:
        hold.append(["Before foundation design", "Further investigation completed and reported; founding stratum and bearing resistance confirmed."])
    if excav:
        hold.append(["After bulk excavation", "Engineer to inspect and appropriately test exposed founding surfaces to verify ultimate bearing resistance ≥300 kPa."])
    hold.append(["Before foundation construction", "Engineer to inspect foundation excavations and confirm removal or remediation of unsuitable, softened or disturbed material."])
    if retaining:
        hold.append(["Before retaining wall backfilling", "Check collection drains, granular drainage and filtration and discharge outlet."])
    hold.append(["Following unexpected ground conditions", "Stop affected works and refer to the engineer before recommencing."])
    d.table(["Hold point", "Required acceptance"], hold, [0.4, 0.6])
    d.p("Results of inspections, testing, remediation and any design changes shall be documented as part of the construction "
        "monitoring records.")

    # ---- conclusions
    sec += 1
    d.h1(f"{sec}. Conclusions and recommendations")
    cc = []
    if not has_field:
        cc.append("Published information does not identify a hazard that would preclude the proposed development, subject to the "
                  "hazards listed in Section 4. Site-specific investigation is required before foundation design.")
    elif verify:
        cc.append("The site is considered suitable for the proposed development using conventional shallow foundations"
                  + (" and specifically designed retaining walls" if retaining else "") + ", provided the specified construction "
                  "verification and temporary works measures are implemented. Excavation is expected to remove weaker shallow soil "
                  "and expose founding material providing 300 kPa ultimate bearing resistance. This shall be verified by the "
                  "engineer before foundation construction.")
    elif specific:
        cc.append("Good ground as defined in NZS 3604 has not been demonstrated, and the foundations shall be specifically designed "
                  "by the engineer for the ground conditions encountered.")
    elif good:
        cc.append("The site is considered suitable for the proposed development using conventional shallow foundations, provided "
                  "the specified construction verification is implemented. "
                  f"Natural ground below approximately {m(fd, 2)} is expected to provide 300 kPa ultimate bearing resistance, "
                  "which shall be verified by the engineer before foundation construction.")
    else:
        cc.append("The current testing does not demonstrate good ground for NZS 3604 foundations. "
                  "Further investigation, as described in Section " + str(found_sec) +
                  ", is required to identify the obstruction"
                  + (", confirm the extent of any fill" if fill_seen else "") + " and establish a founding level and bearing "
                  "resistance before foundations are designed.")
    cc.append(f"Adopt seismic subsoil {sub_txt} for initial structural design.")
    if excav:
        cc.append("The contractor must implement temporary excavation support, rainfall protection, drainage and any necessary "
                  "neighbour approvals.")
    d.p(" ".join(cc))

    # ---- references
    d.add("pagebreak")
    d.h1("References and project records")
    refs.add("nzs3604", "Standards New Zealand, NZS 3604:2011 Timber-framed buildings, Section 3 Site requirements.")
    if a.get("council") and (a["council"].get("councils")):
        refs.add("council", f"{join_and(a['council']['councils'])} hazard mapping, accessed {nice_date(date.today())}.")
    if site.get("legal"):
        refs.add("linz", "Toitū Te Whenua Land Information New Zealand, NZ Primary Parcels and NZ Addresses, CC BY 4.0.")
    for k, txt in refs.items():
        d.add("ref", key=k, text=txt)
    rec = []
    if job.get("workbook"):
        rec.append(job["workbook"]["name"])
    if job.get("photos"):
        rec.append("investigation photographs")
    rec.append(f"Project file {job_no}")
    d.p("Site records: " + join_and(rec) + ".")

    # ---- appendices
    plans, photos = plans_, photos_
    d.add("pagebreak")
    d.h1(f"Appendix {apx['layout']} – Site layout")
    if plans:
        for i, p in enumerate(plans, 1):
            d.figure(base64.b64decode(jobs.photo_b64(job, p)), f"Figure A{i}. " + (p.get("caption") or ph("caption")), 6.6, "jpg")
    else:
        mp = location_map(site)
        if mp:
            d.p("Site location and property boundary. Provided for site arrangement and boundary context only.")
            d.figure(mp, "Figure A1. Site location with the property boundary (LINZ NZ Primary Parcels) outlined. "
                         "Base map © OpenStreetMap contributors.", 6.0)
        else:
            d.p(ph("Insert the site plan showing the building footprint, property boundaries and test locations."))
    if has_field and field.get("scala"):
        d.add("pagebreak")
        d.h1(f"Appendix {apx['scala']} – Scala penetrometer results")
        d.p(f"Field investigation dated {nice_date((field.get('header') or {}).get('date'))}. Penetration resistance is presented "
            "as recorded, in blows per 100 mm. Depth is measured below local ground level at each test.")
        tests = field["scala"]
        depths = sorted({r["depth_m"] for t in tests for r in t["readings"]})
        rows = [[f"{dp:.1f}"] + [next((f"{r['blows']:.0f}" for r in t["readings"] if r["depth_m"] == dp and r["blows"] is not None), "—")
                                 for t in tests] for dp in depths]
        n = len(tests)
        d.table(["Depth (m)"] + [f"Scala {t['test']}" for t in tests], rows, [1 / (n + 1)] * (n + 1),
                caption=f"Table {apx['scala']}1. Scala results (blows per 100 mm). A dash means no recorded result.")
        d.figure(scala_png(tests), f"Figure {apx['scala']}1. Scala penetration resistance versus depth, as recorded in the investigation workbook.", 5.8)
        if field.get("auger"):
            arows = []
            for t in field["auger"]:
                for L in t["layers"]:
                    arows.append([str(t["test"]), f"{L['depth_m']:.1f}–{L['depth_m'] + 0.1:.1f}", L["description"]])
            d.table(["Hand auger", "Depth (m)", "Description (NZGS)"], arows, [0.18, 0.2, 0.62],
                    caption=f"Table {apx.get('scala', 'B')}2. Hand auger log, as recorded.")
    if photos:
        d.add("pagebreak")
        d.h1(f"Appendix {apx['photos']} – Photographic record")
        d.p(f"Photographs from project {job_no}. Directions are approximate where identified; they are not survey bearings.")
        letter = apx["photos"]
        for i, p in enumerate(photos, 1):
            cap = p.get("caption") or ph("caption: what the photo shows and the direction of view")
            if p.get("facing") and "looking" not in cap.lower():
                cap = cap.rstrip(".") + f", looking approximately {compass_word(p['facing'])}"
            d.figure(base64.b64decode(jobs.photo_b64(job, p)), f"Figure {letter}{i}. {cap.rstrip('.')}.", 5.6 if i == 1 else 4.3, "jpg")
    if "aerials" in apx:
        L = apx["aerials"]
        d.add("pagebreak")
        d.h1(f"Appendix {L} – Historic aerial photographs")
        d.p("Orthorectified aerial photographs centred on the site, oldest first. The site is circled in red and the property "
            "boundary is outlined in yellow where available; boundaries are today’s and are shown for reference only. "
            f"Source: Toitū Te Whenua Land Information New Zealand, licensed under CC BY 4.0 [{refs.key('imagery')}].")
        for i, im in enumerate(aer["images"], 1):
            kind = "historic aerial photograph" if im["cat"] == "scanned-aerial-photos" else "aerial photograph"
            yrs = str(im["year"]) if im["year"] == im["year_to"] else f"{im['year']}–{im['year_to']}"
            d.figure(im["png"], f"Figure {L}{i}. {yrs} {kind}" + (f", survey {im['sn']}" if im.get("sn") else "")
                     + f" ({im['gsd']} m resolution).", 6.0)
    return d


def _wind_only(job, refs, d, name, job_no, rdate, status):
    site, proj = job.get("site") or {}, job.get("project") or {}
    d.add("logo")
    d.add("title", text=TITLES["wind"])
    d.add("center", text="  |  ".join(x for x in (name, site.get("address") or ph("address")) if x))
    d.add("center", text=f"{proj.get('company') or ''}  |  Job {job_no}  |  {rdate}")
    d.add("subtitle", text=status)
    d.table(["Document detail", "Information"], [
        ["Project", proj.get("structure_desc") or proj.get("structure") or ph("project")], ["Client", proj.get("client") or ph("client")],
        ["Project reference", job_no], ["Report date", rdate], ["Address", site.get("address") or ph("address")],
        ["Legal description", site.get("legal") or ph("legal description")], ["Prepared by", proj.get("company") or "Your company"],
        ["Professional authorisation", proj.get("authorisation") or ph("name – CPEng number")]], [0.5, 0.5])
    w = job.get("wind")
    d.h1("Executive summary")
    if not w:
        d.p(ph("No wind calculation has been saved for this job. Open the wind calculator, calculate and press Save to report."))
        return d
    r, I = w["result"], w["result"]["inputs"]
    refs.add("wind", "Standards Australia / Standards New Zealand, AS/NZS 1170.2:2021 Structural design actions – Part 2: Wind actions.")
    refs.add("nzs1170_0", "Standards Australia / Standards New Zealand, AS/NZS 1170.0:2002 Structural design actions – Part 0: General principles.")
    vmax = max(x["Vsit"] for x in r["directions"])
    vdes = max(v["Vdes"] for v in r["design"])
    d.p(f"The design wind speed for the building is {vdes:.1f} m/s ({I['limit_state']}, annual probability of exceedance 1/{I['R']}), "
        f"calculated in accordance with AS/NZS 1170.2:2021 for wind region {I['region']}. The highest site wind speed is {vmax:.1f} m/s.")
    d.h1("1. Basis of assessment")
    d.p(f"Site wind speeds have been calculated for the eight cardinal directions in accordance with AS/NZS 1170.2:2021 [R1], with "
        f"the annual probability of exceedance taken from AS/NZS 1170.0 [R2] for importance level {proj.get('importance_level') or ph('IL2')} "
        f"and a design working life of {proj.get('design_life') or ph('50 years')}. The average roof height is {I['h']} m and the "
        f"reference height {I['z']} m. Terrain, shielding and topography were assessed for each direction from LiDAR survey data, "
        "LINZ building outlines and aerial imagery, and confirmed by the engineer.")
    d.h1("2. Site wind speeds")
    d.table(["Direction", "Md", "Mz,cat", "Ms", "Mt", "Vsit,β (m/s)"],
            [[x["direction"], f"{x['Md']:.2f}", f"{x['Mzcat']:.2f}", f"{x['Ms']:.2f}", f"{x['Mt']:.2f}", f"{x['Vsit']:.1f}"] for x in r["directions"]],
            [1 / 6] * 6, caption=f"Table 1. Site wind speeds; regional wind speed V_R = {I['VR']} m/s, M_c = {I['Mc']}.")
    d.h1("3. Building design wind speeds")
    d.table(["Building direction θ", "Vdes,θ (m/s)", "Note"],
            [[f"{v['theta']:.0f}°", f"{v['Vdes']:.1f}", "30 m/s ULS minimum applies" if v["min_applied"] else f"Governed at {v['governing_bearing']:.0f}°"]
             for v in r["design"]], [0.3, 0.3, 0.4])
    d.add("pagebreak")
    d.h1("References and project records")
    for k, txt in refs.items():
        d.add("ref", key=k, text=txt)
    return d


def _hit_short(h):
    return f"{h['layer']} ({h['council']})"


def _nearest_txt(sl, lsl):
    c = [(h.get("distance_m") or 0, h["layer"]) for h in sl] + [(l.get("distance_m") or 0, l.get("layer", "landslide")) for l in lsl]
    dmin, name = min(c)
    return f"{name}, approximately {km(dmin)} away"


class References:
    def __init__(self):
        self._items: dict[str, str] = {}

    def add(self, key, text):
        if key not in self._items:
            self._items[key] = text
        return self.key(key)

    def key(self, key):
        return f"R{list(self._items).index(key) + 1}" if key in self._items else "R?"

    def items(self):
        return [(f"R{i + 1}", t) for i, t in enumerate(self._items.values())]


# ---------------------------------------------------------------- images
def scala_png(tests) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.2, 4.4), dpi=160)
    for t in tests:
        xs, ys = [], []
        for r in t["readings"]:
            if r["blows"] is None:
                continue
            xs += [r["blows"], r["blows"]]
            ys += [r["depth_m"], r["depth_m"] + 0.1]
        ax.plot(xs, ys, lw=1.6, label=f"Scala {t['test']}")
    ax.invert_yaxis()
    ax.set_xlabel("Blows per 100 mm", fontsize=9)
    ax.set_ylabel("Depth below ground level (m)", fontsize=9)
    ax.grid(True, color="#dddddd", lw=0.6)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=max(2.0, max(r["depth_m"] + 0.2 for t in tests for r in t["readings"])), top=0)
    ax.legend(fontsize=8, frameon=True)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def location_map(site, zoom=18) -> bytes | None:
    """Small location map from OpenStreetMap tiles with the parcel boundary; None when offline."""
    import math

    import httpx
    from PIL import Image, ImageDraw
    try:
        lat, lon = site["lat"], site["lon"]
        n = 2 ** zoom
        fx = (lon + 180) / 360 * n
        fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
        tx, ty = int(fx), int(fy)
        canvas = Image.new("RGB", (768, 768), "white")
        with httpx.Client(timeout=8, headers={"User-Agent": "nzgeo/0.5 (open-source desk study tool)"}) as c:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    r = c.get(f"https://tile.openstreetmap.org/{zoom}/{tx + dx}/{ty + dy}.png")
                    r.raise_for_status()
                    canvas.paste(Image.open(io.BytesIO(r.content)).convert("RGB"), ((dx + 1) * 256, (dy + 1) * 256))
        px = lambda lo, la: (((lo + 180) / 360 * n - tx + 1) * 256,  # noqa: E731
                             ((1 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2 * n - ty + 1) * 256)
        dr = ImageDraw.Draw(canvas)
        if site.get("parcel"):
            dr.line([px(*c) for c in site["parcel"]], fill=(209, 73, 91), width=4)
        x, y = px(lon, lat)
        dr.ellipse([x - 8, y - 8, x + 8, y + 8], fill=(0, 49, 100), outline="white", width=2)
        cx, cy = int(x), int(y)
        crop = canvas.crop((max(0, cx - 360), max(0, cy - 240), max(0, cx - 360) + 720, max(0, cy - 240) + 480))
        out = io.BytesIO()
        crop.save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None


# ---------------------------------------------------------------- Word
def to_docx(d: Doc, footer: str) -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor, Twips

    doc = Document(str(TEMPLATE)) if TEMPLATE and TEMPLATE.exists() else Document()
    body_w = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin

    def _arial(r):
        r.font.name = "Arial"
        rpr = r._r.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(k), "Arial")
        for k in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if rf.get(qn(k)) is not None:
                del rf.attrib[qn(k)]

    def runs(par, text, bold=False, color=None):
        pos = 0
        for mt in PH.finditer(text):
            if mt.start() > pos:
                r = par.add_run(text[pos:mt.start()])
                _arial(r)
                r.bold = bold or None
                if color:
                    r.font.color.rgb = RGBColor.from_string(color)
            r = par.add_run("[" + mt.group(1) + "]")
            _arial(r)
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            r.bold = bold or None
            pos = mt.end()
        if pos < len(text):
            r = par.add_run(text[pos:])
            _arial(r)
            r.bold = bold or None
            if color:
                r.font.color.rgb = RGBColor.from_string(color)

    def shade(cell, fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        tcPr.append(shd)

    headings = []
    toc_par = None
    pending_break = False
    for b in d.blocks:
        t = b["t"]
        if t == "pagebreak":
            pending_break = True
            continue
        before = len(doc.element.body) - 1   # new content goes in before the closing sectPr
        if t == "logo":
            if LOGO and LOGO.exists():
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(str(LOGO), width=Inches(2.0))
        elif t == "title":
            p = doc.add_paragraph(style="Title")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            runs(p, b["text"])
        elif t == "center":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            runs(p, b["text"])
        elif t == "subtitle":
            p = doc.add_paragraph(style="Subtitle")
            runs(p, b["text"])
        elif t in ("h1", "h2"):
            p = doc.add_paragraph(style="Heading 1" if t == "h1" else "Heading 2")
            runs(p, b["text"])
            headings.append((t, b["text"]))
        elif t == "p":
            runs(doc.add_paragraph(), b["text"])
        elif t == "ref":
            runs(doc.add_paragraph(), f"[{b['key']}] {b['text']}")
        elif t == "toc":
            h = doc.add_paragraph(style="Heading 1")
            h.add_run("Contents")
            toc_par = doc.add_paragraph()
        elif t == "table":
            ncol = len(b["header"])
            tbl = doc.add_table(rows=1 + len(b["rows"]), cols=ncol)
            tbl.style = doc.styles["Table Grid"]
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            widths = [int(body_w * f) for f in b["widths"]]
            tbl.autofit = False
            grid = tbl._tbl.tblGrid
            for gc, wv in zip(grid.findall(qn("w:gridCol")), widths):
                gc.set(qn("w:w"), str(int(wv / 635)))
            for ri, row in enumerate([b["header"]] + b["rows"]):
                for ci, val in enumerate(row):
                    cell = tbl.cell(ri, ci)
                    cell.width = widths[ci]
                    par = cell.paragraphs[0]
                    par.paragraph_format.space_before = Twips(40)
                    par.paragraph_format.space_after = Twips(40)
                    if ri == 0:
                        shade(cell, HEADFILL)
                        runs(par, str(val), bold=True, color=NAVY)
                    else:
                        runs(par, str(val))
            if b.get("caption"):
                runs(doc.add_paragraph(style="Caption"), b["caption"])
            else:
                doc.add_paragraph().paragraph_format.space_after = Pt(0)
        elif t == "figure":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.keep_with_next = True
            w_in, h_in = _fit(b["data"], b["width_in"], 4.6)
            p.add_run().add_picture(io.BytesIO(b["data"]), width=Inches(w_in))
            runs(doc.add_paragraph(style="Caption"), b["caption"])
        if pending_break:
            first = doc.element.body[before]
            if first.tag == qn("w:p"):
                from docx.text.paragraph import Paragraph
                Paragraph(first, doc._body).paragraph_format.page_break_before = True
            else:
                doc.element.body[before].addprevious(_break_par())
            pending_break = False

    if toc_par is not None:
        _toc_field(toc_par, headings)
    for sec in doc.sections:
        for part in (sec.footer, sec.first_page_footer):
            for par in part.paragraphs:
                for r in par.runs:
                    if "{{FOOTER}}" in r.text:
                        r.text = r.text.replace("{{FOOTER}}", footer)
    _update_fields_on_open(doc)
    cp = doc.core_properties
    cp.title = next((b["text"] for b in d.blocks if b["t"] == "title"), "Report")
    cp.author = ""
    cp.created = cp.modified = datetime.now()
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _fit(data, width_in, max_h_in):
    """Width that keeps a picture no taller than max_h_in."""
    from PIL import Image
    w, h = Image.open(io.BytesIO(data)).size
    if width_in * h / w > max_h_in:
        width_in = max_h_in * w / h
    return width_in, width_in * h / w


def _break_par():
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    r.append(br)
    p.append(r)
    return p


def _toc_field(par, headings):
    """Word TOC field (levels 1-2), pre-filled with the headings so it reads correctly before it is updated."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def fld(p, kind):
        r = OxmlElement("w:r")
        f = OxmlElement("w:fldChar")
        f.set(qn("w:fldCharType"), kind)
        r.append(f)
        p._p.append(r)

    def instr(p, text):
        r = OxmlElement("w:r")
        it = OxmlElement("w:instrText")
        it.set(qn("xml:space"), "preserve")
        it.text = text
        r.append(it)
        p._p.append(r)

    from docx.enum.style import WD_STYLE_TYPE
    _styles = par.part.document.styles
    for _n in ("toc 1", "toc 2"):   # absent from python-docx's default template
        if _n not in [x.name for x in _styles]:
            _styles.add_style(_n, WD_STYLE_TYPE.PARAGRAPH).base_style = _styles["Normal"]
    fld(par, "begin")
    instr(par, ' TOC \\o "1-2" \\h \\z \\u ')
    fld(par, "separate")
    par.style = par.part.document.styles["toc 1"]
    first = True
    cur = par
    for lvl, text in [("h1", "Contents")] + headings:
        if not first:
            cur = _add_after(cur)
            cur.style = cur.part.document.styles["toc 1" if lvl == "h1" else "toc 2"]
        cur.add_run(text)
        first = False
    fld(cur, "end")


def _add_after(par):
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph
    new = OxmlElement("w:p")
    par._p.addnext(new)
    return Paragraph(new, par._parent)


def _update_fields_on_open(doc):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    s = doc.settings.element
    if s.find(qn("w:updateFields")) is None:
        u = OxmlElement("w:updateFields")
        u.set(qn("w:val"), "true")
        s.append(u)


# ---------------------------------------------------------------- HTML preview
CSS = """
:root{--navy:#003164;--fill:#A2BADC;--ink:#222;--muted:#686868;--bg:#e9ecef}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font:10pt/1.45 Arial,Helvetica,sans-serif;color:var(--ink)}
.bar{position:sticky;top:0;z-index:2;display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding:10px 16px;background:#fff;border-bottom:1px solid #ccd}
.bar a,.bar button{font:600 14px system-ui,sans-serif;padding:8px 14px;border-radius:6px;border:1px solid var(--navy);background:var(--navy);color:#fff;text-decoration:none;cursor:pointer}
.bar .ghost{background:#fff;color:var(--navy)}.bar small{color:#555;font:13px system-ui,sans-serif}
.page{background:#fff;max-width:21cm;margin:16px auto;padding:1.8cm 2cm 1.6cm;box-shadow:0 1px 4px rgba(0,0,0,.15)}
.logo{text-align:center}.logo img{width:2in}
h1.title{font-size:24pt;color:var(--navy);text-align:center;margin:6px 0 4px;padding-bottom:6px;border-bottom:1px solid #4F81BD}
.center{text-align:center;margin:4px 0}.subtitle{color:var(--muted);letter-spacing:.08em;font-size:11.5pt;margin:12px 0 10px}
h2.h1{font-size:15.5pt;color:var(--navy);margin:18px 0 6px}h3.h2{font-size:12.5pt;color:var(--navy);margin:12px 0 4px}
p{margin:0 0 7px}table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border:1px solid #000;padding:2px 6px;text-align:left;vertical-align:top}
th{background:var(--fill);color:var(--navy)}.cap{font-style:italic;color:var(--muted);font-size:9pt;margin:3px 0 10px}
figure{margin:8px 0}figure img{max-width:100%;height:auto}mark{background:#ffef3a}
.toc div{display:flex}.toc div span:first-child{white-space:nowrap}.toc .l2{padding-left:12px}
.break{border-top:2px dashed #c9ced6;margin:18px -2cm}
@media (max-width:820px){.page{padding:16px}}
@media print{.bar{display:none}body{background:#fff}.page{box-shadow:none;margin:0;max-width:none;padding:0}.break{border:0;break-after:page;margin:0}}
"""


def to_html(d: Doc, job_id: str | None = None, title="Report") -> str:
    def esc(text):
        out, pos = [], 0
        for mt in PH.finditer(text):
            out.append(_html.escape(text[pos:mt.start()]))
            out.append(f"<mark>[{_html.escape(mt.group(1))}]</mark>")
            pos = mt.end()
        out.append(_html.escape(text[pos:]))
        return "".join(out)

    heads = [(b["t"], b["text"]) for b in d.blocks if b["t"] in ("h1", "h2")]
    h = [f"<!doctype html><html lang='en-NZ'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
         f"<title>{_html.escape(title)}</title><style>{CSS}</style></head><body>"]
    if job_id:
        h.append(f"<div class='bar'><a href='/api/jobs/{job_id}/report.docx'>Download Word document</a>"
                 "<button class='ghost' onclick='window.print()'>Print / save as PDF</button>"
                 "<small>Highlighted text needs the engineer's input before issue. The Word document has the same content and the house style.</small></div>")
    h.append("<div class='page'>")
    for b in d.blocks:
        t = b["t"]
        if t == "logo":
            if LOGO and LOGO.exists():
                h.append(f"<div class='logo'><img alt='Logo' src='data:image/png;base64,{base64.b64encode(LOGO.read_bytes()).decode()}'></div>")
        elif t == "title":
            h.append(f"<h1 class='title'>{esc(b['text'])}</h1>")
        elif t == "center":
            h.append(f"<p class='center'>{esc(b['text'])}</p>")
        elif t == "subtitle":
            h.append(f"<p class='subtitle'>{esc(b['text'])}</p>")
        elif t == "h1":
            h.append(f"<h2 class='h1'>{esc(b['text'])}</h2>")
        elif t == "h2":
            h.append(f"<h3 class='h2'>{esc(b['text'])}</h3>")
        elif t == "p":
            h.append(f"<p>{esc(b['text'])}</p>")
        elif t == "ref":
            h.append(f"<p>[{esc(b['key'])}] {esc(b['text'])}</p>")
        elif t == "pagebreak":
            h.append("<div class='break'></div>")
        elif t == "toc":
            h.append("<h2 class='h1'>Contents</h2><div class='toc'>" + "".join(
                f"<div class='{'l2' if lv == 'h2' else ''}'><span>{esc(tx)}</span></div>" for lv, tx in [("h1", "Contents")] + heads) + "</div>")
        elif t == "table":
            ws = "".join(f"<col style='width:{w * 100:.0f}%'>" for w in b["widths"])
            h.append(f"<table><colgroup>{ws}</colgroup><tr>" + "".join(f"<th>{esc(str(c))}</th>" for c in b["header"]) + "</tr>"
                     + "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>" for r in b["rows"]) + "</table>")
            if b.get("caption"):
                h.append(f"<p class='cap'>{esc(b['caption'])}</p>")
        elif t == "figure":
            mime = "image/jpeg" if b["kind"] == "jpg" else "image/png"
            w_in, _ = _fit(b["data"], b["width_in"], 4.6)
            h.append(f"<figure><img alt='' style='width:{w_in:.2f}in' src='data:{mime};base64,{base64.b64encode(b['data']).decode()}'>"
                     f"<p class='cap'>{esc(b['caption'])}</p></figure>")
    h.append("</div></body></html>")
    return "".join(h)


def footer_text(job: dict) -> str:
    proj = dict(job.get("project") or {})
    site = job.get("site") or {}
    a = address_parts(site.get("address"))
    short = ", ".join(x for x in (a["first"], a["suburb"]) if x) or "Site"
    return f"{proj.get('company') or ''}   |   Job {proj.get('job_no') or '—'}   |   {short}"
