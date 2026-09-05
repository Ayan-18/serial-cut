import shutil

import cv2
import numpy as np
import pytest

from app.infrastructure.processes import run_process
from app.media.rendering import RenderPresetConfig, _crop_filter, build_render_args


@pytest.fixture
def framing_source(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is not installed")
    source = tmp_path / "wide.mp4"
    # Markers outside the old full-height 9:16 crop, but inside the new centre
    # window. No real media or model inference is involved in this regression.
    result = run_process([
        ffmpeg, "-hide_banner", "-y", "-f", "lavfi", "-i",
        "color=c=gray:size=960x540:rate=20:duration=1,"
        "drawbox=x=260:y=80:w=25:h=380:color=red:t=fill,"
        "drawbox=x=675:y=80:w=25:h=380:color=blue:t=fill",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source),
    ], 30)
    assert result.returncode == 0, result.stderr
    return ffmpeg, source


def _render_frame(ffmpeg, source, output, mode, *, at=0.2, **kwargs):
    args = build_render_args(
        ffmpeg, source, output, 0, 1, mode, None, False,
        preset=RenderPresetConfig("test", width=270, height=480, video_bitrate="1200k"),
        **kwargs,
    )
    result = run_process(args, 30)
    assert result.returncode == 0, result.stderr
    capture = cv2.VideoCapture(str(output))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
        ok, frame = capture.read()
        assert ok
        return frame
    finally:
        capture.release()


def test_split_mode_stacks_two_windows(framing_source, tmp_path):
    ffmpeg, source = framing_source
    frame = _render_frame(ffmpeg, source, tmp_path / "split.mp4", "split")
    h = frame.shape[0]
    # Top half is the left of the source (red marker), bottom half the right (blue).
    top = frame[: h // 2 - 20]
    bottom = frame[h // 2 + 20 :]
    assert top[:, :, 2].max() > 200 and top[:, :, 0].max() < 170  # red present, not blue
    assert bottom[:, :, 0].max() > 200 and bottom[:, :, 2].max() < 170  # blue present, not red


@pytest.mark.parametrize("mode", ["center-crop", "blurred-background"])
def test_balanced_centre_reveals_more_source_with_fixed_blurred_borders(framing_source, tmp_path, mode):
    ffmpeg, source = framing_source
    frame = _render_frame(ffmpeg, source, tmp_path / f"{mode}.mp4", mode)
    assert frame.shape == (480, 270, 3)
    # Both markers are visible in the sharp foreground.
    assert frame[240, :, 2].max() > 220
    assert frame[240, :, 0].max() > 220
    # Foreground occupies y=80..400; top/bottom remain the same dim background.
    assert float(frame[120:360, 110:160].mean()) > 110
    assert float(frame[10:60, 110:160].mean()) < 100
    assert float(frame[420:470, 110:160].mean()) < 100


def test_balanced_follow_moves_the_foreground_without_changing_its_size(framing_source, tmp_path):
    ffmpeg, source = framing_source
    points = [
        {"time": 0, "offset": -1}, {"time": 0.4, "offset": -1},
        {"time": 0.48, "offset": 1}, {"time": 1, "offset": 1},
    ]
    left = _render_frame(ffmpeg, source, tmp_path / "left.mp4", "auto-follow", crop_keyframes=points)
    right = _render_frame(ffmpeg, source, tmp_path / "right.mp4", "auto-follow", at=0.8, crop_keyframes=points)
    assert left[240, :, 2].max() > 220 and left[240, :, 0].max() < 180
    assert right[240, :, 0].max() > 220 and right[240, :, 2].max() < 180
    assert np.abs(left[:60].astype(float) - right[:60]).mean() < 3
    assert float(right[420:470, 110:160].mean()) < 100


def test_zoom_keeps_the_foreground_window_inside_the_canvas(framing_source, tmp_path):
    ffmpeg, source = framing_source
    frame = _render_frame(ffmpeg, source, tmp_path / "zoom.mp4", "center-crop", crop_scale=1.25)
    assert float(frame[10:60, 110:160].mean()) < 100
    assert float(frame[120:360, 110:160].mean()) > 110
    assert float(frame[420:470, 110:160].mean()) < 100


def test_portrait_source_fills_the_foreground_without_invalid_crop(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is not installed")
    result = run_process([
        ffmpeg, "-hide_banner", "-y", "-f", "lavfi", "-i",
        "color=c=gray:size=180x320:duration=0.1",
        "-vf", _crop_filter("center-crop", width=270, height=480),
        "-frames:v", "1", str(tmp_path / "portrait.png"),
    ], 30)
    assert result.returncode == 0, result.stderr
    frame = cv2.imdecode(np.frombuffer((tmp_path / "portrait.png").read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert frame.shape == (480, 270, 3)
