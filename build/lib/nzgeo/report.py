"""Desk study report section (HTML), drafted from a site assessment for the engineer to edit."""
from __future__ import annotations

from jinja2 import Environment, select_autoescape

_ENV = Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


def _fmt_m(v):
    if v is None:
        return "not measured"
    return f"{v/1000:.1f} km" if v >= 1000 else f"{v:.0f} m"


_ENV.filters["m"] = _fmt_m

TEMPLATE = r"""<!doctype html><html lang="en-NZ"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Site geology and ground hazards</title>
<style>
:root{--ink:#1d2329;--muted:#5b6670;--line:#d7dde2;--warn:#8a5a00;--warnbg:#fff6e0;--stop:#9b1c1c;--stopbg:#fdecec;--ok:#1f6b3a;--bg:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#e8ecef;--muted:#a3adb5;--line:#3a434b;--warnbg:#3a2f12;--warn:#f2c46b;--stopbg:#3d1d1d;--stop:#ff9b9b;--ok:#7fd49c;--bg:#15191d}}
body{font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg);max-width:900px;margin:0 auto;padding:24px 16px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 6px;border-bottom:1px solid var(--line);padding-bottom:4px}
.meta{color:var(--muted);font-size:.9rem}.box{border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:12px 0}
.warn{background:var(--warnbg);border-color:var(--warn)}.stop{background:var(--stopbg);border-color:var(--stop)}
.tag{display:inline-block;font-size:.75rem;font-weight:600;padding:1px 7px;border-radius:10px;border:1px solid currentColor}
.alt{color:var(--warn)}.edit{color:var(--muted);font-style:italic}
table{border-collapse:collapse;width:100%;font-size:.88rem;margin:8px 0}th,td{border:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{font-weight:600}.scroll{overflow-x:auto}small{color:var(--muted)}ul{padding-left:20px}
</style></head><body>
<h1>Site geology and ground hazards (desk study)</h1>
<div class="meta">{{ a.site.address or "Site" }}{% if a.site.legal %} · {{ a.site.legal }}{% endif %} · {{ "%.6f"|format(a.site.lat) }}, {{ "%.6f"|format(a.site.lon) }} · NZTM {{ a.site.nztm[0] }} E {{ a.site.nztm[1] }} N<br>
Generated {{ a.generated }} by nzgeo {{ a.tool_version }}. Draft for engineer review.</div>

{% set st = a.standards %}
{% if st.status == "not_checked" %}
<div class="box stop"><b>Standards currency not checked.</b> The tool could not reach Standards NZ or MBIE. Confirm that NZS 3604 and NZS 1170.5 / TS 1170.5 citations are current before issue.</div>
{% else %}
{% set n = st.nzs3604 %}
<div class="box {{ 'stop' if n.status == 'newer_cited_update_required' else ('warn' if n.status != 'current' else '') }}">
<b>Standards check ({{ st.checked_at }}).</b>
{% if n.status == "current" %}NZS 3604:{{ n.edition_in_use }} is the current cited edition.
{% elif n.status == "newer_published_not_cited" %}NZS 3604:{{ n.newest_published }} has been published but is not yet cited; NZS 3604:{{ n.edition_in_use }} remains the cited edition and is used here.
{% elif n.status == "newer_cited_update_required" %}{{ n.newest_cited_label }} is now cited. The exposure zone result is withheld until its map is in the data bundle.
{% else %}NZS 3604 status inconclusive; confirm manually.{% endif %}
{% set q = st.nzs3404_3 %}{% if q and q.status == "newer_published_not_cited" %} NZS 3404.3:{{ q.newest_published }} is newer than the {{ q.edition_in_use }} edition in the bundle.{% elif q and q.status == "newer_cited_update_required" %} {{ q.newest_cited_label }} is now cited; update the corrosivity data.{% elif q and q.status == "current" %} NZS 3404.3:{{ q.edition_in_use }} is current{{ " and cited" if q.cited else " (published; not yet cited in an acceptable solution or verification method)" }}.{% endif %}
{% if st.seismic.ts1170_5_cited %} TS 1170.5 appears cited in B1/VM1.{% else %} TS 1170.5 is not cited in B1/VM1 (alternative solution).{% endif %}
{% if st.errors %}<br><small>Sources not reached: {{ st.errors|join("; ") }}</small>{% endif %}
{% for e in (n.evidence or []) + ((st.seismic or {}).evidence or []) %}<br><small>Evidence: “…{{ e.snippet }}…” ({{ e.url }})</small>{% endfor %}
</div>
{% endif %}

<p>This section summarises published regional information for the site. It is a desk study only and does not replace site-specific investigation.</p>

<h2>Published geology</h2>
{% set g = a.geology %}
{% if g.status == "ok" %}
<p>The Geological Map of New Zealand 1:250,000{% if g.edition_year %} ({{ g.edition_year }} service){% endif %} maps the site as
<b>{{ g.unit_name or g.description or "the unit below" }}</b>{% if g.unit_code %} ({{ g.unit_code }}){% endif %}{% if g.description and g.unit_name %}, described as {{ g.description }}{% endif %}{% if g.age %}, of {{ g.age }} age{% endif %}.
The nearest mapped geological boundary is {{ g.boundary_distance_m|m }} to the {{ g.boundary_direction }}.
{% if g.flag_near_boundary %}<b>The site is within 500 m of a mapped boundary; at 1:250,000 boundaries may be several hundred metres in error, so either unit may be present.</b>{% else %}At this scale, mapped boundaries may be several hundred metres in error.{% endif %}</p>
{% if a.rock_strength.status == "ok" %}<p><small>Rock strength grouping (QMAP landslide view): {{ a.rock_strength.attributes|dictsort|map("join", ": ")|join("; ") }}</small></p>{% endif %}
{% else %}<p class="box warn">Geology not retrieved: {{ g.reason }}</p>{% endif %}

<h2>Active faults</h2>
{% set f = a.faults %}
{% if f.status == "ok" %}
{% if f.nearest %}<p>The nearest active fault in the New Zealand Active Faults Database is
<b>{{ f.nearest.name or "an unnamed trace" }}</b>, about {{ f.nearest.distance_m|m }} to the {{ f.nearest.direction }}{% if f.nearest.recurrence_interval_class %}, recurrence interval class {{ f.nearest.recurrence_interval_class }}{% endif %}{% if f.nearest.accuracy %}, location accuracy {{ f.nearest.accuracy }}{% endif %}.</p>
{% else %}<p>No active fault trace is mapped within 10 km of the site.</p>{% endif %}
<p>The site <b>{{ "is" if f.inside_zone else "is not" }}</b> within a Fault Avoidance Zone or Fault Awareness Area in the database.
{% for c in (a.council.findings or []) if "fault" in c.hazards %}Council layer “{{ c.layer }}” ({{ c.council }}): {{ c.relation }}{% if c.distance_m %}, {{ c.distance_m|m }} {{ c.direction }}{% endif %}. {% endfor %}</p>
{% else %}<p class="box warn">Active fault data not retrieved: {{ f.reason }}</p>{% endif %}

<h2>Seismic site parameters</h2>
{% set ts = a.ts1170_5 %}{% set sc = a.site_class %}
{% set z = a.nzs1170_5 %}
{% if z.status == "ok" %}
<p><b>{{ z.standard }}</b> (cited by B1/VM1): hazard factor <b>Z = {{ "%.2f"|format(z.Z) }}</b>. {{ z.basis }}.
{% if z.R %}For an annual probability of exceedance of 1/{{ z.apoe_n }}, R = {{ z.R }} and Z·R = {{ z.ZR }}.{% endif %}</p>
{% set nf = z.near_fault %}
<p>Near-fault factor: {% if nf.applies %}D = {{ nf.D_km }} km ({{ nf.basis }}), so N(T,D) exceeds 1.0 for annual probabilities of exceedance below 1/250:
{% for T, n in nf.N_at_T|dictsort %}N({{ T }} s) = {{ n }}{{ "; " if not loop.last }}{% endfor %}. {{ nf.note or "" }}
{% else %}{{ nf.basis }}{% if nf.D_km %} (D = {{ nf.D_km }} km){% endif %}; N(T,D) = 1.0.{% endif %}</p>
{% if z.flags %}<ul>{% for x in z.flags %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}
{% if z.figure_png %}<p><img alt="Site on {{ z.figure }}" style="max-width:100%;border:1px solid var(--line)" src="data:image/png;base64,{{ z.figure_png }}"><br><small>{{ z.figure }} of NZS 1170.5, site marked in red (georeferenced extract, about ±1–3 km).</small></p>{% endif %}
{% else %}<p><b>NZS 1170.5:2004</b>: {{ z.reason }}. <span class="edit">[Engineer to enter Z from Table 3.3 as modified by B1/VM1.]</span></p>{% endif %}
{% if ts.parameters %}
<p><span class="tag alt">{{ "Alternative solution" if ts.compliance_path == "alternative_solution" else "Verification method" }}</span> <b>{{ ts.standard }}</b>: the site falls under Table {{ ts.table }}, location <b>{{ ts.location }}</b>. {{ ts.label }}</p>
<p>{% if sc.site_class %}Preliminary site class <b>{{ sc.site_class }}</b>{% if sc.range and sc.range|length > 1 %} (range {{ sc.range|join("–") }}){% endif %}, from {{ sc.basis }}{% if sc.vs30 %} (Vs30 ≈ {{ sc.vs30 }} m/s){% endif %}. {{ sc.note or "" }}
{% else %}Site class not assessed ({{ sc.reason }}). <span class="edit">[Engineer to assign.]</span>{% endif %}</p>
{% set cls = sc.range if sc.range else ([sc.site_class] if sc.site_class else ["I","II","III","IV","V","VI"]) %}
<div class="scroll"><table><tr><th>APoE</th><th>M</th><th>D (km)</th>{% for c in cls if c != "VII" %}<th>{{ c }}: PGA</th><th>S<sub>a,s</sub></th><th>T<sub>c</sub></th><th>T<sub>d</sub></th>{% endfor %}</tr>
{% for apoe, p in ts.parameters|dictsort %}<tr{% if ts.selected and ts.selected.apoe_n == apoe %} style="font-weight:600"{% endif %}><td>1/{{ apoe }}</td><td>{{ p.M }}</td><td>{{ p.D }}</td>
{% for c in cls if c != "VII" %}<td>{{ p.classes[c].PGA }}</td><td>{{ p.classes[c].Sas }}</td><td>{{ p.classes[c].Tc }}</td><td>{{ p.classes[c].Td }}</td>{% endfor %}</tr>{% endfor %}</table></div>
{% if "VII" in cls %}<p class="box warn">Site class VII is possible: TS 1170.5 gives no spectra and requires a site-specific study.</p>{% endif %}
<p><small>Nearest TS 1170.5 major fault (reference only): {{ ts.major_fault_reference.name }}, {{ ts.major_fault_reference.distance_km }} km {{ ts.major_fault_reference.direction }}. Source: {{ ts.source }}.</small></p>
{% else %}<p class="box warn">TS 1170.5 parameters not retrieved: {{ ts.reason }}</p>{% endif %}

{% macro council_section(kind, title) %}
{% set hits = (a.council.findings or [])|selectattr("hazards", "contains", kind)|list %}
{% if hits %}<ul>{% for h in hits %}<li><b>{{ h.council }}</b> – {{ h.layer }} <small>({{ h.service }}{% if h.found_by == "arcgis_online_search" %}; found by search, confirm the publisher{% endif %})</small>: {{ h.relation }}{% if h.distance_m %}, {{ h.distance_m|m }} {{ h.direction }}{% endif %}{% if h.attributes %}. <small>{{ h.attributes|dictsort|map("join", ": ")|join("; ") }}</small>{% endif %}</li>{% endfor %}</ul>
{% else %}<p>No {{ title }} layer from {{ (a.council.councils or [])|join(", ") or "the councils" }} identifies this hazard at the site. Council mapping is not exhaustive. <span class="edit">[Engineer commentary.]</span></p>{% endif %}
{% endmacro %}

<h2>Liquefaction</h2>
{{ council_section("liquefaction", "liquefaction") }}
{% if not ((a.council.findings or [])|selectattr("hazards", "contains", "liquefaction")|list) and a.geology.status == "ok" and a.geology.age and ("holocene" in (a.geology.age|string|lower) or "q1" in (a.geology.unit_code|string|lower)) %}
<p class="box warn">The mapped unit is Holocene; treat the site as potentially liquefaction-prone until assessed.</p>{% endif %}

<h2>Slope stability</h2>
{% if a.terrain.slope_max_deg is not none %}<p>Ground slopes across the site range up to {{ a.terrain.slope_max_deg }}°{% if a.terrain.slope_mean_deg is not none %} (mean {{ a.terrain.slope_mean_deg }}°){% endif %}, from the LiDAR used for the wind calculation.</p>{% else %}<p class="edit">[Slope from LiDAR not supplied; run from the wind job.]</p>{% endif %}
{% if a.landslides.status == "error" %}<p class="box warn">Landslide data not retrieved: {{ a.landslides.reason }}</p>{% elif a.landslides.features %}<ul>{% for l in a.landslides.features[:8] %}<li>{{ l.layer }}: {{ l.distance_m|m }} {{ l.direction }}</li>{% endfor %}</ul>{% else %}<p>No landslide in the GNS landslide datasets within {{ a.landslides.search_radius_m|default(1000)|m }}.</p>{% endif %}
{{ council_section("slope", "slope or landslide") }}
{{ council_section("rockfall", "rockfall") }}

<h2>Expansive soils</h2>
{{ council_section("expansive", "expansive soil") }}

<h2>Coastal, flood and other hazards</h2>
<p>{% if a.coast.status == "ok" %}The site is {{ a.coast.distance_m|m if a.coast.distance_m is not none else "more than 2 km" }} from the coast{% if a.coast.direction %} to the {{ a.coast.direction }}{% endif %}{% else %}Distance to coast not measured ({{ a.coast.reason }}){% endif %}{% if a.terrain.ground_elevation_m is not none %}, at about RL {{ a.terrain.ground_elevation_m }} m (NZVD2016){% endif %}.
{% if a.vlm.status == "ok" %} NZ SeaRise gives vertical land movement of {{ a.vlm.vlm_mm_per_yr }} mm/yr at site {{ a.vlm.site_id }}, {{ a.vlm.distance_km }} km away.{% endif %}</p>
{% for kind, title in [("flood","Flooding"),("coastal","Coastal"),("tsunami","Tsunami"),("volcanic","Volcanic"),("geothermal","Geothermal"),("subsidence","Subsidence and soft ground"),("erosion","Erosion")] %}
<p><b>{{ title }}.</b></p>{{ council_section(kind, title|lower) }}
{% endfor %}
{% if a.council.status == "error" %}<p class="box warn">Council hazard layers not checked: {{ a.council.reason }}</p>{% endif %}
{% if a.council.notes %}<p><small>{{ a.council.notes|join(" · ") }}</small></p>{% endif %}

<h2>Contaminated land (HAIL)</h2>
{% set h = a.hail %}
{% if h and h.status == "ok" %}<p>{{ h.council }} – {{ h.register }} ({{ h.layers_checked|length }} layer(s) checked):
{% if h.on_site %}<b>site recorded</b>: {% for x in h.on_site %}{{ x.site or "" }} {{ x.category or "" }} {{ x.status or "" }}{{ "; " if not loop.last }}{% endfor %}.
{% elif h.nearby %}not recorded; nearest listed site {{ h.nearby[0].site or "" }} {{ h.nearby[0].category or "" }} at {{ h.nearby[0].distance_m }} m.
{% else %}not recorded, and none within {{ h.near_m }} m.{% endif %}</p>
{% elif h and h.status == "not_published" %}<p class="box warn">{{ h.council }} does not publish its {{ h.register }} online. Request a property search{% if h.request %}: <a href="{{ h.request }}">{{ h.request }}</a>{% endif %}.</p>
{% else %}<p class="box warn">Contaminated land register not reached{% if h and h.errors %}: {{ h.errors|join("; ") }}{% endif %}.</p>{% endif %}

<h2>Historic aerial photographs</h2>
{% set ae = a.aerials %}
{% if ae and ae.status == "ok" %}<p>{{ ae.surveys|length }} LINZ aerial surveys cover the site: {% for s in ae.surveys %}{{ s.year }} ({{ s.sn or s.cat.split("-")[0] }}, {{ s.gsd }} m){{ ", " if not loop.last }}{% endfor %}.</p>
{% if ae.frames %}<p>Unrectified Crown archive frames over the site (view on Retrolens): {% for f in ae.frames[:12] %}{{ f.date }} {{ f.survey or "" }} run {{ f.run or "?" }} frame {{ f.frame or "?" }}{{ "; " if not loop.last }}{% endfor %}.</p>
{% else %}<p><small>Unrectified Retrolens frames are listed when a LINZ key is set (setup step 4).</small></p>{% endif %}
{% else %}<p class="box warn">Historic aerial imagery not retrieved{% if ae and ae.reason %}: {{ ae.reason }}{% endif %}.</p>{% endif %}

<h2>Durability exposure</h2>
{% set e = a.exposure %}{% set c = a.corrosivity %}
<p>{% if e.status == "blocked" %}<span class="box stop">{{ e.reason }}</span>
{% else %}NZS 3604 exposure zone: <b>{{ e.zone or "not determined" }}</b> under {{ e.standard }}. <small>{{ e.basis }}</small>{% if e.reason %} <small>{{ e.reason }}</small>{% endif %}{% endif %}</p>
{% if e.flags %}<ul>{% for x in e.flags %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}
{% if e.map %}<p><small>Figure 4.2 lookup: {{ e.map.class }} ({{ e.map.map }}); map fit to the LINZ coastline {{ e.map.fit.median_m }} m median, {{ e.map.fit.p90_m }} m 90th percentile.</small></p>{% endif %}
<p><b>Atmospheric corrosivity ({{ c.standard }}).</b>
{% if c.status == "ok" %}Table 2 gives macroclimate category <b>{{ c.macro_category }}</b> ({{ c.characterised_by }}). {{ c.basis }}.
Coast type: {{ c.coast_type_label or "not determined" }} ({{ c.coast_type_source }}).</p>
<div class="scroll"><table><tr><th colspan="3">External</th><th colspan="2">Internal</th></tr>
<tr><th>Exposed</th><th>Sheltered</th><th>Wet</th><th>Dry</th><th>Damp</th></tr>
<tr>{% for k in ["exposed","sheltered","wet","dry","damp"] %}<td{% if c.surface_condition == k %} style="font-weight:600"{% endif %}>{{ c.surface_specific[k] }}</td>{% endfor %}</tr></table></div>
{% if c.surface_category %}<p>Surface-specific category for a {{ c.surface_condition }} surface: <b>{{ c.surface_category }}</b>.</p>{% endif %}
{% else %}{{ c.reason }}. <span class="edit">[Engineer to assign from NZS 3404.3 Table 2.]</span></p>{% endif %}
{% if c.map %}<p><small>Indicative map, {{ c.map.figure }} ({{ c.map.map }}): {{ c.map.class }}; map fit {{ c.map.fit.median_m }} m median.</small></p>{% endif %}
{% if c.flags %}<ul>{% for x in c.flags %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}

<h2>Wind region and lee zones (cross-check for the wind calculation)</h2>
{% set w = a.wind_region %}{% set lz = a.lee_zones %}
<p>{% if w.status == "ok" %}AS/NZS 1170.2 wind region <b>{{ w.region }}</b> (Figure 3.1(B), digitised), {{ w.distance_to_boundary_km }} km from a region boundary{% if w.near_boundary %}; <b>within 10 km of a boundary, confirm against the figure</b>{% endif %}.{% if w.note %} {{ w.note }}.{% endif %}
{% else %}Wind region not checked ({{ w.reason }}).{% endif %}
{% if lz.status == "ok" %}{% if lz.zones %} North Island lee zones: {% for z in lz.zones %}{{ z.zone }} {{ z.range }} ({{ z.part }}){{ "; " if not loop.last }}{% endfor %}. {{ lz.note }}{% else %} Not within a digitised North Island lee zone (zones 1–6); South Island zones are set from the Table 4.5 crests in the wind calculation.{% endif %}{% endif %}</p>
{% if a.notes %}<p><small>{{ a.notes|join(" · ") }}</small></p>{% endif %}

<h2>Recommended investigation</h2>
<p class="edit">[Engineer to complete.]</p>

<h2>Data sources</h2>
<ul>
<li>Geological Map of New Zealand 1:250,000, Earth Sciences New Zealand (GNS Science). {{ a.geology.source }} (retrieved {{ a.geology.retrieved }}).</li>
<li>New Zealand Active Faults Database, Earth Sciences New Zealand (GNS Science), used for non-commercial internal purposes under its terms. {{ a.faults.source }}.</li>
<li>TS 1170.5:2025 seismic demand parameter tables, Standards New Zealand; data from {{ a.ts1170_5.source }}.</li>
{% if a.site_class.basis %}<li>{{ a.site_class.basis }}.</li>{% endif %}
{% if a.coast.source %}<li>{{ a.coast.source }}. Sourced from the LINZ Data Service and licensed for reuse under CC BY 4.0.</li>{% endif %}
{% if a.vlm.source %}<li>{{ a.vlm.source }}.</li>{% endif %}
<li>Council hazard layers ({{ a.council.layers_checked or 0 }} checked): {% for s in (a.council.findings or [])|map(attribute="source")|unique %}{{ s }}{{ "; " if not loop.last }}{% endfor %}{% if not a.council.findings %}none intersecting the site{% endif %}.</li>
<li>Territorial authority and region: Stats NZ 2023 boundaries, CC BY 4.0.</li>
<li>Coastline and coast distance: {{ a.coast_offline.source or "LINZ Topo 1:50k coastline" }}. Sourced from the LINZ Data Service and licensed for reuse under CC BY 4.0.</li>
<li>NZS 3604:2011 Figure 4.2, NZS 3404.3:2026 Table 2 and Figures 1 to 7, and AS/NZS 1170.2:2021 Figures 3.1(B) and 4.6, digitised from licensed copies and georeferenced to the LINZ coastline.</li>
</ul>
<p><small>Regional and national datasets cannot characterise a specific site. All values are for engineer confirmation.</small></p>
</body></html>
"""

def _contains(seq, item):
    return item in (seq or [])


_ENV.tests["contains"] = _contains
_T = _ENV.from_string(TEMPLATE)


def render_html(assessment: dict) -> str:
    return _T.render(a=_Dot(assessment))


class _Dot(dict):
    """Lets the template use a.b.c on nested dicts and returns an empty value for missing keys."""

    def __getattr__(self, k):
        v = self.get(k)
        if isinstance(v, dict):
            return _Dot(v)
        if isinstance(v, list):
            return [_Dot(x) if isinstance(x, dict) else x for x in v]
        return v

    def __getitem__(self, k):
        v = dict.get(self, k)
        return _Dot(v) if isinstance(v, dict) else v
