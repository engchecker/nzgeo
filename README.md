# NZ Site Hazards (nzgeo + nzwind)

One local web app with a menu for four reports: site wind speeds (AS/NZS 1170.2:2021, the `nzwind`
calculator mounted at `/wind/`), geotechnical desk study, Initial Geotechnical Assessment (desk study plus
the uploaded soil suitability spreadsheet and site photos, checked to NZS 3604:2011 clause 3.3), and a
combined report. Sites are found by street address, then Lot/DP, then map click (`nzgeo/locate.py`).

| Module | Purpose |
|---|---|
| `locate.py` | Address (LINZ NZ Addresses, LDS with key, OpenStreetMap fallback), Lot/DP (LINZ NZ Primary Parcels), legal description at a point |
| `fieldsheet.py` | Reads the field sheet and template by label; checks the Report sheet links; fills blank template cells at XML level (macros kept) |
| `goodground.py` | NZS 3604 clauses 3.3.4, 3.3.6, 3.3.7.1(a)–(c) and 3.3.8 screening |
| `photos.py` | Orientation, resizing, EXIF time/GPS/facing, location and date checks |
| `jobs.py`, `iga.py`, `webapp.py`, `menu_page.py` | Job store, report builder, API and menu page |
| `nzwind/auto/shield.py` | Shielding buildings per direction (Cl 4.3) from LINZ outlines and LiDAR heights, with slope exclusion |
| `nzwind/lee.py` | M_lee for all 17 lee zones: Table 4.5 crests; Kaimai, Ruapehu, Tararua (SE) and Coastal Wairarapa crests derived from Figure 4.6 (flagged); Taranaki by the Table 4.4 summit-sector rule (wind data 1.1.0) |

# nzgeo – geotechnical and site hazards module

Desk study checks for one site, run alongside the site wind speed calculation:
geology, active faults, TS 1170.5 seismic parameters, site class, liquefaction, slope and landslides,
flooding, coastal, tsunami, volcanic, geothermal, expansive soils, NZS 3604 exposure zone and
NZS 3404.3:2026 corrosivity. Output is JSON and a drafted report section (HTML) for the engineer to edit.

All results are screening outputs for a suitably qualified engineer to confirm.

## Quick start

Install Python 3.11 or newer, then double-click `run.bat` (Windows) or run `./run.sh` (Mac, Linux). The first run
installs everything and takes several minutes; after that it starts straight away and opens your browser.

## Manual install

Requires Python 3.11 or newer.

    pip install -e .[test]
    pytest
    python -m nzgeo serve        # local web app at http://127.0.0.1:8765/

Optional first-run wizard (stores keys in your OS keychain): `python -m nzgeo.setup_wizard`.
`python -m nzgeo.setup_wizard --forget` removes saved keys.

## What works out of the box

Live services (no key needed): GNS QMAP geology, active faults, landslides, council hazard layers
(`python -m nzgeo discover` crawls all 78 councils), OpenStreetMap address fallback, and the bundled
TS 1170.5:2025 data from GNS Science.

With a free LINZ Data Service key (`LINZ_API_KEY`): NZ Addresses, parcel (Lot/DP) lookup, coastline
distance, historic aerial imagery and building outlines.

## What you must supply yourself

Digitised tables and maps from NZS 3604, NZS 3404.3, AS/NZS 1170.2 and NZS 1170.5 are copyrighted and are
**not** in this repository. Checks that need them (wind region and lee zones, exposure zone, corrosivity, the
AS/NZS 1170.2 wind calculation, NZS 1170.5 Table 3.3) report `unavailable` unless you build your own encrypted
bundle from licensed copies (`python -m nzgeo.secure build <folder>`, `python -m nzwind.secure`).
Vs30 for site class comes from `ucgmsim/nzcvm_data` (wizard step 4).

Word reports use python-docx defaults. For a house style, set `NZGEO_DOCX_TEMPLATE` (a .docx) and
`NZGEO_LOGO` (an image).

## Use

    python -m nzgeo discover                       # crawl all 78 councils once (then monthly)
    python -m nzgeo site --lat -41.125 --lon 175.07 --apoe 500 --html report.html
    python -m nzgeo standards                      # standards currency check on its own

In the wind tool:

    from nzgeo.api import router;  app.include_router(router)          # /api/geotech/site, /report, ...
    from nzgeo.integration import attach_to_job;  attach_to_job(job)   # adds job["geotech"] and the report HTML

`attach_to_job` reads `job["site"]["lat"|"lon"|"address"|"legal"]` and, if present, ground elevation,
LiDAR slope and crest features. Adjust `JOB_KEYS` in `integration.py` to match the wind tool's job fields.

## Settings (environment variables)

| Variable | Purpose |
|---|---|
| LINZ_API_KEY | Distance to coast (LINZ Topo 1:50k coastline, layer set by NZGEO_LINZ_COASTLINE_LAYER, default 50258 – confirm in the LDS catalogue) |
| NZGEO_VS30_H5 | Path to `vs30/NZ_Vs30_HD_With_Offshore.h5` from `ucgmsim/nzcvm_data` (the setup wizard downloads and checks it), for the suggested site class |
| NZGEO_DATA_KEY | Key for the encrypted standards bundle. Normally entered once in the setup wizard and kept in the keychain (or `~/.nzgeo/.data-key`). `secure newkey` creates a NEW key and is only for rebuilding the bundle |
| NZGEO_CACHE | Cache folder (default ~/.nzgeo/cache); responses are cached so a job can be reproduced |
| NZGEO_NZS3604_EDITION | Edition of the digitised NZS 3604 map in the bundle (default 2011) |
| NZGEO_NZS3404_3_EDITION | Edition of NZS 3404.3 in the bundle (default 2026) |

## How each result is reached

- **Councils.** Stats NZ 2023 boundaries give the district and region. `data/councils.json` lists all 78
  councils: 37 with confirmed ArcGIS service roots (own, or shared through Environment Canterbury and
  Wellington Water), one ArcGIS Hub (Horizons), and 41 found by ArcGIS Online search at run time.
  `discover` crawls every root, keeps layers whose names match a hazard type, and stores a catalogue.
  Polygon layers are tested at the site; line and point layers within 500 m.
- **Geology.** Newest `NZL_GNS_250K_Geology_<year>` service on the Earth Sciences NZ (GNS) server; unit at the
  site, distance to the nearest boundary, flagged within 500 m.
- **Faults.** NZ Active Faults Database (1:250k and high-resolution traces, Fault Avoidance Zones and Fault
  Awareness Areas), plus council fault overlays.
- **Seismic.** TS 1170.5:2025 Tables 3.1 and 3.2 (GNS-Science/TS1170.5-SDP, deliverables/v2, bundled):
  settlement polygon row if inside one, otherwise the nearest 0.1° grid point. Labelled **alternative solution**
  unless the standards check finds TS 1170.5 cited in B1/VM1. NZS 1170.5:2004 Z comes from the data bundle.
  Site class from Vs30 uses the TS 1170.5 ranges, with a ±20% range to reflect model uncertainty.
- **Coast.** Distance to the coast from a bundled copy of the LINZ Topo 1:50k coastline (CC BY 4.0), or live
  from LINZ when LINZ_API_KEY is set. The nearest coast is classed as the west/south coast of either island, the
  east coast, or the Chatham Islands for NZS 3404.3 Table 2. Harbours are not detected: pass `coast_type="harbour"`.
- **NZS 3604 exposure.** Zone D distance rules in code (500 m from the coast including harbours, offshore islands,
  50 m from geothermal hot spots); otherwise Figure 4.2, digitised from the vector figure and fitted to the LINZ
  coastline (North Island 230 m median error, South Island 310 m).
- **NZS 3404.3:2026 corrosivity.** Table 2 governs: macroclimate category from the coast type and distance, then
  the surface-specific category for exposed, sheltered, wet, dry and damp conditions. Figures 1 to 7 (national and
  city maps) are looked up as indicative design aids; city maps take precedence, and any disagreement with Table 2
  is flagged. Map fits: national about 150 m median, city maps 33 to 42 m.
- **Wind regions and lee zones (for the wind tool).** `nzgeo.windzones.wind_region(lon, lat)` from AS/NZS 1170.2
  Figure 3.1(B) (about 1 km fit; flagged within 10 km of a boundary, as the drawn lines are about 7 km wide), and
  `lee_zones(lon, lat)` for North Island zones 1 to 6 from Figure 4.6, including Kaimai, Taranaki, Ruapehu,
  Tararua (SE) and Coastal Wairarapa, which Table 4.5 gives no crest coordinates for.
- **Standards currency.** On every report the tool reads Standards NZ and MBIE pages for NZS 3604 and
  NZS/TS 1170.5 edition strings. It reports one of: current; newer edition published but not cited (the cited
  edition is still used); newer edition cited (exposure zone withheld until the new map is digitised); not
  checked (red notice on the report). Evidence snippets and URLs print on the report.

## Data sources and terms

Geological Map of NZ 1:250,000 (CC BY 4.0) and NZ Active Faults Database (non-commercial terms),
Earth Sciences New Zealand; TS 1170.5 tables (Standards NZ, published via GNS-Science/TS1170.5-SDP);
NZ Vs30 model (Foster et al. 2019, MIT); NZ SeaRise VLM (CC BY 4.0); LINZ (CC BY 4.0); Stats NZ
boundaries (CC BY 4.0); council layers under each council's terms.
