"""Facebook Marketplace search through one persistent headless browser (the login lives in the data volume)."""

import os
import queue
import re
import threading
import urllib.parse

from .config import FB_PROFILE, UA
from .marktplaats import num

FB_EXTRACT_JS = r"""
() => Array.from(document.querySelectorAll('a[href*="/marketplace/np/item/"], a[href*="/marketplace/item/"]')).map(a => {
  const img = a.querySelector('img');
  return { href: a.href, img: img ? img.src : '',
           lines: a.innerText.split('\n').map(s => s.trim()).filter(Boolean) };
})
"""
PRICE_LINE = re.compile(r"^(€|EUR|\$|£|Gratis|Free)", re.I)
NOT_LOGGED_IN = "Facebook: niet ingelogd. Klik op 'Inloggen bij Facebook'."


def clear_stale_lock():
    """A container rebuild leaves Chromium's lock files in the volume ("profile in use by another computer").
    Only one browser of ours runs at a time, so a lock found before launching is always stale."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.remove(os.path.join(FB_PROFILE, name))
        except OSError:
            pass


def parse_cards(raw):
    items, seen = [], set()
    for rank, c in enumerate(raw):
        m = re.search(r"/marketplace/(?:np/)?item/(\d+)", c.get("href", ""))
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        lines = c.get("lines") or []
        prices = [ln for ln in lines if PRICE_LINE.match(ln)]
        rest = [ln for ln in lines if not PRICE_LINE.match(ln)]
        if not rest:
            continue
        label = prices[0] if prices else "Zie omschrijving"
        digits = re.sub(r"[^\d]", "", label.split(",")[0])
        price = int(digits) if digits else (0 if re.match(r"gratis|free", label, re.I) else None)
        items.append({
            "source": "facebook", "id": "fb-" + m.group(1), "rank": rank,
            "title": rest[0], "description": "",
            "price": price, "priceLabel": "Gratis" if price == 0 else label,
            "url": "https://www.facebook.com/marketplace/item/%s/" % m.group(1),
            "image": c.get("img") or "", "city": rest[1] if len(rest) > 1 else "",
            "distanceKm": None, "posted": "", "seller": "", "flags": [],
        })
    return items


def search_url(p):
    city = re.sub(r"\s+", "", (p.get("city") or "").strip().lower())
    qs = {"query": p["q"].strip(), "exact": "false"}
    mn, mx, km, days = num(p.get("min")), num(p.get("max")), num(p.get("km")), num(p.get("days"))
    if mn is not None:
        qs["minPrice"] = mn
    if mx is not None:
        qs["maxPrice"] = mx
    if km:
        qs["radius"] = km
    if days:
        qs["daysSinceListed"] = days
    qs["sortBy"] = {"newest": "creation_time_descend", "price_asc": "price_ascend",
                    "price_desc": "price_descend", "distance": "distance_ascend"}.get(p.get("sort"), "best_match")
    # /np/<city>/ is the form Facebook itself uses; it sets the location without the "postcode" popup
    base = "marketplace/np/%s/search" % city if city else "marketplace/search"
    return "https://www.facebook.com/%s?%s" % (base, urllib.parse.urlencode(qs))


class FacebookWorker(threading.Thread):
    """Playwright may only be used from one thread, so every job goes through this queue."""

    def __init__(self):
        super().__init__(daemon=True)
        self.jobs = queue.Queue()
        self.logged_in = None  # None = unknown

    def call(self, kind, arg=None, timeout=90):
        out = queue.Queue()
        self.jobs.put((kind, arg, out))
        res = out.get(timeout=timeout)
        if isinstance(res, Exception):
            raise res
        return res

    def search(self, p):
        return self.call("search", p)

    def release(self):
        """Close the browser so the login window can use the same profile."""
        return self.call("release", timeout=30)

    def check(self):
        return self.call("check", timeout=45)

    def run(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            ctx = None
            while True:
                kind, arg, out = self.jobs.get()
                try:
                    if kind == "release":
                        if ctx:
                            ctx.close()
                        ctx = None
                        out.put(True)
                        continue
                    if kind == "check" and not os.path.isdir(FB_PROFILE):
                        self.logged_in = False
                        out.put(False)
                        continue
                    if ctx is None:
                        clear_stale_lock()
                        ctx = pw.chromium.launch_persistent_context(
                            FB_PROFILE, headless=True, locale="nl-NL", user_agent=UA,
                            viewport={"width": 1280, "height": 1600})
                    if kind == "check":
                        self.logged_in = any(c["name"] == "c_user" for c in ctx.cookies("https://www.facebook.com"))
                        out.put(self.logged_in)
                    else:
                        out.put(self._search(ctx, arg))
                except Exception as e:  # noqa: BLE001
                    out.put(e)
                    try:
                        if ctx:
                            ctx.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ctx = None

    def _search(self, ctx, p):
        if not (p.get("q") or "").strip():
            return []
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not any(c["name"] == "c_user" for c in ctx.cookies("https://www.facebook.com")):
            self.logged_in = False
            raise RuntimeError(NOT_LOGGED_IN)
        page.goto(search_url(p), wait_until="domcontentloaded", timeout=45000)
        if "/login" in page.url or page.locator('input[name="pass"]').count():
            self.logged_in = False
            raise RuntimeError(NOT_LOGGED_IN)
        self.logged_in = True
        try:
            page.wait_for_selector('a[href*="/marketplace/np/item/"], a[href*="/marketplace/item/"]', timeout=15000)
        except Exception:  # noqa: BLE001
            return []
        for _ in range(2 if p.get("light") else 5):  # scrolling loads more results
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1200)
        return parse_cards(page.evaluate(FB_EXTRACT_JS))


FB = FacebookWorker()
