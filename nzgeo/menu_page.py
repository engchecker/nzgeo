"""The menu page served at /."""

PAGE = r"""<!doctype html><html lang="en-NZ"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>NZ Site Hazards</title>
<link rel="stylesheet" href="/static/leaflet/leaflet.css">
<script src="/static/leaflet/leaflet.js"></script>
<style>
:root{--ink:#1d2329;--muted:#5b6670;--line:#d7dde2;--acc:#0b5cad;--accbg:#e8f1fb;--bg:#fff;--panel:#f6f8fa;--ok:#1f6b3a;--okbg:#e9f6ee;--warn:#8a5a00;--warnbg:#fff6e0;--stop:#9b1c1c;--stopbg:#fdecec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#e8ecef;--muted:#a3adb5;--line:#3a434b;--acc:#7db8ff;--accbg:#1b2b40;--bg:#15191d;--panel:#1d2329;--ok:#7fd49c;--okbg:#17301f;--warn:#f2c46b;--warnbg:#3a2f12;--stop:#ff9b9b;--stopbg:#3d1d1d}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
header{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
h1{font-size:1.25rem;margin:0}header small{color:var(--muted)}main{max-width:1100px;margin:0 auto;padding:16px}
h2{font-size:1.05rem;margin:0 0 4px}.step{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0;background:var(--bg)}
.step>p.hint{margin:2px 0 10px;color:var(--muted);font-size:.92rem}.num{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--acc);color:#fff;font-size:.85rem;font-weight:700;margin-right:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.card{border:2px solid var(--line);border-radius:8px;padding:10px 12px;cursor:pointer;display:block}.card:has(input:checked){border-color:var(--acc);background:var(--accbg)}
.card input{margin-right:6px}.card b{font-size:1rem}.card span{display:block;color:var(--muted);font-size:.88rem;margin-top:2px}
label{display:block;font-weight:600;font-size:.9rem;margin:8px 0 3px}input[type=text],input[type=number],select,textarea{width:100%;padding:8px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.searchbar{display:flex;gap:8px}.searchbar input{flex:1}button{padding:9px 14px;border:0;border-radius:6px;background:var(--acc);color:#fff;font:600 15px system-ui;cursor:pointer}
button.ghost{background:transparent;color:var(--acc);border:1px solid var(--acc)}button:disabled{opacity:.5;cursor:not-allowed}
#results{list-style:none;padding:0;margin:8px 0}#results li button{width:100%;text-align:left;background:var(--panel);color:var(--ink);border:1px solid var(--line);margin:3px 0;font-weight:400}
#results small{display:block;color:var(--muted)}#map{height:380px;border:1px solid var(--line);border-radius:8px;margin-top:8px}
.box{border:1px solid var(--line);border-radius:6px;padding:9px 12px;margin:8px 0;font-size:.92rem}.ok{background:var(--okbg);border-color:var(--ok)}.warn{background:var(--warnbg);border-color:var(--warn)}.stop{background:var(--stopbg);border-color:var(--stop)}
.ph{display:grid;grid-template-columns:72px 1fr;gap:10px;align-items:start;border-top:1px solid var(--line);padding:8px 0}.ph img{width:72px;height:72px;object-fit:cover;border-radius:4px;background:var(--panel)}
.ph .row{grid-template-columns:150px 1fr auto}.muted{color:var(--muted)}.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
details summary{cursor:pointer;font-weight:600}[hidden]{display:none!important}ul.f{margin:6px 0;padding-left:18px}ul.f li{margin:2px 0}
@media (max-width:640px){.ph .row{grid-template-columns:1fr}}
</style></head><body>
<header><h1>NZ Site Hazards</h1><small>Version __VERSION__ · draft reports for engineer review</small></header>
<main>

<section class="step"><h2><span class="num">1</span>What do you want to produce?</h2>
<div class="cards" id="types">
<label class="card"><input type="radio" name="rt" value="desk"><b>Geotechnical desk study</b><span>Geology, faults, seismic, council hazards, NZS 3604 exposure and NZS 3404.3 corrosivity.</span></label>
<label class="card"><input type="radio" name="rt" value="iga" checked><b>Initial geotechnical assessment</b><span>Desk study plus your Scala/hand auger spreadsheet and site photos, checked to NZS 3604 clause 3.3.</span></label>
</div></section>

<section class="step" id="s-field"><h2><span class="num">2</span>Upload the field spreadsheet and photos</h2>
<p class="hint">Upload the soil suitability spreadsheet (.xlsm or .xlsx) first: the address and project details are read from it. Then add the site photos.</p>
<label for="wb">Field spreadsheet</label><input id="wb" type="file" accept=".xlsm,.xlsx">
<div id="wb-out"></div>
<label for="ph">Site photos (select several at once; JPEG, PNG or iPhone HEIC)</label><input id="ph" type="file" accept="image/*,.heic,.heif" multiple>
<div id="ph-list"></div>
<details style="margin-top:10px"><summary>Footing assumptions for the NZS 3604 check</summary>
<div class="row">
<div><label for="fd">Footing depth below ground (m)</label><input id="fd" type="number" step="0.05" value="0.45"></div>
<div><label for="fw">Widest footing width (m)</label><input id="fw" type="number" step="0.05" value="0.30"></div>
<div><label for="fa">Building plan area (m²)</label><input id="fa" type="number" step="1" placeholder="sets the number of tests needed"></div>
<div><label for="crit">Blow-count criterion</label><select id="crit"><option value="exceeds">Exceeds 5 and 3 (clause wording)</option><option value="at_least">At least 5 and 3</option></select></div>
</div>
<label><input id="rock" type="checkbox" style="width:auto"> Refusal was on rock (confirmed by the engineer)</label>
</details>
</section>

<section class="step"><h2><span class="num" id="n-site">3</span>Find the site</h2>
<p class="hint">Type the street address (e.g. <i>1 Lambton Quay, Wellington</i>). If it is not found, type the legal description (e.g. <i>Lot 2 DP 12345</i>). Otherwise click the site on the map.</p>
<div class="searchbar"><input id="q" type="text" placeholder="Address, or Lot and DP number" autocomplete="off"><button id="find" type="button">Find</button></div>
<ul id="results"></ul>
<div id="map"></div>
<div id="site-box" class="box" hidden></div>
</section>

<section class="step" id="s-proj"><h2><span class="num" id="n-proj">4</span>Project details</h2>
<p class="hint">Filled from the spreadsheet where it has them. Check and complete.</p>
<div class="row">
<div><label for="p-client">Client</label><input id="p-client" type="text"></div>
<div><label for="p-job_no">Job number</label><input id="p-job_no" type="text"></div>
<div><label for="p-revision">Revision</label><input id="p-revision" type="text" value="0"></div>
<div><label for="p-company">Engineering company</label><input id="p-company" type="text" value=""></div>
<div><label for="p-prepared_by">Prepared by</label><input id="p-prepared_by" type="text"></div>
<div><label for="p-prepared_quals">Qualifications</label><input id="p-prepared_quals" type="text"></div>
<div><label for="p-reviewed_by">Reviewed by</label><input id="p-reviewed_by" type="text"></div>
<div><label for="p-reviewed_quals">Qualifications</label><input id="p-reviewed_quals" type="text"></div>
<div><label for="p-structure">Structure type</label><input id="p-structure" type="text"></div>
<div><label for="p-levels">Levels above ground</label><input id="p-levels" type="text"></div>
<div><label for="p-design_life">Design life</label><select id="p-design_life"><option>50 years</option><option>25 years</option><option>100 years</option><option>5 years</option></select></div>
<div><label for="p-importance_level">Importance level</label><select id="p-importance_level"><option>IL2</option><option>IL1</option><option>IL3</option><option>IL4</option></select></div>
</div>
<h3 style="font-size:1rem;margin:16px 0 2px">Report wording</h3>
<p class="hint">These go straight into the client report. Anything left blank appears highlighted for you to complete in Word.</p>
<div class="row">
<div><label for="p-project_name">Project name (optional)</label><input id="p-project_name" type="text" placeholder="e.g. Muir–O’Neil House"></div>
<div><label for="p-structure_desc">Project (cover page)</label><input id="p-structure_desc" type="text" placeholder="e.g. New two storey dwelling"></div>
<div><label for="p-status">Report status</label><select id="p-status"><option>Draft</option><option>Final</option></select></div>
<div><label for="p-authorisation">Professional authorisation</label><input id="p-authorisation" type="text" placeholder="e.g. Martin Pratchett – CPEng 1026589"></div>
</div>
<label for="p-development">Proposed development (completes “The proposed development comprises …”)</label>
<textarea id="p-development" rows="3" placeholder="e.g. a new two storey residential dwelling on sloping ground, as shown in the Architect’s concepts. It incorporates reinforced concrete masonry subfloor and retaining walls supporting a lightweight timber superstructure"></textarea>
<label for="p-documents">Documents reviewed (completes “The report considers …”)</label>
<input id="p-documents" type="text" placeholder="e.g. the Architect’s concept drawings dated 3 September 2026">
<label for="p-site_notes">Site description notes (added to section 2)</label>
<textarea id="p-site_notes" rows="2" placeholder="e.g. Excavation will be required to establish the lower floor. The greatest cuts are near the southern boundary"></textarea>
<div class="row">
<div><label for="p-subsoil_class">Seismic subsoil class (NZS 1170.5)</label><select id="p-subsoil_class"><option value="">Engineer to confirm</option><option>A</option><option>B</option><option>C</option><option>D</option><option>E</option></select></div>
<div><label for="p-bearing_position">Foundation position when good ground is not shown</label><select id="p-bearing_position">
<option value="tested">Further investigation required (default)</option>
<option value="verify_after_excavation">Adopt 300 kPa, verify after bulk excavation</option>
<option value="specific_design">Specifically designed foundations</option></select></div>
</div>
<label style="font-weight:400"><input id="p-excavation" type="checkbox" style="width:auto"> Excavation / earthworks proposed (adds excavation, contractor and hold-point wording)</label>
<label style="font-weight:400"><input id="p-retaining" type="checkbox" style="width:auto"> Retaining walls proposed (adds retaining-wall parameters table for you to complete)</label>
<details style="margin-top:10px" id="adv"><summary>Seismic and durability options</summary>
<div class="row">
<div><label for="apoe">Annual probability of exceedance (ULS)</label><select id="apoe"><option value="500" selected>1/500 (IL2, 50 years)</option><option value="1000">1/1000 (IL3)</option><option value="2500">1/2500 (IL4)</option><option value="250">1/250</option><option value="100">1/100</option><option value="25">1/25 (SLS1)</option></select></div>
<div><label for="vs30">Vs30 (m/s), if measured</label><input id="vs30" type="number"></div>
<div><label for="sc">Site class</label><select id="sc"><option value="">Suggest from Vs30 model</option><option>I</option><option>II</option><option>III</option><option>IV</option><option>V</option><option>VI</option></select></div>
<div><label for="surf">Steel surface (NZS 3404.3)</label><select id="surf"><option value="">Show all</option><option value="exposed">Exposed</option><option value="sheltered">Sheltered</option><option value="wet">Internal wet</option><option value="dry">Internal dry</option><option value="damp">Internal damp</option></select></div>
<div><label for="ct">Nearest coast type</label><select id="ct"><option value="">Work it out</option><option value="harbour">Harbour / calm saltwater</option><option value="east">East coast</option><option value="ni_ws">North Island west or south coast</option><option value="si_ws">South Island west or south coast</option></select></div>
</div></details>
</section>

<section class="step" id="s-wind"><h2><span class="num" id="n-wind">5</span>Wind calculation</h2>
<p class="hint">Opens the wind calculator in a new tab with the site and wind region filled in. Enter the building, check each direction, then press <b>Save to report</b> at the top of that page and come back here.</p>
<div class="actions"><button id="open-wind" type="button">Open the wind calculator</button><span id="wind-status" class="muted">Not saved yet.</span></div>
</section>

<section class="step"><h2><span class="num" id="n-go">6</span>Create the report</h2>
<div class="actions"><button id="go" type="button">Preview report</button><button id="word" type="button">Download Word document</button><button id="xl" type="button" class="ghost" hidden>Download spreadsheet with desk study filled in</button><span id="msg" class="muted" role="status"></span></div>
<p class="hint" style="margin-top:8px">The preview opens in a new tab with a <b>Download Word document</b> button; highlighted text needs your input. The first report for a council can take a minute while its hazard maps are looked up. Use the browser's Print → Save as PDF to file it.</p>
</section>
</main>
<script>
"use strict";
const WIND = __WIND__;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const state = { site: null, job: null, photos: [], wb: null, wbInfo: null };
const rt = () => document.querySelector("input[name=rt]:checked").value;

function layout() {
  const t = rt(), field = t === "iga" || t === "combined", wind = t === "wind" || t === "combined";
  $("s-field").hidden = !field; $("s-wind").hidden = !wind; $("xl").hidden = !field || !state.wb;
  let n = 0; document.querySelectorAll("main > section.step").forEach((sec) => { if (!sec.hidden) sec.querySelector(".num").textContent = ++n; });
  if (!WIND && wind) $("wind-status").textContent = "The wind calculator is not installed on this computer.";
}
document.querySelectorAll("input[name=rt]").forEach((r) => r.addEventListener("change", layout));

// ---------- map and search ----------
const map = L.map("map").setView([-41.0, 174.0], 5);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 20, maxNativeZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
let marker = null, parcel = null;
map.on("click", (e) => chooseSite({ lat: e.latlng.lat, lon: e.latlng.lng, label: "", kind: "map", source: "map click" }));

async function doSearch() {
  const q = $("q").value.trim(); if (!q) return;
  const ul = $("results"); ul.innerHTML = "<li><button disabled>Searching…</button></li>";
  try {
    const r = await fetch("/api/search?q=" + encodeURIComponent(q)); const j = await r.json();
    if (!j.results.length) { ul.innerHTML = `<li class="box warn">${esc(j.message)}${j.tried.length ? "<br><small>Searched: " + esc(j.tried.join("; ")) + "</small>" : ""}</li>`; return; }
    if (j.results.length === 1) { ul.innerHTML = ""; chooseSite(j.results[0]); return; }
    state.results = j.results;
    ul.innerHTML = `<li class="muted">${j.results.length} matches – choose one:</li>` + j.results.map((x, i) => `<li><button data-i="${i}">${esc(x.label)}<small>${x.kind === "legal" ? "Legal description" : "Address"} · ${esc(x.source)}</small></button></li>`).join("");
  } catch (e) { ul.innerHTML = `<li class="box stop">Search failed: ${esc(e.message)}. Click the site on the map instead.</li>`; }
}
$("find").onclick = doSearch;
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doSearch(); } });
$("results").addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) { chooseSite(state.results[+b.dataset.i]); $("results").innerHTML = ""; } });

async function chooseSite(x) {
  const prev = state.site || {};
  state.site = { lat: x.lat, lon: x.lon,
                 address: x.kind === "address" ? x.label : (prev.address || (state.wbInfo && state.wbInfo.address) || ""),
                 legal: x.legal || null, titles: x.titles || null, area_m2: x.area_m2 || null, parcel: x.parcel || null, source: x.source };
  if (marker) marker.setLatLng([x.lat, x.lon]); else marker = L.marker([x.lat, x.lon], { draggable: true }).addTo(map).on("dragend", (ev) => { const p = ev.target.getLatLng(); chooseSite({ lat: p.lat, lon: p.lng, kind: "map", source: "marker moved" }); });
  map.setView([x.lat, x.lon], 18);
  renderSite();
  if (!state.site.legal) {
    try { const r = await (await fetch(`/api/legal?lat=${x.lat}&lon=${x.lon}`)).json();
      if (r.status === "ok") Object.assign(state.site, { legal: r.legal, titles: r.titles, area_m2: r.area_m2, parcel: r.parcel || state.site.parcel }); } catch {}
  }
  try { const p = await (await fetch(`/api/prefill?lat=${x.lat}&lon=${x.lon}`)).json(); state.site.wind_region = p.wind_region && p.wind_region.region; } catch {}
  renderSite();
}
function renderSite() {
  const s = state.site, b = $("site-box"); b.hidden = false; b.className = "box ok";
  if (parcel) { map.removeLayer(parcel); parcel = null; }
  if (s.parcel) parcel = L.polygon(s.parcel.map((c) => [c[1], c[0]]), { color: "#d1495b", weight: 2, fill: false }).addTo(map);
  b.innerHTML = `<b>Site:</b> ${esc(s.address || "(no street address – type one below)")}<br>
    <b>Legal description:</b> ${esc(s.legal || "not found – enter from the Record of Title")}${s.titles ? " · Title " + esc(s.titles) : ""}${s.area_m2 ? " · " + s.area_m2 + " m²" : ""}<br>
    <b>Coordinates:</b> ${s.lat.toFixed(6)}, ${s.lon.toFixed(6)} <span class="muted">(${esc(s.source)}; drag the marker to adjust)</span>
    ${s.wind_region ? `<br><b>Wind region:</b> ${esc(s.wind_region)} <span class="muted">(Figure 3.1(B), digitised)</span>` : ""}
    <div class="row" style="margin-top:6px"><div><label for="s-addr">Address for the report</label><input id="s-addr" type="text" value="${esc(s.address || "")}"></div>
    <div><label for="s-legal">Legal description</label><input id="s-legal" type="text" value="${esc(s.legal || "")}"></div></div>`;
  $("s-addr").oninput = (e) => { s.address = e.target.value; };
  $("s-legal").oninput = (e) => { s.legal = e.target.value; };
}

// ---------- spreadsheet ----------
$("wb").addEventListener("change", async (e) => {
  const f = e.target.files[0]; state.wb = f || null; layout(); if (!f) return;
  const out = $("wb-out"); out.innerHTML = `<p class="muted">Reading ${esc(f.name)}…</p>`;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await fetch("/api/parse-workbook", { method: "POST", body: fd }); const j = await r.json();
    if (!r.ok) throw new Error(j.detail);
    state.wbInfo = j;
    for (const [k, v] of Object.entries(j.project || {})) { const el = $("p-" + k); if (el && v && !el.dataset.touched) { if (el.tagName === "SELECT" && ![...el.options].some((o) => o.text === v)) el.add(new Option(v)); el.value = v; } }
    out.innerHTML = `<div class="box ${j.verdict && j.verdict.includes("not") ? "stop" : "ok"}"><b>${esc(f.name)}</b>: ${j.scala_tests} Scala tests, ${j.auger_tests} hand auger log(s), tested ${esc(j.date || "?")} by ${esc(j.technician || "?")}.<br><b>${esc(j.verdict || "No Scala results found")}</b> <span class="muted">(default footing 0.45 m deep, 0.3 m wide – change below)</span>
      ${j.findings.length ? `<ul class="f">${j.findings.map(([l, t]) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
      ${j.issues.length ? `<b>Spreadsheet checks:</b><ul class="f">${j.issues.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}</div>`;
    if (j.address && !state.site) { $("q").value = j.address; out.insertAdjacentHTML("beforeend", `<p class="muted" id="wb-search">Address from the spreadsheet, “${esc(j.address)}”, copied into step 3 and searched.</p>`); doSearch(); }
  } catch (err) { out.innerHTML = `<div class="box stop">${esc(err.message)}</div>`; }
});
document.querySelectorAll("[id^=p-]").forEach((el) => el.addEventListener("input", () => { el.dataset.touched = 1; }));

// ---------- photos ----------
const KINDS = { plan: "Site plan / layout (Appendix A)", overview: "Site overview", test: "Test location", scala: "Scala penetrometer", auger: "Hand auger / soil sample", feature: "Site feature", other: "Other" };
$("ph").addEventListener("change", (e) => {
  for (const f of e.target.files) state.photos.push({ file: f, caption: "", kind: "overview", include: true, url: URL.createObjectURL(f) });
  e.target.value = ""; renderPhotos();
});
function renderPhotos() {
  $("ph-list").innerHTML = state.photos.map((p, i) => `<div class="ph"><img src="${p.url}" alt="" onerror="this.style.visibility='hidden'">
    <div><div class="muted">${esc(p.file.name)}</div><div class="row">
    <select data-i="${i}" data-k="kind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}" ${p.kind === k ? "selected" : ""}>${v}</option>`).join("")}</select>
    <input data-i="${i}" data-k="caption" type="text" placeholder="Caption: what the photo shows, slope and direction" value="${esc(p.caption)}">
    <label style="margin:0;font-weight:400"><input data-i="${i}" data-k="include" type="checkbox" ${p.include ? "checked" : ""} style="width:auto"> Include</label></div></div></div>`).join("")
    + (state.photos.length ? `<p class="muted">${state.photos.length} photo(s). They are numbered in this order in the report.</p>` : "");
}
$("ph-list").addEventListener("input", (e) => { const t = e.target, i = t.dataset.i; if (i === undefined) return; state.photos[i][t.dataset.k] = t.type === "checkbox" ? t.checked : t.value; });

// ---------- job ----------
function meta() {
  const proj = {}; document.querySelectorAll("[id^=p-]").forEach((el) => { proj[el.id.slice(2)] = el.type === "checkbox" ? el.checked : el.value; });
  return { job_id: state.job, report_type: rt(), site: state.site, project: proj,
    field_inputs: { footing_depth_m: $("fd").value, footing_width_m: $("fw").value, floor_area_m2: $("fa").value, criterion: $("crit").value, rock_at_refusal: $("rock").checked },
    options: { apoe_n: $("apoe").value, vs30: $("vs30").value, site_class: $("sc").value, surface_condition: $("surf").value, coast_type: $("ct").value } };
}
async function saveJob() {
  if (!state.site) throw new Error("Find the site first.");
  const fd = new FormData(); fd.append("meta", JSON.stringify(meta()));
  const field = rt() === "iga" || rt() === "combined";
  if (field && state.wb && !state.wbSent) fd.append("workbook", state.wb);
  const send = field && state.photos.length && !state.photosSent;
  if (send) state.photos.forEach((p) => fd.append("photos", p.file));
  fd.append("photo_meta", JSON.stringify(state.photos.map(({ caption, kind, include }) => ({ caption, kind, include }))));
  const r = await fetch("/api/jobs", { method: "POST", body: fd }); const j = await r.json();
  if (!r.ok) throw new Error(j.detail);
  state.job = j.id; if (field && state.wb) state.wbSent = true; if (send) state.photosSent = true;
  return j;
}
$("ph").addEventListener("change", () => { state.photosSent = false; });
$("wb").addEventListener("change", () => { state.wbSent = false; });

$("open-wind").onclick = async () => {
  try {
    await saveJob();
    const s = state.site, P = new URLSearchParams({ job: state.job, lat: s.lat, lon: s.lon, name: s.address || "" });
    if (s.wind_region) P.set("region", s.wind_region);
    const il = ($("p-importance_level").value.match(/\d/) || [])[0]; if (il) P.set("il", il);
    const life = { "50 years": "50_years", "25 years": "25_years", "100 years": "100_years_plus", "5 years": "5_years" }[$("p-design_life").value]; if (life) P.set("life", life);
    window.open("/wind/?" + P.toString(), "_blank");
    $("wind-status").textContent = "Wind calculator open in another tab. Waiting for Save to report…";
    poll();
  } catch (e) { $("wind-status").textContent = e.message; }
};
let pollTimer = null;
function poll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!state.job) return;
    const j = await (await fetch("/api/jobs/" + state.job)).json();
    if (j.has_wind) { $("wind-status").innerHTML = `<b style="color:var(--ok)">Wind calculation saved ${esc(j.wind_saved)}.</b>`; clearInterval(pollTimer); }
  }, 3000);
}
$("go").onclick = async () => {
  const m = $("msg"); m.textContent = "Saving…";
  try {
    await saveJob();
    window.open(`/api/jobs/${state.job}/report`, "_blank");
    m.textContent = "Report opening in a new tab.";
  } catch (e) { m.textContent = e.message; }
};
$("word").onclick = async () => {
  const m = $("msg"); m.textContent = "Preparing the Word document…";
  try { await saveJob(); location.href = `/api/jobs/${state.job}/report.docx`; m.textContent = "Word document downloading."; } catch (e) { m.textContent = e.message; }
};
$("xl").onclick = async () => {
  try { await saveJob(); location.href = `/api/jobs/${state.job}/workbook`; } catch (e) { $("msg").textContent = e.message; }
};
layout();
</script></body></html>"""
