"""Load any supported photo into a float32 sRGB array plus metadata.

Core formats (JPEG/PNG/WebP/TIFF) need only Pillow. Optional extras:
  - HEIC/HEIF : pillow-heif, or macOS `sips` as a fallback
  - RAW / DNG : rawpy (LibRaw), or macOS `sips` as a fallback
When a format can't be read, LoadError carries a user-friendly message.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageCms, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import resize_rgb_float  # noqa: E402

RAW_EXT = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".pef", ".srw"}
HEIF_EXT = {".heic", ".heif", ".hif"}
PHONE_MAKES = ("apple", "samsung", "google", "xiaomi", "oneplus", "huawei", "oppo", "vivo", "motorola", "honor")

MAX_SIZE_DEFAULT = 4096  # long edge; keeps memory sane in a sandbox


class LoadError(RuntimeError):
    pass


@dataclass
class Loaded:
    rgb: np.ndarray  # float32 HxWx3, sRGB-encoded, 0..1
    meta: dict = field(default_factory=dict)


# --- EXIF ---------------------------------------------------------------------

def _read_exif(img: Image.Image) -> dict:
    out: dict = {}
    try:
        ex = img.getexif()
        out["make"] = str(ex.get(271, "") or "").strip()
        out["model"] = str(ex.get(272, "") or "").strip()
        sub = ex.get_ifd(0x8769)
        if sub:
            out["iso"] = sub.get(34855)
            out["lens"] = str(sub.get(42036, "") or "").strip()
            for key, tag in (("exposure_time", 33434), ("f_number", 33437), ("focal_length", 37386)):
                v = sub.get(tag)
                out[key] = float(v) if v is not None else None
    except Exception:
        pass
    return {k: v for k, v in out.items() if v not in (None, "")}


def classify_source(meta: dict, is_raw: bool) -> str:
    make = meta.get("make", "").lower()
    model = meta.get("model", "").lower()
    is_phone = any(m in make for m in PHONE_MAKES) or "iphone" in model or "pixel" in model
    if is_raw:
        return "phone_raw" if is_phone else "camera_raw"
    if is_phone:
        return "phone_processed"
    if make or model:
        return "camera_jpeg"
    return "unknown"  # no EXIF: likely a screenshot or social-media re-save


# --- colour management --------------------------------------------------------

def _to_srgb(img: Image.Image) -> Image.Image:
    """Convert to RGB and, if an ICC profile is present (iPhones: Display P3), to sRGB."""
    icc = img.info.get("icc_profile")
    if img.mode != "RGB":
        img = img.convert("RGB")
    if not icc:
        return img
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if "srgb" in ImageCms.getProfileDescription(src).lower():
            return img
        dst = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
    except Exception:
        return img


# --- format loaders -----------------------------------------------------------

def _load_pillow(path: str, max_size: int) -> tuple[np.ndarray, dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext in HEIF_EXT:
        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except ImportError:
            return _load_via_sips(path, max_size, "HEIC")
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:  # noqa: BLE001
        raise LoadError(f"Could not open {os.path.basename(path)} ({e}). Try exporting it as a JPEG.") from e
    meta = _read_exif(img)
    img = ImageOps.exif_transpose(img)
    img = _to_srgb(img)
    if max(img.size) > max_size:
        s = max_size / max(img.size)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0, meta


def _load_via_sips(path: str, max_size: int, what: str) -> tuple[np.ndarray, dict]:
    """macOS-only fallback: let Apple's decoder turn HEIC/RAW into a JPEG."""
    if not shutil.which("sips"):
        raise LoadError(
            f"{what} files need an extra library (pillow-heif / rawpy) that isn't available here. "
            "Export the photo as a JPEG (Photos: File > Export; Lightroom: Export as JPEG) and send that instead."
        )
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "conv.jpg")
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "100", path, "--out", tmp],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(tmp):
            raise LoadError(f"sips could not convert {os.path.basename(path)}: {r.stderr.strip()}")
        arr, meta = _load_pillow(tmp, max_size)
        # sips drops some EXIF; read what survived from the original if Pillow can
        try:
            meta = {**_read_exif(Image.open(path)), **meta}
        except Exception:
            pass
        return arr, meta


def _load_raw(path: str, max_size: int) -> tuple[np.ndarray, dict]:
    try:
        import rawpy  # type: ignore
    except ImportError:
        return _load_via_sips(path, max_size, "RAW")
    try:
        with rawpy.imread(path) as raw:
            lin = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=True,
                output_bps=16,
                gamma=(1, 1),
                output_color=rawpy.ColorSpace.sRGB,
            )
    except Exception as e:  # noqa: BLE001
        raise LoadError(f"Could not decode RAW file {os.path.basename(path)} ({e}).") from e
    lin = lin.astype(np.float32) / 65535.0
    # encode to sRGB here so everything downstream sees the same thing regardless of source
    from common import linear_to_srgb

    rgb = linear_to_srgb(lin)
    h, w = rgb.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        rgb = resize_rgb_float(rgb, (round(w * s), round(h * s)))
    meta: dict = {}
    try:  # many RAWs carry a JPEG preview with EXIF; Pillow can sometimes read the TIFF-ish container
        meta = _read_exif(Image.open(path))
    except Exception:
        pass
    return np.clip(rgb, 0, 1), meta


# --- public API ---------------------------------------------------------------

def load(path: str, max_size: int = MAX_SIZE_DEFAULT) -> Loaded:
    if not os.path.exists(path):
        raise LoadError(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    is_raw = ext in RAW_EXT
    arr, meta = (_load_raw if is_raw else _load_pillow)(path, max_size)
    meta = dict(meta)
    meta.update(
        format=ext.lstrip("."),
        width=int(arr.shape[1]),
        height=int(arr.shape[0]),
        is_raw=is_raw,
    )
    meta["source_class"] = classify_source(meta, is_raw)
    return Loaded(rgb=np.clip(arr, 0.0, 1.0).astype(np.float32), meta=meta)
