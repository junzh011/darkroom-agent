"""Shared helpers: colour transforms, blur, skin mask. numpy + Pillow only."""
from __future__ import annotations

import numpy as np
from PIL import Image

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


# --- transfer functions -----------------------------------------------------

def srgb_to_linear(x):
    x = np.asarray(x, dtype=np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((np.maximum(x, 0) + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x):
    x = np.maximum(np.asarray(x, dtype=np.float32), 0.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def luma(rgb):
    """Rec.709 weights applied to sRGB-encoded values (a decent perceptual proxy)."""
    return (rgb @ LUMA).astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return (t * t * (3 - 2 * t)).astype(np.float32)


# --- HSV (hue in degrees) -----------------------------------------------------

def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(-1)
    d = mx - rgb.min(-1)
    nz = d > 1e-8
    dd = np.where(nz, d, 1.0)
    h = np.where(mx == r, ((g - b) / dd) % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4))
    h = np.where(nz, h * 60.0, 0.0)
    s = np.where(mx > 1e-8, d / np.where(mx > 1e-8, mx, 1.0), 0.0)
    return np.stack([h, s, mx], axis=-1).astype(np.float32)


def hsv_to_rgb(hsv):
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    h6 = (h % 360.0) / 60.0
    fl = np.floor(h6)
    f = h6 - fl
    i = fl.astype(np.int32) % 6
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1).astype(np.float32)


# --- resize / blur ------------------------------------------------------------

def resize2d(a, size):
    """Resize a 2-D float array to size=(w, h) with bilinear filtering."""
    im = Image.fromarray(np.ascontiguousarray(a, dtype=np.float32), mode="F")
    return np.asarray(im.resize(size, Image.BILINEAR), dtype=np.float32)


def resize_rgb_float(rgb, size):
    return np.stack([resize2d(rgb[..., c], size) for c in range(3)], axis=-1)


def _box(a, r, axis):
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def blur(a, sigma):
    """Approximate gaussian blur of a 2-D array using three box passes.
    Large sigmas are computed on a downscaled copy for speed."""
    a = np.asarray(a, dtype=np.float32)
    if sigma < 0.5:
        return a
    h, w = a.shape
    k = max(1, int(sigma // 4))
    work = a
    if k > 1:
        work = resize2d(a, (max(1, w // k), max(1, h // k)))
    s = sigma / k
    width = max(1.0, np.sqrt(4 * s * s + 1))
    r = max(1, int(round((width - 1) / 2)))
    for _ in range(3):
        work = _box(_box(work, r, 0), r, 1)
    if k > 1:
        work = resize2d(work, (w, h))
    return work


# --- skin ---------------------------------------------------------------------

def skin_mask(rgb, soft_sigma=None):
    """Heuristic soft skin mask (0..1). YCbCr box + hue/sat/value gates.
    Good enough as a guard rail; it will miss some skin and catch some wood/sand."""
    r, g, b = (rgb[..., i] * 255.0 for i in range(3))
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    hsv = rgb_to_hsv(rgb)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = (
        (cb > 77) & (cb < 127) & (cr > 133) & (cr < 173)
        & ((hue < 50) | (hue > 345))
        & (sat > 0.12) & (sat < 0.80)
        & (val > 0.12) & (val < 0.99)
    ).astype(np.float32)
    if soft_sigma is None:
        soft_sigma = max(2.0, 0.004 * max(rgb.shape[:2]))
    return np.clip(blur(m, soft_sigma) * 1.5, 0.0, 1.0)
