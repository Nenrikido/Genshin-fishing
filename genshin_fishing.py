"""Genshin fishing bot - Python port of GenshinFishing.ahk.

Detects the fishing state from the game HUD and plays the reel (tension bar)
minigame automatically. Bait selection and casting are still manual until the
new "Prepare to Fish" flow is automated.

Usage:
    python genshin_fishing.py            # live bot (game must be foreground)
    python genshin_fishing.py --test-frames <dir>   # offline check on PNGs

F5 quits the live bot. No registration screen, no updater.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import glob
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(ROOT, "genshinfishing.log")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GAME_EXES = ("GenshinImpact.exe", "YuanShen.exe")

# ImageSearch variation thresholds (max abs channel diff on masked pixels),
# same values as the AHK script
VAR_STATE = 32
VAR_BAR = 80

log_level = 0
_log_file = None


def log(txt, level=0):
    global _log_file
    if log_level >= level:
        if _log_file is None:
            _log_file = open(LOG_PATH, "a", encoding="utf-8")
        t = time.localtime()
        _log_file.write(f"{t.tm_hour}:{t.tm_min}:{t.tm_sec}.{int(time.time()*1000)%1000}[{level}]:{txt}\n")
        _log_file.flush()
        print(f"[{level}] {txt}")


# ---------------------------------------------------------------- window ----

def find_game_window():
    """Return hwnd of the Genshin window, or None."""
    result = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_proc(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if not h:
            return True
        buf = ctypes.create_unicode_buffer(260)
        size = wt.DWORD(260)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(h)
        if ok and os.path.basename(buf.value) in GAME_EXES:
            result.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return result[0] if result else None


def client_rect_on_screen(hwnd):
    """(left, top, width, height) of the client area in screen coords."""
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rect.right, rect.bottom


def game_is_foreground(hwnd):
    return user32.GetForegroundWindow() == hwnd


# ----------------------------------------------------------------- input ----

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class _Input(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MouseInput)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _mouse_event(flags):
    inp = _Input(type=0)
    inp.mi = _MouseInput(0, 0, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_Input))


class Mouse:
    """LMB hold/release with state tracking, like AHK Click Down/Up."""
    def __init__(self):
        self.down = False

    def hold(self):
        if not self.down:
            _mouse_event(MOUSEEVENTF_LEFTDOWN)
            self.down = True

    def release(self):
        if self.down:
            _mouse_event(MOUSEEVENTF_LEFTUP)
            self.down = False


# ------------------------------------------------------------- templates ----

class Template:
    def __init__(self, path):
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(path)
        self.bgr = img
        # fuchsia (BGR 255,0,255) marks transparent pixels
        self.mask = ~((img[:, :, 0] == 255) & (img[:, :, 1] == 0) & (img[:, :, 2] == 255))
        self.mask_u8 = self.mask.astype(np.uint8) * 255
        self.h, self.w = img.shape[:2]
        self.name = os.path.basename(path)


def load_templates(res_dir):
    t = {}
    for name in ("ready", "reel", "casting", "bar", "left", "right", "cur"):
        t[name] = Template(os.path.join(res_dir, name + ".png"))
    return t


def search(scene, tmpl, x0, y0, x1, y1, variation):
    """AHK-ImageSearch-like: find tmpl in scene[y0:y1, x0:x1].

    Returns (x, y) of the template's top-left in scene coords, or None.
    Candidate via masked TM_SQDIFF, then exact max-channel-diff verify.
    """
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(scene.shape[1], x1); y1 = min(scene.shape[0], y1)
    region = scene[y0:y1, x0:x1]
    if region.shape[0] < tmpl.h or region.shape[1] < tmpl.w:
        return None
    res = cv2.matchTemplate(region, tmpl.bgr, cv2.TM_SQDIFF, mask=tmpl.mask_u8)
    res = np.nan_to_num(res, nan=np.inf, posinf=np.inf)
    _, _, minloc, _ = cv2.minMaxLoc(res)
    mx, my = minloc
    win = region[my:my + tmpl.h, mx:mx + tmpl.w].astype(np.int16)
    diff = np.abs(win - tmpl.bgr.astype(np.int16)).max(axis=2)
    if diff[tmpl.mask].max() <= variation:
        return x0 + mx, y0 + my
    return None


# --------------------------------------------------------------- capture ----

class Capture:
    def __init__(self):
        import mss
        self.sct = mss.mss()

    def grab(self, left, top, w, h):
        shot = self.sct.grab({"left": left, "top": top, "width": w, "height": h})
        return np.asarray(shot)[:, :, :3]  # BGRA -> BGR


# ------------------------------------------------------------------- bot ----

class Bot:
    def __init__(self, templates, win_w, win_h):
        self.t = templates
        self.w = win_w
        self.h = win_h
        self.dline = int(np.ceil((win_w ** 2 + win_h ** 2) ** 0.5))
        d = self.dpt
        # same geometry as the AHK script
        self.barR = (d(0.27), d(0.03), d(0.59), d(0.1))
        self.delta = (d(0.025), d(0.005), d(0.035), d(0.014))  # l, t, r, b
        self.barS_left = d(0.22)
        self.barS_right = d(0.64)
        self.icon_region = (win_w - d(0.222), win_h - d(0.084), win_w, win_h)
        self.reset()

    def dpt(self, p):
        return int(np.ceil(p * self.dline))

    def reset(self):
        self.state = "unknown"
        self.state_predict = "unknown"
        self.state_unknown_start = 0.0
        self.bar_y = 0
        self.left_x = self.right_x = self.cur_x = 0
        self.left_x_old = self.right_x_old = self.cur_x_old = 0
        self.left_pred = self.right_pred = self.cur_pred = 0
        self.last_icon = None

    # -- state detection (port of getState) --
    def get_state(self, frame):
        x0, y0, x1, y1 = self.icon_region
        if self.last_icon:
            lx, ly = self.last_icon
            x0 = lx - self.dpt(0.0353 * 0.5)
            y0 = ly - self.dpt(0.0442 * 0.5)
            x1 = lx + self.dpt(0.0353 * 1.5)
            y1 = ly + self.dpt(0.0442 * 1.5)
        for name in ("ready", "reel", "casting"):
            hit = search(frame, self.t[name], x0, y0, x1, y1, VAR_STATE)
            if hit is None and self.last_icon:
                # narrowed window missed: retry full corner region
                hit = search(frame, self.t[name], *self.icon_region, VAR_STATE)
            if hit:
                self.last_icon = hit
                self.state = name
                if self.state_predict != name:
                    log(f"state->{name}", 1)
                self.state_predict = name
                self.state_unknown_start = 0.0
                return
        self.state = "unknown"
        now = time.monotonic()
        if self.state_unknown_start == 0.0:
            self.state_unknown_start = now
        if self.state_predict != "unknown" and now - self.state_unknown_start >= 2.0:
            self.last_icon = None
            self.state_predict = "unknown"
            log("state->unknown", 1)

    # -- reel minigame (port of the AHK reel branch) --
    def reel_tick(self, frame, mouse):
        d_l, d_t, d_r, d_b = self.delta
        if self.bar_y < 2:
            hit = search(frame, self.t["bar"], *self.barR, VAR_BAR)
            if hit is None:
                # not found yet: jiggle the line to keep the fish hooked
                if self.bar_y == 0:
                    self.bar_y = 1
                    mouse.hold()
                else:
                    self.bar_y = 0
                    mouse.release()
            else:
                self.bar_y = hit[1]
                mouse.release()
                self.left_x = self.right_x = self.cur_x = 0
                log(f"get barY={self.bar_y}", 2)
            return True

        def track(name, prev_x):
            if prev_x > 0:
                hit = search(frame, self.t[name], prev_x - d_l, self.bar_y - d_t,
                             prev_x + d_r, self.bar_y + d_b, VAR_BAR)
            else:
                hit = search(frame, self.t[name], self.barS_left, self.bar_y - d_t,
                             self.barS_right, self.bar_y + d_b, VAR_BAR)
            return hit[0] if hit else 0

        lx = track("left", self.left_x)
        if lx:
            self.left_pred = 2 * lx - self.left_x_old
            self.left_x_old = lx
        rx = track("right", self.right_x)
        if rx:
            self.right_pred = 2 * rx - self.right_x_old
            self.right_x_old = rx
        cx = track("cur", self.cur_x)
        if cx:
            self.cur_pred = 2 * cx - self.cur_x_old
            self.cur_x_old = cx
        self.left_x, self.right_x, self.cur_x = lx, rx, cx

        if not lx and not rx and not cx:
            self.get_state(frame)
            mouse.release()
            return self.state_predict == "reel"
        # zone drifting left -> aim near left edge; drifting right -> near right
        if lx + rx < self.left_x_old + self.right_x_old:
            k = 0.2
        elif lx + rx > self.left_x_old + self.right_x_old:
            k = 0.8
        else:
            k = 0.4
        if self.cur_pred < k * self.right_pred + (1 - k) * self.left_pred:
            mouse.hold()
        else:
            mouse.release()
        log(f"leftX={lx} rightX={rx} curX={cx}", 2)
        return True


# -------------------------------------------------------------- live run ----

def run_live():
    global log_level
    log_level = read_log_level()
    log(f"Start (python) at {time.strftime('%Y-%m-%d')}")

    # F5 quits (RegisterHotKey id=1)
    user32.RegisterHotKey(None, 1, 0, 0x74)

    cap = Capture()
    mouse = Mouse()
    bot = None
    hwnd = None
    try:
        while True:
            if quit_hotkey_pressed():
                log("F5 quit")
                break
            if hwnd is None or not user32.IsWindow(hwnd):
                hwnd = find_game_window()
                if hwnd is None:
                    time.sleep(0.8)
                    continue
            if not game_is_foreground(hwnd):
                mouse.release()
                time.sleep(0.5)
                continue
            left, top, w, h = client_rect_on_screen(hwnd)
            if w == 0 or h == 0:
                time.sleep(0.8)
                continue
            res_dir = os.path.join(ROOT, "assets", f"{w}{h}")
            if bot is None or bot.w != w or bot.h != h:
                if not os.path.isdir(res_dir):
                    log(f"Unsupported resolution {w}x{h}")
                    time.sleep(2)
                    continue
                bot = Bot(load_templates(res_dir), w, h)
                log(f"Get dimension={w}x{h}", 1)

            if bot.state_predict == "reel":
                frame = cap.grab(left, top, w, h)
                t0 = time.perf_counter()
                bot.reel_tick(frame, mouse)
                dt = time.perf_counter() - t0
                time.sleep(max(0.01, 0.04 - dt))
                if bot.state_predict != "reel":
                    bot.bar_y = 0
            elif bot.state_predict == "casting":
                frame = cap.grab(left, top, w, h)
                bot.get_state(frame)
                if bot.state_predict == "reel":
                    mouse.hold()
                    time.sleep(0.04)
                else:
                    time.sleep(0.2)
            else:  # unknown / ready
                frame = cap.grab(left, top, w, h)
                bot.get_state(frame)
                if bot.state_predict == "reel":
                    time.sleep(0.04)
                else:
                    bot.bar_y = 0
                    time.sleep(0.8)
    finally:
        mouse.release()
        user32.UnregisterHotKey(None, 1)


def quit_hotkey_pressed():
    msg = wt.MSG()
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        if msg.message == 0x0312:  # WM_HOTKEY
            return True
    return False


def read_log_level():
    """setting.ini [update] log=N (utf-16), default 1 for the python bot."""
    path = os.path.join(ROOT, "setting.ini")
    try:
        import configparser
        cp = configparser.ConfigParser()
        with open(path, encoding="utf-16") as f:
            cp.read_file(f)
        return cp.getint("update", "log", fallback=1)
    except Exception:
        return 1


# ------------------------------------------------------------- test mode ----

def run_test(frames_dir):
    global log_level
    log_level = 2
    files = sorted(glob.glob(os.path.join(frames_dir, "*.png")))
    if not files:
        print("no PNG frames in", frames_dir)
        return 1
    first = cv2.imread(files[0])
    h, w = first.shape[:2]
    res_dir = os.path.join(ROOT, "assets", f"{w}{h}")
    bot = Bot(load_templates(res_dir), w, h)

    class FakeMouse:
        def __init__(self):
            self.down = False
            self.actions = []

        def hold(self):
            if not self.down:
                self.actions.append("hold")
            self.down = True

        def release(self):
            if self.down:
                self.actions.append("release")
            self.down = False

    for f in files:
        frame = cv2.imread(f)
        bot.get_state(frame)
        line = f"{os.path.basename(f)}: state={bot.state}"
        # probe the tension bar on every frame (false-positive check on non-fight ones)
        hit = search(frame, bot.t["bar"], *bot.barR, VAR_BAR)
        if hit:
            m = FakeMouse()
            bot.state_predict = "reel"
            bot.reel_tick(frame, m)  # bar anchor pass
            bot.reel_tick(frame, m)  # element tracking pass
            line += (f" barY={bot.bar_y} left={bot.left_x} right={bot.right_x}"
                     f" cur={bot.cur_x} mouse={'/'.join(m.actions) or 'idle'}")
        bot.bar_y = 0
        bot.left_x = bot.right_x = bot.cur_x = 0
        bot.state_predict = "unknown"
        print(line)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-frames", help="run detection on a directory of PNG frames")
    args = ap.parse_args()
    if args.test_frames:
        sys.exit(run_test(args.test_frames))
    run_live()
