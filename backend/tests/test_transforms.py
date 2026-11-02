import io

import numpy as np
from PIL import Image

from app.config import get_settings
from app.imaging import (
    apply_channel_gains,
    apply_exposure,
    apply_framing,
    encode_png,
    framing_window,
    render_master,
    render_variants,
    sha256_bytes,
    srgb_to_linear,
    variant_plan,
)


def _image(color=(120, 100, 80), size=(80, 100)):
    array = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    array[:, :] = color
    return Image.fromarray(array, mode="RGB")


def test_baseline_png_encoding_is_byte_stable():
    image = _image()
    first = encode_png(image)
    second = encode_png(image)
    assert first == second
    assert sha256_bytes(first) == sha256_bytes(second)


def test_variants_are_independent_of_each_other_and_reproducible():
    settings = get_settings()
    master = _image()
    plan = variant_plan(settings, ["exposure", "colour_balance", "framing"])
    face = (10, 10, 40, 50)
    first = render_variants(master, plan, settings, face)
    second = render_variants(master, plan, settings, face)
    assert [item.sha256 for item in first] == [item.sha256 for item in second]
    assert [item.key for item in first] == [
        "exposure_low",
        "exposure_high",
        "colour_warm",
        "colour_cool",
        "framing_left",
        "framing_right",
    ]
    assert all(item.status == "generated" for item in first)


def test_exposure_uses_linear_rgb_and_records_clipping():
    image = _image((250, 250, 250))
    adjusted, fraction = apply_exposure(image, 1.1)
    assert fraction > 0
    linear = srgb_to_linear(np.asarray(image, dtype=np.float64) / 255.0)
    assert float(linear.max() * 1.1) > 1
    assert adjusted.getpixel((0, 0)) == (255, 255, 255)


def test_channel_gains_leave_green_unchanged_in_linear_space():
    image = _image((100, 140, 180))
    adjusted, _fraction = apply_channel_gains(image, 1.03, 1.0, 0.97)
    assert adjusted.size == image.size
    assert adjusted.tobytes() != image.tobytes()


def test_framing_windows_are_equal_and_reject_when_the_face_leaves():
    width = 200
    shift = int(round(width * 0.02))
    left = framing_window(width, shift, "left")
    right = framing_window(width, shift, "right")
    assert left[1] == right[1]
    assert left[0] == 0
    assert right[0] == shift
    image = _image(size=(200, 220))
    kept, bounds, reason = apply_framing(image, "left", 0.02, (20, 20, 100, 120))
    assert reason is None and kept is not None
    assert kept.size == image.size
    assert bounds["width"] == width - shift
    rejected, _, why = apply_framing(image, "right", 0.02, (0, 10, 3, 40))
    assert rejected is None
    assert "face" in why


def test_excessive_clipping_is_rejected_and_not_replaced():
    settings = get_settings()
    original = settings.max_clip_fraction
    settings.max_clip_fraction = 0.0
    try:
        master = _image((250, 250, 250))
        plan = [spec for spec in variant_plan(settings, ["exposure"]) if spec["key"] == "exposure_high"]
        rendered = render_variants(master, plan, settings, None)
        assert rendered[0].status == "rejected_local"
        assert "clipping" in rendered[0].rejection_reason
        assert len(rendered) == 1
    finally:
        settings.max_clip_fraction = original


def test_master_normalisation_does_not_upscale():
    raw = io.BytesIO()
    _image(size=(600, 800)).save(raw, format="PNG")
    image, encoded = render_master(raw.getvalue(), 1280)
    assert image.size == (600, 800)
    assert encoded.startswith(b"\x89PNG")
