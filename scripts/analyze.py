#!/usr/bin/env python3
"""Measure a photo and print a JSON diagnosis the agent can reason about.

Usage: python analyze.py PHOTO [--max-size N]
These are measurements and hints, not decisions: always look at the photo too.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import blur, luma, resize_rgb_float, rgb_to_hsv, skin_mask, srgb_to_linear  # noqa: E402
from ingest import LoadError, load  # noqa: E402


def _largest_blob(grid: np.ndarray):
    """Largest 4-connected component of a boolean block grid -> ((y0, x0, y1, x1), cell_count) or None."""
    gh, gw = grid.shape
    seen = np.zeros_like(grid, dtype=bool)
    best = None
    for sy in range(gh):
        for sx in range(gw):
            if not grid[sy, sx] or seen[sy, sx]:
                continue
            stack, cells = [(sy, sx)], []
            seen[sy, sx] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < gh and 0 <= nx < gw and grid[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if best is None or len(cells) > best[1]:
                ys, xs = [c[0] for c in cells], [c[1] for c in cells]
                best = ((min(ys), min(xs), max(ys) + 1, max(xs) + 1), len(cells))
    return best


def regions(L: np.ndarray, skin: np.ndarray) -> dict:
    """Bounding boxes (fractions of width/height, displayed frame) of the brightest blob, the largest skin blob and the
    darkest area, as starting points for mask placement: use `center` as the mask centre and about half the larger
    `size` as the radius."""
    h, w = L.shape
    bs = max(8, min(h, w) // 40)
    gh, gw = h // bs, w // bs
    Lb = L[:gh * bs, :gw * bs].reshape(gh, bs, gw, bs).mean(axis=(1, 3))
    Sb = skin[:gh * bs, :gw * bs].reshape(gh, bs, gw, bs).mean(axis=(1, 3))

    def pack(b):
        if not b:
            return None
        (y0, x0, y1, x1), n = b
        return {"bbox": [round(x0 * bs / w, 3), round(y0 * bs / h, 3), round(x1 * bs / w, 3), round(y1 * bs / h, 3)],
                "center": [round((x0 + x1) * bs / 2 / w, 3), round((y0 + y1) * bs / 2 / h, 3)],
                "size": [round((x1 - x0) * bs / w, 3), round((y1 - y0) * bs / h, 3)], "frac": round(n / (gh * gw), 4)}

    return {
        "brightest": pack(_largest_blob(Lb >= max(0.6, float(np.percentile(Lb, 97))))),
        "skin": pack(_largest_blob(Sb > 0.5)) if bool((Sb > 0.5).any()) else None,
        "darkest": pack(_largest_blob(Lb <= float(np.percentile(Lb, 10)))),
        "note": "fractions of width/height in the displayed frame; mask centre = center, radius ≈ half the larger size",
    }


def analyze_array(rgb: np.ndarray, meta: dict) -> dict:
    h, w = rgb.shape[:2]
    s = 1024 / max(h, w)
    small = resize_rgb_float(rgb, (round(w * s), round(h * s))) if s < 1 else rgb
    L = luma(small)
    p = {k: float(np.percentile(L, q)) for k, q in
         (("p1", 1), ("p5", 5), ("p25", 25), ("p50", 50), ("p75", 75), ("p95", 95), ("p99", 99))}

    clip_hi = float((small.max(-1) >= 0.985).mean())
    clip_lo = float((L <= 0.02).mean())
    hsv = rgb_to_hsv(small)

    # white-balance cast from near-neutral midtones (gray-world on a safe subset)
    neutral = (hsv[..., 1] < 0.18) & (hsv[..., 2] > 0.15) & (hsv[..., 2] < 0.85)
    conf = float(neutral.mean())
    cast = {"confidence": round(conf, 3), "temp": "unknown", "tint": "unknown"}
    if neutral.sum() > 200:
        lin = srgb_to_linear(small[neutral]).mean(0)
        r, g, b = (max(float(x), 1e-6) for x in lin)
        temp = float(np.log2(r / b))
        tint = float(np.log2(g / ((r + b) / 2)))
        cast.update(
            temp_stops=round(temp, 3), tint_stops=round(tint, 3),
            temp="warm" if temp > 0.15 else "cool" if temp < -0.15 else "neutral",
            tint="green" if tint > 0.08 else "magenta" if tint < -0.08 else "neutral",
        )

    # skin
    sm = skin_mask(small)
    skin_px = sm > 0.5
    skin = {"fraction": round(float(skin_px.mean()), 4)}
    if skin_px.sum() > 100:
        skin["mean_luma"] = round(float(L[skin_px].mean()), 3)
        hr = np.deg2rad(hsv[..., 0][skin_px])  # circular mean: skin straddles the 0/360 red boundary
        skin["mean_hue_deg"] = round(float(np.rad2deg(np.arctan2(np.sin(hr).mean(), np.cos(hr).mean())) % 360), 1)
        skin["mean_sat"] = round(float(hsv[..., 1][skin_px].mean()), 3)

    # noise: robust estimate from the Laplacian of a full-res centre crop
    ch, cw = min(512, h), min(512, w)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    crop = luma(rgb[y0:y0 + ch, x0:x0 + cw])
    lap = (-4 * crop[1:-1, 1:-1] + crop[:-2, 1:-1] + crop[2:, 1:-1] + crop[1:-1, :-2] + crop[1:-1, 2:])
    noise = float(1.4826 * np.median(np.abs(lap - np.median(lap))) / np.sqrt(20))
    detail = float(blur(crop, 1.0).std())

    spread = p["p99"] - p["p1"]
    key = "low-key" if p["p50"] < 0.25 else "high-key" if p["p50"] > 0.6 else "mid-key"

    flags = []
    if p["p50"] < 0.18 and p["p99"] < 0.8:
        flags.append("underexposed")
    if p["p50"] > 0.65 or clip_hi > 0.05:
        flags.append("overexposed")
    if clip_hi > 0.02:
        flags.append("highlights_clipped")
    if clip_lo > 0.15:
        flags.append("shadows_already_crushed")
    if spread < 0.6:
        flags.append("low_contrast_flat")
    if conf > 0.05 and cast["temp"] in ("warm", "cool"):  # same threshold the guide uses for acting on it
        flags.append(f"{cast['temp']}_cast")
    if skin["fraction"] > 0.02:
        flags.append("skin_present")
        if skin.get("mean_luma", 1) < 0.25:
            flags.append("skin_dark")
        if skin["fraction"] > 0.25:
            flags.append("skin_mask_unreliable")  # warm stone/wood/sepia toning reads as skin; trust your eyes instead
    if noise > 0.02:
        flags.append("noisy")
    if meta.get("source_class") == "unknown":
        flags.append("no_exif_maybe_recompressed")

    return {
        "meta": meta,
        "tone": {**{k: round(v, 3) for k, v in p.items()}, "spread_p99_p1": round(spread, 3), "key": key,
                 "clipped_highlights_frac": round(clip_hi, 4), "crushed_shadows_frac": round(clip_lo, 4)},
        "colour": {"mean_saturation": round(float(hsv[..., 1][hsv[..., 2] > 0.1].mean()), 3), "cast": cast},
        "skin": skin,
        "quality": {"noise_sigma": round(noise, 4), "detail": round(detail, 4)},
        "regions": regions(L, sm),
        "flags": flags,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--max-size", type=int, default=2048)
    a = ap.parse_args()
    try:
        img = load(a.photo, a.max_size)
    except LoadError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(analyze_array(img.rgb, img.meta), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
