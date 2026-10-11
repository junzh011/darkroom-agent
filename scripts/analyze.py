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
        skin["mean_hue_deg"] = round(float(hsv[..., 0][skin_px].mean()), 1)
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
    if conf > 0.03 and cast["temp"] in ("warm", "cool"):
        flags.append(f"{cast['temp']}_cast")
    if skin["fraction"] > 0.02:
        flags.append("skin_present")
        if skin.get("mean_luma", 1) < 0.25:
            flags.append("skin_dark")
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
