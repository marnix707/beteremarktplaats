"""Delivers an alarm message to the chosen channels. Each channel fails on its own."""

import smtplib
from email.message import EmailMessage

import httpx

from . import config, db

CHANNELS = ("browser", "ntfy", "email")


def configured():
    return {
        "browser": True,
        "ntfy": bool(config.NTFY_TOPIC),
        "email": bool(config.SMTP_HOST and config.SMTP_FROM and config.SMTP_TO),
    }


def _ntfy(title, body, url, image):
    msg = {"topic": config.NTFY_TOPIC, "title": title, "message": body, "tags": ["bell"]}
    if url:
        msg["click"] = url
    if image.startswith("https://"):
        msg["attach"] = image
    httpx.post(config.NTFY_URL, json=msg, timeout=15).raise_for_status()


def _email(title, body, url, image):
    m = EmailMessage()
    m["Subject"] = title
    m["From"] = config.SMTP_FROM
    m["To"] = config.SMTP_TO
    m.set_content("%s\n\n%s" % (body, url))
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            _send(s, m)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            _send(s, m)


def _send(s, m):
    if config.SMTP_USER:
        s.login(config.SMTP_USER, config.SMTP_PASSWORD)
    s.send_message(m)


def deliver(alarm_id, channels, title, body, url="", image=""):
    """Returns {channel: None | error text}."""
    ok = configured()
    result = {}
    for ch in channels:
        try:
            if ch not in CHANNELS or not ok[ch]:
                raise RuntimeError("niet ingesteld")
            if ch == "browser":
                db.add_notification(alarm_id, title, body, url, image)
            elif ch == "ntfy":
                _ntfy(title, body, url, image)
            else:
                _email(title, body, url, image)
            result[ch] = None
        except Exception as e:  # noqa: BLE001
            result[ch] = str(e)[:200] or e.__class__.__name__
    return result
