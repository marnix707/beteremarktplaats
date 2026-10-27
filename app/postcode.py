"""Postcode -> city through PDOK Locatieserver (free, Dutch government)."""

import re

import httpx

PC_RE = re.compile(r"^\d{4}\s?([A-Za-z]{2})?$")
_cache = {}


def city(pc):
    pc = pc.replace(" ", "").upper()
    if not PC_RE.match(pc):
        raise ValueError("ongeldige postcode")
    if pc not in _cache:
        r = httpx.get("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free", timeout=10,
                      params={"q": "postcode:" + pc, "fq": "type:postcode", "rows": 1, "fl": "woonplaatsnaam"})
        r.raise_for_status()
        docs = r.json()["response"]["docs"]
        _cache[pc] = docs[0]["woonplaatsnaam"] if docs else None
    return _cache[pc]


def facebook_slug(name):
    """Facebook marketplace city slug: lowercase letters/digits only, 's-Gravenhage is Den Haag."""
    if name == "'s-Gravenhage":
        return "denhaag"
    return re.sub(r"[^a-z0-9]", "", name.lower())
