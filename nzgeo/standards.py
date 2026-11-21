"""Check, at report time, whether newer editions of NZS 3604 or NZS/TS 1170.5 are published and cited.

The check reads Standards NZ and MBIE pages and looks for edition strings. Its result goes on every
report. It never silently changes the method: if a newer NZS 3604 is cited, the exposure zone result
is blocked until the new map is digitised; if TS 1170.5 becomes cited, its label changes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .config import settings
from .http import fetch

NZS3604 = re.compile(r"NZS\s*3604\s*:\s*(\d{4})", re.I)
NZS1170_5 = re.compile(r"NZS\s*1170\.5\s*:\s*(\d{4})", re.I)
TS1170_5 = re.compile(r"TS\s*1170\.5\s*:\s*(\d{4})", re.I)
NZS3404_3 = re.compile(r"NZS\s*3404\.3\s*:\s*(\d{4})", re.I)
SUPERSEDED = re.compile(r"supersed|withdrawn|replaced by|no longer current", re.I)


def _text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _scan(urls: list[str]) -> tuple[list[dict], list[str]]:
    pages, errors = [], []
    for u in urls:
        try:
            body, retrieved = fetch(u, as_json=False, ttl_days=1)
            pages.append({"url": u, "retrieved": retrieved, "text": _text(body)})
        except Exception as e:  # noqa: BLE001
            errors.append(f"{u}: {type(e).__name__}")
    return pages, errors


def _years(pages: list[dict], pat: re.Pattern) -> set[int]:
    return {int(y) for p in pages for y in pat.findall(p["text"])}


def _evidence(pages, pat, year):
    for p in pages:
        m = re.search(pat.pattern.replace(r"(\d{4})", str(year)), p["text"], re.I)
        if m:
            s = p["text"][max(0, m.start() - 80): m.end() + 80].strip()
            return {"url": p["url"], "retrieved": p["retrieved"], "snippet": s}
    return None


def _edition_status(published, cited, pat, in_use, label):
    pub, cit = _years(published, pat), _years(cited, pat)
    newest_pub = max(pub) if pub else None
    newest_cit = max(cit) if cit else None
    if newest_cit and newest_cit > in_use:
        st = "newer_cited_update_required"
    elif newest_pub and newest_pub > in_use:
        st = "newer_published_not_cited"
    elif newest_cit or newest_pub:
        st = "current"
    else:
        st = "inconclusive"
    return {"status": st, "edition_in_use": in_use, "newest_published": newest_pub, "newest_cited": newest_cit,
            "cited": bool(newest_cit and newest_cit >= in_use),
            "newest_cited_label": f"{label}:{newest_cit}" if newest_cit else None,
            "evidence": [e for e in (_evidence(published, pat, newest_pub) if newest_pub else None,
                                     _evidence(cited, pat, newest_cit) if newest_cit else None) if e]}


def check(edition_in_use_3604: int | None = None) -> dict:
    edition_in_use_3604 = edition_in_use_3604 or settings.nzs3604_bundle_edition
    src = settings.standards_sources
    published, e1 = _scan(src["published"])
    cited, e2 = _scan(src["cited"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not published and not cited:
        return {"checked_at": now, "status": "not_checked", "errors": e1 + e2,
                "nzs3604": {"status": "not_checked", "edition_in_use": edition_in_use_3604},
                "seismic": {"status": "not_checked"},
                "nzs3404_3": {"status": "not_checked", "edition_in_use": settings.nzs3404_3_bundle_edition}}

    # NZS 3604
    pub = _years(published, NZS3604)
    cit = _years(cited, NZS3604)
    newest_pub = max(pub) if pub else None
    newest_cit = max(cit) if cit else None
    if newest_cit and newest_cit > edition_in_use_3604:
        st = "newer_cited_update_required"
    elif newest_pub and newest_pub > edition_in_use_3604:
        st = "newer_published_not_cited"
    elif newest_cit or newest_pub:
        st = "current"
    else:
        st = "inconclusive"
    old_superseded = any(f"3604:{edition_in_use_3604}" in p["text"].replace(" ", "") and SUPERSEDED.search(p["text"])
                         for p in published)
    nzs3604 = {"status": st, "edition_in_use": edition_in_use_3604, "newest_published": newest_pub,
               "newest_cited": newest_cit, "newest_cited_label": f"NZS 3604:{newest_cit}" if newest_cit else None,
               "superseded_notice_seen": old_superseded,
               "evidence": [e for e in (_evidence(published, NZS3604, newest_pub) if newest_pub else None,
                                        _evidence(cited, NZS3604, newest_cit) if newest_cit else None) if e]}

    # Seismic: is TS 1170.5 cited by B1/VM1? Is there a newer NZS 1170.5?
    ts_cited = _years(cited, TS1170_5)
    nzs_cited = _years(cited, NZS1170_5)
    seismic = {"status": "ok", "ts1170_5_cited": bool(ts_cited), "ts1170_5_cited_editions": sorted(ts_cited),
               "nzs1170_5_cited_editions": sorted(nzs_cited),
               "compliance_path_ts": "verification_method" if ts_cited else "alternative_solution",
               "evidence": [e for e in (_evidence(cited, TS1170_5, max(ts_cited)) if ts_cited else None,
                                        _evidence(cited, NZS1170_5, max(nzs_cited)) if nzs_cited else None) if e]}
    nzs3404_3 = _edition_status(published, cited, NZS3404_3, settings.nzs3404_3_bundle_edition, "NZS 3404.3")
    return {"checked_at": now, "status": "ok" if not (e1 or e2) else "partial", "errors": e1 + e2,
            "nzs3604": nzs3604, "seismic": seismic, "nzs3404_3": nzs3404_3}
