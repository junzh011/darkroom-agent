#!/usr/bin/env python3
"""List exactly what darkroom-agent changed in a delivered photo, from the recipe embedded in its metadata.

Usage: python3 explain.py PHOTO_graded.jpg            plain-language, value-by-value list
       python3 explain.py PHOTO_graded.jpg --json     the raw recipe
       python3 explain.py PHOTO_graded.jpg --params out.json   write the params back out to re-render or tweak
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grade import read_recipe  # noqa: E402

HSL_BANDS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"]


def pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def sign(v: float, unit: str = "") -> str:
    return f"{v:+.2f}{unit}"


def gloss_global(params: dict, auto_ev) -> list[str]:
    out = []
    g = params.get
    if auto_ev not in (None, 0, 0.0):
        out.append(f"Auto exposure: {sign(auto_ev, ' stops')} to bring the mid-tones to this scene's target")
    if g("exposure_ev"):
        out.append(f"Exposure: {sign(g('exposure_ev'), ' stops')} overall (everything, highlights included)")
    if g("brightness"):
        v = g("brightness")
        out.append(f"Brightness: {sign(v)}: mid-tones {'pulled down' if v < 0 else 'lifted'}, blacks and whites held in place")
    if g("contrast"):
        out.append(f"Contrast: {sign(g('contrast'))} (S-curve around {g('contrast_pivot', 0.5)})")
    for k, up, down in (("highlights", "bright areas brightened", "bright areas pulled down"),
                        ("shadows", "dark areas opened up", "dark areas deepened"),
                        ("whites", "white point raised", "whites compressed"),
                        ("blacks", "deepest tones opened", "black point crushed")):
        if g(k):
            out.append(f"{k.capitalize()}: {sign(g(k))}: {up if g(k) > 0 else down}")
    wb = g("wb") or {}
    if wb.get("temp"):
        out.append(f"White balance: {sign(wb['temp'])} temperature ({'warmer' if wb['temp'] > 0 else 'cooler'})")
    if wb.get("tint"):
        out.append(f"Tint: {sign(wb['tint'])} ({'toward magenta' if wb['tint'] > 0 else 'toward green'})")
    if g("saturation"):
        out.append(f"Saturation: {sign(g('saturation'))} on all colours")
    if g("vibrance"):
        out.append(f"Vibrance: {sign(g('vibrance'))} (weak colours affected most, skin spared)")
    for band, d in (g("hsl") or {}).items():
        parts = [f"{k} {sign(v)}" for k, v in d.items() if v]
        if parts:
            out.append(f"Colour range '{band}': " + ", ".join(parts))
    cg = g("color_grade") or {}
    for region in ("shadows", "midtones", "highlights"):
        r = cg.get(region)
        if r and r.get("sat"):
            out.append(f"Colour toning in {region}: hue {r.get('hue', 0):.0f}°, strength {r['sat']:.2f}")
    if g("fade"):
        out.append(f"Fade: {g('fade'):.3f} (matte lift of the blacks)")
    for k, label in (("clarity", "Clarity (mid-tone local contrast)"), ("sharpen", "Sharpening")):
        if g(k):
            out.append(f"{label}: {sign(g(k))}")
    if g("curves"):
        out.append("Tone curves: " + ", ".join(f"{ch} {pts}" for ch, pts in g("curves").items()))
    if g("lut"):
        out.append(f"LUT: {g('lut').get('path')} at {g('lut').get('strength', 1.0)}")
    for k in ("halation", "vignette", "grain"):
        d = g(k) or {}
        if d.get("amount"):
            out.append(f"{k.capitalize()}: {d}")
    if g("skin_protect") is not None:
        out.append(f"Skin protection: {g('skin_protect')} (hue of detected skin held near the original)")
    return out


def where(m: dict) -> str:
    t = m.get("type")
    if t == "radial":
        cx, cy = m.get("center", [0.5, 0.5])
        s = f"radial centred {pct(cx)} across, {pct(cy)} down, radius {pct(m.get('radius', 0.3))} of the long edge"
        if m.get("aspect") not in (None, 1, 1.0):
            s += f", aspect {m['aspect']}"
        s += f", feather {m.get('feather', 0.5)}"
    elif t == "linear":
        (ax, ay), (bx, by) = m.get("from", [0.5, 0]), m.get("to", [0.5, 0.5])
        s = f"gradient from ({pct(ax)}, {pct(ay)}) fading out by ({pct(bx)}, {pct(by)})"
    elif t == "luminosity":
        s = f"brightness range {m.get('lo', 0)}–{m.get('hi', 1)}"
    elif t == "color":
        s = f"colours near hue {m.get('hue', 0)}° (±{m.get('width', 30)}°)"
    elif t == "image":
        s = f"mask image {os.path.basename(m.get('path', ''))}"
    else:
        s = str(t)
    if m.get("invert"):
        s += ", inverted (everything outside it)"
    if m.get("refine"):
        s += ", snapped to picture edges"
    if m.get("opacity") not in (None, 1, 1.0):
        s += f", opacity {m['opacity']}"
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo")
    ap.add_argument("--json", action="store_true", help="print the raw embedded recipe")
    ap.add_argument("--params", metavar="FILE", help="write the params (with masks) to FILE for re-rendering or tweaking")
    a = ap.parse_args()
    r = read_recipe(a.photo)
    if r is None:
        print(f"No darkroom-agent recipe found in {os.path.basename(a.photo)} (not a delivered file, or metadata was stripped).")
        return 1
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    if a.params:
        with open(a.params, "w") as f:
            json.dump({**r.get("params", {}), "masks": r.get("masks", [])}, f, indent=2)
        print(f"params written to {a.params}")
    print(f"{os.path.basename(a.photo)}: edited by darkroom-agent {r.get('version', '')} on {r.get('created', '?')} "
          f"from {r.get('source', '?')} ({r.get('source_class', '?')}), look {r.get('look')}, scene {r.get('scene') or 'base'}")
    b, af = r.get("before", {}), r.get("after", {})
    if b and af:
        print(f"  Tone: mid-tones {b.get('p50')} → {af.get('p50')}, brightest 1% {b.get('p99')} → {af.get('p99')}, "
              f"clipped highlights {b.get('clipped_highlights_frac')} → {af.get('clipped_highlights_frac')}")
    if r.get("input_size") and r.get("size") and r["input_size"] != r["size"]:
        print(f"  Size: {r['input_size'][0]}×{r['input_size'][1]} → {r['size'][0]}×{r['size'][1]}")
    print("Global adjustments:")
    lines = gloss_global(r.get("params", {}), r.get("auto_exposure_ev"))
    print("\n".join(f"  - {ln}" for ln in lines) if lines else "  - none")
    masks = r.get("masks") or []
    print(f"Local edits ({len(masks)} mask{'s' if len(masks) != 1 else ''}):" if masks else "Local edits: none")
    info = {m.get("index"): m for m in (r.get("mask_info") or [])}
    for i, m in enumerate(masks):
        adj = ", ".join(f"{k} {sign(v) if isinstance(v, (int, float)) else v}" for k, v in (m.get("adjust") or {}).items())
        cov = info.get(i, {}).get("coverage")
        print(f"  {i + 1}. {m.get('name') or m.get('type')}: {where(m)}" + (f", covering {pct(cov)} of the frame" if cov is not None else ""))
        print(f"     → {adj or 'no adjustments'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
