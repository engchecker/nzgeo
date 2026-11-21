"""HTTP with an on-disk cache, so repeated runs and offline review use the same data."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import httpx

from .config import settings

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=settings.timeout_s, follow_redirects=True,
                               headers={"User-Agent": settings.user_agent})
    return _client


def _cache_file(url: str, params: dict | None):
    key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    return settings.cache_dir / key[:2] / f"{key}.json"


def fetch(url: str, params: dict | None = None, *, as_json: bool = True, ttl_days: float | None = None,
          use_cache: bool = True):
    """GET a URL. Returns (body, retrieved_at_iso). Raises httpx errors on failure."""
    ttl = settings.cache_ttl_days if ttl_days is None else ttl_days
    path = _cache_file(url, params)
    if use_cache and path.exists() and (time.time() - path.stat().st_mtime) < ttl * 86400:
        rec = json.loads(path.read_text())
        return rec["body"], rec["retrieved"]
    r = client().get(url, params=params)
    r.raise_for_status()
    body = r.json() if as_json else r.text
    if as_json and isinstance(body, dict) and "error" in body and isinstance(body["error"], dict):
        raise httpx.HTTPStatusError(f"ArcGIS error {body['error']}", request=r.request, response=r)
    retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if use_cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "params": params, "retrieved": retrieved, "body": body}))
    return body, retrieved


def fetch_bytes(url: str, params: dict | None = None, *, ttl_days: float = 30) -> bytes:
    """GET binary content (map images) with the same on-disk cache."""
    path = _cache_file(url, params).with_suffix(".bin")
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_days * 86400:
        return path.read_bytes()
    r = client().get(url, params=params)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith(("application/json", "text/")):
        raise httpx.HTTPStatusError(f"Expected an image, got {r.text[:200]}", request=r.request, response=r)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.content
