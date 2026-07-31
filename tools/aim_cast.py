#!/usr/bin/env python3
"""Closed-loop cast aiming for the fishing script (1920x1080).

While the AutoHotkey script HOLDS the left mouse button (aim mode), this tool
repeatedly: grabs the screen, locates the white elliptical landing reticle on
the water, and injects relative mouse movement to steer it toward the target
fish position, stopping `--offset` px short (landing on the fish scares it).
The AutoHotkey script releases the button afterwards to cast.

The mouse-to-reticle gain is measured on the first iteration (a small probe
move), so no manual gain calibration is needed. Exit code 0 = aligned,
2 = reticle never found (not in aim mode?), 3 = timeout without alignment.

The reticle detector was validated on frames of the project's demo video
(https://www.youtube.com/watch?v=3lvCEh7quxE): a ring of bright, slightly
blue-tinted pixels forming a wide ellipse (~44..100 px wide depending on
distance), detected by convolving the bright-pixel mask with ellipse-ring
kernels and requiring near-complete angular coverage with a hollow interior
(rejects text, the rod line, sparkles and the player character).
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time

import cv2
import numpy as np

REGION = (600, 150, 1650, 860)       # search window (excludes HUD margins)
PLAYER_BOX = (860, 440, 1060, 920)   # the player character, always excluded
ALIGN_TOLERANCE = 26                 # px error considered "aimed"
PROBE_MOVE = (60, 30)                # first move used to measure the gain
MAX_STEP = 220                       # max injected movement per iteration


def send_relative(dx: int, dy: int) -> None:
    """Inject a relative mouse move (MOUSEEVENTF_MOVE); the game reads it."""
    if dx == 0 and dy == 0:
        return
    ctypes.windll.user32.mouse_event(0x0001, int(dx), int(dy), 0, 0)


def grab_screen() -> np.ndarray:
    from PIL import ImageGrab

    im = ImageGrab.grab()
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def bright_mask(img: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(img.astype(np.int16))
    mn = np.minimum(np.minimum(b, g), r)
    m = (mn > 150) & (b > 205) & ((b - r) < 105) & (b >= r - 10)
    return m.astype(np.uint8)


def sector_coverage(dil, cx, cy, a, b_ax) -> int:
    hits = 0
    for k in range(16):
        got = 0
        for t in np.linspace(2 * np.pi * k / 16, 2 * np.pi * (k + 1) / 16, 5):
            x = int(round(cx + a * np.cos(t)))
            y = int(round(cy + b_ax * np.sin(t)))
            if 0 <= y < dil.shape[0] and 0 <= x < dil.shape[1] and dil[y, x]:
                got += 1
        if got >= 2:
            hits += 1
    return hits


def interior_fraction(dil, cx, cy, a, b_ax) -> float:
    ia, ib = int(a * 0.55), max(2, int(b_ax * 0.55))
    tot = wh = 0
    for y in range(max(0, cy - ib), min(dil.shape[0], cy + ib + 1)):
        for x in range(max(0, cx - ia), min(dil.shape[1], cx + ia + 1)):
            dx, dy = x - cx, y - cy
            # the cast line drops through the center; ignore that column
            if (dx / ia) ** 2 + (dy / ib) ** 2 <= 1 and abs(dx) > 6:
                tot += 1
                wh += dil[y, x]
    return wh / max(tot, 1)


def find_reticle(img: np.ndarray, region=REGION):
    x0, y0, x1, y1 = region
    m = bright_mask(img)
    px0, py0, px1, py1 = PLAYER_BOX
    m[py0:py1, px0:px1] = 0
    m = m[y0:y1, x0:x1]
    dil = cv2.dilate(m, np.ones((3, 3), np.uint8))
    dilf = dil.astype(np.float32)
    best = None
    for a in (22, 26, 30, 34, 38, 44, 50):
        for ratio in (2.4, 2.9, 3.4):
            b_ax = max(6, a / ratio)
            h, w = int(b_ax * 2 + 5), int(a * 2 + 5)
            ring = np.zeros((h, w), np.float32)
            for t in np.linspace(0, 2 * np.pi, 240, endpoint=False):
                cv2.circle(ring, (int(round(w // 2 + a * np.cos(t))),
                                  int(round(h // 2 + b_ax * np.sin(t)))), 1, 1.0, -1)
            ring /= ring.sum()
            resp = cv2.filter2D(dilf, -1, ring)
            for _ in range(3):
                _, mx, _, pt = cv2.minMaxLoc(resp)
                if mx < 0.55:
                    break
                cx, cy = pt
                cov = max(sector_coverage(dil, cx + jx, cy + jy, a, b_ax)
                          for jx in (-2, 0, 2) for jy in (-1, 0, 1))
                if cov >= 13 and interior_fraction(dil, cx, cy, a, b_ax) < 0.30:
                    score = mx + cov / 32
                    if best is None or score > best[0]:
                        best = (score, x0 + cx, y0 + cy)
                cv2.circle(resp, pt, 30, 0, -1)
    return None if best is None else (best[1], best[2])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fish-x", type=int, required=True)
    ap.add_argument("--fish-y", type=int, required=True)
    ap.add_argument("--offset", type=int, default=110,
                    help="land this many px short of the fish")
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args()

    deadline = time.time() + args.timeout
    gain_x = gain_y = None
    prev = None
    found_once = False

    while time.time() < deadline:
        pos = find_reticle(grab_screen())
        if pos is None:
            if not found_once:
                time.sleep(0.25)
                continue
            time.sleep(0.15)
            continue
        found_once = True

        # target: offset px short of the fish, along reticle->fish direction
        dx_f = args.fish_x - pos[0]
        dy_f = args.fish_y - pos[1]
        dist = max((dx_f * dx_f + dy_f * dy_f) ** 0.5, 1.0)
        cut = min(args.offset, dist) / dist
        err_x = dx_f * (1 - cut)
        err_y = dy_f * (1 - cut)
        print(f"reticle={pos} err=({err_x:.0f},{err_y:.0f})", flush=True)

        if abs(err_x) <= ALIGN_TOLERANCE and abs(err_y) <= ALIGN_TOLERANCE:
            return 0

        if gain_x is None:
            if prev is None:
                prev = pos
                send_relative(*PROBE_MOVE)
                time.sleep(0.20)
                continue
            moved_x, moved_y = pos[0] - prev[0], pos[1] - prev[1]
            gain_x = PROBE_MOVE[0] / moved_x if abs(moved_x) > 4 else 1.0
            gain_y = PROBE_MOVE[1] / moved_y if abs(moved_y) > 4 else gain_x
            gain_x = max(-8, min(8, gain_x))
            gain_y = max(-8, min(8, gain_y))
            print(f"gain=({gain_x:.2f},{gain_y:.2f})", flush=True)

        mx = int(max(-MAX_STEP, min(MAX_STEP, err_x * gain_x * 0.8)))
        my = int(max(-MAX_STEP, min(MAX_STEP, err_y * gain_y * 0.8)))
        send_relative(mx, my)
        time.sleep(0.18)

    return 3 if found_once else 2


if __name__ == "__main__":
    sys.exit(main())
