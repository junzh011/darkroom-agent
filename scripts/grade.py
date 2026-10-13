#!/usr/bin/env python3
"""Colour-grade a photo from a look + parameter overrides.

Examples:
  python grade.py photo.jpg --look dark-larp --preview --compare
  python grade.py photo.heic --look dark-larp --set exposure_ev=0.3 --set color_grade.shadows.hue=200
  python grade.py photo.jpg --params my_params.json --out final.jpg

Parameter reference: see references/grading-guide.md. Every parameter is optional;
omitted ones are neutral. Order of application is fixed (see grade_array).
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import sys

import numpy as np
from PIL import Image, ImageCms

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from common import (blur, hsv_to_rgb, linear_to_srgb, luma, resize2d, rgb_to_hsv,  # noqa: E402
                    skin_mask, smoothstep, srgb_to_linear)
from ingest import LoadError, load  # noqa: E402

VERSION = "0.4"
RECIPE_TAG = 0x9286  # EXIF UserComment, inside the Exif sub-IFD

HSL_BANDS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"]
HSL_CENTERS = np.array([0, 30, 60, 120, 180, 240, 275, 320], dtype=np.float32)

KNOWN_KEYS = {
    "auto_exposure", "exposure_ev", "wb", "highlights", "shadows", "whites", "blacks", "brightness", "contrast",
    "contrast_pivot", "fade", "curves", "hsl", "vibrance", "saturation", "color_grade", "lut",
    "skin_protect", "clarity", "sharpen", "halation", "vignette", "grain", "white_anchor", "masks",
}


# --- param plumbing -----------------------------------------------------------

def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def set_dotted(d: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def load_look(name_or_path: str) -> dict:
    path = name_or_path
    if not os.path.exists(path):
        path = os.path.join(ROOT, "looks", name_or_path if name_or_path.endswith(".json") else name_or_path + ".json")
    if not os.path.exists(path):
        raise SystemExit(f"Look not found: {name_or_path}. Available: {', '.join(list_looks())}")
    with open(path) as f:
        return json.load(f)


def list_looks() -> list[str]:
    d = os.path.join(ROOT, "looks")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_")) if os.path.isdir(d) else []


def source_offsets(source_class: str) -> dict:
    p = os.path.join(ROOT, "looks", "_sources.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f).get(source_class, {}).get("offsets", {})


# --- tone building blocks -----------------------------------------------------

def monotone_lut(points, n=1024) -> tuple[np.ndarray, np.ndarray]:
    """Monotone cubic (Fritsch-Carlson) through control points; returns (xq, yq)."""
    pts = sorted((float(x), float(y)) for x, y in points)
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)
    if len(xs) < 2:
        return np.linspace(0, 1, n), np.linspace(0, 1, n)
    h = np.diff(xs)
    h[h == 0] = 1e-9
    d = np.diff(ys) / h
    m = np.zeros_like(xs)
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2
    for k in range(len(d)):
        if d[k] == 0:
            m[k] = m[k + 1] = 0
        else:
            a, b = m[k] / d[k], m[k + 1] / d[k]
            s = a * a + b * b
            if s > 9:
                t = 3 / np.sqrt(s)
                m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    xq = np.linspace(0, 1, n)
    xc = np.clip(xq, xs[0], xs[-1])
    i = np.clip(np.searchsorted(xs, xc, side="right") - 1, 0, len(xs) - 2)
    t = (xc - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    y = ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i]
         + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])
    return xq, np.clip(y, 0, 1)


def apply_curve(x: np.ndarray, points) -> np.ndarray:
    xq, yq = monotone_lut(points)
    return np.interp(x, xq, yq).astype(np.float32)


def sigmoid_contrast(x: np.ndarray, c: float, pivot: float) -> np.ndarray:
    if c == 0:
        return x
    if c < 0:  # flatten toward the pivot
        return x + (pivot + (x - pivot) * 0.5 - x) * min(1.0, -c)
    g = 6.0
    s = lambda v: 1.0 / (1.0 + np.exp(-g * (v - pivot)))  # noqa: E731
    f = (s(x) - s(0.0)) / (s(1.0) - s(0.0))
    return x + (f - x) * min(1.0, c)


def lut_from_cube(path: str):
    size, data = None, []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("TITLE"):
                continue
            if line.startswith("LUT_3D_SIZE"):
                size = int(line.split()[1])
            elif line.startswith("LUT_1D_SIZE"):
                raise SystemExit("1D .cube LUTs are not supported yet; use a 3D LUT.")
            elif line.startswith("DOMAIN"):
                continue
            else:
                data.append([float(v) for v in line.split()[:3]])
    if not size or len(data) != size ** 3:
        raise SystemExit(f"Bad .cube file: {path}")
    return np.array(data, dtype=np.float32).reshape(size, size, size, 3)  # [b][g][r]


def apply_lut(rgb: np.ndarray, lut: np.ndarray, strength: float) -> np.ndarray:
    n = lut.shape[0]
    out = np.empty_like(rgb)
    step = 256
    for y in range(0, rgb.shape[0], step):
        blk = np.clip(rgb[y:y + step], 0, 1) * (n - 1)
        i0 = np.floor(blk).astype(np.int32)
        i1 = np.minimum(i0 + 1, n - 1)
        f = blk - i0
        r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
        r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]
        fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
        c00 = lut[b0, g0, r0] * (1 - fr) + lut[b0, g0, r1] * fr
        c01 = lut[b0, g1, r0] * (1 - fr) + lut[b0, g1, r1] * fr
        c10 = lut[b1, g0, r0] * (1 - fr) + lut[b1, g0, r1] * fr
        c11 = lut[b1, g1, r0] * (1 - fr) + lut[b1, g1, r1] * fr
        c0 = c00 * (1 - fg) + c01 * fg
        c1 = c10 * (1 - fg) + c11 * fg
        out[y:y + step] = c0 * (1 - fb) + c1 * fb
    return rgb + (out - rgb) * float(np.clip(strength, 0, 1))


# --- stages -------------------------------------------------------------------

def stage_exposure_wb(rgb, p, report):
    ev = float(p.get("exposure_ev", 0.0))
    ae = p.get("auto_exposure")
    if ae:
        med = float(np.median(luma(rgb[::4, ::4])))
        target = float(ae.get("median", 0.3))
        want = np.log2(max(srgb_to_linear(target), 1e-4) / max(srgb_to_linear(max(med, 1e-3)), 1e-4))
        lim = float(ae.get("max_ev", 1.5))
        auto = float(np.clip(want, -lim, lim)) * float(ae.get("strength", 0.8))
        auto = min(auto, float(ae.get("max_lift", lim)))  # max_lift 0 = darken only, never brighten
        if auto > 0:  # don't let auto-exposure blow out highlights
            p99 = float(np.percentile(luma(rgb[::4, ::4]), 99))
            head = np.log2(1.0 / max(srgb_to_linear(max(p99, 0.05)), 1e-4)) + 0.3
            auto = min(auto, max(head, 0.0))
        report["auto_exposure_ev"] = round(auto, 3)
        report["input_median"] = round(med, 3)
        ev += auto
    lin = srgb_to_linear(rgb) * (2.0 ** ev)
    wb = p.get("wb") or {}
    t, ti = float(wb.get("temp", 0.0)), float(wb.get("tint", 0.0))
    if t or ti:
        gains = np.array([2 ** (0.5 * t), 2 ** (-0.3 * ti), 2 ** (-0.5 * t)], dtype=np.float32)
        gains /= float(gains @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))  # keep luminance
        lin = lin * gains
    return np.clip(linear_to_srgb(lin), 0.0, 1.0)


def stage_tone(x, p):
    h, w = x.shape[:2]
    hi, sh = float(p.get("highlights", 0)), float(p.get("shadows", 0))
    if hi or sh:
        L = luma(x)
        Lb = blur(L, 0.01 * max(h, w))
        if hi:
            x = x + (hi * 0.30 * smoothstep(0.45, 1.0, Lb) * smoothstep(0.3, 1.0, L))[..., None]
        if sh:
            x = x + (sh * 0.30 * (1 - smoothstep(0.0, 0.5, Lb)) * (1 - smoothstep(0.0, 0.7, L)))[..., None]
    bl, wh = float(p.get("blacks", 0)), float(p.get("whites", 0))
    if bl < 0:
        bp = -bl * 0.12
        x = (x - bp) / (1 - bp)
    elif bl > 0:
        x = x + bl * 0.08 * (1 - smoothstep(0.0, 0.35, x))
    if wh > 0:
        x = x / (1 - wh * 0.15)
    elif wh < 0:
        x = x - (-wh) * 0.12 * smoothstep(0.6, 1.0, x)
    x = np.clip(x, 0, 1)
    br = float(p.get("brightness", 0))
    if br:  # midtone power curve: black and white stay put, mids move (negative = darker)
        x = np.power(x, 2.0 ** (-br))
    c = float(p.get("contrast", 0))
    if c:
        x = sigmoid_contrast(x, c, float(p.get("contrast_pivot", 0.5)))
    fade = float(p.get("fade", 0))
    if fade:
        x = fade + x * (1 - fade)
    wa = p.get("white_anchor")
    if wa:  # keep specular peaks bright while mids stay dark: boost scales with x^2
        p99 = float(np.percentile(luma(x[::4, ::4]), 99))
        target, strength = float(wa.get("target", 0.88)), float(wa.get("strength", 0.8))
        if 0.05 < p99 < target:
            p50 = float(np.percentile(luma(x[::4, ::4]), 50))
            a = (target / p99 - 1) / (p99 * p99) * strength
            # never let the anchor brighten the median by more than max_median_lift
            a = min(a, float(wa.get("max_median_lift", 0.10)) / max(p50 * p50, 1e-3))
            x = np.clip(x * (1 + a * x * x), 0, 1)
    curves = p.get("curves") or {}
    if curves:
        if curves.get("master"):
            x = apply_curve(x, curves["master"])
        for i, ch in enumerate("rgb"):
            if curves.get(ch):
                x[..., i] = apply_curve(x[..., i], curves[ch])
    return np.clip(x, 0, 1)


def _band_values(hue, table, key):
    arr = np.array([float((table.get(b) or {}).get(key, 0.0)) for b in HSL_BANDS], dtype=np.float32)
    cs = np.concatenate([HSL_CENTERS, [HSL_CENTERS[0] + 360]])
    hm = hue % 360
    idx = np.clip(np.searchsorted(cs, hm, side="right") - 1, 0, 7)
    t = (hm - cs[idx]) / (cs[idx + 1] - cs[idx])
    return arr[idx] * (1 - t) + arr[(idx + 1) % 8] * t


def stage_colour(x, p):
    hsl = p.get("hsl") or {}
    vib, sat = float(p.get("vibrance", 0)), float(p.get("saturation", 0))
    if hsl or vib or sat:
        hsv = rgb_to_hsv(x)
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        if hsl:
            gate = smoothstep(0.02, 0.15, s)
            h = h + _band_values(h, hsl, "hue") * 30.0 * gate
            s = s * (1 + _band_values(hsv[..., 0], hsl, "sat") * gate)
            v = v * (1 + _band_values(hsv[..., 0], hsl, "lum") * 0.5 * gate)
        if vib:
            skin_hue = 1 - 0.6 * smoothstep(0, 1, 1 - np.abs(((h - 28 + 180) % 360) - 180) / 30.0)
            s = s * (1 + vib * (1 - s) * skin_hue)
        if sat:
            s = s * (1 + sat)
        x = hsv_to_rgb(np.stack([h, np.clip(s, 0, 1), np.clip(v, 0, 1)], axis=-1))

    cg = p.get("color_grade") or {}
    regions = {k: cg[k] for k in ("shadows", "midtones", "highlights") if cg.get(k)}
    if regions:
        L = luma(x)
        bal = float(cg.get("balance", 0.0)) * 0.25
        ws = 1 - smoothstep(0.0 + bal, 0.55 + bal, L)
        wh = smoothstep(0.45 + bal, 1.0 + bal, L)
        wm = np.clip(1 - ws - wh, 0, 1)
        weights = {"shadows": ws, "midtones": wm, "highlights": wh}
        out = x.copy()
        for name, r in regions.items():
            pure = hsv_to_rgb(np.array([[[float(r.get("hue", 0)), 1.0, 1.0]]], dtype=np.float32))[0, 0]
            chroma = pure - float(pure @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))
            w = weights[name][..., None]
            out = out + w * (float(r.get("sat", 0)) * 0.5 * chroma + float(r.get("lum", 0)) * 0.15)
        x = x + (out - x) * float(cg.get("blend", 1.0))
    return np.clip(x, 0, 1)


def stage_skin_protect(orig, x, strength, report=None):
    if strength <= 0:
        return x
    m = skin_mask(orig)
    if float(m.max()) < 0.05:
        return x
    cover = float((m > 0.5).mean())
    if cover > 0.40:  # close-ups can be 30% real skin; beyond ~40% it's warm stone, wood or a sepia grade fooling the detector
        strength *= max(0.0, 1.0 - (cover - 0.40) / 0.30)
        if report is not None:
            report["skin_protect_reduced"] = {"mask_coverage": round(cover, 3), "effective_strength": round(strength, 3)}
        if strength <= 0:
            return x
    h0 = rgb_to_hsv(orig)[..., 0]
    g = rgb_to_hsv(x)
    dh = ((h0 - g[..., 0] + 180) % 360) - 180
    g[..., 0] = g[..., 0] + dh * m * strength
    return np.clip(hsv_to_rgb(g), 0, 1)


def stage_effects(x, p, report):
    h, w = x.shape[:2]
    size = max(h, w)
    clarity, sharpen = float(p.get("clarity", 0)), float(p.get("sharpen", 0))
    if clarity or sharpen:
        L = luma(x)
        if clarity:
            mid = 4 * L * (1 - L)
            x = x + (clarity * 0.6 * (L - blur(L, 0.012 * size)) * mid)[..., None]
        if sharpen:
            L = luma(x)
            x = x + (sharpen * 1.2 * (L - blur(L, max(0.8, 0.0007 * size))))[..., None]
    hal = p.get("halation") or {}
    if hal and float(hal.get("amount", 0)) > 0:
        L = luma(np.clip(x, 0, 1))
        thr = float(hal.get("threshold", 0.7))
        bright = np.clip((L - thr) / max(1e-3, 1 - thr), 0, 1)
        glow = blur(bright, float(hal.get("radius", 0.015)) * size)
        col = np.array(hal.get("color", [1.0, 0.35, 0.15]), dtype=np.float32)
        x = x + (float(hal["amount"]) * glow)[..., None] * col
    vig = p.get("vignette") or {}
    if vig and float(vig.get("amount", 0)) != 0:
        sw, sh_ = max(8, w // 8), max(8, h // 8)
        yy, xx = np.mgrid[0:sh_, 0:sw].astype(np.float32)
        cy, cx = (sh_ - 1) / 2, (sw - 1) / 2
        r = np.sqrt(((yy - cy) / cy) ** 2 + ((xx - cx) / cx) ** 2) / np.sqrt(2)
        mid, feather = float(vig.get("midpoint", 0.5)), max(0.05, float(vig.get("feather", 0.5)))
        m = smoothstep(mid - feather * 0.5, mid + feather * 0.5 + 0.2, r)
        m = resize2d(m, (w, h))
        x = x * (1 + float(vig["amount"]) * m)[..., None]
    gr = p.get("grain") or {}
    if gr and float(gr.get("amount", 0)) > 0:
        rng = np.random.default_rng(int(gr.get("seed", 7)))
        gs = max(1.0, float(gr.get("size", 1.0)) * size / 2500)
        n = rng.standard_normal((max(2, int(h / gs)), max(2, int(w / gs)))).astype(np.float32)
        n = resize2d(n, (w, h)) if gs > 1.01 else n
        L = luma(np.clip(x, 0, 1))
        wgt = 0.35 + 0.65 * 4 * L * (1 - L)  # more grain in mids, less in deep blacks/whites
        x = x + (float(gr["amount"]) * 0.06 * n * wgt)[..., None]
    return np.clip(x, 0, 1)


# --- local edits (masks) --------------------------------------------------------

LOCAL_KEYS = {"exposure_ev", "brightness", "contrast", "contrast_pivot", "highlights", "shadows", "whites", "blacks",
              "saturation", "vibrance", "wb", "clarity", "sharpen"}
LOCAL_LIMITS = {"exposure_ev": 1.0, "brightness": 0.6, "contrast": 0.5, "highlights": 1.0, "shadows": 1.0, "whites": 0.6,
                "blacks": 0.6, "saturation": 0.5, "vibrance": 0.5, "clarity": 0.5, "sharpen": 0.5}
MASK_TINTS = [(1.0, 0.2, 0.2), (0.2, 0.9, 1.0), (1.0, 0.9, 0.2), (0.6, 1.0, 0.3)]


def guided_refine(p, guide, radius, eps=1e-3):
    """Guided filter: snaps a soft mask to the edges of `guide` (luma) so a lift follows a face, not a circle."""
    mean_i, mean_p = blur(guide, radius), blur(p, radius)
    var_i = blur(guide * guide, radius) - mean_i * mean_i
    cov_ip = blur(guide * p, radius) - mean_i * mean_p
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    return np.clip(blur(a, radius) * guide + blur(b, radius), 0.0, 1.0).astype(np.float32)


def mask_weight(spec: dict, x: np.ndarray) -> np.ndarray:
    """0..1 weight map for one mask spec. Coordinates are fractions of width/height (x right, y down);
    radius is a fraction of the long edge."""
    h, w = x.shape[:2]
    long = float(max(h, w))
    t = spec.get("type")
    if t == "radial":
        cx, cy = spec.get("center", [0.5, 0.5])
        r = max(1e-3, float(spec.get("radius", 0.3))) * long
        aspect = max(0.1, float(spec.get("aspect", 1.0)))  # >1 = taller than wide
        feather = float(np.clip(spec.get("feather", 0.5), 0.02, 1.0))
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx - cx * w) / r) ** 2 + ((yy - cy * h) / (r * aspect)) ** 2)
        wgt = 1.0 - smoothstep(1.0 - feather, 1.0, d)
    elif t == "linear":
        (ax, ay), (bx, by) = spec.get("from", [0.5, 0.0]), spec.get("to", [0.5, 0.5])
        ax, ay, bx, by = ax * w, ay * h, bx * w, by * h
        vx, vy = bx - ax, by - ay
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        tt = ((xx - ax) * vx + (yy - ay) * vy) / max(vx * vx + vy * vy, 1e-6)
        wgt = 1.0 - smoothstep(0.0, 1.0, tt)  # full strength at `from`, zero at `to` and beyond
    elif t == "luminosity":
        L = luma(x)
        lo, hi = float(spec.get("lo", 0.0)), float(spec.get("hi", 1.0))
        f = max(0.01, float(spec.get("feather", 0.1)))
        wgt = smoothstep(lo - f, lo + f, L) * (1.0 - smoothstep(hi - f, hi + f, L))
    elif t == "color":
        hsv = rgb_to_hsv(x)
        hue, width = float(spec.get("hue", 0.0)), float(spec.get("width", 30.0))
        f = max(1.0, float(spec.get("feather", 15.0)))
        dh = np.abs(((hsv[..., 0] - hue + 180.0) % 360.0) - 180.0)
        wgt = (1.0 - smoothstep(width, width + f, dh)) * smoothstep(0.05, max(0.06, float(spec.get("min_sat", 0.2))), hsv[..., 1])
    elif t == "image":  # external mask (e.g. person segmentation): white = selected
        path = spec["path"] if os.path.isabs(spec["path"]) else os.path.join(ROOT, spec["path"])
        m = Image.open(path).convert("L").resize((w, h), Image.BILINEAR)
        wgt = np.asarray(m, dtype=np.float32) / 255.0
    else:
        raise SystemExit(f"unknown mask type {t!r}; use radial, linear, luminosity, color or image")
    if spec.get("invert"):
        wgt = 1.0 - wgt
    if spec.get("refine"):
        wgt = guided_refine(wgt, luma(x), radius=max(4, int(0.012 * long)), eps=float(spec.get("refine_eps", 2e-3)))
    return np.clip(wgt * float(spec.get("opacity", 1.0)), 0.0, 1.0).astype(np.float32)


def apply_local(x: np.ndarray, adjust: dict, warns: list, label: str) -> np.ndarray:
    adj = {}
    for k, v in adjust.items():
        if k not in LOCAL_KEYS:
            warns.append(f"{label}: '{k}' is not allowed inside a mask, ignored")
            continue
        if k in LOCAL_LIMITS and isinstance(v, (int, float)) and abs(v) > LOCAL_LIMITS[k]:
            warns.append(f"{label}: {k} {v} clamped to ±{LOCAL_LIMITS[k]}")
            v = float(np.clip(v, -LOCAL_LIMITS[k], LOCAL_LIMITS[k]))
        adj[k] = v
    y = stage_exposure_wb(x, adj, {}) if (adj.get("exposure_ev") or adj.get("wb")) else x
    y = stage_tone(y, adj)
    y = stage_colour(y, adj)
    return stage_effects(y, {k: adj[k] for k in ("clarity", "sharpen") if k in adj}, {})


def stage_masks(x: np.ndarray, params: dict, report: dict):
    masks = params.get("masks") or []
    if not masks:
        return x, None
    warns = report.setdefault("warnings", [])
    overlay = x.copy()
    # picture edges at a fixed working size, so the boundary crop lands in the same place for previews and finals
    wh = (max(1, round(x.shape[1] * 1024 / max(x.shape[:2]))), max(1, round(x.shape[0] * 1024 / max(x.shape[:2]))))
    gy, gx = np.gradient(blur(resize2d(luma(x), wh), 1.5))
    grad = np.abs(gx) + np.abs(gy)
    info = []
    for i, spec in enumerate(masks):
        label = f"mask {i}" + (f" ({spec['name']})" if spec.get("name") else f" ({spec.get('type')})")
        wgt = mask_weight(spec, x)
        y = apply_local(x, spec.get("adjust") or {}, warns, label)
        x = x + (y - x) * wgt[..., None]
        cov = float((wgt > 0.5).mean())
        if cov < 0.002:
            warns.append(f"{label} covers almost nothing; check its placement in the _masks.jpg overlay")
        entry = {"index": i, "type": spec.get("type"), "name": spec.get("name"), "coverage": round(cov, 3),
                 "mean_weight": round(float(wgt.mean()), 3), "tint": ["red", "cyan", "yellow", "green"][i % 4]}
        ws = resize2d(wgt, wh)
        band = np.abs(ws - 0.5) < 0.12
        if band.any():  # the boundary pixel sitting on the strongest picture edge: where a halo would show
            iy, ix = np.unravel_index(int(np.argmax(np.where(band, grad, -1.0))), grad.shape)
            entry["edge_point"] = [round(ix / ws.shape[1], 4), round(iy / ws.shape[0], 4)]
        info.append(entry)
        tint = np.array(MASK_TINTS[i % len(MASK_TINTS)], dtype=np.float32)
        overlay = overlay * (1.0 - 0.55 * wgt[..., None]) + tint * (0.55 * wgt[..., None])
    report["masks"] = info
    return np.clip(x, 0.0, 1.0), np.clip(overlay, 0.0, 1.0)


def grade_array(rgb: np.ndarray, params: dict, report: dict | None = None) -> np.ndarray:
    report = report if report is not None else {}
    x = stage_exposure_wb(rgb, params, report)
    x = stage_tone(x, params)
    x = stage_colour(x, params)
    lut = params.get("lut")
    if lut and lut.get("path"):
        path = lut["path"] if os.path.isabs(lut["path"]) else os.path.join(ROOT, lut["path"])
        x = apply_lut(x, lut_from_cube(path), float(lut.get("strength", 1.0)))
    x = stage_skin_protect(rgb, x, float(params.get("skin_protect", 0.6)), report)
    x, overlay = stage_masks(x, params, report)  # local edits ride on top of the global grade
    if overlay is not None:
        report["_mask_overlay"] = overlay
    return stage_effects(x, params, report)


# --- IO -----------------------------------------------------------------------

def save(x: np.ndarray, path: str, quality: int = 95, recipe: dict | None = None) -> None:
    """Write sRGB output. With `recipe`, the full edit (params, masks, stats) is embedded in the JPEG's EXIF so
    `explain.py` can list exactly what changed later, in any session, without a sidecar file."""
    img = Image.fromarray((np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    ext = os.path.splitext(path)[1].lower()
    kw = {}
    if recipe is not None:
        exif = Image.Exif()
        n_masks = len(recipe.get("masks") or [])
        exif[0x010E] = f"darkroom-agent {recipe.get('version', '')}: scene {recipe.get('scene') or 'base'}, {n_masks} mask(s)"
        exif[0x0131] = f"darkroom-agent {recipe.get('version', '')}"  # Software
        body = json.dumps(recipe, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        exif.get_ifd(0x8769)[RECIPE_TAG] = b"ASCII\x00\x00\x00" + body
        kw["exif"] = exif.tobytes()
    if ext in (".jpg", ".jpeg"):
        img.save(path, quality=quality, subsampling=0, icc_profile=icc, **kw)
    else:
        img.save(path, icc_profile=icc, **kw)


def read_recipe(path: str) -> dict | None:
    """Recipe embedded by save(); None if the file has none."""
    try:
        raw = Image.open(path).getexif().get_ifd(0x8769).get(RECIPE_TAG)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw[8:] if raw[:5] in (b"ASCII", b"UNICO") else raw
        raw = raw.decode("utf-8", "replace")
    raw = raw.strip("\x00 ")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def side_by_side(a: np.ndarray, b: np.ndarray, height: int = 900, gap: int = 12) -> np.ndarray:
    def fit(z):
        s = min(1.0, height / z.shape[0])
        return z if s == 1.0 else np.stack([resize2d(z[..., c], (round(z.shape[1] * s), round(z.shape[0] * s)))
                                            for c in range(3)], axis=-1)
    a, b = fit(a), fit(b)
    hh = max(a.shape[0], b.shape[0])
    canvas = np.full((hh, a.shape[1] + gap + b.shape[1], 3), 0.08, dtype=np.float32)
    canvas[:a.shape[0], :a.shape[1]] = a
    canvas[:b.shape[0], a.shape[1] + gap:] = b
    return canvas


def detail_crops(before: np.ndarray, after: np.ndarray, size: int = 384, extra=None):
    """1:1 crops (at output resolution) of the brightest block, the most textured dark block and, if present,
    the skin region: before | after, one row each. Picked on the *before* image so rows match across rounds."""
    h, w = before.shape[:2]
    size = int(min(size, h, w))
    bs = max(16, size // 4)
    gh, gw = h // bs, w // bs
    L = luma(before)[:gh * bs, :gw * bs].reshape(gh, bs, gw, bs)
    mean, std = L.mean(axis=(1, 3)), L.std(axis=(1, 3))
    picks = [("brightest", *np.unravel_index(int(np.argmax(mean)), mean.shape))]
    tex = np.where(mean < np.percentile(mean, 35), std, -1.0)
    picks.append(("dark texture", *np.unravel_index(int(np.argmax(tex)), tex.shape)))
    m = skin_mask(before) > 0.5
    if 0.02 < float(m.mean()) < 0.25:  # same threshold as analyze.py's skin_mask_unreliable flag
        ys, xs = np.nonzero(m)
        picks.append(("skin (detector guess)", int(np.median(ys)) // bs, int(np.median(xs)) // bs))
    for label, fx, fy in (extra or []):  # requested points, as fractions of width/height
        picks.append((label, int(np.clip(fy, 0, 0.999) * h) // bs, int(np.clip(fx, 0, 0.999) * w) // bs))
    gap_v = np.full((size, 8, 3), 0.08, dtype=np.float32)
    rows = []
    for _, iy, ix in picks:
        cy, cx = iy * bs + bs // 2, ix * bs + bs // 2
        y0 = int(np.clip(cy - size // 2, 0, h - size))
        x0 = int(np.clip(cx - size // 2, 0, w - size))
        rows.append(np.concatenate([before[y0:y0 + size, x0:x0 + size], gap_v, after[y0:y0 + size, x0:x0 + size]], axis=1))
    gap_h = np.full((8, rows[0].shape[1], 3), 0.08, dtype=np.float32)
    out = rows[0]
    for r in rows[1:]:
        out = np.concatenate([out, gap_h, r], axis=0)
    points = [{"row": p[0], "x": round((p[2] * bs + bs // 2) / w, 3), "y": round((p[1] * bs + bs // 2) / h, 3)} for p in picks]
    return out, [p[0] for p in picks], points


def stats(x: np.ndarray) -> dict:
    L = luma(x[::3, ::3])
    return {"p1": round(float(np.percentile(L, 1)), 3), "p50": round(float(np.percentile(L, 50)), 3),
            "p99": round(float(np.percentile(L, 99)), 3),
            "clipped_highlights_frac": round(float((x[::3, ::3].max(-1) >= 0.985).mean()), 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", nargs="?")
    ap.add_argument("--look", default="dark-larp", help="look name in looks/ or a path; 'none' for neutral")
    ap.add_argument("--scene", help="scene variant defined inside the look (see --list-looks)")
    ap.add_argument("--params", help="JSON file merged on top of the look")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override, dotted keys, JSON values")
    ap.add_argument("--out")
    ap.add_argument("--preview", action="store_true", help="small, fast render for iteration (1400 px long edge)")
    ap.add_argument("--compare", action="store_true", help="also write a before|after image and 1:1 detail crops (_compare.jpg, _detail.jpg)")
    ap.add_argument("--crop", action="append", default=[], metavar="X,Y",
                    help="with --compare: add a 1:1 detail crop centred at X,Y (fractions of width,height); repeatable")
    ap.add_argument("--max-size", type=int, default=3072, help="long edge of the output (default 3072; --preview uses 1400). 4096 = full size for 12 MP phone photos, ~1.9GB RAM")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality (default 95)")
    ap.add_argument("--no-source-adjust", action="store_true", help="skip per-device offsets")
    ap.add_argument("--list-looks", action="store_true")
    a = ap.parse_args()

    if a.list_looks:
        for name in list_looks():
            sc_ = load_look(name).get("scenes", {})
            print(name + (f"  scenes: {', '.join(sc_)}" if sc_ else ""))
        return 0
    if not a.photo:
        ap.error("photo is required")

    try:
        img = load(a.photo, 1400 if a.preview else a.max_size)
    except LoadError as e:
        print(json.dumps({"error": str(e)}))
        return 1

    look: dict = {} if a.look == "none" else load_look(a.look)
    scenes = look.pop("scenes", {})
    params = {k: v for k, v in look.items() if not k.startswith("_")}
    if a.scene:
        if a.scene not in scenes:
            raise SystemExit(f"Scene '{a.scene}' not in look '{a.look}'. Available: {', '.join(scenes) or 'none'}")
        params = deep_merge(params, {k: v for k, v in scenes[a.scene].items() if not k.startswith("_")})
    sc = img.meta.get("source_class", "unknown")
    applied_offsets = {}
    if not a.no_source_adjust:
        applied_offsets = source_offsets(sc)
        for k, dv in applied_offsets.items():
            params[k] = float(params.get(k, 0.0)) + float(dv)
    if a.params:
        with open(a.params) as f:
            params = deep_merge(params, json.load(f))
    for item in a.set:
        k, _, v = item.partition("=")
        try:
            val = json.loads(v)
        except json.JSONDecodeError:
            val = v
        set_dotted(params, k.strip(), val)

    params = {k: v for k, v in params.items() if not k.startswith("_")}  # underscore keys are comments
    if isinstance(params.get("masks"), list):
        params["masks"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in params["masks"] if isinstance(m, dict)]
    unknown = sorted(set(params) - KNOWN_KEYS)
    report: dict = {"source_class": sc, "scene": a.scene, "source_offsets_applied": applied_offsets}
    if unknown:
        report["warnings"] = [f"unknown parameters ignored: {unknown}"]

    out = grade_array(img.rgb, params, report)
    overlay = report.pop("_mask_overlay", None)

    stem = os.path.splitext(os.path.basename(a.photo))[0]
    out_path = a.out or f"{stem}_{'preview' if a.preview else 'graded'}.jpg"
    recipe = {
        "tool": "darkroom-agent", "version": VERSION, "created": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "source": os.path.basename(a.photo), "source_class": sc, "look": None if a.look == "none" else a.look, "scene": a.scene,
        "params": {k: v for k, v in params.items() if k != "masks"}, "masks": params.get("masks") or [],
        "auto_exposure_ev": report.get("auto_exposure_ev"), "mask_info": report.get("masks"),
        "before": stats(img.rgb), "after": stats(out),
        "input_size": [img.meta.get("original_width"), img.meta.get("original_height")], "size": [int(out.shape[1]), int(out.shape[0])],
    }
    save(out, out_path, a.quality, recipe=recipe)
    if overlay is not None and (a.preview or a.compare):  # tinted placement check; never written beside a delivered file
        ov_path = os.path.splitext(out_path)[0] + "_masks.jpg"
        save(overlay, ov_path, 88)
        report["mask_overlay"] = ov_path
    report.update(output=out_path, size=[int(out.shape[1]), int(out.shape[0])],
                  input_size=[img.meta.get("original_width"), img.meta.get("original_height")],
                  before=stats(img.rgb), after=stats(out), effective_params=params)
    if a.compare:
        cmp_path = os.path.splitext(out_path)[0] + "_compare.jpg"
        save(side_by_side(img.rgb, out), cmp_path, 90)
        report["compare"] = cmp_path
        extra = [(f"mask {m['index']} edge", *m["edge_point"]) for m in report.get("masks", []) if m.get("edge_point")]
        extra += [("crop " + c, *map(float, c.split(","))) for c in a.crop]
        det, names, points = detail_crops(img.rgb, out, extra=extra)
        det_path = os.path.splitext(out_path)[0] + "_detail.jpg"
        save(det, det_path, 92)
        report["detail"] = {"path": det_path, "rows": names, "points": points,
                            "note": "1:1 crops at output resolution, before | after; points are crop centres as fractions"}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
