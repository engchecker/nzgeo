"""Scala penetrometer and hand auger results checked against NZS 3604:2011 clause 3.3.

Clauses applied:
  3.3.4(a)   test to at least 2 m below the underside of the footing, unless rock is encountered
  3.3.6      a bore hole at each penetrometer test, logged at least every 300 mm to the same depth
  3.3.7.1(a) no organic topsoil, soft or very soft peat or clay, or uncertified fill below footing depth
  3.3.7.1(b) blows per 100 mm exceed five down to twice the widest footing width below the footing,
             and exceed three at greater depths; averaging over up to 300 mm where sets are uniform
  3.3.7.1(c) soil conditions closely similar at every test site
  3.3.8      at least four test sites up to 200 m2 plan area, plus one per additional 100 m2
Results are a screening check for the engineer; they do not replace judgement on the site.
"""
from __future__ import annotations

import math
import re

EXCLUDED = [
    (r"organic|top\s*soil|topsoil", "organic topsoil"),
    (r"\bpeat\b", "peat"),
    (r"\b(very\s+)?soft\b", "soft or very soft soil"),
    (r"\bfill\b", "fill"),
]
REFUSAL_BLOWS = 10  # a final reading at or above this, with the test stopping, is treated as refusal [assumption]


def _readings(test):
    return [(r["depth_m"], r["blows"]) for r in test["readings"] if r["blows"] is not None]


def min_tests(floor_area_m2: float | None) -> int:
    if not floor_area_m2 or floor_area_m2 <= 200:
        return 4
    return 4 + math.ceil((floor_area_m2 - 200) / 100)


def _zone_check(rd, top, bottom, need, strict):
    """Intervals [d, d+0.1) inside [top, bottom): pass if blows exceed `need` (or reach it when not strict),
    or if the average over a window of up to three uniform readings including it does."""
    ok = (lambda v: v > need) if strict else (lambda v: v >= need)
    fails, averaged, checked = [], [], 0
    vals = {round(d, 2): v for d, v in rd}
    for d, v in rd:
        if d + 1e-9 < top or d + 1e-9 >= bottom:
            continue
        checked += 1
        if ok(v):
            continue
        rescued = False
        for w in ((d - 0.1, d, d + 0.1), (d - 0.2, d - 0.1, d), (d, d + 0.1, d + 0.2), (d - 0.1, d), (d, d + 0.1)):
            xs = [vals.get(round(x, 2)) for x in w]
            if None in xs:
                continue
            if max(xs) <= 2 * max(1, min(xs)) and ok(sum(xs) / len(xs)):
                rescued = True
                averaged.append(round(d, 2))
                break
        if not rescued:
            fails.append((round(d, 2), v))
    return {"checked": checked, "fails": fails, "averaged": averaged}


def scala_test(test, footing_depth_m, footing_width_m, *, strict=True, rock=False):
    rd = _readings(test)
    if not rd:
        return {"test": test["test"], "status": "no_data"}
    reached = round(rd[-1][0] + 0.1, 2)
    last = rd[-1][1]
    need_depth = round(footing_depth_m + 2.0, 2)
    z5_bottom = footing_depth_m + 2 * footing_width_m
    a = _zone_check(rd, footing_depth_m, z5_bottom, 5, strict)
    b = _zone_check(rd, z5_bottom, need_depth, 3, strict)
    refusal = reached < need_depth and last >= REFUSAL_BLOWS
    depth_ok = reached + 1e-9 >= need_depth or rock
    res = {
        "test": test["test"], "reached_m": reached, "required_m": need_depth, "depth_ok": depth_ok,
        "refusal": refusal, "final_blows": last,
        "zone5": {"from_m": footing_depth_m, "to_m": round(z5_bottom, 2), **a},
        "zone3": {"from_m": round(z5_bottom, 2), "to_m": need_depth, **b},
        "blows_ok": not a["fails"] and not b["fails"],
    }
    # shallowest footing depth at which (b) is met over the depth tested
    first = None
    for k in range(2, 21):
        df = k / 10
        za = _zone_check(rd, df, df + 2 * footing_width_m, 5, strict)
        zb = _zone_check(rd, df + 2 * footing_width_m, df + 2.0, 3, strict)
        if reached + 1e-9 >= df + 2 * footing_width_m and za["checked"] and not za["fails"] and not zb["fails"]:
            first = df
            break
    res["first_depth_meeting_b_m"] = first
    res["fails_txt"] = "; ".join(f"{d:.1f} m ({v:.0f})" for d, v in a["fails"])
    res["status"] = "pass" if res["blows_ok"] and depth_ok else ("fail" if not res["blows_ok"] else "incomplete")
    return res


def soil_exclusions(auger, footing_depth_m):
    hits = []
    for t in auger:
        for L in t["layers"]:
            if L["depth_m"] + 0.1 <= footing_depth_m + 1e-9:
                continue
            for rx, label in EXCLUDED:
                if re.search(rx, L["description"], re.I) and not re.search(r"\bnot\s+fill|no\s+fill", L["description"], re.I):
                    hits.append({"test": t["test"], "depth_m": L["depth_m"], "found": label, "description": L["description"]})
    return hits


def similarity(results):
    """3.3.7.1(c): compare tests on their median blows in the 5-blow zone and pass/fail outcome."""
    meds = {}
    for r in results:
        if r.get("status") == "no_data":
            continue
        meds[r["test"]] = r
    notes = []
    outcomes = {r["status"] for r in meds.values()}
    if len(outcomes) > 1:
        notes.append("Tests disagree: " + ", ".join(f"test {k} {v['status']}" for k, v in meds.items()) + ".")
    depths = [r["reached_m"] for r in meds.values()]
    if depths and max(depths) - min(depths) >= 0.3:
        notes.append(f"Depth reached varies from {min(depths):.1f} m to {max(depths):.1f} m.")
    firsts = [r["first_depth_meeting_b_m"] for r in meds.values() if r["first_depth_meeting_b_m"]]
    if firsts and max(firsts) - min(firsts) >= 0.3:
        notes.append(f"Depth at which the blow-count criteria are first met varies from {min(firsts):.1f} m to {max(firsts):.1f} m.")
    return {"similar": not notes, "notes": notes}


def checklist_flags(checklist):
    flags = []
    for it in checklist or []:
        p, a = it["prompt"].lower(), it["answer"]
        if a == "Y" and re.search(r"signs of fill|pushover fill", p):
            flags.append(("stop", f"Technician recorded signs of fill (item {it['no']}). Fill is not good ground unless "
                                  "certified under NZS 4431 (NZS 3604 clause 3.3.7.1(a)(iv)). Establish its extent and depth."))
        elif a == "Y" and re.search(r"wet areas|instability|subsidence|retaining", p):
            flags.append(("warn", f"Technician answered Yes: {it['prompt']} {it['notes']}".strip()))
        elif a == "Y" and re.search(r"unusual resistance", p):
            flags.append(("warn", "Technician recorded unusual Scala resistance" + (f": {it['notes']}" if it["notes"] else
                                  "; no depths or remarks recorded") + "."))
        elif a == "Y" and re.search(r"topsoil depth|groundwater|seepage", p) and not it["notes"]:
            flags.append(("info", f"Item {it['no']} answered Yes but no value recorded: {it['prompt']}"))
        elif a == "N" and re.search(r"safe access|locate services", p):
            flags.append(("stop", "Services were not located before testing (item 2)."))
    return flags


def assess(field: dict, *, footing_depth_m=0.45, footing_width_m=0.3, floor_area_m2=None, strict=True,
           rock_at_refusal=False) -> dict:
    scala = [scala_test(t, footing_depth_m, footing_width_m, strict=strict, rock=rock_at_refusal)
             for t in field.get("scala", [])]
    scala = [s for s in scala if s.get("status") != "no_data"]
    excl = soil_exclusions(field.get("auger", []), footing_depth_m)
    sim = similarity(scala)
    need = min_tests(floor_area_m2)
    auger = field.get("auger", [])
    findings = []
    if len(scala) < need:
        findings.append(("stop", f"{len(scala)} Scala tests recorded; NZS 3604 clause 3.3.8 requires at least {need}"
                                 f"{' for the plan area given' if floor_area_m2 else ' for a building up to 200 m²'}."))
    if len(auger) < len(scala):
        findings.append(("warn", f"{len(auger)} hand auger log(s) for {len(scala)} Scala tests. Clause 3.3.6 requires a "
                                 "bore hole at each penetrometer test site."))
    short_auger = [a for a in auger if a["max_depth_m"] + 1e-9 < footing_depth_m + 2.0]
    if short_auger:
        findings.append(("warn", "Hand auger " + ", ".join(f"{a['test']} to {a['max_depth_m']:.1f} m" for a in short_auger)
                                 + f"; clause 3.3.6 requires logging to {footing_depth_m + 2.0:.1f} m (2 m below footing) unless rock."))
    shallow = [s for s in scala if not s["depth_ok"]]
    if shallow:
        ref = [s for s in shallow if s["refusal"]]
        findings.append(("stop", "Scala " + ", ".join(f"test {s['test']} stopped at {s['reached_m']:.1f} m" +
                                                       (f" ({s['final_blows']:.0f} blows, refusal)" if s["refusal"] else "")
                                                       for s in shallow) +
                         f"; clause 3.3.4(a) requires {footing_depth_m + 2.0:.1f} m unless rock is encountered."
                         + (" Refusal on an obstruction is not rock: identify it (boulder, buried rubble or fill, "
                            "old foundation) before relying on the result." if ref else "")))
    failing = [s for s in scala if not s["blows_ok"]]
    if failing:
        findings.append(("stop", "Blow counts below the clause 3.3.7.1(b) criteria under a footing at "
                                 f"{footing_depth_m:.2f} m: " + "; ".join(
            f"test {s['test']} at " + ", ".join(f"{d:.1f} m ({v:.0f})" for d, v in (s['zone5']['fails'] + s['zone3']['fails'])[:6])
            for s in failing) + "."))
    if excl:
        kinds = sorted({e["found"] for e in excl})
        findings.append(("stop", "Hand auger log records " + ", ".join(kinds) + " below footing depth ("
                         + ", ".join(f"test {e['test']} at {e['depth_m']:.1f} m" for e in excl[:4]) + "); clause 3.3.7.1(a)."))
    findings += [(lvl, txt) for lvl, txt in checklist_flags(field.get("checklist"))]
    for n in sim["notes"]:
        findings.append(("warn", "Clause 3.3.7.1(c): " + n))
    gw = (field.get("groundwater") or {}).get("depth_m")

    good = bool(scala) and not failing and not shallow and not excl and len(scala) >= need and sim["similar"] \
        and not any(l == "stop" for l, _ in findings)
    firsts = [s["first_depth_meeting_b_m"] for s in scala]
    verdict = ("Good ground per NZS 3604 is indicated by the tests, subject to engineer review."
               if good else "Good ground per NZS 3604 has not been demonstrated by the tests.")
    return {"footing_depth_m": footing_depth_m, "footing_width_m": footing_width_m, "floor_area_m2": floor_area_m2,
            "criterion": "exceeds (clause wording)" if strict else "at least", "min_tests": need,
            "tests": scala, "exclusions": excl, "similarity": sim, "findings": findings,
            "good_ground": good, "verdict": verdict, "groundwater_m": gw,
            "first_depths": {s["test"]: s["first_depth_meeting_b_m"] for s in scala},
            "all_tests_meet_b_from_m": max(firsts) if firsts and all(firsts) else None}
