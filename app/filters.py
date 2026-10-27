"""Decides which results are hidden and why. Used by the search page and by the alarms."""

import re
import unicodedata

SUGGEST = ["opknapper", "kapot", "defect", "reparatie", "onderdelen", "gezocht", "helm", "slot", "tas", "zitje"]


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def toks(s):
    return [t for t in re.split(r"[^a-z0-9]+", norm(s)) if t]


def relevance(title, q):
    """Every search word must be in the title, and the item must really be that thing.
    A word counts as a hit when it is a whole word or the end of a Dutch compound ('damesfiets' is a fiets),
    or the start of a compound that ends in another search word ('herenfiets' = heren + fiets).
    'fietsshirt' and 'fietshelm' only start with fiets, so they are accessories."""
    words = [w for w in toks(q) if len(w) >= 3]
    if not words:
        return None
    nt = norm(title)
    if any(w not in nt for w in words):
        return "niet in titel"
    tw = toks(title)

    def tail(t, k):
        return any(t == k + f or (t.endswith(k + f) and len(t) > len(k + f) + 1) for f in ("", "s", "en", "n", "je", "jes"))

    def hit(w):
        if any(tail(t, w) for t in tw):
            return True
        others = [o for o in words if o != w]
        return any(t.startswith(w) and any(tail(t, o) for o in others) for t in tw)

    return None if all(hit(w) for w in words) else "accessoire"


WHEEL_RE = re.compile(r"(?<![\d.,])(\d{2}(?:[.,]\d)?)\s*-?\s*(?:inch|inches|duim|\"|\u201d|\u2033|'')", re.I)
WHEEL_WORD_RE = re.compile(r"wiel(?:maat|en|grootte)?\s*[:=]?\s*(\d{2}(?:[.,]\d)?)", re.I)
FRAME_RE = re.compile(r"(?:frame(?:maat|hoogte|grootte)?|maat|fh|rh)\s*[:=]?\s*(?:cm\s*)?(\d{2})(?!\d)", re.I)
CM_RE = re.compile(r"(?<![\d.,/])(\d{2})\s*cm\b", re.I)


def specs(item):
    """Wheel size (inch) and frame size (cm) as far as the title/description say it."""
    text = (item.get("title") or "") + " . " + (item.get("description") or "")
    wheel = {float(m.replace(",", ".")) for m in WHEEL_RE.findall(text) + WHEEL_WORD_RE.findall(text)}
    if re.search(r"\b700\s*c\b", text, re.I):
        wheel.add(28.0)
    wheel = sorted(w for w in wheel if 12 <= w <= 29.5)
    frame = {int(m) for m in FRAME_RE.findall(text) + CM_RE.findall(text)}
    frame = sorted(f for f in frame if 40 <= f <= 70)
    return {"wheel": wheel, "frame": frame}


def reasons(item, p, hidden_ids=()):
    r = []
    flags = item.get("flags") or []
    if item["id"] in hidden_ids:
        r.append("door jou verborgen")
    if p.get("noAds"):
        if "advertentie" in flags:
            r.append("advertentie")
        elif "betaald" in flags:
            r.append("betaalde plaatsing")
        if "website" in flags:
            r.append("link naar website")
    if p.get("private") and "bedrijf" in flags:
        r.append("bedrijf")
    rel = relevance(item.get("title", ""), p.get("q", ""))
    if rel == "accessoire" and p.get("smart"):
        r.append("accessoire")
    if rel == "niet in titel" and p.get("inTitle"):
        r.append("zoekwoord niet in titel")
    text = norm(item.get("title", "") + " " + item.get("description", ""))
    for w in p.get("exclude") or []:
        if norm(w) and norm(w) in text:
            r.append('bevat "%s"' % w)
            break
    for w in p.get("require") or []:
        if norm(w) and norm(w) not in text:
            r.append('mist "%s"' % w)
            break
    r += size_reasons(item, p)
    return r


def _num(v):
    try:
        return float(str(v).replace(",", ".")) if str(v).strip() else None
    except ValueError:
        return None


def size_reasons(item, p):
    """Only hides what is clearly wrong; an ad that does not mention a size stays (unless 'needSize')."""
    wheel, fmin, fmax = _num(p.get("wheel")), _num(p.get("frameMin")), _num(p.get("frameMax"))
    if wheel is None and fmin is None and fmax is None:
        return []
    sp = specs(item)
    r = []
    if wheel is not None:
        if sp["wheel"] and wheel not in sp["wheel"]:
            r.append("wielmaat %s inch" % ("/".join("%g" % w for w in sp["wheel"])))
        elif not sp["wheel"] and p.get("needSize"):
            r.append("wielmaat onbekend")
    if fmin is not None or fmax is not None:
        f = sp["frame"]
        if f and fmin is not None and max(f) < fmin:
            r.append("frame %s cm (te klein)" % max(f))
        elif f and fmax is not None and min(f) > fmax:
            r.append("frame %s cm (te groot)" % min(f))
        elif not f and p.get("needSize"):
            r.append("framemaat onbekend")
    return r
