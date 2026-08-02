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

# Which bait catches which fish (ported from GenshinFishing.ahk)
FISH_BAIT = {
    "medaka": "fruitpaste", "aizenmedaka": "fruitpaste", "dawncatcher": "fruitpaste",
    "crystalfish": "fruitpaste", "glazemedaka": "fruitpaste",
    "sweetflowermedaka": "fruitpaste",
    "stickleback": "redrot", "akaimaou": "redrot", "betta": "redrot",
    "venomspinefish": "redrot", "snowstrider": "redrot",
    "lungedstickleback": "redrot",
    "koi": "fakefly", "rustykoi": "fakefly", "goldenkoi": "fakefly",
    "pufferfish": "fakefly", "bitterpufferfish": "fakefly", "formaloray": "fakefly",
    "teacoloredshirakodai": "falseworm", "brownshirakodai": "falseworm",
    "purpleshirakodai": "falseworm", "abidingangelfish": "falseworm",
    "raimeiangelfish": "falseworm", "divdaray": "falseworm",
    "halcyonjadeaxemarlin": "sugardew", "lazuriteaxemarlin": "sugardew",
    "peachofthedeepwaves": "sugardew", "sandstormangler": "sugardew",
    "sunsetcloudangler": "sugardew", "truefruitangler": "sugardew",
    "blazingheartfeatherbass": "sugardew", "ripplingheartfeatherbass": "sugardew",
    "streamingaxemarlin": "sugardew",
    "jadeheartfeatherbass": "sourbait", "ray": "sourbait",
    "maintenancemekgoldleader": "flashingmaintenancemekbait",
    "maintenancemekinitialconfiguration": "flashingmaintenancemekbait",
    "maintenancemekplatinumcollection": "flashingmaintenancemekbait",
    "maintenancemeksituationcontroller": "flashingmaintenancemekbait",
    "maintenancemekwaterbodycleaner": "flashingmaintenancemekbait",
    "magmarapidfightingfish": "emberglowbait",
    "phonyphlogistonunihornfish": "emberglowbait",
    "secretsourcescoutsweeper": "emberglowbait",
    "divingrapidfightingfish": "spinelgrainbait",
    "floralrapidfightingfish": "spinelgrainbait",
    "floralfightingrapidfish": "spinelgrainbait",
    "greenwavesunfish": "spinelgrainbait", "dusksunfish": "spinelgrainbait",
    "pseudosharkunihornfish": "spinelgrainbait",
    "blazingaxeheadfish": "berrybait", "commonaxeheadfish": "berrybait",
    "frostedaxeheadfish": "berrybait",
    "azuregazecrystaleye": "refreshinglakkabait",
    "nightgazecrystaleye": "refreshinglakkabait",
    "veggiemaulershark": "refreshinglakkabait",
    "neonmaulershark": "refreshinglakkabait",
}

# "Fish Present" row in the Prepare to Fish panel, at 1080p
FISH_SLOT_Y = (432, 520)
FISH_SLOT_X0, FISH_SLOT_STEP, FISH_SLOT_W = 1231, 113, 90

# "Select Bait" tile in the Prepare to Fish panel (opens the bait dialog)
BAIT_TILE = (1643, 795)
# Bait cards live in a centred row in that dialog; buttons sit below it
BAIT_CARD_REGION = (460, 300, 1460, 720)
BAIT_BUTTON_REGION = (400, 680, 1600, 830)

# ImageSearch variation thresholds (max abs channel diff on masked pixels),
# same values as the AHK script
VAR_STATE = 32
# "Start Fishing" button: true matches <=40 across two sessions, false floor >=80
VAR_PANEL = 50
# bait icons: true matches <=48, false floor >=101 (measured when cut)
VAR_BAIT = 60
# Cancel/Confirm in the bait dialog match near-exactly
VAR_MENU = 30

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
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010


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

    def right_click(self):
        """RMB: bound to "change bait" while in fishing mode."""
        self.release()
        _mouse_event(MOUSEEVENTF_RIGHTDOWN)
        time.sleep(0.04)
        _mouse_event(MOUSEEVENTF_RIGHTUP)
        log("RMB click", 1)


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


def load_fish_refs(size=96):
    """game8 fish icons, trimmed of their border and scaled to the panel size."""
    refs = {}
    d = os.path.join(ROOT, "assets", "references", "fish")
    for p in glob.glob(os.path.join(d, "*.png")):
        img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        img = img[:, :, :3]
        pad = int(img.shape[0] * 0.10)
        img = img[pad:img.shape[0] - pad, pad:img.shape[1] - pad]
        refs[os.path.splitext(os.path.basename(p))[0]] = cv2.resize(
            img, (size, size), interpolation=cv2.INTER_AREA)
    return refs


def icon_similarity(a, b):
    """Normalised correlation: tolerant of the panel/reference tint difference."""
    return -float(cv2.matchTemplate(a.astype(np.float32), b.astype(np.float32),
                                    cv2.TM_CCOEFF_NORMED)[0, 0])


def load_templates(res_dir):
    t = {}
    for name in ("ready", "reel", "casting"):
        t[name] = Template(os.path.join(res_dir, name + ".png"))
    # only cut for 1080p so far; without them those steps stay manual
    optional = ["btn_startfishing", "menu_confirm", "menu_cancel"]
    optional += [os.path.splitext(os.path.basename(p))[0]
                 for p in glob.glob(os.path.join(res_dir, "bait_*.png"))]
    for name in optional:
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
        self.panel_started = False
        self.panel_gone = 0
        self.wanted_bait = None
        self.reset_fight()

    def reset_fight(self):
        self.bar_seen = False
        self.bar_misses = 0
        self.zone_w = 150.0 * self.dline / 2202.0
        self.left_x_old = self.right_x_old = self.cur_x_old = None
        self.left_fresh = self.cur_fresh = False
        self.left_pred = self.right_pred = self.cur_pred = 0

    def read_fish_present(self, frame, refs, size=96):
        """Identify the 5 'Fish Present' icons -> [(fish, bait, score)]."""
        out = []
        for i in range(5):
            x = FISH_SLOT_X0 + i * FISH_SLOT_STEP
            crop = frame[FISH_SLOT_Y[0]:FISH_SLOT_Y[1], x:x + FISH_SLOT_W]
            if crop.shape[0] < 10 or crop.shape[1] < 10:
                continue
            pad = int(crop.shape[0] * 0.10)
            crop = crop[pad:crop.shape[0] - pad, pad:crop.shape[1] - pad]
            # an empty slot is flat panel background, not a fish
            if crop.std() < 12:
                continue
            crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
            sc, name = min((icon_similarity(crop, r), n) for n, r in refs.items())
            out.append((name, FISH_BAIT.get(name), sc))
        return out

    def choose_bait(self, fish):
        """Most common bait among the fish present; ties go to the best match."""
        by_bait = {}
        for name, bait, sc in fish:
            if bait is None:
                continue
            n, best = by_bait.get(bait, (0, 0.0))
            by_bait[bait] = (n + 1, min(best, sc))
        if not by_bait:
            return None
        return sorted(by_bait.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[0][0]

    def better_bait(self, fish, min_fish):
        """A bait worth switching to, or None to keep the current one.

        Only fires once nothing in the water matches the equipped bait: the
        panel roster is static, so this live count is the only signal that the
        fish it attracts have been fished out.
        """
        counts = {}
        for f in fish:
            b = f.get("bait")
            if b:
                counts[b] = counts.get(b, 0) + 1
        if not counts:
            return None
        cur = self.wanted_bait
        if cur and counts.get(cur, 0) > 0:
            return None
        best, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= min_fish and best != cur:
            return best
        return None

    def find_menu_button(self, frame, which):
        """Centre of the bait dialog's Confirm/Cancel button, or None."""
        t = self.t.get(f"menu_{which}")
        if t is None:
            return None
        hit = search(frame, t, *BAIT_BUTTON_REGION, VAR_MENU)
        return None if hit is None else (hit[0] + t.w // 2, hit[1] + t.h // 2)

    def find_bait_card(self, frame, bait):
        """-> (centre, already_selected) for a bait in the dialog, else (None, False).

        The selected card renders zoomed, hence the separate _sel template;
        _b/_c are scale variants because the in-game icon scale is fractional.
        """
        for suf in ("", "_b", "_c"):
            t = self.t.get(f"bait_{bait}{suf}")
            if t is None:
                continue
            hit = search(frame, t, *BAIT_CARD_REGION, VAR_BAIT)
            if hit:
                return (hit[0] + t.w // 2, hit[1] + t.h // 2), False
        t = self.t.get(f"bait_{bait}_sel")
        if t is not None:
            hit = search(frame, t, *BAIT_CARD_REGION, VAR_BAIT)
            if hit:
                return (hit[0] + t.w // 2, hit[1] + t.h // 2), True
        return None, False

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
        """Tall golden-yellow column clusters in the tension-bar band.

        Hue is the discriminator: the UI gold sits at H~25 (OpenCV units)
        while warm scenery (sunset water, sand) is H<=15, so an RGB
        "yellowish" test floods with false clusters at sunset. The zone
        outline contributes only ~4px of fill per column, so a filled-height
        threshold keeps just the brackets and the cursor.
        """
        y0, y1 = self.dpt(0.04), self.dpt(0.0635)
        band = frame[y0:y1, self.barS_left:self.barS_right]
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
        H = hsv[:, :, 0].astype(np.int16)
        S = hsv[:, :, 1].astype(np.int16)
        V = hsv[:, :, 2].astype(np.int16)
        m = (H >= 18) & (H <= 34) & (S > 60) & (V > 180)
        heights = m.sum(axis=0)
        min_h = max(8, round(12 * self.dline / 2202))
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
                for c0, c1 in clusters if c1 - c0 >= 2]

    def interpret_bar(self, clusters):
        """-> (zone_left, zone_right, cursor_x), any of which may be None.

        The cursor is a full-height "I" while the brackets are shorter
        chevrons, so the tallest cluster is the cursor. Pairing brackets by a
        zone-width prior instead picks the wrong pair whenever the cursor
        escapes past a bracket, which is exactly when steering matters most.
        """
        s = self.dline / 2202.0
        if not clusters:
            return None, None, None
        if len(clusters) == 1:
            c0, c1, _ = clusters[0]
            # a lone wide blob is the zone with the cursor lost inside it
            if c1 - c0 > 60 * s:
                return c0, c1, None
            return None, None, (c0 + c1) // 2

        if len(clusters) >= 3:
            cur = max(clusters, key=lambda c: c[2])
            rest = [c for c in clusters if c is not cur]
            zl, zr = rest[0][0], rest[-1][1]
            cursor = (cur[0] + cur[1]) // 2
        else:
            a, b = clusters
            wide = 18 * s
            aw, bw = a[1] - a[0], b[1] - b[0]
            zl, zr = a[0], b[1]
            if aw >= wide and aw > bw:
                cursor = (a[0] + a[1]) // 2   # cursor merged into the left one
            elif bw >= wide and bw > aw:
                cursor = (b[0] + b[1]) // 2
            else:
                cursor = None                 # two bare brackets, cursor hidden
        self.zone_w = 0.75 * self.zone_w + 0.25 * (zr - zl)
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

        # Extrapolate one tick ahead, but only from a position measured on the
        # immediately preceding tick - a stale reference makes the prediction
        # explode, which is what made the old steering thrash.
        lead = self.dpt(0.0086)  # max plausible travel per tick, ~19px @1080p

        def predict(now, prev, fresh):
            if not fresh or prev is None:
                return now
            return now + int(np.clip(now - prev, -lead, lead))

        drift = 0
        if zl is not None:
            self.left_pred = predict(zl, self.left_x_old, self.left_fresh)
            self.right_pred = predict(zr, self.right_x_old, self.left_fresh)
            if self.left_fresh and self.left_x_old is not None:
                drift = (zl + zr) - (self.left_x_old + self.right_x_old)
            self.left_x_old, self.right_x_old = zl, zr
        self.left_fresh = zl is not None

        if cx is not None:
            self.cur_pred = predict(cx, self.cur_x_old, self.cur_fresh)
            self.cur_x_old = cx
        elif zl is not None:
            # cursor hidden: it is somewhere in the zone, so aim for the middle
            self.cur_pred = (self.left_pred + self.right_pred) // 2
        self.cur_fresh = cx is not None

        # lead the zone: drifting left -> aim at its left part, and vice versa
        if drift < 0:
            k = 0.25
        elif drift > 0:
            k = 0.75
        else:
            k = 0.5
        target = k * self.right_pred + (1 - k) * self.left_pred
        if self.cur_pred < target:
            mouse.hold()      # tension up moves the cursor right
        else:
            mouse.release()
        log(f"zone={zl}-{zr} cur={cx} pred={self.cur_pred} tgt={int(target)}", 2)
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
    log(f"autostart={cfg['autostart']} autobait={cfg['autobait']} "
        f"autocast={cfg['autocast']} aim={cfg['aim']} rebait={cfg['rebait']} "
        f"cast_hold={cfg['cast_hold']}s cooldown={cfg['cast_cooldown']}s "
        f"bite_timeout={cfg['bite_timeout']}s", 0)
    cast_start = 0.0

    # F5 quits (RegisterHotKey id=1)
    user32.RegisterHotKey(None, 1, 0, 0x74)

    cap = Capture()
    mouse = Mouse()
    fish_refs = load_fish_refs()
    log(f"{len(fish_refs)} fish reference icons loaded", 1)
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
                elif (cfg["autocast"] and cast_start > 0
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
                    now = time.monotonic()
                    # the rod icon still reads "ready" through the cast
                    # animation; casting again there just reels the line back in
                    if cfg["autocast"] and now - cast_start > cfg["cast_cooldown"]:
                        geom = (left, top, w, h)
                        # one scan serves both aiming and the re-bait check
                        fish = (scan_pond(cap, geom)
                                if (cfg["aim"] or cfg["rebait"]) else None)
                        swapped = False
                        if cfg["rebait"] and cfg["autobait"] and fish:
                            better = bot.better_bait(fish, cfg["rebait_min"])
                            if better:
                                swapped = switch_bait(bot, cap, mouse,
                                                      geom, better)
                        if not swapped:
                            log("ready: casting", 1)
                            if cfg["aim"]:
                                aim_and_cast(bot, cap, mouse, geom, cfg,
                                             bot.wanted_bait, fish=fish)
                            else:
                                mouse.cast(cfg["cast_hold"])
                            cast_start = time.monotonic()
                            time.sleep(1.0)
                    else:
                        time.sleep(0.3)
                else:
                    # not in fishing mode: the Prepare to Fish panel may be open
                    bot.reset_fight()
                    btn = bot.find_start_button(frame)
                    if btn is None:
                        bot.panel_gone += 1
                        if bot.panel_gone >= 3:
                            bot.panel_started = False   # panel really closed
                        time.sleep(0.5)
                    else:
                        bot.panel_gone = 0
                        if not bot.panel_started:
                            panel_fish = bot.read_fish_present(frame, fish_refs)
                            log("fish present: "
                                + ", ".join(f"{n}->{b}"
                                            for n, b, _ in panel_fish), 1)
                            want = bot.choose_bait(panel_fish)
                            log(f"recommended bait: {want}", 0)
                            bot.wanted_bait = want
                            if want and cfg["autobait"]:
                                select_bait(bot, cap, mouse,
                                            (left, top, w, h), want)
                                frame = cap.grab(left, top, w, h)
                                btn = bot.find_start_button(frame) or btn
                            if cfg["autostart"]:
                                log("clicking Start Fishing", 1)
                                mouse.click_at(left + btn[0], top + btn[1])
                                bot.panel_started = True
                                time.sleep(2.0)
                            else:
                                time.sleep(1.0)
                        else:
                            time.sleep(0.5)
    finally:
        mouse.release()
        user32.UnregisterHotKey(None, 1)


def select_bait(bot, cap, mouse, geom, want, opener="panel"):
    """Open the Select Bait dialog, pick `want`, confirm. -> True if selected.

    `opener` is how the dialog is reached: "panel" clicks the Select Bait tile
    in Prepare to Fish, "rmb" uses the change-bait button bound to right click
    while fishing (no need to leave fishing mode).

    Every step is template-gated: if the dialog or the bait is not positively
    identified the routine backs out with Cancel rather than clicking blind.
    """
    left, top, w, h = geom

    def grab():
        return cap.grab(left, top, w, h)

    if opener == "rmb":
        mouse.right_click()
    else:
        mouse.click_at(left + BAIT_TILE[0], top + BAIT_TILE[1])
    time.sleep(1.0)
    frame = grab()
    if bot.find_menu_button(frame, "confirm") is None:
        log("bait dialog did not open; leaving bait unchanged", 0)
        return False

    card, already = bot.find_bait_card(frame, want)
    if card is None:
        log(f"bait '{want}' not offered in this water body; keeping current", 0)
        cancel = bot.find_menu_button(frame, "cancel")
        if cancel:
            mouse.click_at(left + cancel[0], top + cancel[1])
            time.sleep(0.8)
        return False

    if already:
        log(f"bait '{want}' already selected", 1)
    else:
        log(f"selecting bait '{want}' at {card}", 1)
        mouse.click_at(left + card[0], top + card[1])
        time.sleep(0.5)
        frame = grab()

    confirm = bot.find_menu_button(frame, "confirm")
    if confirm is None:
        log("confirm button vanished; leaving dialog alone", 0)
        return False
    mouse.click_at(left + confirm[0], top + confirm[1])
    time.sleep(1.2)
    bot.wanted_bait = want
    return True


def scan_pond(cap, geom):
    """Detect the fish currently swimming in front of the player.

    Fish move while stones, plants and the rod do not, so a motion mask over
    a few spaced frames is what separates them from the scenery.
    """
    left, top, w, h = geom
    try:
        from tools.fish_scan import detect_fish
    except Exception as e:                                   # pragma: no cover
        log(f"pond scanner unavailable ({e})", 0)
        return []
    frames = []
    for i in range(3):
        if i:
            time.sleep(0.45)
        frames.append(cap.grab(left, top, w, h))
    motion = np.zeros(frames[0].shape[:2], np.uint8)
    for a, b in zip(frames, frames[1:]):
        motion |= (cv2.absdiff(a, b).max(axis=2) > 16).astype(np.uint8) * 255
    motion = cv2.dilate(motion, np.ones((9, 9), np.uint8))
    return detect_fish(frames[-1], motion)


def switch_bait(bot, cap, mouse, geom, new_bait):
    """Swap bait without leaving fishing mode (RMB opens Select Bait)."""
    log(f"no '{bot.wanted_bait}' fish left; switching to '{new_bait}'", 0)
    return select_bait(bot, cap, mouse, geom, new_bait, opener="rmb")


def aim_and_cast(bot, cap, mouse, geom, cfg, want_bait, fish=None):
    """Steer the landing reticle onto a fish, then cast.

    Falls back to an open-loop cast whenever the pond scan or the reticle
    detector comes up empty, so a failed aim never blocks fishing.
    """
    left, top, w, h = geom
    try:
        from tools.aim_cast import find_reticle, send_relative
    except Exception as e:                                   # pragma: no cover
        log(f"aim tools unavailable ({e}); casting open-loop", 0)
        mouse.cast(cfg["cast_hold"])
        return

    if fish is None:
        fish = scan_pond(cap, geom)
    if not fish:
        log("no fish seen; casting open-loop", 1)
        mouse.cast(cfg["cast_hold"])
        return

    # prefer a fish the chosen bait actually catches, else the biggest
    match = [f for f in fish if want_bait and f.get("bait") == want_bait]
    target = (match or fish)[0]
    log(f"aiming at {target['family']} at ({target['x']},{target['y']})"
        f"{' [bait match]' if match else ''}", 1)

    mouse.hold()
    deadline = time.monotonic() + cfg["aim_timeout"]
    gain_x = gain_y = None
    prev = None
    aligned = False
    try:
        while time.monotonic() < deadline:
            pos = find_reticle(cap.grab(left, top, w, h))
            if pos is None:
                time.sleep(0.2)
                continue
            dx, dy = target["x"] - pos[0], target["y"] - pos[1]
            dist = max((dx * dx + dy * dy) ** 0.5, 1.0)
            # land short of the fish: dropping on top of it scares it away
            keep = 1 - min(cfg["aim_offset"], dist) / dist
            err_x, err_y = dx * keep, dy * keep
            if abs(err_x) <= 26 and abs(err_y) <= 26:
                aligned = True
                break
            if gain_x is None:
                if prev is None:
                    prev = pos
                    send_relative(60, 30)
                    time.sleep(0.2)
                    continue
                mvx, mvy = pos[0] - prev[0], pos[1] - prev[1]
                gain_x = 60 / mvx if abs(mvx) > 4 else 1.0
                gain_y = 30 / mvy if abs(mvy) > 4 else gain_x
                gain_x = max(-8.0, min(8.0, gain_x))
                gain_y = max(-8.0, min(8.0, gain_y))
                log(f"aim gain=({gain_x:.2f},{gain_y:.2f})", 2)
            send_relative(int(max(-220, min(220, err_x * gain_x * 0.8))),
                          int(max(-220, min(220, err_y * gain_y * 0.8))))
            time.sleep(0.18)
        log("aim aligned" if aligned else "aim timed out, casting anyway", 1)
    finally:
        mouse.release()


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
        "autobait": bool(get("autocast", "autobait", 1)),
        "cast_hold": get("autocast", "cast_hold_ms", 600) / 1000.0,
        "cast_cooldown": get("autocast", "cast_cooldown_s", 5),
        "bite_timeout": get("autocast", "bite_timeout_s", 35),
        "rebait": bool(get("autocast", "rebait", 1)),
        "rebait_min": get("autocast", "rebait_min_fish", 2),
        "aim": bool(get("autocast", "aim", 1)),
        "aim_offset": get("autocast", "aim_offset_px", 110),
        "aim_timeout": get("autocast", "aim_timeout_s", 8),
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
