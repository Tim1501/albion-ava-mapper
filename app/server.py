"""Albion Ava Mapper - search Roads of Avalon zones and see what each one holds.

Runs a small web server on 127.0.0.1 and opens the UI in its own Edge app window.
Everything it keeps lives in the `data` folder next to the exe:

    data/game/      zone cards built from Albion's game files (rebuilt by "Update zone data")
    data/icons/     resource icons from render.albiononline.com, saved the first time they're shown
    data/saved.json the zones you starred
    data/settings.json  overlay position, hotkey and capture size
    (the last hotkey capture is only kept in memory, never written to disk)
    data/logs/      error log
"""
import datetime
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import avadata
import capture

try:
    import webview  # pywebview: the always-on-top overlay window
except Exception:  # noqa: BLE001
    webview = None

APP_NAME = "Albion Ava Mapper"
WINDOW_TITLE = "Albion Ava Mapper"  # must match <title> in static/index.html
APP_VERSION = "1.0.0"
DONATE_URL = "https://www.paypal.com/paypalme/DeepTak646"
DISCORD_NAME = "ChanaMasala"
REPO_URL = "https://github.com/Tim1501/albion-ava-mapper"
PORT = int(os.environ.get("AVA_PORT", "8773"))
HOST = "127.0.0.1"
RENDER = "https://render.albiononline.com/v1"

if getattr(sys, "frozen", False):
    # release folder: "Albion Ava Mapper\Albion Ava Mapper.exe" with "data\" right next to it
    ROOT_DIR = os.path.dirname(os.path.abspath(sys.executable))
    STATIC_DIR = os.path.join(sys._MEIPASS, "static")  # type: ignore[attr-defined]
else:
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

DATA_DIR = os.environ.get("AVA_DATA_DIR") or os.path.join(ROOT_DIR, "data")
GAME_DIR = os.path.join(DATA_DIR, "game")
ICON_DIR = os.path.join(DATA_DIR, "icons")
LOG_DIR = os.path.join(DATA_DIR, "logs")
SAVED_FILE = os.path.join(DATA_DIR, "saved.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
for d in (GAME_DIR, ICON_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)


def log(msg):
    try:
        with open(os.path.join(LOG_DIR, "app.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except OSError:
        pass


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# --- background job: update zone data ------------------------------------
JOB = {"running": False, "text": "", "progress": 0.0, "error": None}
JOB_LOCK = threading.Lock()


def set_job(**kw):
    with JOB_LOCK:
        JOB.update(kw)


def start_update():
    with JOB_LOCK:
        if JOB["running"]:
            raise ApiError("An update is already running.", 409)
        JOB.update(running=True, text="Starting…", progress=0.0, error=None)

    def run():
        try:
            meta = avadata.update(GAME_DIR, lambda text, p: set_job(text=text, progress=p))
            global _matcher
            _matcher = None  # re-read the zone names for the hotkey
            set_job(running=False, progress=1.0, text=f"Zone data ready: {meta['zones']} zones")
            log(f"Zone data updated ({meta.get('version')})")
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            set_job(running=False, error=str(e) or e.__class__.__name__)
    threading.Thread(target=run, daemon=True).start()


# --- resource icons --------------------------------------------------------
ICON_RE = re.compile(r"^(ORE|WOOD|FIBER|HIDE|ROCK)$")
_icon_lock = threading.Lock()


def resource_icon(name):
    """Cached icon file. Saved as .cache, not .png: on some PCs, an unknown program writing image
    files gets frozen by monitoring software. Older .png caches are still read."""
    path = os.path.join(ICON_DIR, f"{name}.cache")
    for p in (path, os.path.join(ICON_DIR, f"{name}.png")):
        if os.path.isfile(p):
            return p
    with _icon_lock:
        if os.path.isfile(path):
            return path
        for attempt in range(3):
            try:
                req = urllib.request.Request(f"{RENDER}/item/T5_{name}.png?size=96", headers=avadata.UA)
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                if data.startswith(b"\x89PNG"):
                    with open(path, "wb") as f:
                        f.write(data)
                    return path
            except Exception as e:  # noqa: BLE001
                log(f"Icon {name} failed: {e}")
            time.sleep(1.5 * (attempt + 1))
    return None


# --- api -------------------------------------------------------------------
UPDATE = {}  # {"version", "url"} when GitHub has a newer release


def check_update():
    """Ask GitHub once per start whether a newer release exists (shown as a pill in the header)."""
    def ver(t):
        return tuple(int(x) for x in re.findall(r"\d+", t)[:3])
    try:
        api = REPO_URL.replace("https://github.com/", "https://api.github.com/repos/") + "/releases/latest"
        req = urllib.request.Request(api, headers={"User-Agent": "AlbionAvaMapper/" + APP_VERSION})
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.loads(r.read())
        if ver(rel.get("tag_name", "")) > ver(APP_VERSION):
            UPDATE.update(version=rel["tag_name"].lstrip("v"), url=rel.get("html_url") or REPO_URL + "/releases/latest")
            log(f"Update available: {UPDATE['version']}")
    except Exception as e:  # noqa: BLE001
        log(f"Update check failed: {e}")


def api_open_release(req):
    webbrowser.open(UPDATE.get("url") or REPO_URL + "/releases/latest")
    return {"ok": True}


def api_meta(req):
    return {"app": APP_NAME, "version": APP_VERSION, "update": UPDATE or None, "game": read_json(os.path.join(GAME_DIR, "meta.json")), "job": dict(JOB), "dataDir": DATA_DIR}


def api_update(req):
    start_update()
    return {"ok": True}


def api_job(req):
    return dict(JOB)


def api_get_saved(req):
    saved = read_json(SAVED_FILE, [])
    return saved if isinstance(saved, list) else []


def api_put_saved(req):
    ids = [str(i) for i in (req.body.get("ids") or []) if re.match(r"^TNL-\d{3}$", str(i))][:500]
    write_json(SAVED_FILE, ids)
    return ids


def api_open_folder(req):
    os.startfile(DATA_DIR)  # type: ignore[attr-defined]
    return {"ok": True}


def api_donate(req):
    webbrowser.open(DONATE_URL)  # the user's normal browser, not the app window
    return {"ok": True}


# --- settings, hotkey capture, overlay ----------------------------------------
DEFAULT_SETTINGS = {"hotkey": "F8", "moveHotkey": "F9", "region": "medium",
                    "overlay": {"stripX": None, "stripY": None, "visible": True, "locked": True}}
STRIP_W, STRIP_H = 1000, 96  # compact strip for the 180 px black bars above/below a 2560x1080 game on a 1440p screen
OVERLAY_TITLE = "AVA overlay"
OVERLAY = {"seq": 0, "id": None, "score": 0, "text": "", "lines": [], "at": None, "error": None, "busy": False,
           "closesAt": None}
HOTKEY_STATUS = {"read": {"ok": None, "hotkey": None}, "move": {"ok": None, "hotkey": None}}
_overlay_window = None
LAST_CAPTURE = {"jpg": None}
_hotkey = None
_matcher = None
_settings_lock = threading.Lock()


def load_settings():
    s = read_json(SETTINGS_FILE, {}) or {}
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    out.update({k: v for k, v in s.items() if k in out and k != "overlay"})
    out["overlay"].update(s.get("overlay") or {})
    return out


def save_settings(changes):
    with _settings_lock:
        s = load_settings()
        for k, v in changes.items():
            if k == "overlay":
                s["overlay"].update(v)
            else:
                s[k] = v
        write_json(SETTINGS_FILE, s)
        return s


def matcher():
    global _matcher
    if _matcher is None:
        zones = read_json(os.path.join(GAME_DIR, "zones.json"), []) or []
        _matcher = capture.Matcher(zones)
    return _matcher


def on_hotkey():
    """Hotkey pressed: read the zone name under the mouse and show it in the overlay."""
    if OVERLAY["busy"]:
        return
    OVERLAY["busy"] = True
    try:
        t0 = time.time()
        img, cur, box = capture.grab_around_cursor(load_settings()["region"], with_box=True)
        ov = capture.window_rect(OVERLAY_TITLE) if overlay_visible() else None
        if ov:  # the overlay shows zone names too: paint it out of the capture before reading
            from PIL import ImageDraw
            ImageDraw.Draw(img).rectangle((ov[0] - box[0], ov[1] - box[1], ov[2] - box[0], ov[3] - box[1]), fill=(0, 0, 0))
        t1 = time.time()
        # Kept in memory only: writing a screenshot PNG to disk froze the packaged app on this PC.
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        LAST_CAPTURE["jpg"] = buf.getvalue()
        m = matcher()
        t2 = time.time()
        hit, lines = capture.find_zone(img, cur, m)
        log(f"Capture: grab {int((t1 - t0) * 1000)} ms, ocr+match {int((time.time() - t2) * 1000)} ms, "
            f"{'found ' + hit['id'] if hit else 'no zone'}")
        closes = hit.get("closesIn") if hit else None
        OVERLAY.update(id=hit["id"] if hit else None, score=hit["score"] if hit else 0,
                       text=hit["text"] if hit else "", lines=lines[:12], error=None,
                       closesAt=int(time.time() + closes * 60) if closes is not None else None)
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc())
        OVERLAY.update(id=None, error=str(e) or e.__class__.__name__, lines=[])
    finally:
        OVERLAY.update(seq=OVERLAY["seq"] + 1, at=datetime.datetime.now().isoformat(timespec="seconds"), busy=False)
    if _overlay_window is not None and not load_settings()["overlay"].get("visible", True):
        show_overlay(True)


def on_hotkey_status(name, ok, text):
    before = HOTKEY_STATUS.get(name, {})
    HOTKEY_STATUS[name] = {"ok": ok, "hotkey": text}
    if before.get("ok") != ok or before.get("hotkey") != text:  # log changes only (it retries every 5 s)
        log(f"Hotkey {text} ({name}) " + ("registered" if ok else "could not be registered yet (another program uses it); retrying"))


def set_locked(locked):
    """Locked: the overlay can't be clicked at all (clicks go to the game). Unlocked: drag it."""
    save_settings({"overlay": {"locked": bool(locked)}})
    capture.set_click_through(OVERLAY_TITLE, bool(locked))
    refresh_tray()


def on_move_hotkey():
    """F9: unlock the overlay to drag it, press again to lock it in place."""
    if _overlay_window is not None and not overlay_visible():
        show_overlay(True)
    set_locked(not load_settings()["overlay"].get("locked", True))


def default_strip_pos():
    """Centred in the black bar under a 1080-tall game (or near the bottom of the screen)."""
    sw, sh = capture.primary_screen()
    bar = max(0, (sh - 1080) // 2)
    x = max(0, (sw - STRIP_W) // 2)
    y = sh - bar + (bar - STRIP_H) // 2 if bar >= STRIP_H else sh - STRIP_H - 60
    return x, y


def reset_overlay_position():
    x, y = default_strip_pos()
    capture.move_window(OVERLAY_TITLE, x, y)
    save_settings({"overlay": {"stripX": x, "stripY": y}})
    return x, y


def style_overlay():
    """Exact size, rounded corners, click-through when locked."""
    capture.fix_window_size(OVERLAY_TITLE, STRIP_W, STRIP_H)
    capture.round_corners(OVERLAY_TITLE, STRIP_W, STRIP_H, 10)
    capture.set_click_through(OVERLAY_TITLE, load_settings()["overlay"].get("locked", True))


def show_overlay(visible):
    save_settings({"overlay": {"visible": bool(visible)}})
    if _overlay_window is None:
        return False
    try:
        if visible:
            _overlay_window.show()
            _overlay_window.on_top = True
            style_overlay()
        else:
            _overlay_window.hide()
    except Exception as e:  # noqa: BLE001
        log(f"Overlay show/hide failed: {e}")
    refresh_tray()
    return True


def api_overlay_state(req):
    return {**OVERLAY, "hotkeys": HOTKEY_STATUS, "overlay": _overlay_window is not None,
            "locked": load_settings()["overlay"].get("locked", True)}


def api_overlay_lock(req):
    set_locked(bool(req.body.get("locked", True)))
    return {"ok": True}


def api_overlay_reset(req):
    x, y = reset_overlay_position()
    return {"ok": True, "x": x, "y": y}


def api_overlay_clear(req):
    OVERLAY.update(id=None, score=0, text="", lines=[], error=None, closesAt=None, seq=OVERLAY["seq"] + 1, at=None)
    return {"ok": True}


def api_minimize(req):
    """Close the main window; the app keeps running in the tray (notification area)."""
    if _tray is None:
        raise ApiError("The tray icon is not available, so the app can't keep running in the background.")
    global _in_tray
    _in_tray = True
    threading.Timer(0.3, close_main_windows).start()
    try:
        _tray.notify("Albion Ava Mapper is still running. Click the tray icon to open it.", "Albion Ava Mapper")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


def api_settings(req):
    return {**load_settings(), "hotkeyStatus": HOTKEY_STATUS, "overlayAvailable": _overlay_window is not None,
            "regions": list(capture.REGIONS), "trayAvailable": _tray is not None}


def api_put_settings(req):
    changes = {}
    current = load_settings()
    for field in ("hotkey", "moveHotkey"):
        if field in req.body:
            hk = str(req.body[field]).strip()
            try:
                capture.parse_hotkey(hk)
            except ValueError as e:
                raise ApiError(str(e)) from None
            other = current["moveHotkey" if field == "hotkey" else "hotkey"]
            if hk.upper() == str(other).upper():
                raise ApiError(f"{hk} is already used for the other hotkey.")
            changes[field] = hk
    if req.body.get("region") in capture.REGIONS:
        changes["region"] = req.body["region"]
    s = save_settings(changes)
    if _hotkey:
        if "hotkey" in changes:
            _hotkey.set("read", changes["hotkey"])
        if "moveHotkey" in changes:
            _hotkey.set("move", changes["moveHotkey"])
        time.sleep(0.25)
    return {**s, "hotkeyStatus": HOTKEY_STATUS, "overlayAvailable": _overlay_window is not None}


def api_overlay_show(req):
    if not show_overlay(True):
        raise ApiError("The overlay isn't available on this PC (Microsoft Edge WebView2 is missing).")
    return {"ok": True}


def api_overlay_hide(req):
    show_overlay(False)
    return {"ok": True}


def api_capture_now(req):
    """Same as pressing the hotkey, after a short delay so you can move the mouse onto the game."""
    delay = max(0, min(10, int(req.body.get("delay") or 0)))
    threading.Timer(delay, on_hotkey).start()
    return {"ok": True}


def api_pick(req):
    """Show a zone in the overlay without capturing (manual search in the overlay)."""
    zid = str(req.body.get("id") or "")
    if not re.match(r"^TNL-\d{3}$", zid):
        raise ApiError("Bad zone id")
    OVERLAY.update(id=zid, score=1, text="", lines=[], error=None, closesAt=None, seq=OVERLAY["seq"] + 1,
                   at=datetime.datetime.now().isoformat(timespec="seconds"))
    return {"ok": True}


def create_overlay():
    """The always-on-top, draggable overlay (needs pywebview + Edge WebView2)."""
    global _overlay_window
    if webview is None:
        log("pywebview not available: no overlay")
        return
    st = load_settings()["overlay"]
    x, y = st.get("stripX"), st.get("stripY")
    if x is None or y is None:  # first start: centred in the black bar under the game
        x, y = default_strip_pos()
    try:
        _overlay_window = webview.create_window(
            OVERLAY_TITLE, f"http://{HOST}:{PORT}/overlay.html", width=STRIP_W, height=STRIP_H,
            x=int(x), y=int(y), resizable=False, frameless=True, easy_drag=False, shadow=False, min_size=(200, 40),
            on_top=True, background_color="#14110f", hidden=not st.get("visible", True))
    except Exception as e:  # noqa: BLE001
        log(f"Overlay could not be created: {e}")
        _overlay_window = None
        return
    pending = {"t": None}

    def moved(x, y):  # remember where it was dragged to (saved half a second after it stops)
        if pending["t"]:
            pending["t"].cancel()
        pending["t"] = threading.Timer(0.5, lambda: save_settings({"overlay": {"stripX": int(x), "stripY": int(y)}}))
        pending["t"].start()

    def closing():  # Alt+F4 on the overlay hides it instead of closing it
        if _quitting:
            return True  # the app is quitting: don't save the overlay as hidden for next time
        threading.Thread(target=lambda: show_overlay(False), daemon=True).start()
        return False

    _overlay_window.events.moved += moved
    _overlay_window.events.closing += closing
    _overlay_window.events.shown += style_overlay
    _overlay_window.events.loaded += style_overlay


# --- tray icon (notification area) ----------------------------------------------
try:
    import pystray
except Exception:  # noqa: BLE001
    pystray = None
_tray = None
_in_tray = False  # the main window was minimized to the tray: keep running without it


def refresh_tray():
    if _tray is not None:
        try:
            _tray.update_menu()
        except Exception:  # noqa: BLE001
            pass


def start_tray():
    """Albion Ava Mapper's icon in the "show hidden icons" area: open, overlay controls, quit."""
    global _tray
    if pystray is None:
        log("pystray not available: no tray icon")
        return
    try:
        from PIL import Image
        icon = Image.open(os.path.join(STATIC_DIR, "icon.png"))
        ov = lambda: load_settings()["overlay"]  # noqa: E731
        menu = pystray.Menu(
            pystray.MenuItem("Open Albion Ava Mapper", lambda: api_open_window(None), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show overlay", lambda: show_overlay(not overlay_visible()),
                             checked=lambda item: overlay_visible(), enabled=lambda item: _overlay_window is not None),
            pystray.MenuItem("Unlocked for moving", lambda: set_locked(not ov().get("locked", True)),
                             checked=lambda item: not ov().get("locked", True), enabled=lambda item: _overlay_window is not None),
            pystray.MenuItem("Reset overlay position", lambda: reset_overlay_position(),
                             enabled=lambda item: _overlay_window is not None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: shutdown_app("quit from tray")),
        )
        _tray = pystray.Icon("AlbionAvaMapper", icon, "Albion Ava Mapper", menu)
        threading.Thread(target=_tray.run, daemon=True).start()
    except Exception as e:  # noqa: BLE001
        log(f"Tray icon failed: {e}")
        _tray = None


# --- standalone app window (same as Albion.loadouts) -----------------------
WINDOW_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA") or DATA_DIR, "AlbionAvaMapper", "window")
_window_proc = None
_last_ping = None
_bye_at = None


def find_app_browser():
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    local = os.environ.get("LOCALAPPDATA", "")
    for path in (
        os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(local, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
    ):
        if path and os.path.isfile(path):
            return path
    return None


def open_app_window(url):
    global _window_proc
    exe = find_app_browser()
    if not exe:
        webbrowser.open(url)
        return
    os.makedirs(WINDOW_PROFILE, exist_ok=True)
    args = [
        exe, f"--app={url}", f"--user-data-dir={WINDOW_PROFILE}", "--window-size=1360,900",
        "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-extensions",
        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows", "--disable-features=msEdgeStartupBoost,Translate",
    ]
    try:
        proc = subprocess.Popen(args)
        if _window_proc is None:
            _window_proc = proc
    except OSError as e:
        log(f"Could not open app window: {e}")
        webbrowser.open(url)


def app_windows():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith(WINDOW_TITLE):
                    found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def close_main_windows():
    try:
        import ctypes
        for hwnd in app_windows():
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception:  # noqa: BLE001
        pass


_quitting = False


def shutdown_app(reason="quit"):
    global _quitting
    _quitting = True
    log(f"Stopping ({reason})")
    if _window_proc is not None:
        try:
            import ctypes
            for hwnd in app_windows():
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:  # noqa: BLE001
            pass
    if _tray is not None:
        try:
            _tray.stop()  # remove the tray icon now, not when the mouse next passes over it
        except Exception:  # noqa: BLE001
            pass
    # A plain exit can hang while the overlay's .NET/WebView2 threads shut down: end the process outright.
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.TerminateProcess(k32.GetCurrentProcess(), 0)
    finally:
        os._exit(0)


def overlay_visible():
    return _overlay_window is not None and load_settings()["overlay"].get("visible", True)


def watch_window():
    """Quit once the main window is closed, unless the overlay is still showing.

    The main window's page pings every 5 s; while it's open the pings keep coming.
    """
    seen, missing = False, 0
    while True:
        time.sleep(1.5)
        try:
            open_now = bool(app_windows())
        except Exception:  # noqa: BLE001
            open_now = True
        if open_now:
            seen, missing = True, 0
            global _in_tray
            _in_tray = False
            continue
        if overlay_visible() or _in_tray:
            seen, missing = False, 0  # the overlay or the tray keeps the app running
            continue
        if seen:
            missing += 1
            if missing >= 3:
                shutdown_app("window closed")
        now = time.time()
        if _bye_at and now - _bye_at > 8 and (_last_ping or 0) < _bye_at:
            shutdown_app("window said bye")
        if _last_ping and now - _last_ping > 90:
            shutdown_app("window stopped responding")


def api_open_window(req):
    """Open (another) main window, e.g. from the overlay."""
    if app_windows():
        try:
            import ctypes
            hwnd = app_windows()[0]
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return {"ok": True}
        except Exception:  # noqa: BLE001
            pass
    open_app_window(f"http://{HOST}:{PORT}/")
    return {"ok": True}


def api_ping(req):
    global _last_ping
    _last_ping = time.time()
    return {"ok": True}


def api_bye(req):
    global _bye_at
    _bye_at = time.time()
    return {"ok": True}


def api_shutdown(req):
    threading.Timer(0.3, shutdown_app).start()
    return {"ok": True}


ROUTES = [
    ("GET", r"/api/meta", api_meta),
    ("POST", r"/api/update-data", api_update),
    ("GET", r"/api/job", api_job),
    ("GET", r"/api/saved", api_get_saved),
    ("PUT", r"/api/saved", api_put_saved),
    ("POST", r"/api/open-folder", api_open_folder),
    ("POST", r"/api/donate", api_donate),
    ("POST", r"/api/open-release", api_open_release),
    ("POST", r"/api/shutdown", api_shutdown),
    ("GET", r"/api/ping", api_ping),
    ("POST", r"/api/bye", api_bye),
    ("GET", r"/api/overlay/state", api_overlay_state),
    ("POST", r"/api/overlay/lock", api_overlay_lock),
    ("POST", r"/api/overlay/reset", api_overlay_reset),
    ("POST", r"/api/overlay/clear", api_overlay_clear),
    ("POST", r"/api/minimize", api_minimize),
    ("POST", r"/api/open-window", api_open_window),
    ("POST", r"/api/overlay/show", api_overlay_show),
    ("POST", r"/api/overlay/hide", api_overlay_hide),
    ("POST", r"/api/overlay/pick", api_pick),
    ("POST", r"/api/capture", api_capture_now),
    ("GET", r"/api/settings", api_settings),
    ("PUT", r"/api/settings", api_put_settings),
]
ROUTES = [(m, re.compile(f"^{p}$"), f) for m, p, f in ROUTES]


class Handler(BaseHTTPRequestHandler):
    server_version = "AlbionAvaMapper/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", cache="no-store"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, cache="no-store"):
        with open(path, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript") or ctype.endswith("json"):
            ctype += "; charset=utf-8"
        self._send(200, data, ctype, cache)

    def _handle(self, method):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                if method != "GET" and self.headers.get("X-AVA-App") != "1":
                    raise ApiError("Forbidden", 403)  # other websites can't set this header
                for m, rx, fn in ROUTES:
                    if m == method and rx.match(path):
                        length = int(self.headers.get("Content-Length") or 0)
                        raw = self.rfile.read(length) if length else b""
                        self.body = json.loads(raw) if raw else {}
                        return self._send(200, fn(self))
                raise ApiError("Not found", 404)
            if method != "GET":
                raise ApiError("Not found", 404)
            m = re.match(r"^/icon/res/([A-Z]+)\.png$", path)
            if m and ICON_RE.match(m.group(1)):
                p = resource_icon(m.group(1))
                if not p:
                    raise ApiError("Icon unavailable", 404)
                with open(p, "rb") as f:
                    return self._send(200, f.read(), "image/png", "max-age=604800")
            if path == "/capture/last.jpg":
                if not LAST_CAPTURE["jpg"]:
                    raise ApiError("No capture yet", 404)
                return self._send(200, LAST_CAPTURE["jpg"], "image/jpeg")
            m = re.match(r"^/game/(zones|meta)\.json$", path)
            if m:
                p = os.path.join(GAME_DIR, f"{m.group(1)}.json")
                if not os.path.isfile(p):
                    raise ApiError("Zone data not downloaded yet", 404)
                return self._file(p)
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.normpath(os.path.join(STATIC_DIR, rel))
            if not full.startswith(os.path.normpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
                raise ApiError("Not found", 404)
            self._file(full)
        except ApiError as e:
            self._send(e.code, {"error": str(e)})
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            self._send(500, {"error": f"Unexpected error: {e}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")


class ExclusiveServer(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows, reuse would let two copies share (and fight over) one port

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def set_port(port):
    global PORT
    PORT = port


def already_running():
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/meta", timeout=1) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main():
    global _hotkey
    capture.make_dpi_aware()
    url = f"http://{HOST}:{PORT}/"
    open_window = "--no-browser" not in sys.argv
    if already_running():
        if open_window:
            open_app_window(url)
        return
    server = None
    for port in range(PORT, PORT + 10):  # if the port is stuck (e.g. a copy that didn't exit), use the next one
        try:
            server = ExclusiveServer((HOST, port), Handler)
            break
        except OSError:
            log(f"Port {port} is busy, trying the next one")
    if server is None:
        log("No free port found")
        return
    set_port(server.server_address[1])
    url = f"http://{HOST}:{PORT}/"
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"Started on {url} (data: {DATA_DIR})")
    capture._trace = lambda m: log(f"  {m}")
    _hotkey = capture.Hotkeys({"read": on_hotkey, "move": on_move_hotkey}, on_hotkey_status)
    st = load_settings()
    _hotkey.set("read", st["hotkey"])
    _hotkey.set("move", st["moveHotkey"])
    if open_window:
        threading.Timer(0.3, lambda: open_app_window(url)).start()
    threading.Thread(target=watch_window, daemon=True).start()
    threading.Thread(target=check_update, daemon=True).start()
    start_tray()
    if "--no-overlay" not in sys.argv:
        create_overlay()
    if _overlay_window is not None:
        try:
            webview.start()  # runs the overlay until the app quits
        except Exception as e:  # noqa: BLE001
            log(f"Overlay stopped: {e}")
    while True:  # keep serving (also after the overlay, if it ever ends)
        time.sleep(3600)


if __name__ == "__main__":
    main()
