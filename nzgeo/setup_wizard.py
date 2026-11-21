"""Step-by-step setup. Run by the installer, or any time with:  python -m nzgeo.setup_wizard

Every step checks its own result and says exactly what to do if something is wrong.
Re-running is safe: finished steps are detected and skipped.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from .config import CONFIG_FILE, HOME_DIR

VS30_URL = "https://media.githubusercontent.com/media/ucgmsim/nzcvm_data/main/vs30/NZ_Vs30_HD_With_Offshore.h5"
VS30_SHA256 = "6c0b929aea60902c40ad94d30ebb9293e67dd0d94ddcbb27b0441aa340bd724d"
TOTAL = 7

# ---------- screen helpers ----------
_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
if os.name == "nt":
    os.system("")  # enables colour codes in the Windows console


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _COLOUR else s


def title(s):
    print("\n" + _c("1;36", "=" * 64) + "\n" + _c("1;36", "  " + s) + "\n" + _c("1;36", "=" * 64))


def step(n, s):
    print("\n" + _c("1;34", f"STEP {n} of {TOTAL}:  {s}") + "\n" + _c("34", "-" * 64))


def ok(s):
    print(_c("32", "  [OK]    ") + s)


def warn(s):
    print(_c("33", "  [NOTE]  ") + s)


def fail(s):
    print(_c("31", "  [PROBLEM] ") + s)


def say(s=""):
    print("  " + s)


def ask(prompt, default=None, inp=input):
    sfx = f" [{default}]" if default is not None else ""
    try:
        a = inp(_c("1", f"\n  > {prompt}{sfx}: ")).strip()
    except EOFError:
        a = ""
    return a or (default or "")


def yes(prompt, default="Y", inp=input):
    while True:
        a = ask(prompt + " (Y/N)", default, inp).lower()
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False
        say("Please type Y for yes or N for no, then press Enter.")


# ---------- settings storage ----------
def load_cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_cfg(cfg: dict):
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=1))


def store_secret(name: str, value: str) -> str:
    """Keychain if available, else a private file. Returns where it went."""
    try:
        import keyring
        keyring.set_password("nzgeo", name, value)
        if keyring.get_password("nzgeo", name) == value:
            return "your computer's password store (keychain)"
    except Exception:
        pass
    p = HOME_DIR / f".{name}"
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(value)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    os.environ["LINZ_API_KEY" if name == "linz-api-key" else "NZGEO_DATA_KEY"] = value
    return f"a private file ({p})"


def read_secret(name: str) -> str | None:
    from .config import _secret
    v = _secret(name)
    if v:
        return v
    p = HOME_DIR / f".{name}"
    return p.read_text().strip() if p.exists() else None


# ---------- steps ----------
def s1_check(inp=input) -> bool:
    step(1, "Checking this computer")
    good = True
    if sys.version_info >= (3, 11):
        ok(f"Python {sys.version.split()[0]}")
    else:
        fail(f"Python {sys.version.split()[0]} is too old. Install Python 3.12 and run the installer again.")
        good = False
    for mod in ("httpx", "shapely", "pyproj", "numpy", "jinja2", "fastapi", "uvicorn", "cryptography", "keyring", "h5py",
                "scipy", "PIL", "openpyxl", "multipart", "rasterio", "geopandas", "nzwind", "docx", "matplotlib"):
        try:
            __import__(mod)
        except Exception:
            fail(f"Component '{mod}' is missing. Run the installer again; it installs all components.")
            good = False
    if good:
        ok("All program components are installed")
    try:
        HOME_DIR.mkdir(parents=True, exist_ok=True)
        (HOME_DIR / ".write-test").write_text("x")
        (HOME_DIR / ".write-test").unlink()
        ok(f"Settings folder: {HOME_DIR}")
    except Exception as e:
        fail(f"Cannot write to {HOME_DIR} ({e}). Ask IT to give you write access to your home folder.")
        good = False
    return good


def s2_data_key(inp=input) -> bool:
    step(2, "Unlock the standards data (required)")
    from .secure import check_key
    existing = read_secret("data-key")
    if existing and check_key(existing):
        ok("The data key is already set up and works. Nothing to do.")
        return True
    say("The maps and tables from the Standards are encrypted. You need the data key")
    say("that was sent to you separately, in a file called  nzgeo-data-key.txt")
    say("")
    say("Do this now:")
    say("  1. Find the file nzgeo-data-key.txt (usually in your Downloads folder).")
    say("  2. Open it (double-click). It contains ONE line of letters and numbers,")
    say("     ending in an = sign.")
    say("  3. Select the whole line and copy it (Ctrl+C on Windows, Cmd+C on Mac).")
    say("  4. Click back in THIS window, paste it (right-click > Paste, or Ctrl+V / Cmd+V)")
    say("     and press Enter.")
    for attempt in range(1, 4):
        k = ask("Paste the data key here", inp=inp).strip().strip('"').strip("'")
        if not k:
            fail("Nothing was pasted. Try again.")
            continue
        if check_key(k):
            where = store_secret("data-key", k)
            ok(f"Key accepted and saved in {where}.")
            say("You can now delete nzgeo-data-key.txt, or keep it somewhere safe")
            say("(for example in your password manager) for the next computer.")
            return True
        fail(f"That key does not open the data (attempt {attempt} of 3).")
        say("Check you copied the whole line, including the = at the end, and nothing else.")
    fail("The key was not accepted. Run setup again later with the correct key file.")
    return False


def _wind_key_ok(k: str) -> bool:
    try:
        from nzwind.secure import _decode, decrypt
        decrypt(_decode(k))
        return True
    except Exception:
        return False


def _wind_key_saved() -> str | None:
    try:
        from nzwind.secure import get_key
        import base64
        return base64.urlsafe_b64encode(get_key()).decode().rstrip("=")
    except Exception:
        p = HOME_DIR / ".nzwind-data-key"
        return p.read_text().strip() if p.exists() else None


def s3_wind_key(inp=input) -> bool:
    step(3, "Unlock the wind calculator data (required for wind reports)")
    k = _wind_key_saved()
    if k and _wind_key_ok(k):
        ok("The wind data key is already set up and works. Nothing to do.")
        return True
    say("The wind calculator's AS/NZS 1170 tables are encrypted with their own key,")
    say("in the file  nzwind-data-key.txt  (the second line is the key).")
    say("If you ran 'rekey' on the wind tool before, use the new key you saved then.")
    say("")
    say("  1. Open nzwind-data-key.txt. Copy ONLY the line of letters and numbers.")
    say("  2. Paste it here and press Enter. Press Enter on its own to skip.")
    for attempt in range(1, 4):
        k = ask("Paste the wind data key here", inp=inp).strip().strip('"').strip("'")
        if not k:
            warn("Skipped. Wind reports will say 'Data locked: no key' until you run setup again.")
            return True
        if _wind_key_ok(k):
            where = None
            try:
                import keyring
                keyring.set_password("nzwind", "data-key", k)
                if keyring.get_password("nzwind", "data-key") == k:
                    where = "your computer's password store (keychain)"
            except Exception:
                pass
            if not where:
                p = HOME_DIR / ".nzwind-data-key"
                HOME_DIR.mkdir(parents=True, exist_ok=True)
                p.write_text(k)
                try:
                    os.chmod(p, 0o600)
                except Exception:
                    pass
                os.environ["NZWIND_DATA_KEY_FILE"] = str(p)
                where = f"a private file ({p})"
            ok(f"Wind key accepted and saved in {where}.")
            return True
        fail(f"That key does not open the wind data (attempt {attempt} of 3). Copy only the key line.")
    fail("The wind key was not accepted. Run setup again later with the correct key.")
    return False


def s3_linz(inp=input) -> bool:
    step(4, "LINZ API key (optional)")
    existing = read_secret("linz-api-key")
    if existing:
        ok("A LINZ key is already saved. Nothing to do.")
        return True
    say("Without a LINZ key the tool still finds addresses and Lot/DP numbers (LINZ's")
    say("public map services) and measures distance to the coast (built-in LINZ")
    say("coastline). A key adds: the list of early Retrolens (Crown archive) photo")
    say("frames over the site, building outlines for the wind calculator's automatic")
    say("terrain mapping, a second LINZ route for searches, and the live coastline.")
    say("You can skip this and add it later by running setup again.")
    if not yes("Do you want to add a LINZ API key now?", "N", inp):
        warn("Skipped. Coast distance uses the built-in LINZ coastline.")
        return True
    say("")
    say("Get a key like this (free):")
    say("  1. Go to https://data.linz.govt.nz and sign in (or register, then sign in).")
    say("  2. Click your name in the top menu, then click 'API Keys'.")
    say("  3. Click 'Create API Key'. In 'API Key Label' type:  nzgeo")
    say("  4. Select 'Data access only', then click 'Add'.")
    say("  5. Copy the key that appears.")
    k = ask("Paste the LINZ API key here (or press Enter to skip)", inp=inp).strip()
    if not k:
        warn("Skipped.")
        return True
    try:
        import httpx
        r = httpx.get(f"https://data.linz.govt.nz/services;key={k}/wfs",
                      params={"service": "WFS", "request": "GetCapabilities"}, timeout=20)
        if r.status_code == 200 and "WFS_Capabilities" in r.text[:2000]:
            ok("LINZ accepted the key.")
        else:
            warn(f"LINZ answered {r.status_code}; the key may be wrong. It is saved anyway; "
                 "if coast checks fail, run setup again and re-enter it.")
    except Exception:
        warn("Could not reach LINZ to test the key (no internet?). It is saved; it will be tested on first use.")
    where = store_secret("linz-api-key", k)
    ok(f"Saved in {where}.")
    return True


def s4_vs30(inp=input) -> bool:
    step(5, "Download the Vs30 ground model (recommended)")
    cfg = load_cfg()
    target = HOME_DIR / "data" / "NZ_Vs30_HD_With_Offshore.h5"
    if target.exists() and _sha(target) == VS30_SHA256:
        cfg["vs30_h5"] = str(target); save_cfg(cfg)
        ok("Vs30 model already downloaded and checked.")
        return True
    say("This 8 MB file lets the tool suggest a seismic site class. It comes from the")
    say("NZ Community Velocity Model (University of Canterbury), MIT licence.")
    if not yes("Download it now?", "Y", inp):
        warn("Skipped. Site class will show as 'engineer to assign'.")
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import httpx
        tmp = target.with_suffix(".part")
        with httpx.stream("GET", VS30_URL, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) or 7641020
            done, last = 0, -1
            with open(tmp, "wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk); done += len(chunk)
                    pc = min(100, 100 * done // total)
                    if pc // 5 != last:
                        last = pc // 5
                        print(f"\r  Downloading... {pc:3d}%", end="", flush=True)
        print()
        if _sha(tmp) != VS30_SHA256:
            tmp.unlink(missing_ok=True)
            fail("The download was damaged (checksum did not match). Run setup again to retry.")
            return False
        tmp.replace(target)
    except Exception as e:
        print()
        fail(f"Download failed: {type(e).__name__}. Check the internet connection and run setup again.")
        say("If your office uses a web proxy, ask IT to allow media.githubusercontent.com.")
        return False
    cfg["vs30_h5"] = str(target); save_cfg(cfg)
    os.environ["NZGEO_VS30_H5"] = str(target)
    ok("Downloaded and checked.")
    return True


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def s5_councils(inp=input) -> bool:
    step(6, "Find council hazard maps (optional, takes 10–30 minutes)")
    from .discover import discover_all, load_catalogue
    have = len(load_catalogue().get("councils", {}))
    if have >= 70:
        ok(f"Council catalogue already built ({have} councils). Nothing to do.")
        return True
    say("The tool checks every council's online hazard maps. It can look them all up")
    say("now (best done once, while you have a coffee), or look up each council the")
    say("first time you run a site there (that first site is then slower).")
    if not yes("Look up all councils now?", "N", inp):
        warn("Skipped. Councils will be looked up as needed.")
        return True
    t0 = time.time()

    def prog(k, n, name):
        print(f"\r  [{k:2d}/{n}] {name[:44]:44s}", end="", flush=True)
    try:
        cat = discover_all(progress=prog)
    except Exception as e:
        print()
        fail(f"Stopped early: {type(e).__name__}. What was found is saved; run setup again to finish.")
        return False
    print()
    n = sum(len(v["layers"]) for v in cat["councils"].values())
    ok(f"Found {n} hazard layers across {len(cat['councils'])} councils in {(time.time() - t0) / 60:.0f} minutes.")
    return True


def s6_selftest(inp=input) -> bool:
    step(7, "Self-test")
    good = True
    from .secure import load_bundle
    load_bundle.cache_clear()
    b = load_bundle()
    if b and "nzs1170_5_z" in b:
        ok(f"Standards data opens ({len(b)} data sets)")
    else:
        fail("Standards data does not open. Run setup again and complete step 2.")
        good = False
    try:
        from . import coast, seismic
        p = seismic.ts_parameters(174.776, -41.287, apoe_n=500)
        assert p["location"]
        ok("TS 1170.5 tables work (test site: Wellington)")
        c = coast.distance(174.776, -41.287)
        assert c["distance_m"] is not None and c["distance_m"] < 2000
        ok(f"Coastline works (test site is {c['distance_m']} m from the coast)")
        if b:
            z = seismic.nzs1170_5_z(174.776, -41.287, b, apoe_n=500)
            assert abs(z["Z"] - 0.40) < 1e-9
            ok("NZS 1170.5 hazard factor works (Wellington Z = 0.40)")
    except Exception as e:
        fail(f"Built-in data check failed ({type(e).__name__}). Run the installer again.")
        good = False
    k = _wind_key_saved()
    if k and _wind_key_ok(k):
        ok("Wind calculator data opens")
    else:
        warn("Wind calculator data is locked (no wind key). Wind reports cannot be calculated.")
    import httpx
    for name, url in (("LINZ aerial photographs (historic and current)", "https://nz-imagery.s3-ap-southeast-2.amazonaws.com/catalog.json"),
                      ("LINZ address and parcel search", "https://services.arcgis.com/xdsHIIxuCWByZiCB/ArcGIS/rest/services?f=json"),("Earth Sciences NZ (geology and faults)", "https://gis.gns.cri.nz/server/rest/services?f=json"),
                      ("Stats NZ (council boundaries)", "https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services?f=json"),
                      ("Standards NZ (standards check)", "https://www.standards.govt.nz/"),
                      ("MBIE Building Performance (citations)", "https://www.building.govt.nz/")):
        try:
            r = httpx.get(url, timeout=15, follow_redirects=True)
            (ok if r.status_code < 400 else warn)(f"{name}: {'reachable' if r.status_code < 400 else 'answered ' + str(r.status_code)}")
        except Exception:
            warn(f"{name}: not reachable. Reports will say this data could not be retrieved. "
                 "If your office uses a proxy or firewall, ask IT to allow this site.")
    return good


def forget() -> int:
    """Remove saved keys (keychain entries and private files). Used when uninstalling."""
    try:
        import keyring
        keyring.delete_password("nzwind", "data-key")
    except Exception:
        pass
    (HOME_DIR / ".nzwind-data-key").unlink(missing_ok=True)
    for name in ("data-key", "linz-api-key"):
        try:
            import keyring
            keyring.delete_password("nzgeo", name)
        except Exception:
            pass
        (HOME_DIR / f".{name}").unlink(missing_ok=True)
    ok("Saved keys removed from this computer.")
    return 0


def main(argv=None, inp=input) -> int:
    if argv and "--forget" in argv:
        return forget()
    title("NZ Site Hazards – setup")
    say("This takes about 5 minutes. Read each step and follow the instructions.")
    say("You can close this window at any time and run setup again later;")
    say("finished steps are remembered.")
    results = []
    for fn in (s1_check, s2_data_key, s3_wind_key, s3_linz, s4_vs30, s5_councils, s6_selftest):
        r = fn(inp=inp)
        results.append(r)
        if fn in (s1_check,) and not r:
            break
    title("Setup finished" if all(results) else "Setup finished with problems")
    if all(results):
        say("Everything is ready.")
        say("To use the tool: double-click  'NZ Site Hazards'  on your desktop.")
    else:
        say("Fix the items marked PROBLEM above, then run setup again:")
        say("double-click  'NZ Site Hazards - Setup'  on your desktop.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
