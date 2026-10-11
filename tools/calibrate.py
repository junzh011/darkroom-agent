#!/usr/bin/env python3
"""Calibrate looks against before/after pairs (dev tool, not part of the skill runtime).

Pairs live in a folder as NN_before.<ext> / NN_after.<ext>.

  fit   For each pair, find the global slider values that best turn the before into the after.
        python tools/calibrate.py fit evals/larp-shoot-1 --out work/fit.json
  eval  Render each before with a look and score it against the after; writes before|ours|yours strips.
        python tools/calibrate.py eval evals/larp-shoot-1 --look dark-larp --out-dir work/eval

Error is mean absolute difference in sRGB (0..1) at a small working size, so ~0.02 is close and ~0.1 is clearly off.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from analyze import analyze_array  # noqa: E402
from common import resize_rgb_float  # noqa: E402
from grade import deep_merge, grade_array, load_look, save, source_offsets  # noqa: E402
from ingest import HEIF_EXT, RAW_EXT, load  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"} | HEIF_EXT | RAW_EXT

# the sliders we fit: (dotted key, lower, upper)
SLIDERS = [
    ("exposure_ev", -2.0, 1.0),
    ("brightness", -1.5, 1.0),
    ("contrast", -1.0, 1.0),
    ("highlights", -1.0, 1.0),
    ("shadows", -1.0, 1.0),
    ("blacks", -1.0, 1.0),
    ("saturation", -0.8, 1.0),
    ("wb.temp", -1.0, 1.0),
    ("wb.tint", -1.0, 1.0),
]
FIT_BASE = {"skin_protect": 0.0}  # plain sliders only, like the phone's editor


def find_pairs(folder: str, only: str | None = None) -> dict[str, dict[str, str]]:
    keep = set(only.split(",")) if only else None
    pairs: dict[str, dict[str, str]] = {}
    for f in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(f)
        if f.startswith(".") or "_" not in stem or ext.lower() not in IMAGE_EXT:
            continue  # videos and other files are skipped
        if keep is not None and stem.split("_", 1)[0] not in keep:
            continue
        n, kind = stem.split("_", 1)
        if kind.lower() in ("before", "after"):
            pairs.setdefault(n, {})[kind.lower()] = os.path.join(folder, f)
    return {n: p for n, p in pairs.items() if len(p) == 2}


def load_pair(p: dict[str, str], size: int):
    b, a = load(p["before"], size), load(p["after"], size)
    if b.rgb.shape != a.rgb.shape:  # cropped or rotated differently: force to the before's frame
        a.rgb = resize_rgb_float(a.rgb, (b.rgb.shape[1], b.rgb.shape[0]))
    return b, a


def to_params(vec) -> dict:
    out = json.loads(json.dumps(FIT_BASE))
    for (key, _, _), v in zip(SLIDERS, vec):
        d = out
        parts = key.split(".")
        for k in parts[:-1]:
            d = d.setdefault(k, {})
        d[parts[-1]] = round(float(v), 3)
    return out


def mae(x, y) -> float:
    return float(np.abs(x - y).mean())


def nelder_mead(f, x0, step=0.25, iters=400, tol=1e-6):
    n = len(x0)
    pts = [np.array(x0, dtype=np.float64)]
    for i in range(n):
        v = pts[0].copy()
        v[i] += step
        pts.append(v)
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = np.argsort(vals)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < tol:
            break
        c = np.mean(pts[:-1], axis=0)
        xr = c + (c - pts[-1])
        fr = f(xr)
        if fr < vals[0]:
            xe = c + 2 * (c - pts[-1])
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = c + 0.5 * (pts[-1] - c)
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def cmd_fit(a) -> int:
    lo = np.array([s[1] for s in SLIDERS])
    hi = np.array([s[2] for s in SLIDERS])
    results = {}
    for n, p in find_pairs(a.folder, a.only).items():
        b, af = load_pair(p, a.size)

        def loss(v):
            v = np.clip(v, lo, hi)
            return mae(grade_array(b.rgb, to_params(v)), af.rgb) + a.reg * float(np.sum(v * v)) / len(v)

        best, _ = nelder_mead(loss, np.zeros(len(SLIDERS)), iters=a.iters)
        best = np.clip(best, lo, hi)
        fitted = grade_array(b.rgb, to_params(best))
        tone = analyze_array(b.rgb, b.meta)["tone"]
        results[n] = {
            "params": to_params(best),
            "mae_no_edit": round(mae(b.rgb, af.rgb), 4),
            "mae_fit": round(mae(fitted, af.rgb), 4),
            "input": {k: tone[k] for k in ("p1", "p50", "p95", "p99", "key")},
            "source_class": b.meta.get("source_class"),
        }
        r = results[n]
        print(f"pair {n}: no-edit {r['mae_no_edit']:.4f} -> fit {r['mae_fit']:.4f}  "
              + " ".join(f"{k}={v:+.2f}" for (k, _, _), v in zip(SLIDERS, best)), flush=True)
    med = np.median([[_get(r["params"], k) for k, _, _ in SLIDERS] for r in results.values()], axis=0)
    summary = {"pairs": results, "median_params": to_params(med)}
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            json.dump(summary, f, indent=2)
    print("median:", " ".join(f"{k}={v:+.2f}" for (k, _, _), v in zip(SLIDERS, med)))
    return 0


def _get(d: dict, dotted: str) -> float:
    for k in dotted.split("."):
        d = d.get(k, {}) if isinstance(d, dict) else {}
    return float(d) if not isinstance(d, dict) else 0.0


def strip(images, height=600, gap=10):
    from common import resize2d

    fitted = []
    for z in images:
        s = height / z.shape[0]
        fitted.append(np.stack([resize2d(z[..., c], (round(z.shape[1] * s), height)) for c in range(3)], axis=-1))
    width = sum(z.shape[1] for z in fitted) + gap * (len(fitted) - 1)
    canvas = np.full((height, width, 3), 0.08, dtype=np.float32)
    x = 0
    for z in fitted:
        canvas[:, x:x + z.shape[1]] = z
        x += z.shape[1] + gap
    return canvas


def cmd_eval(a) -> int:
    raw = load_look(a.look)
    scenes = raw.pop("scenes", {})
    look = {k: v for k, v in raw.items() if not k.startswith("_")}
    if a.scene:
        look = deep_merge(look, {k: v for k, v in scenes[a.scene].items() if not k.startswith("_")})
    label = a.look + (f"/{a.scene}" if a.scene else "")
    os.makedirs(a.out_dir, exist_ok=True)
    scores = []
    for n, p in find_pairs(a.folder, a.only).items():
        b, af = load_pair(p, a.size)
        params = json.loads(json.dumps(look))
        for k, dv in source_offsets(b.meta.get("source_class", "unknown")).items():
            params[k] = float(params.get(k, 0.0)) + float(dv)
        ours = grade_array(b.rgb, params)
        s_no, s_ours = mae(b.rgb, af.rgb), mae(ours, af.rgb)
        scores.append((s_no, s_ours))
        save(strip([b.rgb, ours, af.rgb]), os.path.join(a.out_dir, f"eval_{n}.jpg"), 88)
        print(f"pair {n}: no-edit {s_no:.4f}  {label} {s_ours:.4f}")
    arr = np.array(scores)
    print(f"mean: no-edit {arr[:, 0].mean():.4f}  {label} {arr[:, 1].mean():.4f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("folder")
    f.add_argument("--out")
    f.add_argument("--size", type=int, default=384)
    f.add_argument("--iters", type=int, default=400)
    f.add_argument("--reg", type=float, default=0.002, help="small pull toward zero so equivalent sliders don't wander")
    f.add_argument("--only", help="comma-separated pair numbers, e.g. 07,09")
    e = sub.add_parser("eval")
    e.add_argument("folder")
    e.add_argument("--look", default="dark-larp")
    e.add_argument("--scene", help="scene variant from the look, applied to every pair evaluated")
    e.add_argument("--only", help="comma-separated pair numbers, e.g. 07,09")
    e.add_argument("--out-dir", default="work/eval")
    e.add_argument("--size", type=int, default=768)
    a = ap.parse_args()
    return cmd_fit(a) if a.cmd == "fit" else cmd_eval(a)


if __name__ == "__main__":
    sys.exit(main())
