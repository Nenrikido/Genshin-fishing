"""Genshin fishing bot (1920x1080).

Reads the fishing state off the HUD and runs the whole loop: Prepare to Fish
panel -> bait -> Start Fishing -> cast -> bite -> tension-bar minigame ->
recast, re-baiting when the fish it targets are gone.

Usage:
    python genshin_fishing.py                      # live bot
    python genshin_fishing.py --selftest           # check assets and config
    python genshin_fishing.py --test-frames <dir>  # offline check on PNGs

F5 quits the live bot. Runs elevated: Genshin ignores synthetic input from a
non-elevated process.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import glob
import math
import os
import sys
import time

import cv2
import numpy as np

# Two roots, because a PyInstaller build separates them: templates and
# reference icons ride inside the exe (sys._MEIPASS), while setting.ini and
# the log belong next to it where the user can reach them.
FROZEN = getattr(sys, "frozen", False)
ROOT = os.path.dirname(sys.executable if FROZEN
                       else os.path.abspath(__file__))
ASSETS = os.path.join(getattr(sys, "_MEIPASS", ROOT), "assets")
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

# "Fish Present" row in the Prepare to Fish panel, at 1080p. The row holds
# between one and five tiles and is centred, so their x depends on how many
# there are - locate_fish_slots() reads the actual tiles off the frame.
FISH_SLOT_Y = (432, 520)
FISH_SLOT_STEP, FISH_SLOT_W = 113, 94
FISH_MATCH_MAX = -0.45             # icon_similarity above this is a guess

# Camera turn: measured -1.95 screen px of world travel per mouse unit, so a
# few hundred units covers any correction. Bigger steps only pin the OS
# cursor against a screen edge, where the moves stop having any effect.
AIM_PROBE, AIM_STEP_MAX = 80, 200
FISH_ROW_X = (1110, 1900)          # the "Fish Present" box
FISH_ROW_CENTER = 1501             # tiles are centred on this

# "Select Bait" tile in the Prepare to Fish panel (opens the bait dialog)
BAIT_TILE = (1643, 795)
# Bait cards live in a centred row in that dialog; buttons sit below it
BAIT_CARD_REGION = (460, 300, 1460, 720)
BAIT_BUTTON_REGION = (400, 680, 1600, 830)
BAIT_CARD_Y = (432, 600)           # the card row inside that region
BAIT_CARD_STEP, BAIT_CARD_W = 139, 123
BAIT_ROW_CENTER = 959              # cards are centred on this, 1..5 of them
BAIT_TEMPLATE_SIZE = 84            # matched crop, centred on the icon
# The on-screen size a bait icon renders at depends on how much padding its
# reference art carries, not on anything about the dialog: measured 98 for
# fruitpaste and 126 for sugardew in the same layout. So sweep the scale
# rather than shipping a few fixed guesses.
BAIT_ICON_SIZES = range(96, 131, 2)
BAIT_EDGE_MASK = 56                # local contrast above this gets fuchsia-masked
# The panel shows the bait actually on the rod, at the same icon scale
BAIT_PANEL_TILE = (1580, 730, 1710, 860)

# ImageSearch variation thresholds (max abs channel diff on masked pixels),
# same values as the AHK script
VAR_STATE = 32
# "Start Fishing" button: true matches <=40 across two sessions, false floor >=80
VAR_PANEL = 50
# bait icons: true matches <=48, false floor >=101 (measured when cut)
# Bait cards: with the scale swept, the worst true match measured needs 86
# while no absent bait matched below 100 on any labelled dialog.
VAR_BAIT = 92
# Reading the equipped bait off the panel is a 1-of-11 guess with nothing to
# fall back on, so it is held to a much tighter fit: correct matches measured
# 38-40, the best wrong one 118.
VAR_BAIT_EQUIPPED = 70
# Cancel/Confirm in the bait dialog match near-exactly
VAR_MENU = 30

log_level = 0
log_to_file = True
_log_file = None


def log(txt, level=0):
    global _log_file, log_to_file
    if log_level >= level:
        now = time.time()
        stamp = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now*1000)%1000:03d}"
        if log_to_file:
            if _log_file is None:
                try:
                    _log_file = open(LOG_PATH, "a", encoding="utf-8")
                except OSError as e:
                    # a build dropped somewhere unwritable still runs fine
                    print(f"(no log file: {e})")
                    log_to_file = False
            if _log_file is not None:
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
    def __init__(self, path, img=None, name=None):
        if img is None:
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None:
                raise FileNotFoundError(path)
        self.bgr = img
        # fuchsia (BGR 255,0,255) marks transparent pixels
        self.mask = ~((img[:, :, 0] == 255) & (img[:, :, 1] == 0) & (img[:, :, 2] == 255))
        self.mask_u8 = self.mask.astype(np.uint8) * 255
        self.h, self.w = img.shape[:2]
        self.name = name or os.path.basename(path)


def load_fish_refs(size=96):
    """game8 fish icons, trimmed of their border and scaled to the panel size."""
    refs = {}
    d = os.path.join(ASSETS, "references", "fish")
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
    # menu_confirm/menu_cancel are plain crops of the dialog's button text
    # from a 1080p screenshot, at (1100,740)-(1260,776) and (700,740)-(850,776);
    # text only, so they match whether the glyphs are keyboard or controller.
    for name in ("btn_startfishing", "menu_confirm", "menu_cancel"):
        p = os.path.join(res_dir, name + ".png")
        if os.path.exists(p):
            t[name] = Template(p)
    return t


def load_bait_arts():
    """game8 bait card art, scaled to screen size on demand by Bot."""
    arts = {}
    for p in glob.glob(os.path.join(ASSETS, "references", "bait", "*.png")):
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is not None:
            arts[os.path.splitext(os.path.basename(p))[0]] = img
    return arts


def build_bait_template(art, icon_size):
    """Reference art rendered at `icon_size`, cropped and edge-masked.

    Sub-pixel differences between our resize and the game's renderer pile up
    on high-contrast edges, so those pixels are masked out rather than
    compared.
    """
    scaled = cv2.resize(art, (icon_size, icon_size), interpolation=cv2.INTER_CUBIC)
    m = (icon_size - BAIT_TEMPLATE_SIZE) // 2
    crop = scaled[m:m + BAIT_TEMPLATE_SIZE, m:m + BAIT_TEMPLATE_SIZE].copy()
    k = np.ones((3, 3), np.uint8)
    contrast = (cv2.dilate(crop, k).astype(int)
                - cv2.erode(crop, k).astype(int)).max(axis=2)
    crop[contrast > BAIT_EDGE_MASK] = (255, 0, 255)
    return crop


def match_score(scene, tmpl, x0, y0, x1, y1):
    """Best placement of tmpl in scene[y0:y1, x0:x1] -> (x, y, worst diff).

    Candidate via masked TM_SQDIFF, then the exact max-channel difference
    AHK's ImageSearch compares against its *variation.
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
    return x0 + mx, y0 + my, int(diff[tmpl.mask].max())


def search(scene, tmpl, x0, y0, x1, y1, variation):
    """(x, y) of tmpl's top-left in scene coords if it matches, else None."""
    hit = match_score(scene, tmpl, x0, y0, x1, y1)
    if hit is not None and hit[2] <= variation:
        return hit[0], hit[1]
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
        self.bait_arts = load_bait_arts()
        self._bait_tpl = {}
        self.w = win_w
        self.h = win_h
        self.dline = int(np.ceil((win_w ** 2 + win_h ** 2) ** 0.5))
        d = self.dpt
        # The tension-bar track is centred on the screen and its width is
        # fixed (measured at 720..1199 on 1080p). Searching only inside it
        # keeps sunlit scenery out of the yellow mask entirely.
        self.bar_left = win_w // 2 - d(0.113)
        self.bar_right = win_w // 2 + d(0.113)
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
        self.rejected_baits = set()
        self.reset_fight()

    def reset_fight(self):
        self.bar_seen = False
        self.bar_misses = 0
        self.left_x_old = self.right_x_old = self.cur_x_old = None
        self.left_fresh = self.cur_fresh = False
        self.left_pred = self.right_pred = self.cur_pred = 0

    @staticmethod
    def locate_fish_slots(frame):
        """x of each 'Fish Present' tile, read off the frame.

        The row is centred, so a fixed five-slot grid lands half a tile off
        whenever the point holds four fish - which is most of them. The tiles
        are lighter than the box behind them, so a column-brightness profile
        finds their edges directly.
        """
        x0, x1 = FISH_ROW_X
        band = frame[FISH_SLOT_Y[0] - 2:FISH_SLOT_Y[1] + 5, x0:x1]
        if band.shape[0] < 10 or band.shape[1] < 100:
            return []
        v = band.astype(np.float32).mean(axis=2).mean(axis=0)
        lit = np.where(v > np.percentile(v, 20) + 6)[0]
        runs = []
        if len(lit):
            start = prev = lit[0]
            for x in lit[1:]:
                if x - prev > 4:
                    runs.append((start, prev))
                    start = x
                prev = x
            runs.append((start, prev))
        runs = [r for r in runs if r[1] - r[0] > 30]
        if not runs:
            return []
        left, right = runs[0][0] + x0, runs[-1][1] + x0
        n = int(round((right - left - FISH_SLOT_W) / FISH_SLOT_STEP)) + 1
        n = max(1, min(5, n))
        # trust the count, not the measured edge: a dark fish clips its tile
        left = FISH_ROW_CENTER - (n * FISH_SLOT_STEP - (FISH_SLOT_STEP -
                                                        FISH_SLOT_W)) // 2
        return [left + i * FISH_SLOT_STEP for i in range(n)]

    def read_fish_present(self, frame, refs, size=96):
        """Identify the 'Fish Present' icons -> [(fish, bait, score)]."""
        out = []
        for x in self.locate_fish_slots(frame):
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
        """Most common bait among the fish present; ties go to the best match.

        Slots the game draws as plain silhouettes - fish not yet caught - hold
        no colour to match on and score around -0.2 to -0.35, against -0.5 and
        better for a real identification. Guessing from those is worse than
        not recommending anything, which just leaves the current bait on.
        """
        by_bait = {}
        for name, bait, sc in fish:
            if bait is None or sc > FISH_MATCH_MAX:
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
            if b and b not in self.rejected_baits:
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

    @staticmethod
    def locate_bait_cards(frame):
        """Centre x of each card in the Select Bait dialog (1..5, centred)."""
        y0, y1 = BAIT_CARD_Y
        band = frame[y0 - 2:y1, 400:1520]
        if band.shape[0] < 20:
            return []
        v = band.astype(np.float32).mean(axis=2).mean(axis=0)
        lit = np.where(v > np.percentile(v, 30) + 12)[0]
        runs = []
        if len(lit):
            s = p = lit[0]
            for x in lit[1:]:
                if x - p > 5:
                    runs.append((s + 400, p + 400))
                    s = x
                p = x
            runs.append((s + 400, p + 400))
        runs = [r for r in runs if r[1] - r[0] > 40]
        if not runs:
            return []
        # a selected card glows past its own edge, so derive the count from
        # the span and then place the cards on the exact centred grid
        span = runs[-1][1] - runs[0][0]
        n = max(1, min(5, int(round((span - BAIT_CARD_W) / BAIT_CARD_STEP)) + 1))
        return [int(BAIT_ROW_CENTER + (i - (n - 1) / 2) * BAIT_CARD_STEP)
                for i in range(n)]

    def bait_template(self, bait, size):
        key = (bait, size)
        t = self._bait_tpl.get(key)
        if t is None:
            art = self.bait_arts.get(bait)
            if art is None:
                return None
            t = Template(None, build_bait_template(art, size), f"{bait}@{size}")
            self._bait_tpl[key] = t
        return t

    def read_equipped_bait(self, frame):
        """Which bait the Prepare panel shows on the rod, or None if unsure.

        Without this the bot has no idea what it is fishing with whenever a
        water body refuses its choice, and then "re-baits" away from a bait
        it never had.
        """
        best = None
        for name in self.bait_arts:
            for size in BAIT_ICON_SIZES:
                t = self.bait_template(name, size)
                hit = match_score(frame, t, *BAIT_PANEL_TILE)
                if hit and (best is None or hit[2] < best[0]):
                    best = (hit[2], name)
        if best is None or best[0] > VAR_BAIT_EQUIPPED:
            log(f"equipped bait unrecognised (best {best})", 2)
            return None
        log(f"equipped bait: {best[1]} (diff {best[0]})", 1)
        return best[1]

    def find_bait_card(self, frame, bait):
        """Centre of `bait`'s card in the dialog, or None.

        Searched card by card over a sweep of icon scales: which scale fits
        depends on the reference art's own padding, so one fixed size can
        only ever work for the few baits it was calibrated on. The best-
        scoring card wins rather than the first one over the threshold -
        several baits are plain coloured balls that pass on each other.
        """
        if bait not in self.bait_arts:
            return None
        y0, y1 = BAIT_CARD_Y
        best = None
        for cx in self.locate_bait_cards(frame):
            for size in BAIT_ICON_SIZES:
                t = self.bait_template(bait, size)
                if t is None:
                    continue
                hit = match_score(frame, t, cx - 70, y0 - 6, cx + 70, y1)
                if hit and hit[2] <= VAR_BAIT and (best is None or hit[2] < best[0]):
                    best = (hit[2], cx)
        if best is None:
            return None
        log(f"bait '{bait}' card at x={best[1]} (diff {best[0]})", 2)
        return best[1], (y0 + y1) // 2

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
    # Two fill thresholds separate the two kinds of yellow the UI draws: the
    # zone is a rounded outline carrying only a few filled pixels per column,
    # while its end chevrons and the cursor are tall solid glyphs. Reading the
    # zone from the outline instead of from a pair of glyphs is what makes
    # this robust - the glyphs merge and split as the cursor slides past a
    # chevron, and any rule for pairing them fails exactly then.
    def _runs(self, heights, thr, gap=3):
        xs = np.where(heights >= thr)[0]
        if not len(xs):
            return []
        runs, start, prev = [], xs[0], xs[0]
        for x in xs[1:]:
            if x - prev > gap:
                runs.append((start, prev))
                start = x
            prev = x
        runs.append((start, prev))
        return [(int(a) + self.bar_left, int(b) + self.bar_left)
                for a, b in runs if b - a >= 2]

    def detect_bar(self, frame):
        """-> (outline_runs, glyph_runs) of golden-yellow columns in the band.

        Hue is the discriminator: the UI gold sits at H~25 (OpenCV units)
        while warm scenery (sunset water, sand) is H<=15, so an RGB
        "yellowish" test floods with false runs at sunset.
        """
        y0, y1 = self.dpt(0.04), self.dpt(0.0635)
        band = frame[y0:y1, self.bar_left:self.bar_right]
        hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
        H = hsv[:, :, 0].astype(np.int16)
        S = hsv[:, :, 1].astype(np.int16)
        V = hsv[:, :, 2].astype(np.int16)
        heights = ((H >= 18) & (H <= 34) & (S > 60) & (V > 180)).sum(axis=0)
        s = self.dline / 2202.0
        return (self._runs(heights, max(2, round(3 * s))),
                self._runs(heights, max(8, round(12 * s))))

    def interpret_bar(self, outline, glyphs):
        """-> (zone_left, zone_right, cursor_x), any of which may be None."""
        s = self.dline / 2202.0
        edge = 16 * s

        def has_chevron(a, b):
            # a real zone is capped by solid chevrons; warm scenery is not
            return any(g[0] <= a + edge and g[1] >= a - 4
                       or g[1] >= b - edge and g[0] <= b + 4 for g in glyphs)

        zone = None
        for a, b in outline:                       # widest plausible outline
            if (40 * s <= b - a <= 320 * s and has_chevron(a, b)
                    and (zone is None or b - a > zone[1] - zone[0])):
                zone = (a, b)
        if zone is None:
            # bar fading in or out: a single glyph can only be the cursor
            if len(glyphs) == 1:
                a, b = glyphs[0]
                return None, None, (a + b) // 2
            return None, None, None

        zl, zr = zone
        merged = 16 * s
        brackets, free = [], []
        for a, b in glyphs:
            if (a <= zl + edge and b >= zl - 4) or (b >= zr - edge and a <= zr + 4):
                brackets.append((a, b))
            else:
                free.append((a, b))
        if free:
            # more than one loose glyph is rare; trust the nearer to last time
            ref = self.cur_x_old if self.cur_x_old is not None else (zl + zr) // 2
            a, b = min(free, key=lambda t: abs((t[0] + t[1]) // 2 - ref))
            return zl, zr, (a + b) // 2
        if brackets:
            # cursor sitting on a chevron widens it well past a bare one
            a, b = max(brackets, key=lambda t: t[1] - t[0])
            if b - a > merged:
                return zl, zr, (a + b) // 2
        return zl, zr, None

    def reel_tick(self, frame, mouse):
        outline, glyphs = self.detect_bar(frame)
        zl, zr, cx = self.interpret_bar(outline, glyphs)

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
    relaunch through UAC. Declining the prompt continues in detection-only
    mode. The packaged build carries a requireAdministrator manifest, so it
    is already elevated by the time this runs."""
    if ctypes.windll.shell32.IsUserAnAdmin():
        return True
    args = "" if FROZEN else f'"{os.path.abspath(__file__)}"'
    r = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, args, ROOT, 1)
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
            res_dir = os.path.join(ASSETS, f"{w}{h}")
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
                        # re-baiting is about fish getting fished out, so it
                        # only makes sense once we have actually fished here
                        if (cfg["rebait"] and cfg["autobait"] and fish
                                and cast_start > 0):
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
                            bot.rejected_baits = set()   # new fishing point
                            bot.wanted_bait = bot.read_equipped_bait(frame)
                            panel_fish = bot.read_fish_present(frame, fish_refs)
                            log("fish present: "
                                + ", ".join(f"{n}->{b}"
                                            + ("" if s <= FISH_MATCH_MAX else "?")
                                            for n, b, s in panel_fish), 1)
                            want = bot.choose_bait(panel_fish)
                            log(f"recommended bait: {want}", 0)
                            if (want and cfg["autobait"]
                                    and want != bot.wanted_bait):
                                # select_bait overwrites wanted_bait only if
                                # it really selected it, so a refusal leaves
                                # the bait we read off the panel standing
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

    card = bot.find_bait_card(frame, want)
    if card is None:
        # the dialog lists only what this water body accepts, and that does
        # not change while we fish it: never ask for this bait again here
        bot.rejected_baits.add(want)
        log(f"bait '{want}' not offered in this water body; keeping current", 0)
        cancel = bot.find_menu_button(frame, "cancel")
        if cancel:
            mouse.click_at(left + cancel[0], top + cancel[1])
            time.sleep(0.8)
        return False

    # clicking the card is a no-op when it is already the selected one, and
    # the selected state cannot be read off the card reliably (the keyboard
    # focus frame is brighter than the selection glow)
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
    cur = bot.wanted_bait or "an unrecognised bait"
    log(f"no fish left for {cur}; switching to '{new_bait}'", 0)
    return select_bait(bot, cap, mouse, geom, new_bait, opener="rmb")


def world_shift(prev, cur):
    """How far the scene slid between two grabs, in screen px -> (dx, dy).

    Phase correlation over the whole view, which is dominated by water and
    terrain, so it measures camera rotation directly. Much steadier than
    tracking any single feature, and it needs nothing to be detected.
    """
    (sx, sy), _ = cv2.phaseCorrelate(prev, cur)
    return sx * 2.0, sy * 2.0


def _aim_frame(cap, geom):
    left, top, w, h = geom
    g = cv2.cvtColor(cap.grab(left, top, w, h)[150:850, 300:1650],
                     cv2.COLOR_BGR2GRAY).astype(np.float32)
    return cv2.resize(g, None, fx=0.5, fy=0.5)


def aim_and_cast(bot, cap, mouse, geom, cfg, want_bait, fish=None):
    """Turn the camera until a fish sits under the cast, then cast.

    The landing ring cannot be steered across the screen - it stays a fixed
    distance ahead of the camera - so aiming means turning until the fish
    arrives at it. Charging while aiming is what broke an earlier version:
    the cast kept growing for the whole aim window and ended up landing on
    the far bank, which the game marks invalid (the ring turns red).

    Steps are small on purpose, and each one goes out as a stream of tiny
    deltas rather than a single jump. The camera turns about 2 screen px per
    mouse unit, so a few hundred units covers any correction - and an
    injected move still drags the OS cursor, which stops responding once it
    is pinned against a screen edge.
    """
    try:
        from tools.aim_cast import (send_relative_smooth, center_cursor,
                                    cursor_near_edge)
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

    # prefer a fish the chosen bait actually catches, else the likeliest
    match = [f for f in fish if want_bait and f.get("bait") == want_bait]
    target = (match or fish)[0]
    fish_x = float(target["x"])
    log(f"aiming at {target['family']} at ({target['x']},{target['y']})"
        f"{' [bait match]' if match else ''}", 1)

    aim_x, tol = cfg["aim_x"], cfg["aim_tolerance"]
    deadline = time.monotonic() + cfg["aim_timeout"]
    center_cursor(geom)                # start with room to move either way
    prev = _aim_frame(cap, geom)
    gain = None            # screen px of world travel per mouse unit
    probe = AIM_PROBE
    stalls = 0
    outcome = "timed out"
    while time.monotonic() < deadline:
        err = aim_x - fish_x           # how far the fish must still travel
        if abs(err) <= tol:
            outcome = "aimed"
            break
        if cursor_near_edge(geom):
            center_cursor(geom)        # else further moves get clamped away
            log("aim: recentred the cursor", 2)
        sent = int(math.copysign(probe, -err) if gain is None
                   else max(-AIM_STEP_MAX, min(AIM_STEP_MAX, err / gain)))
        if sent == 0:
            outcome = "aimed"          # inside one mouse unit of the target
            break
        send_relative_smooth(sent, 0)  # ~0.08s of small deltas
        time.sleep(0.09)               # let the camera settle before measuring
        cur = _aim_frame(cap, geom)
        sx, _ = world_shift(prev, cur)
        prev = cur
        fish_x += sx                   # the fish rides the world
        if abs(sx) < 4:
            stalls += 1
            # one dead step means nothing; the camera drops the odd input
            if gain is None and probe < AIM_STEP_MAX:
                probe = min(AIM_STEP_MAX, probe * 2)
                continue
            if stalls < 3:
                continue
            outcome = f"camera not responding (last step {sent})"
            break
        stalls = 0
        g = sx / sent
        gain = g if gain is None else 0.5 * gain + 0.5 * g
        log(f"aim: world {sx:+.0f}px for {sent:+.0f} units, "
            f"gain={gain:.3f}, fish now x={fish_x:.0f}", 2)
    log(f"aim {outcome} (fish x={fish_x:.0f}, want {aim_x})", 1)
    mouse.cast(cfg["cast_hold"])


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
        # screen x the cast lands on: the landing ring sits at a fixed spot
        # ahead of the camera (measured 984..1007 across every session), so
        # aiming means turning until the fish reaches it
        "aim_x": get("autocast", "aim_x_px", 995),
        "aim_tolerance": get("autocast", "aim_tolerance_px", 45),
        "aim_timeout": get("autocast", "aim_timeout_s", 6),
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
    res_dir = os.path.join(ASSETS, f"{w}{h}")
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
        outline, glyphs = bot.detect_bar(frame)
        zl, zr, cx = bot.interpret_bar(outline, glyphs)
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


def run_selftest():
    """Check a build carries everything it needs, without the game running."""
    global log_level, log_to_file
    log_level, log_to_file = 1, False
    print(f"build      : {'packaged exe' if FROZEN else 'source tree'}")
    print(f"data dir   : {ROOT}       (setting.ini, genshinfishing.log)")
    print(f"assets     : {ASSETS}")
    ok = True

    res = sorted(d for d in glob.glob(os.path.join(ASSETS, "*"))
                 if os.path.isdir(d) and os.path.basename(d)[0].isdigit())
    print(f"resolutions: {len(res)} ({', '.join(os.path.basename(d) for d in res)})")
    ok &= len(res) > 0

    try:
        t = load_templates(os.path.join(ASSETS, "19201080"))
        print(f"1080p templates: {len(t)} ({', '.join(sorted(t))})")
        ok &= {"ready", "reel", "casting", "btn_startfishing",
               "menu_confirm", "menu_cancel"} <= set(t)
    except Exception as e:
        print(f"1080p templates: FAILED ({e})")
        ok = False

    arts, fish = load_bait_arts(), load_fish_refs()
    print(f"bait art   : {len(arts)}")
    print(f"fish icons : {len(fish)}")
    ok &= len(arts) >= 11 and len(fish) >= 45

    cfg = read_config()
    where = "setting.ini" if os.path.exists(os.path.join(ROOT, "setting.ini")) \
        else "defaults (no setting.ini next to me)"
    print(f"config     : {where}")
    print("             " + ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))

    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"elevated   : {admin}" + ("" if admin else "   <- clicks will be ignored"))
    print("\nself-test " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-frames", help="run detection on a directory of PNG frames")
    ap.add_argument("--selftest", action="store_true",
                    help="check assets and config load, then exit")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(run_selftest())
    if args.test_frames:
        sys.exit(run_test(args.test_frames))
    run_live()
