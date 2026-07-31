#!/usr/bin/env python3
"""Generate 1920x1080 bait-menu templates for the auto bait selection feature.

The in-game "Select Bait" dialog renders each bait as a ~123x123 card in a
horizontally centered grid (step ~139px). The game8 reference icons in
assets/references/bait/ contain the exact same card art, so scaling them
to the in-game size yields templates that AutoHotkey's ImageSearch can match.

For each bait two templates are produced in assets/19201080/:
  - bait_<name>.png      unselected card (icon rendered at ~112px)
  - bait_<name>_sel.png  selected card (icon rendered at ~126px, has a glow)

Pixels that are unreliable to match (anti-aliased edges, glow-adjacent areas)
are painted fuchsia (#FF00FF) so ImageSearch's *TransFuchsia option ignores
them. Both templates are 84x84 and share the same click-center offset (+42).

Additionally menu_confirm.png / menu_cancel.png are cropped from
screenshots/bait_menu_opened.png so the script can verify the dialog is open
and locate the buttons.

Everything is validated against the screenshot (which shows sugardew selected,
sourbait and flashingmaintenancemekbait unselected) by simulating ImageSearch:
per-pixel max-channel difference over unmasked pixels must stay within the
variation for the true card and exceed it everywhere else.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT = ROOT / "screenshots" / "bait_menu_opened.png"
FISHING_UI = ROOT / "screenshots" / "fishing_ui.png"
REF_BAIT_DIR = ROOT / "assets" / "references" / "bait"
OUT_DIR = ROOT / "assets" / "19201080"
REPORT_PATH = ROOT / "assets" / "references" / "menu_match_report.json"

TEMPLATE_SIZE = 84          # final template edge; click center = +42,+42
# The exact in-game icon scale is fractional, so ship a few nearby scales and
# let the script try them in order ("" first, then _b, _c).
NORMAL_ICON_SIZES = {"": 111, "_b": 110, "_c": 113}   # unselected card
SELECTED_ICON_SIZE = 126    # icon size on the selected (zoomed) card
EDGE_MASK_THRESHOLD = 56    # local contrast above this gets fuchsia-masked
VARIATION = 48              # target ImageSearch *variation
FUCHSIA = (255, 0, 255)

# Dialog interior at 1920x1080 (excludes the Cancel/Confirm button row).
DIALOG = (460, 300, 1460, 720)

# Ground truth in the screenshot: card top-left boxes and selection state.
KNOWN_CARDS = {
    "sugardew": ((759, 440, 123, 123), True),
    "sourbait": ((898, 440, 124, 123), False),
    "flashingmaintenancemekbait": ((1037, 440, 124, 123), False),
}

# Button text crops (x0, y0, x1, y1) picked to avoid the input-glyph icons.
CONFIRM_BOX = (1100, 740, 1260, 776)
CANCEL_BOX = (700, 740, 850, 776)

# Fishing-mode HUD buttons (bottom right, from fishing_ui.png): the rod (cast,
# LMB) and bait (open menu, RMB) icons. They sit on a semi-transparent circle
# over the 3D world, so only the solid white glyph pixels are kept; the rest
# is fuchsia-masked to be scene independent.
HUD_BUTTONS = {
    "btn_rod": (1585, 955, 1645, 1015),
    "btn_bait": (1680, 955, 1740, 1015),
}
GLYPH_BRIGHTNESS = 175      # pixels darker than this are masked out


def build_template(ref_bgr: np.ndarray, icon_size: int) -> np.ndarray:
    scaled = cv2.resize(ref_bgr, (icon_size, icon_size), interpolation=cv2.INTER_CUBIC)
    margin = (icon_size - TEMPLATE_SIZE) // 2
    crop = scaled[margin:margin + TEMPLATE_SIZE, margin:margin + TEMPLATE_SIZE].copy()

    # Mask pixels whose 3x3 neighborhood has high contrast: sub-pixel scaling
    # differences between our resize and the game's renderer concentrate there.
    kernel = np.ones((3, 3), np.uint8)
    local_max = cv2.dilate(crop, kernel)
    local_min = cv2.erode(crop, kernel)
    contrast = (local_max.astype(int) - local_min.astype(int)).max(axis=2)
    crop[contrast > EDGE_MASK_THRESHOLD] = FUCHSIA
    return crop


def masked_diff(image: np.ndarray, template: np.ndarray, x: int, y: int) -> int:
    h, w = template.shape[:2]
    live = image[y:y + h, x:x + w].astype(int)
    tpl = template.astype(int)
    mask = ~np.all(template == FUCHSIA, axis=2)
    if not mask.any():
        return 255
    return int(np.abs(live - tpl).max(axis=2)[mask].max())


def best_match(image: np.ndarray, template: np.ndarray, box: tuple[int, int, int, int]):
    """Exhaustive masked search (like ImageSearch) via SQDIFF shortlist."""
    x0, y0, x1, y1 = box
    region = image[y0:y1, x0:x1]
    mask = (~np.all(template == FUCHSIA, axis=2)).astype(np.uint8) * 255
    res = cv2.matchTemplate(region, template, cv2.TM_SQDIFF, mask=np.dstack([mask] * 3))
    res = np.nan_to_num(res, nan=np.inf, posinf=np.inf)
    best = (255, -1, -1)
    flat = np.argsort(res, axis=None)[:400]
    for idx in flat:
        py, px = np.unravel_index(idx, res.shape)
        d = masked_diff(image, template, x0 + px, y0 + py)
        if d < best[0]:
            best = (d, int(x0 + px), int(y0 + py))
    return best


def main() -> None:
    if not SCREENSHOT.exists():
        raise FileNotFoundError(f"Missing screenshot: {SCREENSHOT}")
    image = cv2.imread(str(SCREENSHOT), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Unable to read image: {SCREENSHOT}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    report = {"variation": VARIATION, "templates": [], "validation": []}

    for icon_path in sorted(REF_BAIT_DIR.glob("*.png")):
        bait = icon_path.stem
        ref = cv2.imread(str(icon_path), cv2.IMREAD_UNCHANGED)
        if ref is None:
            continue
        ref_bgr = ref[:, :, :3]

        all_sizes = dict(NORMAL_ICON_SIZES)
        all_sizes["_sel"] = SELECTED_ICON_SIZE
        for suffix, icon_size in all_sizes.items():
            tpl = build_template(ref_bgr, icon_size)
            masked = float(np.all(tpl == FUCHSIA, axis=2).mean())
            out = OUT_DIR / f"bait_{bait}{suffix}.png"
            cv2.imwrite(str(out), tpl)
            report["templates"].append({
                "bait": bait, "kind": "selected" if suffix else "normal",
                "file": out.name, "masked_frac": round(masked, 3),
            })

    # Confirm / Cancel button templates come straight from the screenshot.
    for name, (x0, y0, x1, y1) in (("menu_confirm", CONFIRM_BOX), ("menu_cancel", CANCEL_BOX)):
        cv2.imwrite(str(OUT_DIR / f"{name}.png"), image[y0:y1, x0:x1])
        report["templates"].append({
            "bait": None, "kind": name, "file": f"{name}.png",
            "size": [x1 - x0, y1 - y0],
        })

    # Fishing-mode HUD button templates from fishing_ui.png, glyph-only.
    fishing_ui = cv2.imread(str(FISHING_UI), cv2.IMREAD_COLOR)
    if fishing_ui is None:
        raise RuntimeError(f"Unable to read image: {FISHING_UI}")
    for name, (x0, y0, x1, y1) in HUD_BUTTONS.items():
        crop = fishing_ui[y0:y1, x0:x1].copy()
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        glyph = (gray >= GLYPH_BRIGHTNESS).astype(np.uint8)
        # drop anti-aliased glyph borders, which blend with the background
        glyph = cv2.erode(glyph, np.ones((3, 3), np.uint8))
        crop[glyph == 0] = FUCHSIA
        kept = float(glyph.mean())
        cv2.imwrite(str(OUT_DIR / f"{name}.png"), crop)
        report["templates"].append({
            "bait": None, "kind": name, "file": f"{name}.png",
            "glyph_frac": round(kept, 3),
        })
        d, fx, fy = best_match(fishing_ui, crop, (1500, 930, 1919, 1079))
        good = d <= VARIATION and abs(fx - x0) <= 3 and abs(fy - y0) <= 3
        ok_hud = good
        report["validation"].append({
            "template": f"{name}.png", "min_diff": d, "found_at": [fx, fy],
            "expected_match": True, "matched": d <= VARIATION,
        })
        print(f"{'OK ' if good else 'BAD'} {name}.png min_diff={d} at {fx},{fy} glyph_frac={kept:.2f}")
        if not good:
            raise SystemExit(f"HUD button template validation failed: {name}")

    # Validation: every template searched over the dialog area. For baits
    # visible in the screenshot at least one scale variant must hit inside the
    # right card; any hit anywhere else (or for absent baits) is a failure.
    ok = True
    for icon_path in sorted(REF_BAIT_DIR.glob("*.png")):
        bait = icon_path.stem
        expected = KNOWN_CARDS.get(bait)
        for kind, suffixes in (("normal", list(NORMAL_ICON_SIZES)), ("selected", ["_sel"])):
            should_match = expected is not None and expected[1] == (kind == "selected")
            any_correct_hit = False
            wrong_hit = False
            for suffix in suffixes:
                tpl = cv2.imread(str(OUT_DIR / f"bait_{bait}{suffix}.png"))
                d, fx, fy = best_match(image, tpl, DIALOG)
                hit = d <= VARIATION
                inside = False
                if hit and expected is not None:
                    (cx, cy, cw, chh), _ = expected
                    inside = cx <= fx + 42 <= cx + cw and cy <= fy + 42 <= cy + chh
                any_correct_hit |= hit and inside and should_match
                wrong_hit |= hit and not (inside and should_match)
                report["validation"].append({
                    "template": f"bait_{bait}{suffix}.png", "min_diff": d,
                    "found_at": [fx, fy], "expected_match": should_match, "matched": hit,
                })
                print(f"    bait_{bait}{suffix}.png min_diff={d} at {fx},{fy}")
            good = (any_correct_hit if should_match else True) and not wrong_hit
            ok &= good
            print(f"{'OK ' if good else 'BAD'} {bait} [{kind}] expect_match={should_match}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report:", REPORT_PATH)
    if not ok:
        raise SystemExit("Validation failed - see report")
    print("All validations passed.")


if __name__ == "__main__":
    main()
