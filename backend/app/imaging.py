"""Deterministic selfie normalisation and one-factor variants.

Pipeline sod-transform-1
- Apply EXIF orientation. Treat the resulting pixels as sRGB.
- Downscale with Lanczos so the long side is at most the configured length.
  Never upscale.
- Encode the master and every submission as PNG (compress level 3). JPEG
  compression is not part of this experiment.
- Exposure multipliers are applied in linear RGB after the IEC 61966-2-1 sRGB
  electro-optical transfer function, then encoded back. Values outside [0, 1]
  are clipped and counted.
- Warm and cool variants multiply red and blue in that same linear RGB. Green
  stays at 1. These are channel-gain perturbations, not measured Kelvin shifts.
- Framing uses equal-sized crop windows shifted by the configured fraction of
  image width, then Lanczos-resized back to the master size. This is a digital
  framing perturbation, not a physical head rotation.
All variants are derived from the same master pixels.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from app.config import (
    COLOUR_CONVERSION,
    ENCODE_METHOD,
    PIPELINE_VERSION,
    RESIZE_METHOD,
    Settings,
)

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    encoded = np.where(
        clipped <= 0.0031308,
        clipped * 12.92,
        1.055 * np.power(clipped, 1.0 / 2.4) - 0.055,
    )
    return np.clip(encoded, 0.0, 1.0)


def encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


def decode_image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return ImageOps.exif_transpose(image)


def normalize_image(image: Image.Image, long_side: int) -> Image.Image:
    rgb = image.convert("RGB")
    width, height = rgb.size
    longest = max(width, height)
    if longest > long_side:
        scale = long_side / longest
        rgb = rgb.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
    return rgb


def _rgb_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0


def _from_srgb(array: np.ndarray) -> Image.Image:
    encoded = np.rint(np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    return Image.fromarray(encoded, mode="RGB")


def clipping_fraction(linear: np.ndarray) -> float:
    outside = np.any((linear < 0.0) | (linear > 1.0), axis=-1)
    return float(np.mean(outside))


def apply_exposure(image: Image.Image, multiplier: float) -> tuple[Image.Image, float]:
    linear = srgb_to_linear(_rgb_array(image)) * multiplier
    fraction = clipping_fraction(linear)
    return _from_srgb(linear_to_srgb(linear)), fraction


def apply_channel_gains(
    image: Image.Image, red_gain: float, green_gain: float, blue_gain: float
) -> tuple[Image.Image, float]:
    linear = srgb_to_linear(_rgb_array(image))
    linear = linear * np.array([red_gain, green_gain, blue_gain], dtype=np.float64)
    fraction = clipping_fraction(linear)
    return _from_srgb(linear_to_srgb(linear)), fraction


def framing_window(width: int, shift_pixels: int, direction: str) -> tuple[int, int]:
    if shift_pixels < 1:
        raise ValueError("framing shift rounds to zero pixels")
    crop_width = width - shift_pixels
    if crop_width < 2:
        raise ValueError("framing crop is smaller than 2 pixels")
    if direction == "left":
        x0 = 0
    elif direction == "right":
        x0 = shift_pixels
    else:
        raise ValueError(f"unknown framing direction {direction}")
    return x0, crop_width


def apply_framing(
    image: Image.Image,
    direction: str,
    fraction: float,
    face_box: tuple[int, int, int, int] | None,
) -> tuple[Image.Image | None, dict, str | None]:
    array = np.asarray(image.convert("RGB"))
    height, width = array.shape[:2]
    shift = int(round(width * fraction))
    try:
        x0, crop_width = framing_window(width, shift, direction)
    except ValueError as exc:
        return None, {}, str(exc)
    bounds = {"x": x0, "y": 0, "width": crop_width, "height": height, "shift_pixels": shift}
    if face_box is not None:
        fx, fy, fw, fh = face_box
        inside = fx >= x0 and fy >= 0 and fx + fw <= x0 + crop_width and fy + fh <= height
        if not inside:
            return None, bounds, "face would leave the crop window; variant rejected"
    crop = array[:, x0 : x0 + crop_width]
    resized = Image.fromarray(crop, mode="RGB").resize((width, height), Image.Resampling.LANCZOS)
    return resized, bounds, None


@dataclass
class RenderedImage:
    key: str
    factor: str
    role: str
    params: dict
    png_bytes: bytes | None
    sha256: str | None
    width: int | None
    height: int | None
    crop_bounds: dict | None
    clipping_fraction: float | None
    status: str
    rejection_reason: str | None = None
    pipeline_version: str = PIPELINE_VERSION
    colour_conversion: str = COLOUR_CONVERSION
    resize_method: str = RESIZE_METHOD
    encode_method: str = ENCODE_METHOD


def render_master(data: bytes, long_side: int) -> tuple[Image.Image, bytes]:
    image = normalize_image(decode_image(data), long_side)
    encoded = encode_png(image)
    # Re-open so later variants start from the stored master bytes.
    stored = Image.open(io.BytesIO(encoded))
    stored.load()
    return stored.convert("RGB"), encoded


def variant_plan(settings: Settings, factors: list[str]) -> list[dict]:
    chosen = set(factors)
    plan = []
    if "exposure" in chosen:
        plan.append(
            {
                "key": "exposure_low",
                "factor": "exposure",
                "params": {"exposure_multiplier": settings.exposure_low, "colour_space": COLOUR_CONVERSION},
            }
        )
        plan.append(
            {
                "key": "exposure_high",
                "factor": "exposure",
                "params": {"exposure_multiplier": settings.exposure_high, "colour_space": COLOUR_CONVERSION},
            }
        )
    if "colour_balance" in chosen:
        plan.append(
            {
                "key": "colour_warm",
                "factor": "colour_balance",
                "params": {
                    "red_gain": settings.warm_red_gain,
                    "green_gain": 1.0,
                    "blue_gain": settings.warm_blue_gain,
                    "colour_space": COLOUR_CONVERSION,
                    "note": "channel-gain perturbation, not a measured colour temperature",
                },
            }
        )
        plan.append(
            {
                "key": "colour_cool",
                "factor": "colour_balance",
                "params": {
                    "red_gain": settings.cool_red_gain,
                    "green_gain": 1.0,
                    "blue_gain": settings.cool_blue_gain,
                    "colour_space": COLOUR_CONVERSION,
                    "note": "channel-gain perturbation, not a measured colour temperature",
                },
            }
        )
    if "framing" in chosen:
        plan.append(
            {
                "key": "framing_left",
                "factor": "framing",
                "params": {
                    "direction": "left",
                    "shift_fraction_of_width": -settings.framing_shift_fraction,
                    "note": "digital framing perturbation, not physical head rotation",
                },
            }
        )
        plan.append(
            {
                "key": "framing_right",
                "factor": "framing",
                "params": {
                    "direction": "right",
                    "shift_fraction_of_width": settings.framing_shift_fraction,
                    "note": "digital framing perturbation, not physical head rotation",
                },
            }
        )
    return plan


def render_variants(
    master: Image.Image,
    plan: list[dict],
    settings: Settings,
    face_box: tuple[int, int, int, int] | None,
) -> list[RenderedImage]:
    rendered: list[RenderedImage] = []
    for spec in plan:
        factor = spec["factor"]
        params = spec["params"]
        image: Image.Image | None
        bounds = None
        reason = None
        fraction = 0.0
        if factor == "exposure":
            image, fraction = apply_exposure(master, float(params["exposure_multiplier"]))
        elif factor == "colour_balance":
            image, fraction = apply_channel_gains(
                master, float(params["red_gain"]), float(params["green_gain"]), float(params["blue_gain"])
            )
        elif factor == "framing":
            image, bounds, reason = apply_framing(
                master, params["direction"], settings.framing_shift_fraction, face_box
            )
            fraction = 0.0
        else:
            image, reason = None, f"unknown factor {factor}"
        if image is not None and fraction > settings.max_clip_fraction:
            reason = (
                f"clipping fraction {fraction:.4f} exceeds configured maximum {settings.max_clip_fraction:.4f}"
            )
            image = None
        if image is None:
            rendered.append(
                RenderedImage(
                    key=spec["key"],
                    factor=factor,
                    role="variant",
                    params=params,
                    png_bytes=None,
                    sha256=None,
                    width=None,
                    height=None,
                    crop_bounds=bounds,
                    clipping_fraction=fraction,
                    status="rejected_local",
                    rejection_reason=reason,
                )
            )
            continue
        payload = encode_png(image)
        rendered.append(
            RenderedImage(
                key=spec["key"],
                factor=factor,
                role="variant",
                params=params,
                png_bytes=payload,
                sha256=sha256_bytes(payload),
                width=image.width,
                height=image.height,
                crop_bounds=bounds,
                clipping_fraction=fraction,
                status="generated",
            )
        )
    return rendered


@dataclass
class FaceBox:
    x: int
    y: int
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def detect_faces(image: Image.Image) -> list[FaceBox]:
    if cv2 is None:
        raise RuntimeError("OpenCV is not installed; face framing cannot be checked")
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        raise RuntimeError("Haar cascade failed to load")
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    width, height = image.size
    found = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(max(24, int(width * 0.18)), max(24, int(height * 0.18))),
    )
    boxes = [FaceBox(int(x), int(y), int(w), int(h)) for (x, y, w, h) in found]
    boxes.sort(key=lambda box: box.width * box.height, reverse=True)
    return boxes


def _check(name: str, status: str, detail: str, heuristic: str) -> dict:
    return {"name": name, "status": status, "detail": detail, "heuristic": heuristic}


def validate_capture(image: Image.Image, settings: Settings, faces: list[FaceBox] | None = None) -> dict:
    """Local capture checks. These are engineering heuristics, not provider certification."""
    checks: list[dict] = []
    width, height = image.size
    short_side = min(width, height)
    if short_side < 480:
        checks.append(
            _check(
                "dimensions",
                "fail",
                f"Short side is {short_side}px. SD analysis documentation asks for at least 480px.",
                "Compared with the published SD minimum short side. This app does not upscale.",
            )
        )
    else:
        checks.append(
            _check(
                "dimensions",
                "pass",
                f"{width}×{height} after orientation and normalisation.",
                "Local measurement of the normalised image.",
            )
        )
    if faces is None:
        try:
            faces = detect_faces(image)
            face_note = "OpenCV Haar frontal-face cascade on the normalised image."
        except RuntimeError as exc:
            faces = []
            face_note = str(exc)
    else:
        face_note = "Face boxes were supplied by the caller."
    if len(faces) != 1:
        checks.append(
            _check(
                "single_face",
                "fail",
                f"Detected {len(faces)} frontal faces. The experiment needs one face so framing crops can be bounded.",
                face_note + " A miss here is a local heuristic failure, not a YouCam result.",
            )
        )
        face = None
    else:
        face = faces[0]
        ratio = face.width / width
        edge = min(face.x, face.y, width - (face.x + face.width), height - (face.y + face.height))
        margin = int(round(width * settings.framing_shift_fraction)) + 2
        status = "pass"
        detail = f"One face, width {ratio:.0%} of the image."
        if ratio < 0.45 or ratio > 0.9:
            status = "warn"
            detail += " Provider guidance prefers the face at roughly 60–80% of image width."
        if edge < margin:
            status = "fail"
            detail = "The face is too close to the edge for a 2% framing shift to keep it inside the crop."
        checks.append(_check("single_face", status, detail, face_note))
    gray = np.asarray(image.convert("L"), dtype=np.float64)
    if cv2 is not None:
        variance = float(cv2.Laplacian(gray.astype(np.uint8), cv2.CV_64F).var())
    else:
        variance = float(np.var(gray))
    blur_status = "pass" if variance >= settings.blur_variance_min else "fail"
    checks.append(
        _check(
            "blur",
            blur_status,
            f"Laplacian variance is {variance:.1f}. Configured minimum is {settings.blur_variance_min:.1f}.",
            "Variance of a Laplacian filter. This is not a provider sharpness certificate.",
        )
    )
    luma = gray
    clipped = np.mean((luma <= 5) | (luma >= 250))
    clip_status = "pass" if clipped <= settings.capture_clip_fraction_max else "fail"
    if clipped > settings.capture_clip_fraction_max / 2 and clip_status == "pass":
        clip_status = "warn"
    checks.append(
        _check(
            "clipping",
            clip_status,
            f"{clipped:.1%} of pixels are near black or white.",
            "Share of luma values ≤5 or ≥250. Local heuristic only.",
        )
    )
    mid = width // 2
    if mid > 0:
        imbalance = abs(float(luma[:, :mid].mean()) - float(luma[:, mid:].mean()))
    else:
        imbalance = 0.0
    light_status = "pass"
    if imbalance > settings.lighting_imbalance_max:
        light_status = "fail"
    elif imbalance > settings.lighting_imbalance_max * 0.6:
        light_status = "warn"
    checks.append(
        _check(
            "lighting_balance",
            light_status,
            f"Left/right mean luma differs by {imbalance:.1f} (0–255).",
            "Absolute difference of mean luma in the two horizontal halves. Not a lighting meter.",
        )
    )
    failed = [item["name"] for item in checks if item["status"] == "fail"]
    return {
        "ok": not failed,
        "failed": failed,
        "checks": checks,
        "width": width,
        "height": height,
        "face": face.as_dict() if face else None,
        "disclaimer": (
            "These checks are local heuristics so the experiment can reject unusable captures early. "
            "They are not YouCam certification and they do not describe skin."
        ),
    }


def pipeline_description(settings: Settings) -> dict:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "colour_conversion": COLOUR_CONVERSION,
        "resize_method": RESIZE_METHOD,
        "encode_method": ENCODE_METHOD,
        "normalize_long_side": settings.normalize_long_side,
        "exposure_multipliers": [settings.exposure_low, settings.exposure_high],
        "channel_gains": {
            "warm": {"red": settings.warm_red_gain, "green": 1.0, "blue": settings.warm_blue_gain},
            "cool": {"red": settings.cool_red_gain, "green": 1.0, "blue": settings.cool_blue_gain},
        },
        "framing_shift_fraction_of_width": settings.framing_shift_fraction,
        "max_clip_fraction": settings.max_clip_fraction,
        "notes": [
            "Each variant is rendered from the same normalised master.",
            "Exposure and channel gains run in linear RGB after sRGB decoding.",
            "Framing shifts are digital crops, not head rotation.",
            "A locally rejected variant is kept as a rejection. It is not replaced.",
        ],
    }
