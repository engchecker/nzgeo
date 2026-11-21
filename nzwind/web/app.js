"use strict";
const DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const BEARING = Object.fromEntries(DIRS.map((d, i) => [d, i * 45]));
const TC_VAR = { 1: "--tc1", 2: "--tc2", 2.5: "--tc25", 3: "--tc3", 4: "--tc4" };
const form = document.getElementById("inputs");
const $ = (id) => document.getElementById(id);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const tcColour = (tc) => css(TC_VAR[tc] || "--tc2");

const state = {
  selected: "N",
  dirs: Object.fromEntries(DIRS.map((d) => [d, blankDir()])),
  result: null, meta: null, auto: null, autoKey: null,
};

function blankDir() {
  return { bands: [{ tc: 3, to_m: 2000 }], shielding: [], topo: { kind: "none", H: 0, Lu: 0, x: 0, peak_zone: false },
           mzcat_override: null, ms_override: null, mh_override: null, mlee_override: null, suggested: null };
}

// ---------- form values ----------
const num = (name) => { const v = form.elements[name].value; return v === "" ? null : Number(v); };
function building() {
  return {
    name: form.elements.name.value,
    eaves_height_m: num("eaves_height_m"), ridge_height_m: num("ridge_height_m"),
    length_m: num("length_m"), width_m: num("width_m"),
    orientation_deg: ((num("orientation_deg") ?? 0) % 360 + 360) % 360,
    reference_height_m: num("reference_height_m"),
    circular_section: form.elements.circular_section.checked,
  };
}
const hOf = (b) => ((b.eaves_height_m ?? 0) + (b.ridge_height_m ?? 0)) / 2;
const zOf = (b) => b.reference_height_m || hOf(b);
const windowOf = (z) => [20 * z, 20 * z + Math.max(500, 40 * z)];
function site() {
  const lat = num("lat"), lon = num("lon");
  return lat === null || lon === null ? null : { lat, lon };
}
const fmt0 = (v) => Math.round(v).toLocaleString("en-NZ");
const f2 = (v) => Number(v).toFixed(2);
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sameJSON = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ---------- suggestion status ----------
function terrainStatus(d) {
  const dir = state.dirs[d];
  if (!dir.suggested) return "manual";
  return sameJSON(dir.bands, dir.suggested.bands) && dir.mzcat_override === null ? "suggested" : "edited";
}
function topoStatus(d) {
  const dir = state.dirs[d];
  if (!dir.suggested || !dir.suggested.topo) return "manual";
  return sameJSON(dir.topo, dir.suggested.topo) && dir.mh_override === null ? "suggested" : "edited";
}
const STATUS_TEXT = { suggested: "Suggested", edited: "Edited by engineer", manual: "Manual" };

// ---------- direction tabs ----------
function renderTabs() {
  const res = state.result;
  $("dir-tabs").innerHTML = DIRS.map((d) => {
    const row = res && res.directions.find((r) => r.direction === d);
    const sub = row ? `${row.Vsit.toFixed(1)} m/s` : bandSummary(state.dirs[d]);
    const st = terrainStatus(d) === "edited" || topoStatus(d) === "edited" ? "edited" : terrainStatus(d);
    const stTxt = st === "manual" ? "" : `<span class="st ${st}">${st === "edited" ? "Edited" : "Suggested"}</span>`;
    return `<button type="button" class="dir-tab" role="tab" aria-selected="${d === state.selected}" data-dir="${d}"><b>${d}</b><small>${sub}</small>${stTxt}</button>`;
  }).join("");
}
function bandSummary(dir) {
  return dir.mzcat_override ? `Mz ${dir.mzcat_override}` : dir.bands.map((b) => "TC" + b.tc).join(", ") || "no terrain";
}
function selectDir(d) { state.selected = d; renderTabs(); renderEditor(); renderEvidence(); drawMapOverlays(); }
$("dir-tabs").addEventListener("click", (e) => { const t = e.target.closest(".dir-tab"); if (t) selectDir(t.dataset.dir); });
$("dir-tabs").addEventListener("keydown", (e) => {
  if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
  selectDir(DIRS[(DIRS.indexOf(state.selected) + (e.key === "ArrowRight" ? 1 : 7)) % 8]);
  $("dir-tabs").querySelector(`[data-dir="${state.selected}"]`).focus();
});

// ---------- terrain strip (evidence graphic) ----------
function strip(bins, z, coverage) {
  const W = 640, H = 58, pad = 6, [a, b] = windowOf(z), end = Math.max(coverage, b);
  const X = (m) => pad + (W - 2 * pad) * m / end;
  let s = `<svg class="strip" viewBox="0 0 ${W} ${H}" role="img" aria-label="Proposed terrain category by distance upwind">`;
  bins.forEach((x) => {
    const lowConf = x.confidence === "low";
    s += `<rect x="${X(x.start_m)}" y="14" width="${X(x.end_m) - X(x.start_m)}" height="18" fill="${tcColour(x.tc)}" ${lowConf ? 'fill-opacity="0.55"' : ""}><title>${x.start_m}–${x.end_m} m: TC${x.tc} (${x.confidence})</title></rect>`;
  });
  s += `<rect x="${X(0)}" y="14" width="${X(a) - X(0)}" height="18" fill="${css("--panel")}" fill-opacity="0.65"><title>Lag distance 20z: ignored</title></rect>`;
  s += `<path d="M${X(a)} 36 v6 H${X(b)} v-6" fill="none" stroke="${css("--wind")}" stroke-width="1.5"/>`;
  s += `<text x="${X(a)}" y="54">${fmt0(a)} m</text><text x="${X(b)}" y="54" text-anchor="end">${fmt0(b)} m</text>`;
  s += `<text x="${(X(a) + X(b)) / 2}" y="54" text-anchor="middle" fill="${css("--wind")}">averaging window</text>`;
  s += `<text x="${X(0)}" y="10">site</text><text x="${X(end)}" y="10" text-anchor="end">upwind</text>`;
  if (coverage < b) s += `<text x="${X(coverage)}" y="10" text-anchor="middle" fill="${css("--bad")}">mapped to ${fmt0(coverage)} m</text>`;
  return s + "</svg>";
}

// ---------- elevation profile ----------
function profileSvg(t, z) {
  if (!t || !t.profile) return "";
  const p = t.profile, pts = p.s.map((s, i) => [s, p.z[i]]).filter((q) => q[1] !== null);
  if (pts.length < 2) return "";
  const W = 640, H = 170, l = 40, r = 10, top = 12, bot = 26;
  const smin = pts[0][0], smax = pts.at(-1)[0];
  const zs = pts.map((q) => q[1]), zmin = Math.min(...zs), zmax = Math.max(...zs) + Math.max(5, z);
  const X = (s) => l + (W - l - r) * (s - smin) / (smax - smin), Y = (e) => top + (H - top - bot) * (1 - (e - zmin) / Math.max(zmax - zmin, 1));
  let d = `M${X(pts[0][0])} ${H - bot}` + pts.map((q) => ` L${X(q[0]).toFixed(1)} ${Y(q[1]).toFixed(1)}`).join("") + ` L${X(smax)} ${H - bot} Z`;
  let s = `<svg class="profile" viewBox="0 0 ${W} ${H}" role="img" aria-label="Ground profile through the site"><path class="ground" d="${d}"/>`;
  s += `<line class="axis" x1="${l}" x2="${W - r}" y1="${H - bot}" y2="${H - bot}"/>`;
  s += `<text x="${l}" y="${H - 8}">${fmt0(-smin)} m upwind</text><text x="${W - r}" y="${H - 8}" text-anchor="end">${fmt0(smax)} m downwind</text>`;
  s += `<text x="4" y="${Y(zmax) + 10}">${zmax.toFixed(0)}</text><text x="4" y="${Y(zmin)}">${zmin.toFixed(0)} m</text>`;
  const ze = pts.reduce((a, q) => (Math.abs(q[0]) < Math.abs(a[0]) ? q : a))[1];
  s += `<rect class="site" x="${X(0) - 3}" y="${Y(ze + z)}" width="6" height="${Y(ze) - Y(ze + z)}"><title>Site, z = ${z.toFixed(1)} m</title></rect>`;
  if (t.feature && t.feature.kind !== "none") {
    const cs = t.crest_s, ce = t.crest_E, f = t.feature;
    s += `<line class="mark" x1="${X(cs)}" x2="${X(cs)}" y1="${Y(ce)}" y2="${Y(ce - f.H)}"/>`;
    s += `<text class="mark-text" x="${X(cs) + 6}" y="${Y(ce - f.H * 0.25)}">H ${f.H} m</text>`;
    s += `<line class="mark" x1="${X(cs - f.Lu)}" x2="${X(cs)}" y1="${Y(ce - f.H / 2)}" y2="${Y(ce - f.H / 2)}" stroke-dasharray="3 3"/>`;
    s += `<text class="mark-text" x="${X(cs - f.Lu) - 6}" y="${Y(ce - f.H / 2) + 4}" text-anchor="end">Lu ${f.Lu} m</text>`;
    s += `<text class="mark-text" x="${X(cs)}" y="${Y(ce) - 4}" text-anchor="middle">crest</text>`;
  }
  return s + "</svg>";
}

// ---------- direction editor ----------
function renderEditor() {
  const d = state.selected, dir = state.dirs[d], b = building();
  const z = zOf(b), h = hOf(b), [lag, win] = windowOf(z);
  const tcOpts = (v) => [1, 2, 2.5, 3, 4].map((c) => `<option value="${c}" ${c == v ? "selected" : ""}>TC${c}</option>`).join("");
  const ts = terrainStatus(d), ps = topoStatus(d);
  const auto = state.auto && state.auto.directions[d];
  const sug = dir.suggested;
  const terrainSuggest = sug ? `
    <div class="suggest">
      <div class="suggest-head"><strong>Suggested from mapping</strong><span class="status ${ts}">${STATUS_TEXT[ts]}</span></div>
      ${strip(auto.bins, z, auto.coverage_m)}
      <div class="suggest-head"><span class="small muted">${sug.bands.map((x, i) => `TC${x.tc} to ${fmt0(x.to_m)} m`).join(", ")}</span>
      ${ts !== "suggested" ? `<button type="button" class="link" data-use="bands">Use suggested bands</button>` : ""}</div>
    </div>` : "";
  const f = sug && sug.topo;
  const topoSuggest = sug && auto.topography ? `
    <div class="suggest">
      <div class="suggest-head"><strong>Suggested from LiDAR profile</strong><span class="status ${ps}">${STATUS_TEXT[ps]}</span></div>
      <p class="small" style="margin:0">${f.kind === "none" ? "No hill, ridge or escarpment raises M<sub>h</sub> above 1.0." :
        `${f.kind === "hill" ? "Hill or ridge" : "Escarpment"}: H ${f.H} m, L<sub>u</sub> ${f.Lu} m, x ${f.x} m, section at ${auto.topography.bearing}°, M<sub>h</sub> ${auto.topography.mh}`}</p>
      ${profileSvg(auto.topography, z)}
      ${(auto.topography.flags || []).map((x) => `<p class="small conf-medium" style="margin:4px 0 0">${escapeHtml(x)}</p>`).join("")}
      ${ps !== "suggested" ? `<button type="button" class="link" data-use="topo">Use suggested feature</button>` : ""}
    </div>` : "";
  $("dir-editor").innerHTML = `
  <div class="block">
    <h3>Terrain, wind from ${d}</h3>
    ${terrainSuggest}
    <p class="note">${sug ? "Bands used in the calculation. Edit any band to override the suggestion." : "Enter terrain upwind of the site, nearest first. Each band runs from the end of the previous one."}</p>
    <table class="rows"><thead><tr><th>Category</th><th>Ends at (m upwind)</th><th></th></tr></thead><tbody>
      ${dir.bands.map((bd, i) => `<tr>
        <td><select data-k="bands.${i}.tc" aria-label="Band ${i + 1} terrain category">${tcOpts(bd.tc)}</select></td>
        <td><input type="number" min="1" step="any" value="${bd.to_m}" data-k="bands.${i}.to_m" aria-label="Band ${i + 1} end distance"></td>
        <td><button type="button" class="icon" data-del="bands.${i}" aria-label="Remove band ${i + 1}">Remove</button></td></tr>`).join("")}
    </tbody></table>
    <button type="button" class="link" data-add="bands">Add band</button>
    <p class="window-note">Averaging window ${fmt0(lag)}–${fmt0(win)} m upwind (lag 20z, then max(500 m, 40z)).</p>
  </div>
  <div class="block">
    <h3>Topography</h3>
    ${topoSuggest}
    <p class="note">Most adverse cross-section within ±22.5° of ${d}. x is negative upwind of the crest, positive downwind.</p>
    <div class="grid4">
      <label>Feature<select data-k="topo.kind">
        ${["none", "hill", "escarpment"].map((k) => `<option value="${k}" ${dir.topo.kind === k ? "selected" : ""}>${{ none: "None", hill: "Hill or ridge", escarpment: "Escarpment" }[k]}</option>`).join("")}
      </select></label>
      <label>H (m)<input type="number" step="any" min="0" value="${dir.topo.H}" data-k="topo.H"></label>
      <label>L<sub>u</sub> (m)<input type="number" step="any" min="0" value="${dir.topo.Lu}" data-k="topo.Lu"></label>
      <label>x (m)<input type="number" step="any" value="${dir.topo.x}" data-k="topo.x"></label>
    </div>
    <label class="check"><input type="checkbox" ${dir.topo.peak_zone ? "checked" : ""} data-k="topo.peak_zone"><span>Site within the peak zone of Figure 4.5 (upwind slope over 0.45)</span></label>
  </div>
  <div class="block">
    <h3>Shielding buildings</h3>
    <p class="note">Buildings in the 45° sector within 20h = ${fmt0(20 * h)} m, at least h = ${h.toFixed(1)} m tall. No trees or vegetation. ${h > 25 ? "<strong>h exceeds 25 m, so shielding does not apply.</strong>" : ""}</p>
    <table class="rows"><thead><tr><th>Height (m)</th><th>Breadth (m)</th><th>Distance (m)</th><th class="w-check" title="Upwind ground slope over 0.2 and building not higher above datum (Figure 4.2)">Slope excl.</th><th></th></tr></thead><tbody>
      ${dir.shielding.map((s, i) => `<tr>
        <td><input type="number" min="0" step="any" value="${s.height_m}" data-k="shielding.${i}.height_m" aria-label="Building ${i + 1} height"></td>
        <td><input type="number" min="0" step="any" value="${s.breadth_m}" data-k="shielding.${i}.breadth_m" aria-label="Building ${i + 1} breadth"></td>
        <td><input type="number" min="0" step="any" value="${s.distance_m}" data-k="shielding.${i}.distance_m" aria-label="Building ${i + 1} distance"></td>
        <td class="w-check"><input type="checkbox" ${s.slope_excluded ? "checked" : ""} data-k="shielding.${i}.slope_excluded" aria-label="Building ${i + 1} excluded by slope"></td>
        <td><button type="button" class="icon" data-del="shielding.${i}" aria-label="Remove building ${i + 1}">Remove</button>${s.bearing_deg !== undefined ? `<br><small class="muted">LINZ #${s.id}, ${s.bearing_deg}°${s.borderline ? ", near sector edge" : ""}${s.ground_gradient !== undefined ? `, slope ${s.ground_gradient}` : ""}</small>` : ""}</td></tr>`).join("")}
    </tbody></table>
    <button type="button" class="link" data-add="shielding">Add building</button>
    ${shieldNote(d, dir)}
  </div>
  <div class="block">
    <h3>Engineer overrides</h3>
    <p class="note">Leave blank to use the calculated value. Overrides are listed in the results.</p>
    <div class="grid4">
      ${[["mzcat_override", "M<sub>z,cat</sub>"], ["ms_override", "M<sub>s</sub>"], ["mh_override", "M<sub>h</sub>"], ["mlee_override", "M<sub>lee</sub>"]]
        .map(([k, l]) => `<label>${l}<input type="number" step="0.01" min="0" value="${dir[k] ?? ""}" data-k="${k}"></label>`).join("")}
    </div>
  </div>`;
}

function setPath(obj, path, value) {
  const keys = path.split("."); let o = obj;
  for (let i = 0; i < keys.length - 1; i++) o = o[keys[i]];
  o[keys.at(-1)] = value;
}
$("dir-editor").addEventListener("change", (e) => {
  const k = e.target.dataset.k; if (!k) return;
  const dir = state.dirs[state.selected];
  let v;
  if (e.target.type === "checkbox") v = e.target.checked;
  else if (k === "topo.kind") v = e.target.value;
  else v = e.target.value === "" ? (k.endsWith("override") ? null : 0) : Number(e.target.value);
  setPath(dir, k, v);
  renderEditor(); renderTabs(); schedule();
});
$("dir-editor").addEventListener("click", (e) => {
  const dir = state.dirs[state.selected], t = e.target;
  if (t.dataset.add === "bands") {
    const last = dir.bands.at(-1); dir.bands.push({ tc: last ? last.tc : 3, to_m: (last ? last.to_m : 0) + 1000 });
  } else if (t.dataset.add === "shielding") {
    dir.shielding.push({ height_m: Math.max(hOf(building()), 3), breadth_m: 10, distance_m: 30, slope_excluded: false });
  } else if (t.dataset.del) {
    const [list, i] = t.dataset.del.split("."); dir[list].splice(Number(i), 1);
  } else if (t.dataset.use === "bands") {
    dir.bands = structuredClone(dir.suggested.bands); dir.mzcat_override = null;
  } else if (t.dataset.use === "topo") {
    dir.topo = structuredClone(dir.suggested.topo); dir.mh_override = null;
  } else return;
  renderEditor(); renderTabs(); schedule();
});
$("copy-all").addEventListener("click", () => {
  const src = state.dirs[state.selected];
  DIRS.forEach((d) => {
    if (d === state.selected) return;
    const keep = state.dirs[d].suggested;
    state.dirs[d] = structuredClone(src); state.dirs[d].suggested = keep;
  });
  renderTabs(); schedule();
  $("copy-all").textContent = `Copied ${state.selected} to all directions`;
  setTimeout(() => { $("copy-all").textContent = "Copy this direction to all"; }, 2000);
});

// ---------- evidence ----------
function renderEvidence() {
  const d = state.selected, auto = state.auto && state.auto.directions[d];
  if (!auto) { $("evidence").innerHTML = ""; return; }
  const z = zOf(building()), [a, b] = windowOf(z);
  const flags = [...new Set(auto.bins.filter((x) => x.end_m > a && x.start_m < b).flatMap((x) => x.flags))];
  const bands = auto.bands.map((x, i) => `<li><span class="tcchip" style="background:${tcColour(x.tc)}">TC${x.tc}</span>
      <span>${fmt0(x.start_m)}–${fmt0(x.end_m)} m</span><span class="conf-${x.confidence}">${x.confidence} confidence</span>
      <button type="button" class="link" data-street="${i}">Street-level view</button></li>`).join("");
  const m = (x, k, p = 1) => (x.metrics[k] === null || x.metrics[k] === undefined ? "–" : Number(x.metrics[k]).toFixed(p));
  const rows = auto.bins.map((x) => `<tr class="${x.end_m <= a ? "lag" : ""}">
      <td>${x.start_m}–${x.end_m}</td><td>TC${x.tc}</td><td>${x.tc_low === x.tc_high ? "" : `${x.tc_low}–${x.tc_high}`}</td>
      <td class="conf-${x.confidence}">${x.confidence}</td><td>${m(x, "bldg_per_ha")}</td><td>${m(x, "house_eq_per_ha")}</td>
      <td>${m(x, "bldg_h_mean")}</td><td>${m(x, "obstructions_per_ha")}</td><td>${m(x, "tall_isolated_per_ha")}</td>
      <td>${(x.metrics.tall_veg_cover * 100).toFixed(0)}%</td><td>${(x.metrics.water_frac * 100).toFixed(0)}%</td>
      <td>${x.tc_z0 === null ? "n/a" : x.tc_z0.toFixed(1)}</td>
      <td class="rule">${escapeHtml(x.rule)}${x.flags.length ? "<br>" + x.flags.map(escapeHtml).join("<br>") : ""}</td></tr>`).join("");
  $("evidence").innerHTML = `
    <h3>Evidence for wind from ${d}</h3>
    <ul class="band-list">${bands}</ul>
    ${flags.length ? `<ul class="flags">${flags.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
    <details><summary>Measurements for each 50 m bin</summary>
      <div class="bins-wrap"><table class="bins"><thead><tr>
        <th>Distance (m)</th><th>TC</th><th>Range</th><th>Confidence</th><th>Bldg/ha</th><th>House eq./ha</th>
        <th>Bldg h (m)</th><th>Obstr./ha</th><th>&gt;5 m /ha</th><th>Tall veg.</th><th>Water</th><th>z0 check</th><th style="text-align:left">Rule applied</th>
      </tr></thead><tbody>${rows}</tbody></table></div>
      <p class="small muted">Bins within the lag distance (faded) are ignored by Clause 4.2.3. "z0 check" is the category implied by roughness length (Note to Cl 4.2.1), used only to set confidence.</p>
    </details>`;
}
$("evidence").addEventListener("click", async (e) => {
  const i = e.target.dataset.street; if (i === undefined) return;
  const band = state.auto.directions[state.selected].bands[Number(i)];
  const [lon, lat] = band.evidence_point;
  const heading = (BEARING[state.selected] + 180) % 360;
  openStreet(lon, lat, heading, `TC${band.tc}, ${fmt0(band.start_m)}–${fmt0(band.end_m)} m upwind (${state.selected})`);
});

let mlyViewer = null;
async function openStreet(lon, lat, heading, title) {
  const dlg = $("street");
  $("street-title").textContent = `Street-level view: ${title}`;
  const r = await (await fetch(`api/streetlevel?lon=${lon}&lat=${lat}&heading=${heading}`)).json();
  const gLink = `<a href="${r.google_street_view}" target="_blank" rel="noopener">Open Google Street View at this point</a> (for viewing only; not used in the classification).`;
  const mly = r.mapillary;
  if (mly && mly.id && state.meta.mapillary_token && window.mapillary) {
    $("mly").hidden = false;
    if (!mlyViewer) mlyViewer = new mapillary.Viewer({ accessToken: state.meta.mapillary_token, container: "mly", imageId: mly.id });
    else mlyViewer.moveTo(mly.id).catch(() => {});
    $("street-note").innerHTML = `Mapillary image ${mly.id}${mly.captured_at ? ", captured " + new Date(mly.captured_at).toLocaleDateString("en-NZ") : ""}. ${gLink}`;
  } else {
    $("mly").hidden = true;
    $("street-note").innerHTML = `${state.meta.mapillary_token ? "No Mapillary image within about 200 m." : "Set MAPILLARY_TOKEN to view Mapillary imagery here."} ${gLink}`;
  }
  dlg.showModal();
}
$("street-close").addEventListener("click", () => $("street").close());

// ---------- data panel ----------
const ASSUMPTIONS = [
  ["bin_m", "Radial bin length along each sector", "m"], ["house_area_m2", "Plan area of one house-size obstruction", "m²"],
  ["tc3_house_eq_per_ha", "House-size obstructions per ha for TC3 (Cl 4.2.1(d))", "/ha"],
  ["tc2_max_per_ha", "Maximum obstructions per ha for TC2 (Cl 4.2.1(b))", "/ha"],
  ["tc4_min_h", "Minimum mean building height for TC4 (Cl 4.2.1(e))", "m"],
  ["dense_forest_cover", "Tall vegetation cover treated as dense forest (TC3)", ""],
  ["some_trees_cover", "Tall vegetation cover treated as some trees (TC2.5)", ""],
  ["tall_isolated_per_ha", "Isolated obstructions over 5 m per ha giving TC2.5", "/ha"],
  ["water_frac", "Water fraction treated as a water surface (TC1)", ""],
  ["near_threshold", "Within this fraction of a threshold, the neighbouring TC is shown as the range", ""],
];
function renderDataPanel() {
  const a = state.auto; if (!a) { $("data-panel").hidden = true; return; }
  $("data-panel").hidden = false;
  const prov = Object.entries(a.provenance).map(([k, v]) => `<tr><td><strong>${escapeHtml(k)}</strong></td><td>${escapeHtml(typeof v === "string" ? v : Object.entries(v).map(([kk, vv]) => `${kk}: ${Array.isArray(vv) ? vv.join(", ") : vv}`).join("; "))}</td></tr>`).join("");
  const asm = ASSUMPTIONS.map(([k, t, u]) => `<tr><td>${t}</td><td>${a.parameters[k]} ${u}</td></tr>`).join("");
  const issues = [...a.issues, ...a.flags];
  $("data-body").innerHTML = `
    ${a.demo ? `<p class="demo-banner">Demonstration data: synthetic terrain, not the real site.</p>` : ""}
    <h3>Sources</h3><table>${prov || "<tr><td>None</td></tr>"}</table>
    <h3 style="margin-top:14px">Classification assumptions</h3>
    <p class="small muted">Thresholds from Clause 4.2.1 are applied as written; the others are assumptions to confirm against benchmark sites.</p>
    <table>${asm}</table>
    ${issues.length ? `<h3 style="margin-top:14px">Issues</h3><ul class="warnings">${issues.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}`;
}

// ---------- shielding suggestions ----------
function shieldNote(d, dir) {
  const a = state.auto && state.auto.directions[d] && state.auto.directions[d].shielding;
  if (!state.auto) return `<p class="note">Map terrain to suggest shielding buildings from LINZ outlines and LiDAR heights.</p>`;
  if (!a) return `<p class="note">${escapeHtml((state.auto.shielding && state.auto.shielding.reason) || "No shielding suggestion for this direction.")}</p>`;
  const sug = dir.suggested && dir.suggested.shielding;
  const same = sug && JSON.stringify(sug.map(shKey).sort()) === JSON.stringify(dir.shielding.map(shKey).sort());
  const ex = a.excluded || [];
  return `<p class="note">${sug ? (same ? "Suggested from LINZ building outlines and LiDAR heights." : "<strong>Edited</strong> from the suggestion (" + sug.length + " building(s)).") : ""}
    ${ex.length ? ` ${ex.length} building(s) in the sector left out: ` + ex.slice(0, 6).map((x) => `#${x.id} at ${fmt0(x.distance_m)} m (${escapeHtml(x.reason)})`).join("; ") + (ex.length > 6 ? "…" : "") : ""}
    ${(a.flags || []).map((f) => `<br>${escapeHtml(f)}`).join("")}
    ${sug && !same ? ` <button type="button" class="link" data-restore-shield="${d}">Restore suggestion</button>` : ""}</p>`;
}
const shKey = (x) => [Number(x.height_m).toFixed(1), Number(x.breadth_m).toFixed(1), Number(x.distance_m).toFixed(1), !!x.slope_excluded].join("|");
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-restore-shield]"); if (!t) return;
  const dir = state.dirs[t.dataset.restoreShield]; dir.shielding = structuredClone(dir.suggested.shielding); dir.ms_override = null;
  renderEditor(); schedule();
});

// ---------- automatic mapping ----------
function bandsFromBins(bins, key) {
  const out = [];
  bins.forEach((b) => {
    const tc = b[key];
    if (out.length && out.at(-1).tc === tc) out.at(-1).to_m = b.end_m; else out.push({ tc, to_m: b.end_m });
  });
  return out;
}
async function runAuto() {
  const s = site(), b = building(); if (!s) return;
  const btn = $("auto"), st = $("auto-status");
  btn.disabled = true; st.className = "small"; st.textContent = "Fetching LiDAR, buildings, land cover and imagery. This can take a minute for a new site.";
  try {
    const r = await fetch("api/auto", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lon: s.lon, lat: s.lat, h: hOf(b), z: zOf(b) }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "Mapping failed");
    state.auto = j; state.autoKey = `${s.lon},${s.lat}`;
    DIRS.forEach((d) => {
      const a = j.directions[d], dir = state.dirs[d];
      const sugBands = bandsFromBins(a.bins, "tc");
      const sugTopo = a.topography ? structuredClone(a.topography.feature) : null;
      const sugShield = a.shielding ? a.shielding.buildings.map((x) => ({ height_m: x.height_m, breadth_m: x.breadth_m, distance_m: x.distance_m,
        slope_excluded: !!x.slope_excluded, id: x.id, bearing_deg: x.bearing_deg, borderline: !!x.borderline, ground_gradient: x.ground_gradient })) : null;
      dir.suggested = { bands: sugBands, low: bandsFromBins(a.bins, "tc_low"), high: bandsFromBins(a.bins, "tc_high"), topo: sugTopo, shielding: sugShield };
      dir.bands = structuredClone(sugBands); dir.mzcat_override = null;
      if (sugShield) { dir.shielding = structuredClone(sugShield); dir.ms_override = null; }
      if (sugTopo) { dir.topo = structuredClone(sugTopo); dir.mh_override = null; }
    });
    if (j.site.elevation_m !== null) { form.elements.elevation_m.value = j.site.elevation_m; $("elev-src").hidden = false; }
    const nIssues = j.issues.length;
    st.textContent = `${j.demo ? "Demonstration data mapped" : "Mapped"}: suggestions loaded for all eight directions.${nIssues ? ` ${nIssues} data issue(s); see Data used.` : ""}`;
    $("tc-key").hidden = false;
    renderTabs(); renderEditor(); renderEvidence(); renderDataPanel(); drawMapOverlays(); schedule();
  } catch (e) {
    st.className = "small err"; st.textContent = e.message;
  } finally { btn.disabled = !site(); }
}
$("auto").addEventListener("click", runAuto);

// ---------- site search ----------
async function doSearch() {
  const q = $("q").value.trim(); if (!q) return;
  const ul = $("search-results"); ul.hidden = false; ul.innerHTML = `<li><button type="button" disabled>Searching…</button></li>`;
  try {
    const r = await fetch(`api/search?q=${encodeURIComponent(q)}`); const j = await r.json();
    if (!r.ok) throw new Error(j.detail);
    if (!j.results.length) { ul.innerHTML = `<li><button type="button" disabled>No matches. Try the street number and name, or "Lot 2 DP 12345".</button></li>`; return; }
    if (j.results.length === 1) { pick(j.results[0]); return; }
    state.searchResults = j.results;
    ul.innerHTML = j.results.map((x, i) => `<li><button type="button" data-pick="${i}">${escapeHtml(x.label)}<small>${x.kind}</small></button></li>`).join("");
  } catch (e) { ul.innerHTML = `<li><button type="button" disabled>${escapeHtml(e.message)}</button></li>`; }
}
function pick(x) {
  $("search-results").hidden = true;
  if (x.kind !== "coordinates" && !form.elements.name.value) form.elements.name.value = x.label;
  setSite(x.lat, x.lon);
}
$("find").addEventListener("click", doSearch);
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doSearch(); } });
$("search-results").addEventListener("click", (e) => { const i = e.target.closest("[data-pick]"); if (i) pick(state.searchResults[Number(i.dataset.pick)]); });

// ---------- calculation ----------
let timer = null;
function schedule() { clearTimeout(timer); timer = setTimeout(calculate, 300); }
async function calculate() {
  const s = site(), b = building();
  $("h-out").textContent = hOf(b).toFixed(2);
  drawMapOverlays();
  const err = $("error");
  if (!s) { err.hidden = true; showResults(null); return; }
  const directions = Object.fromEntries(DIRS.map((d) => {
    const { suggested, ...rest } = state.dirs[d];
    const x = { ...rest };
    if (suggested) {
      x.suggested_bands = suggested.bands; x.bands_low = suggested.low; x.bands_high = suggested.high;
      if (suggested.topo) x.suggested_topo = suggested.topo;
      if (suggested.shielding) x.suggested_shielding = suggested.shielding.map(({ height_m, breadth_m, distance_m, slope_excluded }) => ({ height_m, breadth_m, distance_m, slope_excluded }));
    }
    return [d, x];
  }));
  const body = {
    ...s, region: form.elements.region.value, elevation_m: num("elevation_m") ?? 0,
    importance_level: Number(form.elements.importance_level.value), design_life: form.elements.design_life.value,
    limit_state: form.querySelector("input[name=limit_state]:checked").value, building: b, directions,
  };
  try {
    const r = await fetch("api/calc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(readableError(j.detail));
    err.hidden = true; state.result = j;
    showResults(j);
  } catch (e) {
    err.textContent = e.message; err.hidden = false;
    state.result = null; showResults(null, true);
  }
  renderTabs();
}
function readableError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${d.loc.slice(1).join(" › ")}: ${d.msg}`).join("; ");
  return "Calculation failed. Check the inputs.";
}

function showResults(r, keepEmptyHidden) {
  $("results").hidden = !r;
  $("results-empty").hidden = !!r || !!keepEmptyHidden;
  if (!r) { $("res-basis").textContent = ""; return; }
  const I = r.inputs;
  $("res-basis").textContent = `${I.limit_state}, R = ${I.R} years, ${I.region}: V_R = ${I.VR} m/s, M_c = ${I.Mc}, h = ${I.h} m, z = ${I.z} m`;
  const ovr = new Set(r.overrides.map((o) => o.direction + o.factor));
  const vmax = Math.max(...r.directions.map((x) => x.Vsit));
  $("res-table").querySelector("tbody").innerHTML = r.directions.map((x) => {
    const c = (f, v) => `<td class="${ovr.has(x.direction + f) ? "ovr" : ""}">${f2(v)}</td>`;
    const mzEdited = ovr.has(x.direction + "Mz,cat") || ovr.has(x.direction + "Terrain bands");
    const mhEdited = ovr.has(x.direction + "Mh") || ovr.has(x.direction + "Topography");
    const rng = x.Vsit_range ? `${x.Vsit_range[0].toFixed(1)}–${x.Vsit_range[1].toFixed(1)}` : (x.source.terrain === "edited" ? "engineer set" : "");
    return `<tr class="${x.Vsit === vmax ? "gov" : ""}"><td>${x.direction}</td><td>${f2(x.Md)}</td><td class="${mzEdited ? "ovr" : ""}">${f2(x.Mzcat)}</td>${c("Ms", x.Ms)}<td class="${mhEdited ? "ovr" : ""}">${f2(x.Mh)}</td>${c("Mlee", x.Mlee)}<td>${f2(x.Mt)}</td><td class="v">${x.Vsit.toFixed(1)}</td><td class="rng">${rng}</td></tr>`;
  }).join("");
  const faceNames = ["along the long axis", "across the building", "along the long axis", "across the building"];
  $("vdes").innerHTML = r.design.map((v, i) => `<div>
      <div class="f">θ = ${v.theta}°, ${faceNames[i]}</div>
      <div class="v">${v.Vdes.toFixed(1)}<small>m/s</small></div>
      <div class="f ${v.min_applied ? "floor" : ""}">${v.min_applied ? "30 m/s ULS minimum applies" : "governs at " + v.governing_bearing + "°"}</div></div>`).join("");
  $("overrides").innerHTML = r.overrides.length ? `<p>* Engineer changes: ${r.overrides.map((o) => o.suggested
      ? `${o.direction} ${o.factor.toLowerCase()} changed from "${o.suggested}" to "${o.entered}"`
      : `${o.direction} ${o.factor} ${o.computed === null ? "–" : f2(o.computed)} → ${f2(o.used)}`).join("; ")}</p>` : "";
  const lee = r.directions.filter((x) => x.detail.lee.range).map((x) => `${x.direction}: ${x.detail.lee.range} lee, ${x.detail.lee.zone} zone, ${x.detail.lee.distance_km} km from crest, M_lee ${f2(x.detail.lee.mlee)}`);
  const cover = [];
  if (state.auto) {
    const [, end] = windowOf(zOf(building()));
    const covered = Math.min(...DIRS.map((d) => state.auto.directions[d].coverage_m));
    if (end > covered) cover.push(`Averaging window now reaches ${fmt0(end)} m but terrain was mapped to ${fmt0(covered)} m. Map terrain again.`);
  }
  $("warnings").innerHTML = [...cover, ...lee, ...r.warnings].map((w) => `<li>${escapeHtml(w)}</li>`).join("");
  drawRose(r);
  buildPrintSummary(r);
}

// ---------- wind rose ----------
function drawRose(r) {
  const svg = $("rose"), R = 150, vals = r.directions.map((x) => x.Vsit);
  const top = Math.max(60, Math.ceil(Math.max(...vals) / 10) * 10);
  const rad = (v) => 34 + (R - 34) * v / top;
  const vmax = Math.max(...vals);
  const pol = (b, d) => [Math.sin(b * Math.PI / 180) * d, -Math.cos(b * Math.PI / 180) * d];
  let s = "";
  for (let v = 20; v <= top; v += 20) {
    const [tx, ty] = pol(22.5, rad(v) + 2);
    s += `<circle class="rose-ring" r="${rad(v)}"/><text class="rose-ringtxt" x="${tx + 2}" y="${ty - 2}">${v}</text>`;
  }
  if (r.inputs.limit_state === "ULS") s += `<circle class="rose-ring min" r="${rad(30)}"><title>30 m/s ULS minimum</title></circle>`;
  r.directions.forEach((x) => {
    if (x.Vsit_range) {
      const [a0, b0] = pol(x.bearing, rad(x.Vsit_range[0])), [a1, b1] = pol(x.bearing, rad(x.Vsit_range[1]));
      s += `<line x1="${a0}" y1="${b0}" x2="${a1}" y2="${b1}" stroke="${css("--wind")}" stroke-opacity="0.3" stroke-width="18"><title>${x.direction} terrain range</title></line>`;
    }
    const [x0, y0] = pol(x.bearing, 34), [x1, y1] = pol(x.bearing, rad(x.Vsit));
    const [lx, ly] = pol(x.bearing, R + 30), [vx, vy] = pol(x.bearing, rad(Math.max(x.Vsit, x.Vsit_range ? x.Vsit_range[1] : 0)) + 16);
    const isMax = x.Vsit === vmax;
    s += `<line class="rose-spoke ${isMax ? "max" : ""}" x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}"><title>${x.direction}: ${x.Vsit.toFixed(1)} m/s</title></line>`;
    s += `<text class="rose-label" x="${lx}" y="${ly + 4}" text-anchor="middle">${x.direction}</text>`;
    s += `<text class="rose-value ${isMax ? "max" : ""}" x="${vx}" y="${vy + 4}" text-anchor="middle" paint-order="stroke" stroke="var(--panel)" stroke-width="4">${x.Vsit.toFixed(1)}</text>`;
  });
  const b = building(), L = b.length_m || 1, W = b.width_m || 1, k = 44 / Math.max(L, W);
  s += `<g transform="rotate(${b.orientation_deg})"><line class="rose-axis" x1="0" y1="${-L * k / 2 - 10}" x2="0" y2="${L * k / 2 + 10}"/>
        <rect class="rose-bldg" x="${-W * k / 2}" y="${-L * k / 2}" width="${W * k}" height="${L * k}"/></g>`;
  svg.innerHTML = s;
}

// ---------- print ----------
function buildPrintSummary(r) {
  const b = building(), s = site(), I = r.inputs;
  const srcTxt = (d) => { const x = r.directions.find((q) => q.direction === d).source; return `terrain ${x.terrain}, topography ${x.topography}, shielding ${x.shielding}`; };
  const rows = [
    ["Job", b.name || "–"], ["Site", `${s.lat.toFixed(6)}, ${s.lon.toFixed(6)} (NZTM ${I.nztm_e} E, ${I.nztm_n} N)`],
    ["Region / elevation", `${I.region}, ${I.elevation_m} m ASL`],
    ["Building", `Eaves ${b.eaves_height_m} m, ridge ${b.ridge_height_m} m, h = ${I.h} m, z = ${I.z} m; ${b.length_m} × ${b.width_m} m, long axis ${b.orientation_deg}°`],
    ["Design basis", `IL${form.elements.importance_level.value}, ${form.elements.design_life.selectedOptions[0].text}, ${I.limit_state}, R = ${I.R} years`],
    ["Terrain bands", DIRS.map((d) => `${d}: ${state.dirs[d].bands.map((x) => `TC${x.tc} to ${x.to_m} m`).join(", ")} (${srcTxt(d)})`).join("; ")],
    ["Shielding", DIRS.filter((d) => state.dirs[d].shielding.length).map((d) => `${d} (${r.directions.find((q) => q.direction === d).source.shielding}): ${state.dirs[d].shielding.map((x) => `${x.height_m} m high × ${x.breadth_m} m at ${x.distance_m} m${x.slope_excluded ? " (slope-excluded)" : ""}`).join(", ")}`).join("; ") || "None"],
    ["Topography", DIRS.filter((d) => state.dirs[d].topo.kind !== "none").map((d) => { const t = state.dirs[d].topo; return `${d}: ${t.kind}, H ${t.H} m, Lu ${t.Lu} m, x ${t.x} m${t.peak_zone ? ", peak zone" : ""}`; }).join("; ") || "None"],
    ["Mapping data", state.auto ? (state.auto.demo ? "DEMONSTRATION DATA" : Object.entries(state.auto.provenance).map(([k, v]) => `${k}: ${v.dataset || v.method || ""}${v.capture ? " (" + [].concat(v.capture).join(", ") + ")" : ""}`).join("; ")) : "Not used: terrain entered manually"],
    ["Data", `AS/NZS 1170 data files v${r.data_version}; printed ${new Date().toLocaleString("en-NZ")}`],
  ];
  $("print-summary").innerHTML = `<h1>Site wind speed, AS/NZS 1170.2:2021</h1><table>${rows.map(([k, v]) => `<tr><td><strong>${k}</strong></td><td>${escapeHtml(String(v))}</td></tr>`).join("")}</table>`;
}
$("print").addEventListener("click", () => window.print());

// ---------- map ----------
let map = null, mapReady = false, marker = null;
const M_PER_DEG = 111320;
function offset(lon, lat, east, north) { return [lon + east / (M_PER_DEG * Math.cos(lat * Math.PI / 180)), lat + north / M_PER_DEG]; }
function sector(lon, lat, bearing, r0, r1) {
  const pts = [];
  for (let a = bearing - 22.5; a <= bearing + 22.5 + 1e-9; a += 2.5) pts.push(offset(lon, lat, Math.sin(a * Math.PI / 180) * r1, Math.cos(a * Math.PI / 180) * r1));
  for (let a = bearing + 22.5; a >= bearing - 22.5 - 1e-9; a -= 2.5) pts.push(offset(lon, lat, Math.sin(a * Math.PI / 180) * r0, Math.cos(a * Math.PI / 180) * r0));
  pts.push(pts[0]);
  return pts;
}
function footprint(lon, lat, b) {
  const t = b.orientation_deg * Math.PI / 180, L = (b.length_m || 0) / 2, W = (b.width_m || 0) / 2;
  const corner = (a, c) => offset(lon, lat, a * Math.sin(t) + c * Math.cos(t), a * Math.cos(t) - c * Math.sin(t));
  return [corner(L, -W), corner(L, W), corner(-L, W), corner(-L, -W), corner(L, -W)];
}
function circle(lon, lat, r) { const pts = []; for (let a = 0; a <= 360; a += 5) pts.push(offset(lon, lat, Math.sin(a * Math.PI / 180) * r, Math.cos(a * Math.PI / 180) * r)); return pts; }
const poly = (coords, props = {}) => ({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [coords] } });

function drawMapOverlays() {
  if (!mapReady) return;
  const s = site(), b = building(), empty = { type: "FeatureCollection", features: [] };
  if (!s) { ["sectors", "footprint", "shield", "tcbins"].forEach((k) => map.getSource(k).setData(empty)); return; }
  const z = zOf(b), h = hOf(b), [lag, win] = windowOf(z);
  map.getSource("sectors").setData({ type: "FeatureCollection", features: DIRS.map((d) => poly(sector(s.lon, s.lat, BEARING[d], lag, win), { sel: d === state.selected ? 1 : 0, dir: d })) });
  map.getSource("footprint").setData({ type: "FeatureCollection", features: [poly(footprint(s.lon, s.lat, b))] });
  map.getSource("shield").setData({ type: "FeatureCollection", features: h <= 25 ? [poly(circle(s.lon, s.lat, 20 * h))] : [] });
  const feats = [];
  if (state.auto) DIRS.forEach((d) => state.auto.directions[d].bins.forEach((x) => {
    if (x.start_m >= win + 100) return;
    feats.push(poly(sector(s.lon, s.lat, BEARING[d], x.start_m, x.end_m), { color: tcColour(x.tc), low: x.confidence === "low" ? 1 : 0, dir: d }));
  }));
  map.getSource("tcbins").setData({ type: "FeatureCollection", features: feats });
  if (marker) marker.setLngLat([s.lon, s.lat]);
}

function initMap(key) {
  if (typeof maplibregl === "undefined") { $("map-note").textContent = "Map library failed to load."; $("map-note").hidden = false; return; }
  const sources = {}, layers = [{ id: "bg", type: "background", paint: { "background-color": css("--paper") } }];
  if (key) {
    sources.aerial = { type: "raster", tileSize: 256, maxzoom: 22,
      tiles: [`https://basemaps.linz.govt.nz/v1/tiles/aerial/WebMercatorQuad/{z}/{x}/{y}.webp?api=${key}`],
      attribution: "© Toitū Te Whenua LINZ, CC BY 4.0" };
    layers.push({ id: "aerial", type: "raster", source: "aerial" });
  } else {
    $("map-note").innerHTML = "No LINZ Basemaps key set, so aerial imagery is off. Set <code>LINZ_BASEMAPS_KEY</code> before starting the server.";
    $("map-note").hidden = false;
  }
  map = new maplibregl.Map({ container: "map", style: { version: 8, sources, layers }, center: [174.0, -41.0], zoom: 5, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-left");
  map.on("load", () => {
    const fc = { type: "FeatureCollection", features: [] };
    ["tcbins", "sectors", "footprint", "shield"].forEach((k) => map.addSource(k, { type: "geojson", data: fc }));
    map.addLayer({ id: "tcbins-fill", type: "fill", source: "tcbins", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.55 } });
    map.addLayer({ id: "tcbins-low", type: "line", source: "tcbins", filter: ["==", ["get", "low"], 1], paint: { "line-color": "#A3261B", "line-width": 1, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "sectors-fill", type: "fill", source: "sectors", paint: { "fill-color": "#1F5FA8", "fill-opacity": ["case", ["==", ["get", "sel"], 1], 0.18, 0.0] } });
    map.addLayer({ id: "sectors-line", type: "line", source: "sectors", paint: { "line-color": "#1F5FA8", "line-width": ["case", ["==", ["get", "sel"], 1], 2.2, 0.8] } });
    map.addLayer({ id: "shield-line", type: "line", source: "shield", paint: { "line-color": "#4E5B57", "line-width": 1.2, "line-dasharray": [3, 2] } });
    map.addLayer({ id: "footprint-fill", type: "fill", source: "footprint", paint: { "fill-color": "#FFFFFF", "fill-opacity": 0.9 } });
    map.addLayer({ id: "footprint-line", type: "line", source: "footprint", paint: { "line-color": "#1B2422", "line-width": 1.5 } });
    mapReady = true; drawMapOverlays();
    const s = site(); if (s) placeMarker(s, true);
  });
  map.on("click", "sectors-fill", (e) => { selectDir(e.features[0].properties.dir); e.preventDefault(); });
  map.on("click", (e) => { if (e.defaultPrevented) return; setSite(e.lngLat.lat, e.lngLat.lng); });
}
function placeMarker(s, fly) {
  if (!map) return;
  if (!marker) {
    marker = new maplibregl.Marker({ draggable: true, color: "#1B2422" }).setLngLat([s.lon, s.lat]).addTo(map);
    marker.on("dragend", () => { const p = marker.getLngLat(); setSite(p.lat, p.lng, false); });
  }
  marker.setLngLat([s.lon, s.lat]);
  if (fly) map.jumpTo({ center: [s.lon, s.lat], zoom: 14.5 });
}
function setSite(lat, lon, fly = true) {
  form.elements.lat.value = lat.toFixed(6); form.elements.lon.value = lon.toFixed(6);
  onSiteChange(fly);
}
function clearSuggestions() {
  state.auto = null; state.autoKey = null;
  DIRS.forEach((d) => { state.dirs[d].suggested = null; });
  $("elev-src").hidden = true; $("tc-key").hidden = true; $("auto-status").textContent = "";
  renderEvidence(); renderDataPanel();
}
async function onSiteChange(fly) {
  const s = site();
  $("site-hint").hidden = !!s;
  $("auto").disabled = !s;
  if (!s) return;
  if (state.autoKey && state.autoKey !== `${s.lon},${s.lat}`) clearSuggestions();
  placeMarker(s, fly);
  try {
    const r = await fetch(`api/locate?lon=${s.lon}&lat=${s.lat}`); const j = await r.json();
    $("nztm").textContent = `NZTM2000: ${fmt0(j.nztm_e)} E, ${fmt0(j.nztm_n)} N`;
  } catch { /* coordinates still usable */ }
  try {  // wind region from the digitised Figure 3.1(B) (NZ Site Hazards app)
    const p = await (await fetch(`/api/prefill?lat=${s.lat}&lon=${s.lon}`)).json();
    const w = p.wind_region || {};
    if (w.region && [...form.elements.region.options].some((o) => o.value === w.region)) {
      form.elements.region.value = w.region;
      $("region-note").textContent = `${w.region} from the digitised Figure 3.1(B)` + (w.near_boundary ? `, ${w.distance_to_boundary_km} km from a region boundary: confirm against the figure.` : ". Confirm.");
    }
  } catch { /* region stays as entered */ }
  renderTabs(); renderEditor(); schedule();
}

// ---------- wiring ----------
form.addEventListener("input", (e) => {
  if (["lat", "lon"].includes(e.target.name)) { onSiteChange(true); return; }
  if (e.target.name === "q") return;
  if (e.target.name === "elevation_m") $("elev-src").hidden = true;
  if (["eaves_height_m", "ridge_height_m", "reference_height_m"].includes(e.target.name)) { renderEditor(); renderEvidence(); }
  schedule();
});
form.addEventListener("submit", (e) => e.preventDefault());

(async function init() {
  const meta = await (await fetch("api/meta")).json();
  state.meta = meta;
  form.elements.region.innerHTML = meta.regions.map((r) => `<option ${r === "NZ2" ? "selected" : ""}>${r}</option>`).join("");
  form.elements.design_life.innerHTML = Object.entries(meta.lives).map(([k, v]) => `<option value="${k}" ${k === "50_years" ? "selected" : ""}>${v}</option>`).join("");
  $("data-version").textContent = meta.demo ? "Demonstration mode" : meta.data_version ? `Data v${meta.data_version}` : "Data locked: no key";
  renderTabs(); renderEditor();
  initMap(meta.basemaps_key);
  applyParams();
  calculate();
})();

// ---------- opened from the NZ Site Hazards menu ----------
const PARAMS = new URLSearchParams(location.search);
const JOB = PARAMS.get("job");
function applyParams() {
  const set = (name, v) => { if (v !== null && v !== "" && form.elements[name]) form.elements[name].value = v; };
  set("name", PARAMS.get("name"));
  if (PARAMS.get("region") && [...form.elements.region.options].some((o) => o.value === PARAMS.get("region"))) {
    form.elements.region.value = PARAMS.get("region");
    const note = document.createElement("small");
    note.className = "muted"; note.textContent = " Set from the digitised Figure 3.1(B) – confirm.";
    form.elements.region.after(note);
  }
  set("importance_level", PARAMS.get("il"));
  set("design_life", PARAMS.get("life"));
  const lat = parseFloat(PARAMS.get("lat")), lon = parseFloat(PARAMS.get("lon"));
  if (isFinite(lat) && isFinite(lon)) setSite(lat, lon);
  if (JOB) $("save-job").hidden = false;
}
$("save-job").addEventListener("click", async () => {
  const st = $("save-status"); st.hidden = false;
  if (!state.result) { st.className = "small err"; st.textContent = "Complete the calculation first (results must show)."; return; }
  const summary = [...$("print-summary").querySelectorAll("tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.innerText));
  try {
    const r = await fetch(`/api/jobs/${encodeURIComponent(JOB)}/wind`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result: state.result, summary }) });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    st.className = "small"; st.textContent = "Saved to the report. Go back to the NZ Site Hazards tab and press Create report.";
  } catch (e) { st.className = "small err"; st.textContent = "Not saved: " + e.message; }
});
