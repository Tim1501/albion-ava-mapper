"""Hotkey capture: grab the screen around the mouse, read it with Windows OCR, find the zone name.

Only reads pixels from the screen (like a screenshot). It never touches the game's memory,
network traffic or input.
"""
import ctypes
import difflib
import re
import threading
from ctypes import wintypes

from PIL import Image

try:
    import winocr
except Exception:  # noqa: BLE001
    winocr = None

user32 = ctypes.windll.user32
_trace = None  # optional logger for timing


def make_dpi_aware():
    """So mouse coordinates and screenshots use the same real pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def virtual_screen():
    """(left, top, right, bottom) of all monitors together."""
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    return left, top, left + user32.GetSystemMetrics(78), top + user32.GetSystemMetrics(79)


# capture area around the cursor: (left, up, right, down) in pixels
REGIONS = {
    "small": (380, 200, 380, 140),
    "medium": (560, 300, 560, 200),
    "large": (800, 420, 800, 300),
}


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


_gdi_ready = None


def _gdi():
    """gdi32 with 64-bit-safe argument types (handles overflow a plain int otherwise)."""
    global _gdi_ready
    if _gdi_ready is None:
        g, W = ctypes.windll.gdi32, wintypes
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [W.HDC], W.HDC
        g.CreateCompatibleBitmap.argtypes, g.CreateCompatibleBitmap.restype = [W.HDC, ctypes.c_int, ctypes.c_int], W.HBITMAP
        g.SelectObject.argtypes, g.SelectObject.restype = [W.HDC, W.HGDIOBJ], W.HGDIOBJ
        g.BitBlt.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.HDC, ctypes.c_int, ctypes.c_int, W.DWORD]
        g.BitBlt.restype = W.BOOL
        g.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT]
        g.GetDIBits.restype = ctypes.c_int
        g.DeleteObject.argtypes, g.DeleteObject.restype = [W.HGDIOBJ], W.BOOL
        g.DeleteDC.argtypes, g.DeleteDC.restype = [W.HDC], W.BOOL
        user32.GetDC.argtypes, user32.GetDC.restype = [W.HWND], W.HDC
        user32.ReleaseDC.argtypes, user32.ReleaseDC.restype = [W.HWND, W.HDC], ctypes.c_int
        _gdi_ready = g
    return _gdi_ready


def grab_screen(left, top, width, height):
    """Copy a screen rectangle with plain GDI BitBlt (no CAPTUREBLT, which can stall in a packaged app)."""
    gdi = _gdi()
    screen = user32.GetDC(None)
    mem = gdi.CreateCompatibleDC(screen)
    bmp = gdi.CreateCompatibleBitmap(screen, width, height)
    old = gdi.SelectObject(mem, bmp)
    try:
        if not gdi.BitBlt(mem, 0, 0, width, height, screen, left, top, 0x00CC0020):  # SRCCOPY
            raise OSError("Screen copy failed")
        bih = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(width * height * 4)
        gdi.GetDIBits(mem, bmp, 0, height, buf, ctypes.byref(bih), 0)  # DIB_RGB_COLORS
        return Image.frombuffer("RGB", (width, height), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        gdi.SelectObject(mem, old)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(mem)
        user32.ReleaseDC(None, screen)


def grab_around_cursor(size="medium", with_box=False):
    x, y = cursor_pos()
    l, u, r, d = REGIONS.get(size, REGIONS["medium"])
    vl, vt, vr, vb = virtual_screen()
    box = (max(vl, x - l), max(vt, y - u), min(vr, x + r), min(vb, y + d))
    img = grab_screen(box[0], box[1], box[2] - box[0], box[3] - box[1])
    if with_box:
        return img, (x - box[0], y - box[1]), box
    return img, (x - box[0], y - box[1])


# --- matching ----------------------------------------------------------------
# characters OCR often mixes up, folded the same way on both sides
_FOLD = str.maketrans({"l": "i", "1": "i", "|": "i", "!": "i", "j": "i", "0": "o", "5": "s", "8": "b"})


def fold(s):
    s = s.lower().replace("rn", "m").replace("vv", "w")
    s = s.translate(_FOLD)
    return re.sub(r"[^a-z]", "", s)


class Matcher:
    def __init__(self, zones):
        self.zones = [(z["id"], fold(z["name"])) for z in zones]

    def best(self, text):
        t = fold(text)
        if len(t) < 6:
            return None, 0.0
        best, best_score = None, 0.0
        for zid, name in self.zones:
            sm = difflib.SequenceMatcher(None, t, name, autojunk=False)
            if sm.real_quick_ratio() < best_score or sm.quick_ratio() < best_score:
                continue
            s = sm.ratio()
            if s > best_score:
                best, best_score = zid, s
        return best, best_score


def read_lines(img):
    """[(text, center_x, center_y)] for each OCR line. Small text is upscaled first."""
    if winocr is None:
        raise RuntimeError("Windows OCR is not available on this PC.")
    scale = 2 if img.height < 700 else 1
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale))
    if _trace:
        _trace("ocr start")
    res = winocr.recognize_pil_sync(img, "en")
    if _trace:
        _trace("ocr done")
    out = []
    for line in res.get("lines", []):
        words = line.get("words") or []
        if not words:
            continue
        xs = [w["bounding_rect"]["x"] + w["bounding_rect"]["width"] / 2 for w in words]
        ys = [w["bounding_rect"]["y"] + w["bounding_rect"]["height"] / 2 for w in words]
        out.append((line["text"], sum(xs) / len(xs) / scale, sum(ys) / len(ys) / scale))
    return out


# "Closes in", allowing the usual OCR slips in the word itself ("Ciose5 in", "C1oses ln").
CLOSES_ANCHOR = re.compile(r"c[l1i|!][o0]s\w*?\s*[i1l|!]n", re.I)
CLOSES_RE = re.compile(r"^\s*(?:(\d{1,2})\s*h)?\s*(?:(\d{1,2})\s*m(?!s))?\s*(?:(\d{1,2})\s*s)?", re.I)
# Glyphs the game font's digits get misread as. Only applied after "Closes in", and never to the
# unit letters h / m / s, so "i i h 35 m" -> "11 h 35 m".
DIGIT_FIX = str.maketrans({"i": "1", "I": "1", "l": "1", "|": "1", "!": "1", "j": "1", "]": "1", "[": "1",
                           "o": "0", "O": "0", "D": "0", "Q": "0", "S": "5", "B": "8", "Z": "2", "z": "2",
                           "G": "6", "b": "6", "q": "9", "g": "9", "T": "7", "A": "4"})


def closes_in_minutes(text):
    """'Closes in 23 h 11 m' -> 1391 (minutes), or None. Tolerates OCR slips like 'i i h 35 m'."""
    a = CLOSES_ANCHOR.search(text)
    if not a:
        return None
    rest = text[a.end():].translate(DIGIT_FIX)
    rest = re.sub(r"(?<=\d)[\s.,']+(?=\d)", "", rest)  # "1 1 h" -> "11 h": one number split in two
    m = CLOSES_RE.search(rest)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    if mi > 59 or s > 59:
        return None
    return h * 60 + mi + (1 if s else 0)


def find_zone(img, cursor, matcher, threshold=0.72):
    """Best zone name in the image.

    The portal tooltip reads "Road of Avalon to" / <zone name> / players / "Closes in 23 h 11 m",
    with one corner at the mouse. The line after "Road of Avalon to" gets priority; otherwise the
    strongest match closest to the cursor wins. Also returns the portal's closing time if it's shown.
    """
    lines = read_lines(img)
    anchors = {i + 1 for i, (t, _, _) in enumerate(lines) if "roadof" in fold(t) or "avaionto" in fold(t)}
    candidates = []
    for i, (text, cx, cy) in enumerate(lines):
        options = [text]
        if i + 1 < len(lines):  # a long name can wrap onto two lines
            options.append(text + " " + lines[i + 1][0])
        # a line can also hold extra words around the name ("Setent-In-Qinsum (T6)")
        options += [m.group(0) for m in re.finditer(r"[A-Za-z|!1l]+(?:\s*-\s*[A-Za-z|!1l]+){1,3}", text)]
        for opt in options:
            zid, score = matcher.best(opt)
            if zid and score >= threshold:
                dist = ((cx - cursor[0]) ** 2 + (cy - cursor[1]) ** 2) ** 0.5
                rank = round(score, 2) + (0.2 if i in anchors else 0)
                candidates.append((rank, -dist, zid, opt, score, i))
    candidates.sort(reverse=True)
    lines_text = [t for t, _, _ in lines]
    if not candidates:
        return None, lines_text
    _, _, zid, text, score, idx = candidates[0]
    closes = None
    for t, _, _ in lines[idx:idx + 4]:  # the timer sits a couple of lines under the name
        closes = closes_in_minutes(t)
        if closes is not None:
            break
    return {"id": zid, "score": round(score, 2), "text": text, "closesIn": closes}, lines_text


# --- global hotkey ---------------------------------------------------------------
MODS = {"ALT": 0x1, "CTRL": 0x2, "CONTROL": 0x2, "SHIFT": 0x4, "WIN": 0x8}
NOREPEAT = 0x4000
WM_HOTKEY, WM_APP_RELOAD = 0x0312, 0x8001


def parse_hotkey(text):
    """'Ctrl+Shift+F8' -> (modifiers, virtual key) or raises ValueError."""
    parts = [p.strip().upper() for p in str(text).replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty hotkey")
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in MODS:
            raise ValueError(f"Unknown modifier '{p}'")
        mods |= MODS[p]
    if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", key):
        vk = 0x70 + int(key[1:]) - 1
    elif re.fullmatch(r"[A-Z0-9]", key):
        vk = ord(key)
    else:
        named = {"INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22, "PAUSE": 0x13,
                 "SCROLLLOCK": 0x91, "`": 0xC0, "TILDE": 0xC0}
        if key not in named:
            raise ValueError(f"Unknown key '{key}'")
        vk = named[key]
    return mods, vk


class Hotkeys:
    """Global hotkeys on their own thread, e.g. {"read": "F8", "move": "F9"}.

    callbacks: {name: function}. on_status(name, ok, text) reports whether Windows accepted each key.
    """

    def __init__(self, callbacks, on_status):
        self.callbacks, self.on_status = callbacks, on_status
        self.keys = {}  # name -> "F8"
        self.ids = {}   # hotkey id -> name
        self.thread_id = None
        self._ready = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()
        self._ready.wait(3)

    def set(self, name, text):
        parse_hotkey(text)  # raises if invalid
        self.keys[name] = text
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_APP_RELOAD, 0, 0)

    def _register(self):
        for hid in list(self.ids):
            user32.UnregisterHotKey(None, hid)
        self.ids = {}
        for i, (name, text) in enumerate(sorted(self.keys.items()), start=1):
            mods, vk = parse_hotkey(text)
            ok = bool(user32.RegisterHotKey(None, i, mods | NOREPEAT, vk))
            if ok:
                self.ids[i] = name
            self.on_status(name, ok, text)
        if len(self.ids) < len(self.keys):  # a key is taken (e.g. a copy that is still closing): try again soon
            threading.Timer(5, lambda: user32.PostThreadMessageW(self.thread_id, WM_APP_RELOAD, 0, 0)).start()

    def _loop(self):
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create the message queue
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_RELOAD:
                self._register()
            elif msg.message == WM_HOTKEY:
                fn = self.callbacks.get(self.ids.get(msg.wParam))
                if fn:
                    threading.Thread(target=fn, daemon=True).start()


def primary_screen():
    """(width, height) of the main monitor in real pixels."""
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def window_rect(title):
    """(left, top, right, bottom) of a window by title, or None."""
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def move_window(title, x, y):
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0010)  # NOSIZE|NOZORDER|NOACTIVATE
    return bool(hwnd)


def round_corners(title, width, height, radius=12):
    """Clip the window to a rounded rectangle, so there are no square/white corners."""
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    gdi = ctypes.windll.gdi32
    gdi.CreateRoundRectRgn.restype = wintypes.HRGN
    rgn = gdi.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1, radius * 2, radius * 2)
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    return bool(user32.SetWindowRgn(hwnd, rgn, True))  # Windows owns the region from here


def set_click_through(title, on, alpha=255):
    """Locked overlay: the mouse goes straight through it to the game, and it never takes focus.

    Also keeps it off the taskbar / Alt+Tab (tool window). alpha: 0-255 opacity.
    """
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    GWL_EXSTYLE = -20
    user32.GetWindowLongW.restype = ctypes.c_long
    before = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    st = (before | 0x00080000 | 0x00000080 | 0x08000000) & ~0x00040000  # + LAYERED | TOOLWINDOW | NOACTIVATE, - APPWINDOW
    st = (st | 0x00000020) if on else (st & ~0x00000020)  # TRANSPARENT: clicks pass through
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, st)
    user32.SetLayeredWindowAttributes(hwnd, 0, int(alpha), 0x2)  # LWA_ALPHA
    # The taskbar only re-checks TOOLWINDOW / APPWINDOW when a window is shown, so the overlay kept its
    # taskbar button: hide and re-show it once (without taking focus) to drop the button.
    # Async (posted, never waits): called from other threads, and a blocking call can deadlock the overlay's UI thread.
    if (before ^ st) & (0x00000080 | 0x00040000) and user32.IsWindowVisible(hwnd):
        user32.ShowWindowAsync(hwnd, 0)  # SW_HIDE
        user32.ShowWindowAsync(hwnd, 4)  # SW_SHOWNOACTIVATE
        user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x4000)  # HWND_TOPMOST, NOSIZE|NOMOVE|NOACTIVATE|ASYNCWINDOWPOS
    return True


def fix_window_size(title, width, height):
    """Give a frameless window its exact size (pywebview subtracts a title bar it doesn't have)."""
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        user32.SetWindowPos(hwnd, None, 0, 0, int(width), int(height), 0x0002 | 0x0004 | 0x0010)  # NOMOVE|NOZORDER|NOACTIVATE
    return bool(hwnd)


def exclude_from_capture(title):
    """Hide our overlay from screenshots, so it never covers the text we read (Windows 10 2004+)."""
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        try:
            return bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))  # WDA_EXCLUDEFROMCAPTURE
        except Exception:  # noqa: BLE001
            return False
    return False
