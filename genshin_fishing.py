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
# "Start Fishing" button: true matches <=40 across two sessions, false floor >=80
VAR_PANEL = 50

log_level = 0
log_to_file = True
_log_file = None


def log(txt, level=0):
    global _log_file
    if log_level >= level:
        now = time.time()
        stamp = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now*1000)%1000:03d}"
        if log_to_file:
            if _log_file is None:
                _log_file = open(LOG_PATH, "a", encoding="utf-8")
            _log_file.write(f"{stamp}[{level}]:{txt}\n")
            _log_file.flush()
        print(f"{stamp}[{level}] {txt}")


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
            log("LMB down", 1)

    def release(self):
        if self.down:
            _mouse_event(MOUSEEVENTF_LEFTUP)
            self.down = False
            log("LMB up", 1)

    def click_at(self, screen_x, screen_y):
        """Move to a screen position and click (menus need a real cursor pos)."""
        self.release()
        user32.SetCursorPos(int(screen_x), int(screen_y))
        time.sleep(0.05)
        _mouse_event(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.04)
        _mouse_event(MOUSEEVENTF_LEFTUP)
        log(f"click at {screen_x},{screen_y}", 1)

    def cast(self, hold_s):
        """Charge and release the rod: hold LMB, then let go."""
        self.hold()
        time.sleep(hold_s)
        self.release()


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
    # only cut for 1080p so far; without it the panel is simply not automated
    for name in ("btn_startfishing",):
        p = os.path.join(res_dir, name + ".png")
        if os.path.exists(p):
            t[name] = Template(p)
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
        self.last_icon = None
        self.reset_fight()

    def reset_fight(self):
        self.bar_seen = False
        self.bar_misses = 0
        self.zone_w = 150.0 * self.dline / 2202.0
        self.left_x_old = self.right_x_old = self.cur_x_old = 0
        self.left_pred = self.right_pred = self.cur_pred = 0

    def find_start_button(self, frame):
        """Center of the active 'Start Fishing' button, or None.

        Only matches while the button is enabled (a rod and bait are picked),
        so a click is always meaningful.
        """
        t = self.t.get("btn_startfishing")
        if t is None:
            return None
        d = self.dpt
        hit = search(frame, t, d(0.5), d(0.42), self.w, self.h, VAR_PANEL)
        if hit is None:
            return None
        return hit[0] + t.w // 2, hit[1] + t.h // 2

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

    # -- reel minigame: column-profile detector on the tension bar band --
    # Elements (brackets ◄ ►, cursor I) are tall solid-yellow column clusters;
    # the zone outline between brackets is only ~4px of fill per column, so a
    # filled-height threshold separates them. Robust to motion blur, which
    # broke per-element template matching (~20% cursor hit rate live).
    def detect_bar(self, frame):
        y0, y1 = self.dpt(0.0418), self.dpt(0.0627)
        band = frame[y0:y1, self.barS_left:self.barS_right]
        r = band[:, :, 2].astype(np.int16)
        g = band[:, :, 1].astype(np.int16)
        b = band[:, :, 0].astype(np.int16)
        m = (r > 150) & (g > 120) & (r - b > 45) & (g - b > 25)
        heights = m.sum(axis=0)
        min_h = max(10, round(14 * self.dline / 2202))
        xs = np.where(heights >= min_h)[0]
        clusters = []
        if len(xs):
            start = prev = xs[0]
            for x in xs[1:]:
                if x - prev > 3:
                    clusters.append((start, prev))
                    start = x
                prev = x
            clusters.append((start, prev))
        return [(int(c0) + self.barS_left, int(c1) + self.barS_left,
                 int(heights[c0:c1 + 1].max()))
                for c0, c1 in clusters if c1 - c0 >= 3]

    def interpret_bar(self, clusters):
        """-> (zone_left, zone_right, cursor_x), any of which may be None."""
        s = self.dline / 2202.0
        if len(clusters) < 2:
            if len(clusters) == 1:
                c0, c1, _ = clusters[0]
                return None, None, (c0 + c1) // 2
            return None, None, None
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sep = clusters[j][1] - clusters[i][0]
                if 80 * s <= sep <= 210 * s:
                    score = abs(sep - self.zone_w)
                    if best is None or score < best[0]:
                        best = (score, i, j, sep)
        if best is None:
            c = max(clusters, key=lambda c: c[2])
            return None, None, (c[0] + c[1]) // 2
        _, i, j, sep = best
        zl, zr = clusters[i][0], clusters[j][1]
        rest = [c for k, c in enumerate(clusters) if k not in (i, j)]
        if rest:
            c = max(rest, key=lambda c: c[2])
            cursor = (c[0] + c[1]) // 2
        else:
            # cursor hidden behind a bracket: the overlapped cluster is wider
            lw = clusters[i][1] - clusters[i][0]
            rw = clusters[j][1] - clusters[j][0]
            if lw > 26 * s:
                cursor = clusters[i][0] + lw // 2
            elif rw > 26 * s:
                cursor = clusters[j][0] + rw // 2
            else:
                cursor = None
        self.zone_w = 0.7 * self.zone_w + 0.3 * sep
        return zl, zr, cursor

    def reel_tick(self, frame, mouse):
        clusters = self.detect_bar(frame)
        zl, zr, cx = self.interpret_bar(clusters)

        if zl is None and cx is None:
            self.bar_misses += 1
            # bar gone mid-fight (~0.25s) means it is over; never appearing at
            # all (~3s) means the reel state was a false read
            if self.bar_misses >= (6 if self.bar_seen else 120):
                self.get_state(frame)
                mouse.release()
                return self.state_predict == "reel"
            if not self.bar_seen:
                # bite just started, bar still fading in: jiggle to hook
                if mouse.down:
                    mouse.release()
                else:
                    mouse.hold()
            return True
        self.bar_misses = 0
        if not self.bar_seen:
            self.bar_seen = True
            log(f"bar found zone={zl}-{zr} cur={cx}", 1)

        if zl is not None:
            self.left_pred = 2 * zl - self.left_x_old if self.left_x_old else zl
            self.right_pred = 2 * zr - self.right_x_old if self.right_x_old else zr
            drift = (zl + zr) - (self.left_x_old + self.right_x_old)
            self.left_x_old, self.right_x_old = zl, zr
        else:
            drift = 0
        if cx is not None:
            self.cur_pred = 2 * cx - self.cur_x_old if self.cur_x_old else cx
            self.cur_x_old = cx
        elif zl is not None:
            # cursor invisible but zone visible: it is inside the zone, aim center
            self.cur_pred = (self.left_pred + self.right_pred) // 2
            self.cur_x_old = 0

        # zone drifting left -> aim near left edge; drifting right -> near right
        if drift < 0:
            k = 0.2
        elif drift > 0:
            k = 0.8
        else:
            k = 0.4
        if self.cur_pred < k * self.right_pred + (1 - k) * self.left_pred:
            mouse.hold()
        else:
            mouse.release()
        log(f"zone={zl}-{zr} cur={cx} pred={self.cur_pred} k={k}", 2)
        return True


# -------------------------------------------------------------- live run ----

def ensure_elevated():
    """Genshin drops synthetic input from non-elevated processes (UIPI), so
    relaunch through UAC like the AHK version did. Declining the prompt
    continues in detection-only mode."""
    if ctypes.windll.shell32.IsUserAnAdmin():
        return True
    script = os.path.abspath(__file__)
    r = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}"', ROOT, 1)
    if r > 32:  # elevated copy launched, this one exits
        sys.exit(0)
    return False


def run_live():
    global log_level
    cfg = read_config()
    log_level = cfg["log"]
    elevated = ensure_elevated()
    log(f"Start (python) at {time.strftime('%Y-%m-%d')}, admin={elevated}")
    if not elevated:
        log("NOT elevated: clicks will likely be ignored by the game", 0)
    log(f"autostart={cfg['autostart']} autocast={cfg['autocast']} "
        f"cast_hold={cfg['cast_hold']}s bite_timeout={cfg['bite_timeout']}s", 0)
    cast_start = 0.0

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
                time.sleep(max(0.005, 0.025 - dt))
                if bot.state_predict != "reel":
                    bot.reset_fight()
                    cast_start = 0.0
            elif bot.state_predict == "casting":
                frame = cap.grab(left, top, w, h)
                bot.get_state(frame)
                if bot.state_predict == "reel":
                    bot.reset_fight()
                    mouse.hold()
                    time.sleep(0.025)
                elif (cfg["autocast"] and cast_start
                        and time.monotonic() - cast_start > cfg["bite_timeout"]):
                    # nothing bit: reel in so the ready branch can recast
                    log(f"no bite in {cfg['bite_timeout']}s, reeling in", 1)
                    mouse.click_at(left + w // 2, top + h // 2)
                    cast_start = 0.0
                    time.sleep(1.5)
                else:
                    time.sleep(0.2)
            else:  # unknown / ready
                frame = cap.grab(left, top, w, h)
                bot.get_state(frame)
                if bot.state_predict == "reel":
                    bot.reset_fight()
                    time.sleep(0.025)
                elif bot.state_predict == "ready":
                    bot.reset_fight()
                    if cfg["autocast"]:
                        log("ready: casting", 1)
                        mouse.cast(cfg["cast_hold"])
                        cast_start = time.monotonic()
                        time.sleep(1.0)
                    else:
                        time.sleep(0.8)
                else:
                    # not in fishing mode: the Prepare to Fish panel may be open
                    bot.reset_fight()
                    btn = bot.find_start_button(frame) if cfg["autostart"] else None
                    if btn:
                        log("Prepare to Fish panel: starting", 1)
                        mouse.click_at(left + btn[0], top + btn[1])
                        time.sleep(1.5)
                    else:
                        time.sleep(0.5)
    finally:
        mouse.release()
        user32.UnregisterHotKey(None, 1)


def quit_hotkey_pressed():
    msg = wt.MSG()
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        if msg.message == 0x0312:  # WM_HOTKEY
            return True
    return False


def read_config():
    """setting.ini, written as UTF-16 by the AHK build. All keys optional."""
    cp = None
    path = os.path.join(ROOT, "setting.ini")
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            import configparser
            c = configparser.ConfigParser()
            with open(path, encoding=enc) as f:
                c.read_file(f)
            cp = c
            break
        except Exception:
            continue

    def get(section, key, default, cast=int):
        if cp is None:
            return default
        try:
            return cast(cp.get(section, key))
        except Exception:
            return default

    return {
        "log": get("update", "log", 1),
        "autostart": bool(get("autocast", "autostart", 1)),
        "autocast": bool(get("autocast", "enabled", 1)),
        "cast_hold": get("autocast", "cast_hold_ms", 600) / 1000.0,
        "bite_timeout": get("autocast", "bite_timeout_s", 35),
    }


# ------------------------------------------------------------- test mode ----

def run_test(frames_dir):
    global log_level, log_to_file
    log_level = 2
    log_to_file = False  # keep offline runs out of genshinfishing.log
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

    # Replay the frames as one continuous fight so the tracking state
    # (zone width prior, predicted positions, drift) evolves like it does live.
    mouse = FakeMouse()
    stats = {"zone": 0, "cursor": 0, "blind": 0, "in_zone": 0, "decided": 0}
    for f in files:
        frame = cv2.imread(f)
        bot.get_state(frame)
        clusters = bot.detect_bar(frame)
        zl, zr, cx = bot.interpret_bar(clusters)
        if zl is not None:
            stats["zone"] += 1
        if cx is not None:
            stats["cursor"] += 1
        if zl is None and cx is None:
            stats["blind"] += 1
        bot.state_predict = "reel"
        before = mouse.down
        bot.reel_tick(frame, mouse)
        if zl is not None and cx is not None:
            stats["decided"] += 1
            if zl <= cx <= zr:
                stats["in_zone"] += 1
        print(f"{os.path.basename(f)}: state={bot.state} zone={zl}-{zr} cur={cx}"
              f" lmb={'DOWN' if mouse.down else 'up'}{' *' if before != mouse.down else ''}")
    n = len(files)
    print(f"\n{n} frames: zone found {stats['zone']}, cursor found {stats['cursor']},"
          f" nothing {stats['blind']}")
    print(f"cursor inside zone on {stats['in_zone']}/{stats['decided']} fully-tracked frames")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-frames", help="run detection on a directory of PNG frames")
    args = ap.parse_args()
    if args.test_frames:
        sys.exit(run_test(args.test_frames))
    run_live()
