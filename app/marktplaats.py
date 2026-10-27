"""Marktplaats search through its public JSON API."""

import json
import re
import time
import urllib.parse

import httpx

from .config import UA

URL_RE = re.compile(r"(https?://|www\.)|\b[a-z0-9-]{3,}\.(nl|com|be|de|eu|shop|store|net)\b", re.I)
BUSINESS_TRAITS = {"ADMARKT_CONSOLE", "CUSTOMER_SUPPORT_BUSINESS_LINE", "SELLER_PROFILE_URL",
                   "UNIQUE_SELLING_POINTS", "SHOPPING_CART"}
PRICE_LABELS = {"BID": "Bieden", "FREE": "Gratis", "RESERVED": "Gereserveerd",
                "SEE_DESCRIPTION": "Zie omschrijving", "TO_BE_AGREED_UPON": "N.o.t.k.",
                "ON_REQUEST": "Op aanvraag", "EXCHANGE": "Ruilen", "FAST_BID": "Bieden"}
ORIGIN = "https://www.marktplaats.nl"


def _abs(url):
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return ORIGIN + url
    return url


BID_TYPES = ("MIN_BID", "BID_FROM", "BID", "FAST_BID")
VIP_RE = re.compile(r"^https://www\.marktplaats\.nl/v/[\w\-./]+$")
_bid_cache = {}
BID_CACHE_SECONDS = 120


def bids(url):
    """Bids are not in the search results, only on the ad page. Returns {"count": n, "highest": euros | None}."""
    if not VIP_RE.match(url):
        raise ValueError("geen Marktplaats-advertentie")
    now = time.time()
    hit = _bid_cache.get(url)
    if hit and now - hit[0] < BID_CACHE_SECONDS:
        return hit[1]
    r = httpx.get(url, headers={"User-Agent": UA, "Accept-Language": "nl-NL,nl;q=0.9"},
                  timeout=20, follow_redirects=False)
    r.raise_for_status()
    t = r.text
    i = t.find('"isBiddingEnabled"')
    j = t.find('"bids":', i) if i >= 0 else -1
    if j < 0:
        raise ValueError("biedingen niet gevonden")
    arr, _ = json.JSONDecoder().raw_decode(t[j + 7:])
    values = [b["value"] for b in arr if isinstance(b.get("value"), (int, float))]
    out = {"count": len(values), "highest": max(values) / 100 if values else None}
    if len(_bid_cache) > 500:
        _bid_cache.clear()
    _bid_cache[url] = (now, out)
    return out


def hq_image(raw):
    """The list only carries a ~150px thumbnail; the same picture exists at ~730px (rule $_85)."""
    pics = raw.get("pictures") or []
    url = (pics[0].get("extraExtraLargeUrl") or pics[0].get("largeUrl")) if pics else ""
    if not url:
        urls = raw.get("imageUrls") or []
        url = re.sub(r"\$_\d+\.jpg", "$_85.jpg", urls[0]) if urls else ""
    return url


def num(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def search(p):
    q = (p.get("q") or "").strip()
    if not q:
        return []
    base = {"query": q, "limit": "100", "searchInTitleAndDescription": "true", "viewOptions": "list-view"}
    sort = p.get("sort", "newest")
    if sort == "newest":
        base.update(sortBy="SORT_INDEX", sortOrder="DECREASING")
    elif sort == "price_asc":
        base.update(sortBy="PRICE", sortOrder="INCREASING")
    elif sort == "price_desc":
        base.update(sortBy="PRICE", sortOrder="DECREASING")
    elif sort == "distance":
        base.update(sortBy="LOCATION", sortOrder="INCREASING")
    pc = (p.get("pc") or "").replace(" ", "").upper()
    km = num(p.get("km"))
    if pc and km:
        base["postcode"] = pc
        base["distanceMeters"] = str(km * 1000)
    extra = []
    mn, mx = num(p.get("min")), num(p.get("max"))
    if mn is not None or mx is not None:
        extra.append(("attributeRanges[]", "PriceCents:%d:%d" % ((mn or 0) * 100,
                                                                 (mx if mx is not None else 1000000) * 100)))
    days = num(p.get("days"))
    if days:
        extra.append(("attributesByKey[]", "offeredSince:%d" % int((time.time() - days * 86400) * 1000)))

    items, seen = [], set()
    pages = 1 if p.get("light") else 3  # up to ~300 results
    headers = {"User-Agent": UA, "Accept": "application/json", "Accept-Language": "nl-NL,nl;q=0.9"}
    with httpx.Client(timeout=20, headers=headers) as client:
        for page in range(pages):
            params = list(base.items()) + extra + [("offset", str(page * 100))]
            r = client.get(ORIGIN + "/lrp/api/search?" + urllib.parse.urlencode(params))
            r.raise_for_status()
            data = r.json()
            listings = data.get("listings") or []
            for rank, raw in enumerate(listings):
                it = parse_item(raw, page * 100 + rank)
                if it and it["id"] not in seen:
                    seen.add(it["id"])
                    items.append(it)
            total = data.get("totalResultCount") or 0
            if len(listings) < 100 or (page + 1) * 100 >= total:
                break
    return items


def parse_item(raw, rank):
    item_id = str(raw.get("itemId") or "")
    if not item_id:
        return None
    price = raw.get("priceInfo") or {}
    cents = price.get("priceCents") or 0
    ptype = price.get("priceType") or ""
    loc = raw.get("location") or {}
    seller = raw.get("sellerInformation") or {}
    traits = set(raw.get("traits") or [])
    dist = loc.get("distanceMeters")
    imgs = [hq_image(raw)]
    desc = raw.get("categorySpecificDescription") or raw.get("description") or ""
    website = str(seller.get("sellerWebsiteUrl") or "")

    flags = []
    if raw.get("priorityProduct") and raw.get("priorityProduct") != "NONE":
        flags.append("betaald")        # Topadvertentie / Dagtopper
    if item_id.startswith("a") or "admarkt" in website or raw.get("adType") == "Admarkt":
        flags.append("advertentie")    # Admarkt: ads from businesses
    if traits & BUSINESS_TRAITS:
        flags.append("bedrijf")
    if website or URL_RE.search(desc):
        flags.append("website")        # sends you to an external site

    if cents and ptype in ("FIXED", "", "MIN_BID", "BID_FROM"):
        label = "€ " + format(cents / 100, ",.0f").replace(",", ".")
        if ptype in ("MIN_BID", "BID_FROM"):
            label = "Bieden v.a. " + label
    else:
        label = PRICE_LABELS.get(ptype, "Zie omschrijving")

    return {
        "source": "marktplaats", "id": "mp-" + item_id, "rank": rank,
        "title": raw.get("title") or "", "description": desc[:700],
        "price": cents / 100 if cents else None, "priceLabel": label,
        "url": _abs(raw.get("vipUrl")) or ORIGIN + "/v/" + item_id,
        "image": _abs(imgs[0]) if imgs and imgs[0] else "",
        "city": loc.get("cityName") or "",
        "distanceKm": round(dist / 1000, 1) if isinstance(dist, (int, float)) and dist >= 0 else None,
        "posted": raw.get("date") or "",
        "seller": seller.get("sellerName") or "",
        "flags": flags,
        "bid": ptype in BID_TYPES,
    }
