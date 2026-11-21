"""Command line.

  python -m nzgeo site --lat -41.29 --lon 174.78 [--apoe 500] [--vs30 300] [--html out.html]
  python -m nzgeo discover [--council "Hutt City Council"]
  python -m nzgeo standards
  python -m nzgeo councils
  python -m nzgeo serve        (the map-based app)
  python -m nzgeo setup        (the setup wizard)
"""
import argparse
import json
import sys

from . import councils, discover, standards
from .report import render_html
from .site import assess


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nzgeo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("site")
    s.add_argument("--lat", type=float, required=True)
    s.add_argument("--lon", type=float, required=True)
    s.add_argument("--apoe", type=int, default=500)
    s.add_argument("--vs30", type=float)
    s.add_argument("--site-class")
    s.add_argument("--surface", choices=["exposed", "sheltered", "interior"])
    s.add_argument("--address")
    s.add_argument("--html")
    d = sub.add_parser("discover")
    d.add_argument("--council", action="append")
    sub.add_parser("standards")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--no-browser", action="store_true")
    sub.add_parser("setup")
    sub.add_parser("councils")
    a = ap.parse_args(argv)
    if a.cmd == "site":
        res = assess(a.lon, a.lat, apoe_n=a.apoe, vs30=a.vs30, site_class=a.site_class,
                     surface_condition=a.surface, address=a.address)
        if a.html:
            open(a.html, "w", encoding="utf-8").write(render_html(res))
            print(f"Wrote {a.html}")
        else:
            json.dump(res, sys.stdout, indent=1, default=str)
    elif a.cmd == "discover":
        cat = discover.discover_all(a.council)
        for k, v in sorted(cat["councils"].items()):
            print(f"{len(v['layers']):5d}  {k}  ({v['found_by']}, {v['services_scanned']} services)")
    elif a.cmd == "serve":
        from .webapp import serve
        serve(a.port, not a.no_browser)
    elif a.cmd == "setup":
        from .setup_wizard import main as wiz
        raise SystemExit(wiz())
    elif a.cmd == "standards":
        json.dump(standards.check(), sys.stdout, indent=1)
    elif a.cmd == "councils":
        for c in councils.registry()["councils"]:
            print(f"{c['status']:15s} {c['type']:12s} {c['name']}")


if __name__ == "__main__":
    main()
