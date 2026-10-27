"""Alarms: saved searches that are re-run in the background and report new results."""

import logging
import random
import threading
import time

from . import db, filters, notify, search

log = logging.getLogger("alarms")
MAX_INDIVIDUAL = 5  # more new results than this in one run: the rest is summarised in one message
_run_lock = threading.Lock()


def new_items(alarm):
    """Fetches every source of the alarm and returns (new visible items, errors, sources now seeded).

    A source is seeded on its first successful run: its current results count as seen, nothing is reported.
    """
    p = dict(alarm["params"], light=True, sort="newest")
    hidden = db.hidden_ids()
    seen = db.seen_ids(alarm["id"])
    seeded = set(alarm["seeded"])
    found, errors = [], []
    for src in p["sources"]:
        try:
            items = search.fetch(src, p)
        except Exception as e:  # noqa: BLE001
            errors.append("%s: %s" % (src, (str(e).splitlines() or [e.__class__.__name__])[0][:120]))
            continue
        if src in seeded:
            found += [i for i in items if i["id"] not in seen and not filters.reasons(i, p, hidden)]
        seeded.add(src)
        db.mark_seen(alarm["id"], [i["id"] for i in items])
    return found, errors, seeded


def _message(item):
    title = "%s · %s" % (item["priceLabel"], item["title"])
    body = " · ".join(x for x in (item["source"].capitalize(), item["city"]) if x)
    return title, body


def run(alarm):
    with _run_lock:
        found, errors, seeded = new_items(alarm)
        sent = {}
        for it in found[:MAX_INDIVIDUAL]:
            title, body = _message(it)
            sent = notify.deliver(alarm["id"], alarm["channels"], title, body, it["url"], it["image"])
        if len(found) > MAX_INDIVIDUAL:
            notify.deliver(alarm["id"], alarm["channels"], "%d nieuwe resultaten voor '%s'" % (
                len(found) - MAX_INDIVIDUAL, alarm["name"]), "Open de site om ze te bekijken.")
        status = "%d nieuw" % len(found) if found else "niets nieuws"
        bad = ["%s: %s" % (c, e) for c, e in sent.items() if e] + errors
        if bad:
            status += " · " + "; ".join(bad)
        nxt = time.time() + alarm["interval_min"] * 60 + random.uniform(0, 60)
        db.finish_run(alarm["id"], seeded, nxt, status)
        return status


def loop():
    while True:
        try:
            for alarm in db.due_alarms(time.time()):
                try:
                    run(alarm)
                except Exception:  # noqa: BLE001
                    log.exception("alarm %s failed", alarm["id"])
                    db.finish_run(alarm["id"], alarm["seeded"], time.time() + 600, "fout bij controleren")
        except Exception:  # noqa: BLE001
            log.exception("alarm loop")
        time.sleep(20)


def start():
    threading.Thread(target=loop, daemon=True, name="alarms").start()
