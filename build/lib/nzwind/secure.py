"""Encrypted storage for the AS/NZS 1170 data tables.

The tables live only in data/standards.enc (AES-256-GCM). They are decrypted in memory when the
tool starts and are never written to disk in plain form.

Key lookup, in order:
  1. NZWIND_DATA_KEY environment variable (base64url, 32 bytes)
  2. NZWIND_DATA_KEY_FILE environment variable naming a file that holds the key
  3. The operating system keychain (Windows Credential Manager, macOS Keychain, Secret Service),
     service "nzwind", account "data-key"

Commands:
  python -m nzwind.secure check            confirm the key opens the data
  python -m nzwind.secure store-key        save the current key in the OS keychain
  python -m nzwind.secure rekey            new key, re-encrypt, store the new key in the OS keychain
  python -m nzwind.secure rekey --print    as above, and print the new key once (for a password manager)
"""
import base64, gzip, json, os, secrets, sys
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BUNDLE = Path(os.environ.get("NZWIND_DATA", Path(__file__).resolve().parent / "data")) / "standards.enc"
MAGIC = b"NZW1"
AAD = b"nzwind-standards-v1"
KEYRING = ("nzwind", "data-key")

class DataKeyError(RuntimeError):
    pass

def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None

def _decode(k: str) -> bytes:
    raw = base64.urlsafe_b64decode(k.strip() + "=" * (-len(k.strip()) % 4))
    if len(raw) != 32:
        raise DataKeyError("Data key must be 32 bytes (base64url)")
    return raw

def get_key() -> bytes:
    if os.environ.get("NZWIND_DATA_KEY"):
        return _decode(os.environ["NZWIND_DATA_KEY"])
    if os.environ.get("NZWIND_DATA_KEY_FILE"):
        return _decode(Path(os.environ["NZWIND_DATA_KEY_FILE"]).read_text())
    kr = _keyring()
    if kr:
        try:
            k = kr.get_password(*KEYRING)
            if k:
                return _decode(k)
        except Exception:
            pass
    raise DataKeyError("The standards data is encrypted and no key was found. Set NZWIND_DATA_KEY, "
                       "or run `python -m nzwind.secure store-key` once with the key set.")

def encrypt(tables: dict, key: bytes, path: Path = BUNDLE):
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, gzip.compress(json.dumps(tables).encode()), AAD)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(MAGIC + nonce + ct)
    os.replace(tmp, path)

def decrypt(key: bytes | None = None, path: Path = BUNDLE) -> dict:
    blob = path.read_bytes()
    if blob[:4] != MAGIC:
        raise DataKeyError(f"{path.name} is not an nzwind data bundle")
    try:
        pt = AESGCM(key or get_key()).decrypt(blob[4:16], blob[16:], AAD)
    except Exception as e:
        if isinstance(e, DataKeyError):
            raise
        raise DataKeyError("The data key does not open the standards data (wrong key, or the file has been altered)") from None
    return json.loads(gzip.decompress(pt))

def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

def store_key(k: str):
    kr = _keyring()
    if not kr:
        raise DataKeyError("Python keyring is not available; keep the key in NZWIND_DATA_KEY instead")
    kr.set_password(*KEYRING, k)

def main(argv):
    cmd = argv[0] if argv else "check"
    if cmd == "check":
        t = decrypt()
        print(f"OK: {len(t)} tables decrypted in memory; data version {t['general_rules']['_meta']['version']}")
    elif cmd == "store-key":
        k = os.environ.get("NZWIND_DATA_KEY")
        if not k:
            raise SystemExit("Set NZWIND_DATA_KEY first")
        decrypt(_decode(k))
        store_key(k)
        print("Key saved in the OS keychain. You can now remove NZWIND_DATA_KEY from the environment.")
    elif cmd == "rekey":
        tables = decrypt()
        k = new_key()
        stored = False
        try:
            store_key(k); stored = True
        except Exception as e:
            if "--print" not in argv:
                raise SystemExit(f"Could not store the new key in the OS keychain ({e}); rerun with --print and keep the key yourself")
        encrypt(tables, _decode(k))
        decrypt(_decode(k))
        print("Data re-encrypted with a new key." + (" New key stored in the OS keychain." if stored else ""))
        if "--print" in argv:
            print(f"New key (shown once): {k}")
    else:
        raise SystemExit(__doc__)

if __name__ == "__main__":
    main(sys.argv[1:])
