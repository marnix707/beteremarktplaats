import queue
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import marktplaats, postcode
from . import alarms, config, db, fblogin, filters, notify, search
from .facebook import FB

STATIC = __file__.rsplit("/", 2)[0] + "/static"


@asynccontextmanager
async def lifespan(_):
    db.conn()
    FB.start()
    alarms.start()
    yield


app = FastAPI(title="BetereMarktplaats", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status():
    # Cheap, never starts the browser: Facebook is "unknown" until the first search or login check.
    return {"facebook": FB.logged_in, "loginRunning": fblogin.running(), "channels": notify.configured(),
            "suggest": filters.SUGGEST, "minInterval": config.MIN_INTERVAL_MIN}


@app.get("/api/search/{source}")
def search_source(source: str, request: Request):
    if source not in search.SOURCES:
        raise HTTPException(404)
    p = search.parse_params(request.query_params)
    if not p["q"]:
        return {"items": []}
    try:
        items = search.fetch(source, p, fresh=request.query_params.get("fresh") == "1")
    except queue.Empty:
        raise HTTPException(504, "Facebook reageerde niet op tijd.")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, (str(e).splitlines() or ["Onbekende fout"])[0][:200])
    hidden = db.hidden_ids()
    for it in items:
        it["why"] = filters.reasons(it, p, hidden)
        it["specs"] = filters.specs(it)
    return {"items": items}


@app.get("/api/postcode/{pc}")
def postcode_city(pc: str):
    try:
        name = postcode.city(pc)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "Postcode opzoeken mislukt.")
    return {"city": name, "slug": postcode.facebook_slug(name) if name else None}


@app.get("/api/default")
def get_default():
    return db.get_setting("default_search")


@app.put("/api/default")
def put_default(body: dict):
    if not str(body.get("q", "")).strip():
        raise HTTPException(400, "Vul eerst een zoekterm in.")
    db.set_setting("default_search", body)
    return {"ok": True}


@app.delete("/api/default")
def delete_default():
    db.set_setting("default_search", None)
    return {"ok": True}


@app.get("/api/bids")
def bids(url: str):
    try:
        return marktplaats.bids(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "Biedingen ophalen mislukt.")


@app.put("/api/hide/{item_id}")
def hide(item_id: str):
    db.set_hidden(item_id, True)
    return {"ok": True}


@app.delete("/api/hide/{item_id}")
def unhide(item_id: str):
    db.set_hidden(item_id, False)
    return {"ok": True}


# ---- Facebook login

@app.post("/api/facebook/login")
def facebook_login():
    try:
        fblogin.start()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, "Inloggen starten mislukt: %s" % e)
    return {"ok": True}


@app.delete("/api/facebook/login")
def facebook_login_stop():
    fblogin.stop()
    return {"ok": True}


@app.post("/api/facebook/check")
def facebook_check():
    try:
        return {"facebook": FB.check()}
    except Exception:  # noqa: BLE001
        return {"facebook": None}


# ---- Alarms

class AlarmIn(BaseModel):
    params: dict
    channels: list[str] = Field(default_factory=lambda: ["browser"])
    interval_min: int = 10


def _public(a):
    return {k: a[k] for k in ("id", "name", "params", "channels", "interval_min", "enabled", "last_run",
                              "last_status")}


@app.get("/api/alarms")
def list_alarms():
    return [_public(a) for a in db.list_alarms()]


@app.post("/api/alarms")
def create_alarm(body: AlarmIn):
    p = search.parse_params(body.params)
    if not p["q"] or not p["sources"]:
        raise HTTPException(400, "Vul een zoekterm in en kies minstens één site.")
    channels = [c for c in body.channels if c in notify.CHANNELS]
    if not channels:
        raise HTTPException(400, "Kies minstens één manier om gewaarschuwd te worden.")
    interval = max(config.MIN_INTERVAL_MIN, min(body.interval_min, 1440))
    alarm_id = db.add_alarm(p["q"], p, channels, interval)
    return _public(db.get_alarm(alarm_id))


def _get(alarm_id):
    a = db.get_alarm(alarm_id)
    if not a:
        raise HTTPException(404)
    return a


@app.patch("/api/alarms/{alarm_id}")
def toggle_alarm(alarm_id: int, enabled: bool):
    _get(alarm_id)
    db.set_enabled(alarm_id, enabled)
    return {"ok": True}


@app.delete("/api/alarms/{alarm_id}")
def delete_alarm(alarm_id: int):
    db.delete_alarm(alarm_id)
    return {"ok": True}


@app.post("/api/alarms/{alarm_id}/test")
def test_alarm(alarm_id: int):
    a = _get(alarm_id)
    return notify.deliver(alarm_id, a["channels"], "Testalarm: %s" % a["name"],
                          "Zo ziet een melding eruit.", config.PUBLIC_URL)


@app.post("/api/alarms/{alarm_id}/run")
def run_alarm(alarm_id: int):
    a = _get(alarm_id)
    result = {}
    t = threading.Thread(target=lambda: result.update(status=alarms.run(a)))
    t.start()
    t.join(120)
    return {"status": result.get("status", "duurt lang, het resultaat volgt vanzelf")}


@app.get("/api/notifications")
def notifications(after: int | None = None):
    # No `after`: just tell the page where we are, so old messages are not replayed
    if after is None:
        return {"last": db.last_notification_id(), "items": []}
    items = db.notifications_after(after)
    return {"last": items[-1]["id"] if items else after, "items": items}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
