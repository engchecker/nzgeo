"""Read a soil suitability workbook (field sheet + Initial Geotechnical Assessment template).

Cells are found by their labels, not fixed addresses, so small layout changes still read.
Also accepts any workbook with a block headed 'Scala' / 'Depth (m)' / 'Blows/100mm'.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime

import openpyxl

SHEET_FIELD = ("initial information", "field sheet", "field data")
SHEET_TEMPLATE = ("field data entry",)
SHEET_REPORT = ("report",)


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        m = re.search(r"-?\d+(?:\.\d+)?", str(v))
        return float(m.group()) if m else None


def _sheet(wb, names):
    for ws in wb.worksheets:
        if ws.title.strip().lower() in names:
            return ws
    for ws in wb.worksheets:
        if any(n in ws.title.lower() for n in names):
            return ws
    return None


def _find(ws, pattern, *, col=None, start_row=1):
    rx = re.compile(pattern, re.I)
    for row in ws.iter_rows(min_row=start_row):
        for c in row:
            if col and c.column != col:
                continue
            if isinstance(c.value, str) and rx.search(c.value):
                return c
    return None


def _right_value(ws, cell, max_cols=8):
    """First value to the right of a label; stops at the next label (text ending in ':')."""
    for k in range(1, max_cols + 1):
        v = ws.cell(cell.row, cell.column + k).value
        if isinstance(v, str) and v.strip().endswith(":"):
            return None
        if v not in (None, ""):
            return v
    return None


# ---------------------------------------------------------------- field sheet
def _scala(ws, issues):
    head = _find(ws, r"scala penetrometer")
    if not head:
        return []
    tn = _find(ws, r"^test number", start_row=head.row)
    dh = _find(ws, r"^depth", start_row=head.row)
    if not tn or not dh:
        return []
    cols = []
    for c in range(tn.column + 1, tn.column + 12):
        v = ws.cell(tn.row, c).value
        if v in (None, ""):
            break
        cols.append((c, _txt(v)))
    gl_row = _find(ws, r"ground level", start_row=head.row)
    tests = []
    for c, name in cols:
        readings, depths = [], []
        r = dh.row + 1
        while True:
            d = _num(ws.cell(r, dh.column).value)
            if d is None and depths and ws.cell(r, dh.column).value is None and \
                    any(_num(ws.cell(r, cc).value) is not None for cc, _ in cols):
                d = depths[-1] + 0.1          # depth formula without a saved value: 0.1 m spacing
                if not any("0.1 m spacing" in i for i in issues):
                    issues.append("Some Scala depths had no saved value (formulas not calculated); "
                                  "depths were taken at 0.1 m spacing.")
            if d is None or (ws.cell(r, dh.column).value and isinstance(ws.cell(r, dh.column).value, str)
                             and not re.match(r"^\s*-?\d", ws.cell(r, dh.column).value)):
                break
            v = ws.cell(r, c).value
            depths.append(round(d, 2))
            readings.append(_num(v))
            r += 1
            if r - dh.row > 200:
                break
        # trailing blanks are "not tested"; internal blanks are a recording gap
        last = max((i for i, v in enumerate(readings) if v is not None), default=-1)
        rd = [(depths[i], readings[i]) for i in range(last + 1)]
        gaps = [d for d, v in rd if v is None]
        if gaps:
            issues.append(f"Scala test {name}: no blow count recorded at {', '.join(f'{g:.1f}' for g in gaps)} m.")
        if last >= 0:
            tests.append({"test": name, "ground_level_m": _num(ws.cell(gl_row.row, c).value) if gl_row else None,
                          "readings": [{"depth_m": d, "blows": v} for d, v in rd]})
    return tests


def _auger(ws):
    head = _find(ws, r"hand aug[eu]r.*test pit|test pit.*field data|hand aug[eu]r.*field")
    if not head:
        return []
    tn = _find(ws, r"^test number", start_row=head.row)
    dh = _find(ws, r"^depth", start_row=head.row)
    if not tn or not dh:
        return []
    # each test block starts with a 'Depth' column; the test number sits above the block's second column
    starts = [c.column for c in ws[dh.row] if isinstance(c.value, str) and re.match(r"^depth", c.value, re.I)]
    out = []
    for k, sc in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else sc + 6
        hdr = [(_txt(ws.cell(dh.row, c).value) or f"col{c}").lower() for c in range(sc + 1, end)]
        name = _txt(ws.cell(tn.row, sc + 1).value) or _txt(ws.cell(tn.row, sc).value) or str(k + 1)
        layers = []
        r = dh.row + 1
        prev = None
        while r < dh.row + 200:
            d = _num(ws.cell(r, sc).value)
            if d is None and prev is not None and any(_txt(ws.cell(r, c).value) for c in range(sc + 1, end)):
                d = prev + 0.1                # depth formula without a saved value
            if d is None:
                break
            prev = d
            parts = [_txt(ws.cell(r, c).value) for c in range(sc + 1, end)]
            desc = " ".join(p for p in parts if p)
            if desc:
                layers.append({"depth_m": round(d, 2), "fields": dict(zip(hdr, parts)), "description": desc})
            r += 1
        if layers:
            out.append({"test": name, "layers": layers, "max_depth_m": round(layers[-1]["depth_m"] + 0.1, 2)})
    return out


def _checklist(ws):
    items = []
    hdr = _find(ws, r"^prompt$")
    if not hdr:
        return items
    for r in range(hdr.row + 1, hdr.row + 60):
        no, prompt = ws.cell(r, hdr.column - 1).value, ws.cell(r, hdr.column).value
        if isinstance(prompt, str) and prompt.strip() and isinstance(no, (int, float)):
            items.append({"no": int(no), "prompt": prompt.strip(), "answer": _txt(ws.cell(r, hdr.column + 1).value).upper(),
                          "notes": _txt(ws.cell(r, hdr.column + 2).value)})
        elif isinstance(no, str) and re.search(r"groundwater found|scala", no, re.I):
            break
    return items


def _groundwater(ws):
    out = {}
    d = _find(ws, r"^depth \(mbgl\)")
    if d:
        out["depth_m"] = _num(_right_value(ws, d, 4))
        dt = _find(ws, r"^date$", col=d.column, start_row=d.row)
        if dt and dt.row - d.row <= 2:
            out["date"] = _txt(_right_value(ws, dt, 4)) or None
    sv = _find(ws, r"average shear vane")
    if sv:
        out["shear_vane_kpa"] = _num(_right_value(ws, sv, 4))
    return out


def read_field_sheet(ws) -> dict:
    issues: list[str] = []
    head = {}
    for lab, key in ((r"^job no", "job_no"), (r"^date:?$", "date"), (r"^site address", "address"),
                     (r"^technician", "technician")):
        c = _find(ws, lab)
        if c:
            v = _right_value(ws, c, 4)
            head[key] = _txt(v) or None
    checklist = _checklist(ws)
    summary = next((i["notes"] for i in checklist if re.search(r"technician summary", i["prompt"], re.I)), "")
    return {"header": head, "checklist": checklist, "technician_summary": summary,
            "scala": _scala(ws, issues), "auger": _auger(ws), "groundwater": _groundwater(ws), "issues": issues}


# ---------------------------------------------------------------- template (Field Data Entry)
def read_template(ws) -> dict:
    """Input rows of the template: label in column B, entry in column F, comment in column G."""
    rows = []
    for r in range(1, ws.max_row + 1):
        lab = ws.cell(r, 2).value
        if not isinstance(lab, str) or len(lab.strip()) < 3:
            continue
        v, cm = ws.cell(r, 6).value, ws.cell(r, 7).value
        rows.append({"row": r, "label": re.sub(r"\s+", " ", lab.strip()), "value": _txt(v) or None,
                     "comment": _txt(cm) or None})
    photos = []
    ph = _find(ws, r"^site photos")
    if ph:
        hdr = _find(ws, r"^photo no", start_row=ph.row)
        if hdr:
            for r in range(hdr.row + 1, hdr.row + 20):
                n, d = ws.cell(r, hdr.column).value, ws.cell(r, hdr.column + 1).value
                if not isinstance(n, (int, float)):
                    break
                photos.append({"no": int(n), "description": _txt(d)})
    return {"rows": rows, "photo_descriptions": photos}


def template_value(tmpl: dict, label_start: str, *, nth: int = 0, field: str = "value"):
    hits = [r for r in tmpl.get("rows", []) if r["label"].lower().startswith(label_start.lower())]
    return hits[nth][field] if len(hits) > nth else None


# ---------------------------------------------------------------- report sheet checks and images
_REF = re.compile(r"'([^']+)'!\$?([A-Z]+)\$?(\d+)")


def _report_link_check(wb_formulas, field_ws_title) -> list[str]:
    """Check the Report sheet's Scala grid points at the matching field-sheet cells."""
    rep = _sheet(wb_formulas, SHEET_REPORT)
    if rep is None:
        return []
    issues = []
    first = None
    for row in rep.iter_rows():
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("=") and field_ws_title in c.value:
                m = _REF.search(c.value)
                if m and m.group(1) == field_ws_title and c.column <= 6 and c.column >= 2:
                    if first is None:
                        first = (c.row, c.column, int(m.group(3)), openpyxl.utils.column_index_from_string(m.group(2)))
                    r0, c0, fr0, fc0 = first
                    exp_r, exp_c = fr0 + (c.row - r0), fc0 + (c.column - c0)
                    got_c = openpyxl.utils.column_index_from_string(m.group(2))
                    if (int(m.group(3)), got_c) != (exp_r, exp_c) and c.row - r0 < 60:
                        issues.append(f"Report sheet cell {c.coordinate} reads '{field_ws_title}'!{m.group(2)}{m.group(3)}; "
                                      f"expected {openpyxl.utils.get_column_letter(exp_c)}{exp_r}. "
                                      "The printed Scala table may show the wrong test's value.")
    return issues[:10]


def embedded_images(data: bytes) -> list[dict]:
    """Images placed in the workbook, with the sheet and anchor row, and any hyperlink on them."""
    out = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return out
    names = set(z.namelist())
    wbx = z.read("xl/workbook.xml").decode("utf8", "ignore")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8", "ignore")
    rid_target = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    rid_target.update({a: b for b, a in re.findall(r'Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
    for name, rid in re.findall(r'<sheet [^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wbx):
        sheet = "xl/" + rid_target.get(rid, "").lstrip("/").replace("xl/", "")
        srels = sheet.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if srels not in names:
            continue
        for dr in re.findall(r'Target="\.\./drawings/(drawing\d+\.xml)"', z.read(srels).decode()):
            dxml = z.read(f"xl/drawings/{dr}").decode("utf8", "ignore")
            drels_name = f"xl/drawings/_rels/{dr}.rels"
            drels = z.read(drels_name).decode() if drels_name in names else ""
            tmap = {}
            for m in re.finditer(r"<Relationship [^>]*>", drels):
                t = m.group(0)
                i = re.search(r'Id="([^"]+)"', t)
                g = re.search(r'Target="([^"]+)"', t)
                if i and g:
                    tmap[i.group(1)] = g.group(1)
            for anc in re.findall(r"<xdr:(?:twoCellAnchor|oneCellAnchor)[\s\S]*?</xdr:(?:twoCellAnchor|oneCellAnchor)>", dxml):
                emb = re.search(r'r:embed="([^"]+)"', anc)
                if not emb or emb.group(1) not in tmap:
                    continue
                row = re.search(r"<xdr:from>[\s\S]*?<xdr:row>(\d+)</xdr:row>", anc)
                link = re.search(r'hlinkClick [^>]*r:id="([^"]+)"', anc)
                media = "xl/" + tmap[emb.group(1)].replace("../", "")
                if media not in names or not re.search(r"\.(png|jpe?g)$", media, re.I):
                    continue
                out.append({"sheet": name, "row": int(row.group(1)) + 1 if row else None, "media": media,
                            "hyperlink": tmap.get(link.group(1)) if link else None, "bytes": z.read(media)})
    return out


# ---------------------------------------------------------------- entry point
def read_workbook(data: bytes, filename: str = "") -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, keep_vba=False)
    field_ws = _sheet(wb, SHEET_FIELD) or next((ws for ws in wb.worksheets if _find(ws, r"scala")), None)
    tmpl_ws = _sheet(wb, SHEET_TEMPLATE)
    out = {"filename": filename, "sheets": [ws.title for ws in wb.worksheets], "issues": []}
    if field_ws is not None:
        f = read_field_sheet(field_ws)
        out.update({k: f[k] for k in ("header", "checklist", "technician_summary", "scala", "auger", "groundwater")})
        out["issues"] += f["issues"]
    else:
        out["issues"].append("No field sheet with Scala results was found in the workbook.")
        out.update({"header": {}, "checklist": [], "technician_summary": "", "scala": [], "auger": [], "groundwater": {}})
    out["template"] = read_template(tmpl_ws) if tmpl_ws is not None else {"rows": [], "photo_descriptions": []}
    try:
        wbf = openpyxl.load_workbook(io.BytesIO(data), data_only=False, keep_vba=False)
        if field_ws is not None:
            out["issues"] += _report_link_check(wbf, field_ws.title)
    except Exception:
        pass
    imgs = embedded_images(data)
    for im in imgs:
        if im["hyperlink"] and im["hyperlink"].startswith("http"):
            im["note"] = (f"Placeholder picture linked to {im['hyperlink']} – not a site photograph. "
                          "Replace it before the spreadsheet report is issued.")
            out["issues"].append(f"{im['sheet']} sheet, row {im['row']}: " + im["note"])
        elif (im["row"] or 99) <= 2:
            im["note"] = "Logo"
    out["images"] = [{k: v for k, v in im.items()} for im in imgs]
    return out


# ---------------------------------------------------------------- write desk study answers back
def fill_template(data: bytes, answers: dict[str, str]) -> tuple[bytes, list[str]]:
    """Return a copy of the workbook with blank template cells filled.

    `answers` maps a template row label (column B text, matched case-insensitively from its start)
    to text. Only empty input cells are filled; nothing the engineer typed is overwritten.
    The workbook is edited at XML level, so macros, charts, images and protection are kept.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    ws = _sheet(wb, SHEET_TEMPLATE)
    if ws is None:
        return data, []
    targets = {}
    for lab, text in answers.items():
        c = _find(ws, "^" + re.escape(lab[:40]), col=2)
        if not c or not text:
            continue
        inp = ws.cell(c.row, 6)
        if inp.value in (None, ""):
            targets[inp.coordinate] = text
    if not targets:
        return data, []
    zin = zipfile.ZipFile(io.BytesIO(data))
    wbx = zin.read("xl/workbook.xml").decode()
    rels = zin.read("xl/_rels/workbook.xml.rels").decode()
    rid = re.search(r'<sheet [^>]*name="' + re.escape(ws.title) + r'"[^>]*r:id="([^"]+)"', wbx).group(1)
    rel = next(m.group(0) for m in re.finditer(r"<Relationship [^>]*>", rels) if f'Id="{rid}"' in m.group(0))
    path = "xl/" + re.search(r'Target="([^"]+)"', rel).group(1).lstrip("/").replace("xl/", "")
    xml = zin.read(path).decode()
    for ref, text in targets.items():
        xml = _set_inline(xml, ref, text)
    if "<calcPr" in wbx:
        wbx = re.sub(r"<calcPr([^>]*)/>", lambda m: "<calcPr" + re.sub(r'\s*fullCalcOnLoad="[^"]*"', "", m.group(1))
                     + ' fullCalcOnLoad="1"/>', wbx)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zin.infolist():
            b = zin.read(item.filename)
            if item.filename == path:
                b = xml.encode()
            elif item.filename == "xl/workbook.xml":
                b = wbx.encode()
            elif item.filename == "xl/calcChain.xml":
                continue
            zo.writestr(item, b)
    res = out.getvalue()
    if "xl/calcChain.xml" in zin.namelist():
        res = _drop_calcchain(res)
    return res, sorted(targets)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _col_n(ref: str) -> int:
    return openpyxl.utils.column_index_from_string(re.match(r"[A-Z]+", ref).group())


def _set_inline(xml: str, ref: str, text: str) -> str:
    row = int(re.search(r"\d+", ref).group())
    newc = lambda s: f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{_esc(text)}</t></is></c>'  # noqa: E731
    m = re.search(rf'<c r="{ref}"(?P<a>[^>]*?)(?:/>|>[\s\S]*?</c>)', xml)
    if m:
        st = re.search(r'\ss="\d+"', m.group("a"))
        return xml[:m.start()] + newc(st.group(0) if st else "") + xml[m.end():]
    rm = re.search(rf'<row r="{row}"[^>]*?(?:/>|>[\s\S]*?</row>)', xml)
    if rm:
        rowxml = rm.group(0)
        if rowxml.endswith("/>"):
            rowxml = rowxml[:-2] + ">" + newc("") + "</row>"
        else:
            cells = list(re.finditer(r'<c r="([A-Z]+)\d+"', rowxml))
            pos = next((c.start() for c in cells if _col_n(c.group(1)) > _col_n(ref)), rowxml.rfind("</row>"))
            rowxml = rowxml[:pos] + newc("") + rowxml[pos:]
        return xml[:rm.start()] + rowxml + xml[rm.end():]
    rows = list(re.finditer(r'<row r="(\d+)"', xml))
    pos = next((r.start() for r in rows if int(r.group(1)) > row), xml.find("</sheetData>"))
    return xml[:pos] + f'<row r="{row}">' + newc("") + "</row>" + xml[pos:]


def _drop_calcchain(data: bytes) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zin.infolist():
            b = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                b = re.sub(rb'<Override [^>]*calcChain[^>]*/>', b"", b)
            elif item.filename == "xl/_rels/workbook.xml.rels":
                b = re.sub(rb'<Relationship [^>]*calcChain[^>]*/>', b"", b)
            zo.writestr(item, b)
    return out.getvalue()
