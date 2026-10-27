"""One-time Facebook login: a real browser inside the container, shown through noVNC on port 6080.

Run by the site ("Inloggen bij Facebook"); stops itself when the browser window is closed.
"""

import os
import socket
import subprocess
import sys
import threading
import time

from .config import FB_PROFILE, UA
from .facebook import FB, clear_stale_lock

DISPLAY = ":99"
NOVNC_PORT = 6080
MAX_SECONDS = 15 * 60

_procs = []
_lock = threading.Lock()


def running():
    return bool(_procs) and _procs[-1].poll() is None


def _wait(ready, what, seconds=15):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if ready():
            return
        time.sleep(0.2)
    raise RuntimeError("%s startte niet" % what)


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def start():
    """Returns when the login screen is reachable on port 6080, or raises."""
    with _lock:
        if running():
            return
        _stop_procs()
        FB.release()  # the browser profile can only be open once
        clear_stale_lock()
        env = dict(os.environ, DISPLAY=DISPLAY)
        try:
            steps = (
                (["Xvfb", DISPLAY, "-screen", "0", "1280x900x24"],
                 lambda: os.path.exists("/tmp/.X11-unix/X" + DISPLAY[1:]), "Het virtuele scherm"),
                (["x11vnc", "-display", DISPLAY, "-nopw", "-forever", "-shared", "-rfbport", "5900", "-quiet"],
                 lambda: _port_open(5900), "VNC"),
                (["websockify", "--web", "/usr/share/novnc", str(NOVNC_PORT), "localhost:5900"],
                 lambda: _port_open(NOVNC_PORT), "noVNC"),
            )
            for cmd, ready, what in steps:
                _procs.append(subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                _wait(ready, what)
            _procs.append(subprocess.Popen([sys.executable, "-m", "app.fblogin"], env=env))
            time.sleep(3)
            if not running():
                raise RuntimeError("De browser kon niet starten")
        except Exception:
            _stop_procs()
            raise
        threading.Thread(target=_watch, daemon=True).start()


def _watch():
    t0 = time.time()
    while running() and time.time() - t0 < MAX_SECONDS:
        time.sleep(1)
    stop()


def _stop_procs():
    for p in reversed(_procs):
        if p.poll() is None:
            p.terminate()
    for p in _procs:
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    _procs.clear()


def stop():
    with _lock:
        _stop_procs()
    try:
        FB.check()
    except Exception:  # noqa: BLE001
        pass


def _browser():
    """Runs inside the virtual display: open Facebook and wait until the window is closed."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            FB_PROFILE, headless=False, locale="nl-NL", user_agent=UA, no_viewport=True,
            args=["--window-position=0,0", "--window-size=1280,900"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.facebook.com/marketplace/")
        while ctx.pages:
            time.sleep(1)
        ctx.close()


if __name__ == "__main__":
    _browser()
