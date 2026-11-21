"""Encrypted bundle for maps and tables digitised from licensed copies of the standards.

AES-256-GCM. The key is read from NZGEO_DATA_KEY (base64), then the OS keychain
(service 'nzgeo', user 'data-key'). Without a key, checks that need the bundle report
'unavailable' rather than guessing.

Build:   python -m nzgeo.secure build <folder>      (folder of .json/.geojson files; key = file stem)
Key:     python -m nzgeo.secure newkey [--store]
"""
from __future__ import annotations

import base64
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

from .config import settings

MAGIC = b"NZGEO1"


def _key() -> bytes | None:
    from .config import _secret
    k = _secret("data-key")
    try:
        return base64.b64decode(k.strip()) if k else None
    except Exception:
        return None


def check_key(k: str) -> bool:
    """True if k opens the bundle."""
    try:
        decrypt(Path(settings.bundle_path).read_bytes(), base64.b64decode(k.strip()))
        return True
    except Exception:
        return False


def encrypt(obj: dict, key: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, json.dumps(obj).encode(), MAGIC)


def decrypt(blob: bytes, key: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not blob.startswith(MAGIC):
        raise ValueError("not an nzgeo bundle")
    nonce, ct = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
    return json.loads(AESGCM(key).decrypt(nonce, ct, MAGIC))


@lru_cache(maxsize=1)
def load_bundle() -> dict | None:
    p = Path(settings.bundle_path)
    k = _key()
    if not p.exists() or not k:
        return None
    return decrypt(p.read_bytes(), k)


def _main(argv: list[str]) -> None:
    if argv[:1] == ["newkey"]:
        k = base64.b64encode(os.urandom(32)).decode()
        if "--store" in argv:
            import keyring
            keyring.set_password("nzgeo", "data-key", k)
            print("Key stored in the OS keychain (service 'nzgeo').")
        else:
            print(k)
    elif argv[:1] == ["build"] and len(argv) == 2:
        k = _key()
        if not k:
            sys.exit("No key: set NZGEO_DATA_KEY or run `newkey --store` first")
        obj = {p.stem: json.loads(p.read_text()) for p in sorted(Path(argv[1]).glob("*.*json"))}
        Path(settings.bundle_path).write_bytes(encrypt(obj, k))
        print(f"Wrote {settings.bundle_path} with: {', '.join(obj)}")
    else:
        print(__doc__)


if __name__ == "__main__":
    _main(sys.argv[1:])
