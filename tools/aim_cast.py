#!/usr/bin/env python3
"""Cast-aiming primitives for the fishing bot (1920x1080).

genshin_fishing.aim_and_cast drives the loop; this module supplies the two
pieces it needs: locating the landing reticle, and injecting relative mouse
movement that the game reads as camera turn.

The reticle is the trajectory preview: a long bright line arcing down to a
flat hollow ring on the water. Both are found as one connected component of
bright pixels - tall, thin along its length, ending in a row whose horizontal
*extent* is wide while its pixel *count* stays low. That hollowness is what
separates the ring from anything solid and bright (the player character, the
HUD, sun glare), so no exclusion boxes are needed.
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time

import cv2
import numpy as np

REGION = (420, 150, 1700, 900)       # search window (excludes HUD margins)
ALIGN_TOLERANCE = 26                 # px error considered "aimed"
PROBE_MOVE = (60, 30)                # first move used to measure the gain
MAX_STEP = 220                       # max injected movement per iteration
RING_MIN, RING_MAX = 24, 130         # ring width, near..far cast


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _Input(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MouseInput)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def send_relative(dx: int, dy: int) -> None:
    """Inject a relative mouse move the game reads as camera turn.

    SendInput rather than the older mouse_event: same MOUSEEVENTF_MOVE, but
    it is the path the rest of the bot's clicks already take and it is not
    subject to mouse_event's message coalescing.
    """
    if dx == 0 and dy == 0:
        return
    inp = _Input(type=0)
    inp.mi = _MouseInput(int(dx), int(dy), 0, 0x0001, 0, None)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_Input))


def bright_mask(img: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(img.astype(np.int16))
    mn = np.minimum(np.minimum(b, g), r)
    m = (mn > 150) & (b > 205) & ((b - r) < 105) & (b >= r - 10)
    return m.astype(np.uint8)


def _ring_row(comp: np.ndarray, lo: int):
    """Widest-extent row at or below `lo` -> (extent, count, row, centre_x)."""
    best = None
    for r in range(lo, comp.shape[0]):
        cols = np.where(comp[r])[0]
        if len(cols) < 2:
            continue
        ext = int(cols.max() - cols.min() + 1)
        if best is None or ext > best[0]:
            best = (ext, int(len(cols)), r, int((cols.min() + cols.max()) // 2))
    return best


def find_reticle(img: np.ndarray, region=REGION):
    """Centre of the cast landing ring, or None if the preview is not up.

    Reliable in daylight (21/21 on the recorded aim frames) but not at night,
    where the ring is dim and turns pink once the landing spot is invalid: it
    finds ~1 frame in 9 there. It also fires on bright menu panels, so only
    call it on frames where a cast is actually being aimed. The bot does not
    steer by it - aiming turns the camera and measures the world - this is
    for checking where a cast lands, e.g. to calibrate `aim_x_px`.
    """
    x0, y0, x1, y1 = region
    m = bright_mask(img)[y0:y1, x0:x1]
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if h < 60 or not (20 <= w <= 400):
            continue
        comp = lab[y:y + h, x:x + w] == i
        lo = max(0, h - 26)
        ring = _ring_row(comp, lo)
        if ring is None:
            continue
        ext, cnt, ry, cx = ring
        # a ring is wide but mostly empty across; anything solid is not one
        if not (RING_MIN <= ext <= RING_MAX) or cnt > ext * 0.65:
            continue
        # and the line feeding into it is thin
        stem = [int(np.count_nonzero(comp[r]))
                for r in range(max(0, lo - 40), max(1, lo - 8))]
        if stem and np.median(stem) > 14:
            continue
        if best is None or h + ext > best[0]:
            best = (h + ext, x0 + x + cx, y0 + y + ry)
    return None if best is None else (int(best[1]), int(best[2]))


def main() -> int:
    """Preview the detector on a screenshot: `python -m tools.aim_cast <png>`."""
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    args = ap.parse_args()
    for path in args.images:
        img = cv2.imread(path)
        print(f"{path}: {find_reticle(img) if img is not None else 'unreadable'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
