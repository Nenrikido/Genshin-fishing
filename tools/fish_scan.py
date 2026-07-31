#!/usr/bin/env python3
"""Scan the pond for fish and suggest baits (1920x1080).

Fish visible in the water are detected as color anomalies against the smooth
water background and classified into coarse color families, each mapped to
the bait that fish family eats. The result is written as an ini file the
AutoHotkey script reads:

    [scan]
    count=3
    bait1=flashingmaintenancemekbait   ; ranked bait suggestions
    bait2=fruitpaste
    fish1_x=884                        ; fish screen positions, largest first
    fish1_y=441
    fish1_bait=flashingmaintenancemekbait
    ...

Usage:
    python tools/fish_scan.py --out %TEMP%/genshinfishing/scan_result.ini
    python tools/fish_scan.py --image screenshots/fishing_ui.png --debug dbg.png

Without --image the primary screen is grabbed (the game must run 1920x1080).
Species can not truly be identified from above the water without a trained
model (see IrisRainbowNeko/genshin_auto_fish for the YOLOX approach); this
uses color heuristics, so ambiguous colors map to the most common family.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

# Screen region that can contain water (HUD margins excluded).
WATER_REGION = (60, 100, 1860, 920)
# Regions that always produce false blobs: player character (bottom center)
# and the minimap (top left).
EXCLUDE_BOXES = [(860, 440, 1060, 920), (0, 0, 310, 300)]

MIN_AREA = 120
MAX_AREA = 12000
MIN_FILL = 0.25            # blob area / bbox area; rejects thin diagonals (rod)
DIFF_THRESHOLD = 26
MOTION_THRESHOLD = 16      # frame-to-frame difference that counts as movement
MOTION_FRAMES = 3
MOTION_INTERVAL = 0.6      # seconds between captured frames
MAX_FISH = 5
MIN_FAMILY_PIXELS = 60     # blob must contain at least this many family pixels
MIN_FAMILY_FRAC = 0.12

# Coarse color family -> bait. OpenCV hue is 0..179. These are heuristics:
# gold/metallic = maintenance meks, pale = medaka family, red = betta family,
# blue = heartfeather bass family, purple = angelfish/shirakodai family,
# orange = koi family.
COLOR_RULES = [
    # (name, bait, h_lo, h_hi, s_lo, s_hi, v_lo, v_hi)
    # meks are strongly saturated gold; koi are the same hue but washed out
    ("gold",   "flashingmaintenancemekbait", 12, 30, 110, 256, 110, 256),
    ("koi",    "fakefly",                    10, 30,  40, 110, 120, 256),
    ("redkoi", "fakefly",                   150, 180,  35, 110, 120, 256),
    ("redkoi2", "fakefly",                    0, 10,  35, 110, 120, 256),
    ("red",    "redrot",                      0, 10, 110, 256,  80, 256),
    ("red2",   "redrot",                    168, 180, 110, 256,  80, 256),
    ("blue",   "sourbait",                   95, 125, 120, 256, 100, 256),
    ("purple", "falseworm",                 126, 150,  80, 256,  70, 256),
    ("pale",   "fruitpaste",                  0, 180,   0,  55, 150, 256),
]


def classify(hsv_pixels: np.ndarray) -> tuple[str, str] | None:
    """Pick the color family by counting matching pixels inside the blob.

    Using the blob mean does not work: fish blobs include surrounding water,
    which drags the mean toward green. Counting per-rule pixels keeps the
    dominant fish color. 'pale' only wins when no saturated family qualifies,
    since specular highlights on anything are white."""
    h, s, v = hsv_pixels[:, 0], hsv_pixels[:, 1], hsv_pixels[:, 2]
    counts = {}
    for name, bait, h0, h1, s0, s1, v0, v1 in COLOR_RULES:
        m = (h >= h0) & (h < h1) & (s >= s0) & (s < s1) & (v >= v0) & (v < v1)
        n = int(m.sum())
        if n >= MIN_FAMILY_PIXELS and n >= MIN_FAMILY_FRAC * len(hsv_pixels):
            counts[(name, bait)] = n
    saturated = {k: n for k, n in counts.items() if k[0] != "pale"}
    if saturated:
        return max(saturated, key=saturated.get)
    if counts:
        return next(iter(counts))
    return None


def grab_screen() -> np.ndarray:
    from PIL import ImageGrab

    im = ImageGrab.grab()
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def grab_motion_frames() -> tuple[np.ndarray, np.ndarray | None]:
    """Capture several frames; returns (last frame, motion mask).

    Fish swim while stones, plants, the rod and UI stay still, so the motion
    mask is what separates fish from everything the single-frame anomaly
    detector cannot reject."""
    import time

    frames = []
    for i in range(MOTION_FRAMES):
        if i:
            time.sleep(MOTION_INTERVAL)
        frames.append(grab_screen())
    motion = np.zeros(frames[0].shape[:2], np.uint8)
    for a, b in zip(frames, frames[1:]):
        d = cv2.absdiff(a, b).max(axis=2)
        motion |= (d > MOTION_THRESHOLD).astype(np.uint8) * 255
    motion = cv2.dilate(motion, np.ones((9, 9), np.uint8))
    return frames[-1], motion


def detect_fish(image: np.ndarray, motion: np.ndarray | None = None,
                debug_path: str | None = None):
    # smooth water estimate; fish/ripples are local deviations from it
    background = cv2.medianBlur(image, 51)
    diff = cv2.absdiff(image, background).max(axis=2)

    mask = (diff > DIFF_THRESHOLD).astype(np.uint8) * 255
    if motion is not None:
        mask &= motion
    x0, y0, x1, y1 = WATER_REGION
    border = np.zeros_like(mask)
    border[y0:y1, x0:x1] = 255
    mask &= border
    for ex0, ey0, ex1, ey1 in EXCLUDE_BOXES:
        mask[ey0:ey1, ex0:ex1] = 0

    # opening removes thin structures (ripple rings, the rod line)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    fishes = []
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        area = cv2.contourArea(c)
        bx, by, bw, bh = cv2.boundingRect(c)
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        if area < MIN_FILL * bw * bh:
            continue
        blob = np.zeros((bh, bw), np.uint8)
        cv2.drawContours(blob, [c - [bx, by]], -1, 255, -1)
        pixels = hsv[by:by + bh, bx:bx + bw][blob > 0]
        family = classify(pixels)
        fishes.append({
            "x": bx + bw // 2, "y": by + bh // 2, "area": int(area),
            "family": family[0] if family else "unknown",
            "bait": family[1] if family else "",
        })

    # classified fish first, biggest first
    fishes.sort(key=lambda f: (f["bait"] == "", -f["area"]))
    fishes = fishes[:MAX_FISH * 3]

    if debug_path:
        dbg = image.copy()
        cv2.rectangle(dbg, (x0, y0), (x1, y1), (80, 80, 80), 1)
        for ex0, ey0, ex1, ey1 in EXCLUDE_BOXES:
            cv2.rectangle(dbg, (ex0, ey0), (ex1, ey1), (0, 0, 128), 1)
        for f in fishes:
            color = (0, 255, 0) if f["bait"] else (0, 165, 255)
            cv2.circle(dbg, (f["x"], f["y"]), 18, color, 2)
            cv2.putText(dbg, f'{f["family"]} {f["area"]}', (f["x"] - 30, f["y"] - 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cv2.imwrite(debug_path, dbg)
    return fishes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="analyze this file instead of the screen")
    ap.add_argument("--out", help="write the scan result ini here")
    ap.add_argument("--debug", help="write an annotated debug image here")
    args = ap.parse_args()

    if args.image:
        image, motion = cv2.imread(args.image), None
        if image is None:
            raise SystemExit(f"cannot read image: {args.image}")
        print("NOTE: single image mode has no motion mask; static objects "
              "(stones, plants) can appear as false fish. Live capture uses "
              "motion and does not have this problem.")
    else:
        image, motion = grab_motion_frames()
    if image.shape[:2] != (1080, 1920):
        raise SystemExit(f"expected 1920x1080, got {image.shape[1]}x{image.shape[0]}")

    fishes = detect_fish(image, motion, args.debug)
    known = [f for f in fishes if f["bait"]][:MAX_FISH]
    bait_ranking = [b for b, _ in Counter(f["bait"] for f in known).most_common(3)]

    for f in fishes:
        print(f'{f["family"]:8s} bait={f["bait"] or "-":26s} at {f["x"]},{f["y"]} '
              f'area={f["area"]}')
    print("bait ranking:", bait_ranking)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[scan]", f"count={len(known)}"]
        for i, b in enumerate(bait_ranking, 1):
            lines.append(f"bait{i}={b}")
        for i, f in enumerate(known, 1):
            lines.append(f"fish{i}_x={f['x']}")
            lines.append(f"fish{i}_y={f['y']}")
            lines.append(f"fish{i}_bait={f['bait']}")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("wrote", out)


if __name__ == "__main__":
    main()
