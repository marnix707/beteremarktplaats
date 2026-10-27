"""Search parameters and fetching, shared by the search page and the alarms."""

import threading
import time

from . import marktplaats
from .facebook import FB

SOURCES = ("marktplaats", "facebook")
TEXT_FIELDS = ("q", "min", "max", "pc", "km", "city", "days", "sort")
FILTER_FIELDS = ("wheel", "frameMin", "frameMax")  # applied afterwards, never sent to the sites
DEFAULT_FLAGS = {"noAds": True, "smart": True, "inTitle": True, "private": False, "needSize": False}


def _bool(v, default):
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "on", "yes")


def parse_params(raw):
    """Normalises query-string values or a stored alarm dict into one clean dict."""
    p = {k: str(raw.get(k) or "").strip() for k in TEXT_FIELDS}
    p["sort"] = p["sort"] or "newest"
    for k in FILTER_FIELDS:
        p[k] = str(raw.get(k) or "").strip()
    for k, default in DEFAULT_FLAGS.items():
        p[k] = _bool(raw.get(k), default)
    for key in ("exclude", "require"):
        words = raw.get(key) or []
        if isinstance(words, str):
            words = words.split(",")
        p[key] = [w.strip().lower() for w in words if w.strip()]
    src = raw.get("sources") or list(SOURCES)
    if isinstance(src, str):
        src = src.split(",")
    p["sources"] = [s for s in src if s in SOURCES]
    return p


_cache = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = 180


def _fetch(source, p):
    if source == "marktplaats":
        return marktplaats.search(p)
    return FB.search(p)


def fetch(source, p, fresh=True):
    """Alarms and explicit searches fetch fresh; changing a filter on the page reuses a recent result."""
    key = (source,) + tuple(p.get(k, "") for k in TEXT_FIELDS)
    now = time.time()
    if not fresh:
        with _cache_lock:
            hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return [dict(i) for i in hit[1]]
    items = _fetch(source, p)
    if not p.get("light"):
        with _cache_lock:
            for k in [k for k, v in _cache.items() if now - v[0] > CACHE_SECONDS]:
                del _cache[k]
            _cache[key] = (now, [dict(i) for i in items])
    return items
