from __future__ import annotations

import heapq
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, cast

from app.infrastructure.atomic import replace_atomically, temp_sibling, write_text_atomically
from app.infrastructure.processes import ProcessResult, run_process


logger = logging.getLogger(__name__)


CropMode = Literal["auto-follow", "center-crop", "blurred-background"]
# Also used by the render fingerprint; changing framing must not reuse an old MP4.
CROP_LAYOUT_VERSION = "balanced-v1"
FOREGROUND_HEIGHT_FRACTION = 2 / 3


@dataclass(frozen=True)
class RenderedArtifacts:
    output_path: Path
    metadata_path: Path
    subtitle_path: Path | None
    cover_path: Path | None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RenderPresetConfig:
    name: str
    width: int = 1080
    height: int = 1920
    video_bitrate: str = "8M"
    audio_bitrate: str = "160k"


RENDER_PRESETS = {
    "youtube_shorts": RenderPresetConfig(name="youtube_shorts", video_bitrate="8M", audio_bitrate="160k"),
    "instagram_reels": RenderPresetConfig(name="instagram_reels", video_bitrate="10M", audio_bitrate="192k"),
    "preview": RenderPresetConfig(name="preview", width=540, height=960, video_bitrate="1800k", audio_bitrate="96k"),
}


def build_render_args(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    crop_mode: CropMode,
    subtitle_path: Path | None,
    use_nvenc: bool,
    crop_offset_x: float = 0.0,
    crop_scale: float = 1.0,
    crop_keyframes: list[dict] | None = None,
    preset: RenderPresetConfig | None = None,
    loudnorm_filter: str = "loudnorm=I=-16:TP=-1.5:LRA=11",
    extra_video_filters: list[str] | None = None,
    audio_stream_index: int | None = None,
) -> list[str]:
    preset = preset or RENDER_PRESETS["youtube_shorts"]
    filters = [
        _crop_filter(
            crop_mode,
            crop_offset_x,
            crop_scale,
            crop_keyframes,
            width=preset.width,
            height=preset.height,
        )
    ]
    if subtitle_path is not None:
        filters.append(f"ass='{_escape_filter_path(subtitle_path)}'")
    filters.extend(extra_video_filters or [])
    encoder = "h264_nvenc" if use_nvenc else "libx264"
    duration = max(0.1, end_time - start_time)
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-ss",
        f"{start_time:.3f}",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        f"0:{audio_stream_index}" if audio_stream_index is not None else "0:a:0?",
        "-t",
        f"{duration:.3f}",
        "-vf",
        ",".join(filters),
        "-c:v",
        encoder,
        "-b:v",
        preset.video_bitrate,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        preset.audio_bitrate,
        "-af",
        loudnorm_filter,
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_loudnorm_analysis_args(
    ffmpeg_path: str,
    input_path: Path,
    start_time: float,
    end_time: float,
    audio_stream_index: int | None = None,
) -> list[str]:
    duration = max(0.1, end_time - start_time)
    return [
        ffmpeg_path,
        "-hide_banner",
        "-ss",
        f"{start_time:.3f}",
        "-i",
        str(input_path),
        "-map",
        f"0:{audio_stream_index}" if audio_stream_index is not None else "0:a:0?",
        "-t",
        f"{duration:.3f}",
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]


def parse_loudnorm_stats(stderr: str) -> dict | None:
    start = stderr.find("{")
    end = stderr.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None


def loudnorm_second_pass_filter(stats: dict | None) -> str:
    if not stats:
        return "loudnorm=I=-16:TP=-1.5:LRA=11"
    required = ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]
    if not all(key in stats for key in required):
        return "loudnorm=I=-16:TP=-1.5:LRA=11"
    return (
        "loudnorm=I=-16:TP=-1.5:LRA=11:"
        f"measured_I={stats['input_i']}:"
        f"measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:"
        f"measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true:print_format=summary"
    )


def build_cover_args(ffmpeg_path: str, input_path: Path, output_path: Path, at_seconds: float) -> list[str]:
    # input is the already-vertical rendered clip; just grab one frame.
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-ss",
        f"{at_seconds:.3f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(output_path),
    ]


def render_clip(
    ffmpeg_path: str,
    input_path: Path,
    output_dir: Path,
    slug: str,
    start_time: float,
    end_time: float,
    crop_mode: CropMode,
    subtitle_text: str | None,
    metadata: dict,
    crop_offset_x: float = 0.0,
    crop_scale: float = 1.0,
    crop_keyframes: list[dict] | None = None,
    use_nvenc: bool = False,
    preset_name: str = "youtube_shorts",
    loudnorm_two_pass: bool = False,
    extra_video_filters: list[str] | None = None,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
    audio_stream_index: int | None = None,
    face_detector_model: Path | None = None,
) -> RenderedArtifacts:
    warnings: list[str] = []
    logger.info(
        "Rendering clip: input=%s slug=%s start=%.3f end=%.3f preset=%s nvenc=%s subtitles=%s",
        input_path,
        slug,
        start_time,
        end_time,
        preset_name,
        use_nvenc,
        subtitle_text is not None,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = output_dir / f"{slug}.ass" if subtitle_text else None
    if subtitle_path is not None:
        write_text_atomically(subtitle_path, subtitle_text)
    output_path = output_dir / f"{slug}.mp4"
    temp_output = temp_sibling(output_path).with_suffix(".mp4")
    preset = RENDER_PRESETS.get(preset_name, RENDER_PRESETS["youtube_shorts"])
    loudnorm_filter = "loudnorm=I=-16:TP=-1.5:LRA=11"
    if loudnorm_two_pass:
        logger.info("Running loudnorm analysis pass: slug=%s", slug)
        analysis = runner(
            build_loudnorm_analysis_args(
                ffmpeg_path,
                input_path,
                start_time,
                end_time,
                audio_stream_index,
            ),
            1800,
        )
        stats = parse_loudnorm_stats(analysis.stderr) if analysis.returncode == 0 else None
        if stats is not None:
            loudnorm_filter = loudnorm_second_pass_filter(stats)
        else:
            logger.warning("loudnorm analysis failed, using single-pass loudnorm: slug=%s", slug)
            warnings.append("Двухпроходный loudnorm не дал результат — применён обычный одно­проходный.")
    def run_video_render(enable_nvenc: bool) -> ProcessResult:
        return runner(
            build_render_args(
                ffmpeg_path,
                input_path,
                temp_output,
                start_time,
                end_time,
                crop_mode,
                subtitle_path,
                enable_nvenc,
                crop_offset_x,
                crop_scale,
                crop_keyframes,
                preset=preset,
                loudnorm_filter=loudnorm_filter,
                extra_video_filters=extra_video_filters,
                audio_stream_index=audio_stream_index,
            ),
            3600,
        )

    result = run_video_render(use_nvenc)
    if result.returncode != 0 and use_nvenc:
        temp_output.unlink(missing_ok=True)
        logger.warning("NVENC render failed, retrying with libx264: slug=%s returncode=%s", slug, result.returncode)
        result = run_video_render(False)
    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        logger.warning("FFmpeg render failed: slug=%s returncode=%s", slug, result.returncode)
        raise RuntimeError(result.stderr.strip() or "FFmpeg не смог отрендерить клип")
    if temp_output.exists():
        replace_atomically(temp_output, output_path)
    cover_path = output_dir / f"{slug}.jpg"
    temp_cover = temp_sibling(cover_path).with_suffix(".jpg")
    # Pick the cover from the finished vertical clip: it is already cropped/tracked
    # and small, so this is one cheap decode instead of a second pass over the source.
    clip_duration = max(0.1, end_time - start_time)
    cover_at = select_cover_timestamp(output_path, 0.0, clip_duration, face_detector_model)
    cover_result = runner(build_cover_args(ffmpeg_path, output_path, temp_cover, cover_at), 120)
    if cover_result.returncode == 0 and temp_cover.exists():
        replace_atomically(temp_cover, cover_path)
    else:
        temp_cover.unlink(missing_ok=True)
        logger.warning("Cover generation failed: slug=%s returncode=%s", slug, cover_result.returncode)
        cover_path = None
    metadata_path = output_dir / f"{slug}.json"
    write_text_atomically(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    logger.info("Clip rendered: output=%s metadata=%s cover=%s", output_path, metadata_path, cover_path)
    return RenderedArtifacts(output_path, metadata_path, subtitle_path, cover_path, warnings)


def select_cover_timestamp(
    input_path: Path,
    start_time: float,
    end_time: float,
    face_detector_model: Path | None = None,
) -> float:
    duration = max(0.1, end_time - start_time)
    fallback = min(end_time - 0.05, start_time + min(1.0, duration / 2))
    try:
        import cv2

        capture = cv2.VideoCapture(str(input_path))
        if not capture.isOpened():
            return fallback
        detector = None
        if face_detector_model is not None and Path(face_detector_model).exists():
            try:
                detector = cv2.FaceDetectorYN.create(str(face_detector_model), "", (320, 320), 0.7, 0.3, 5000)
            except cv2.error:
                detector = None
        best: tuple[float, float] | None = None
        try:
            for index in range(7):
                timestamp = start_time + duration * (index + 1) / 8
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ok, frame = capture.read()
                if not ok:
                    continue
                height, width = frame.shape[:2]
                if width > 720:
                    scale = 720 / width
                    frame = cv2.resize(frame, (720, max(1, round(height * scale))))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                brightness = float(gray.mean())
                exposure = max(0.0, 1.0 - abs(brightness - 125.0) / 125.0)
                face_areas: list[float] = []
                if detector is not None:
                    detector.setInputSize((frame.shape[1], frame.shape[0]))
                    _, found = detector.detect(frame)
                    if found is not None:
                        for row in cast("list[Any]", found):  # cv2 returns an untyped ndarray
                            face_areas.append(float(row[2]) * float(row[3]))
                face_bonus = (max(face_areas, default=0.0) / max(1, gray.size)) * 5000
                edge_penalty = min(index, 6 - index) * 2
                score = sharpness + exposure * 35 + face_bonus + edge_penalty
                if best is None or score > best[0]:
                    best = (score, timestamp)
        finally:
            capture.release()
        return best[1] if best is not None else fallback
    except Exception:
        logger.debug("Cover timestamp face/sharpness selection failed, using fallback", exc_info=True)
        return fallback


def _crop_filter(
    crop_mode: CropMode,
    offset_x: float = 0.0,
    scale: float = 1.0,
    keyframes: list[dict] | None = None,
    width: int = 1080,
    height: int = 1920,
) -> str:
    offset_x = max(-1.0, min(1.0, offset_x))
    scale = max(1.0, min(2.0, scale))
    keyframes = smooth_crop_keyframes(keyframes or [])
    # A large, sharp window in the middle of the vertical canvas: at 1080x1920
    # it is 1080x1280, revealing 1.5x more of a landscape source than full-height
    # cropping. Zoom changes the crop inside that window, never its outer size.
    # The old blurred-background value remains a readable alias for centre mode.
    foreground_height = max(2, round(height * FOREGROUND_HEIGHT_FRACTION / 2) * 2)
    scaled_width = max(2, round(width * scale / 2) * 2)
    scaled_height = max(2, round(foreground_height * scale / 2) * 2)
    x_ratio = (offset_x + 1.0) / 2.0
    ratio_expression = (
        _tracking_ratio_expression(keyframes)
        if crop_mode == "auto-follow" and keyframes
        else f"{x_ratio:.4f}"
    )
    return (
        "split=2[base][fg];"
        f"[base]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma=28,lutrgb=r='val*0.65':g='val*0.65':b='val*0.65'[bg];"
        f"[fg]scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase:force_divisible_by=2,"
        f"crop={width}:{foreground_height}:x='max(0,min(iw-ow,(iw-ow)*({ratio_expression})))':y='(ih-oh)/2'[fit];"
        "[bg][fit]overlay=0:'(H-h)/2',setsar=1"
    )


# Keyframes closer together than this were a deliberate fast transition (a manual
# cut in the editor / a test) and skip the pan-rate rail.
_CUT_GAP_SECONDS = 0.12
# The face tracker already spring-smooths its trajectory; this clamp is only a
# rail against a corrupt keyframe teleporting the crop at a normal spacing. Well
# above the spring's own peak speed so it never touches a real reframe.
_MAX_PAN_PER_SECOND = 4.0


def smooth_crop_keyframes(keyframes: list[dict], max_step_per_second: float = _MAX_PAN_PER_SECOND) -> list[dict]:
    points: list[dict] = []
    last_offset: float | None = None
    last_time: float | None = None
    for item in sorted(keyframes, key=lambda value: float(value.get("time", 0))):
        try:
            timestamp = max(0.0, float(item["time"]))
            offset = max(-1.0, min(1.0, float(item["offset"])))
        except (KeyError, TypeError, ValueError):
            continue
        if last_offset is not None and last_time is not None:
            gap = timestamp - last_time
            if gap >= _CUT_GAP_SECONDS:
                max_step = max_step_per_second * gap
                offset = max(last_offset - max_step, min(last_offset + max_step, offset))
        if points and abs(points[-1]["time"] - timestamp) < 0.03:
            points[-1] = {"time": timestamp, "offset": round(offset, 4)}
        else:
            points.append({"time": timestamp, "offset": round(offset, 4)})
        last_offset = offset
        last_time = timestamp
    return _cap_keyframes(points)


# FFmpeg's expression evaluator falls over around a few KB regardless of shape;
# a smooth (pre-filtered) trajectory needs far fewer points than this anyway.
_MAX_RENDER_KEYFRAMES = 55


def _cap_keyframes(points: list[dict]) -> list[dict]:
    """Ramer-Douglas-Peucker: keep only points that bend the trajectory by more
    than `_RDP_EPSILON`, so a smooth curve collapses to its real turns and the
    FFmpeg crop expression stays short. A hard ceiling caps pathological input."""
    if len(points) < 3:
        return points
    last = len(points) - 1
    keep = {0, last}

    def worst(lo: int, hi: int) -> tuple[float, int]:
        t0, o0 = points[lo]["time"], points[lo]["offset"]
        span = (points[hi]["time"] - t0) or 1e-6
        slope = (points[hi]["offset"] - o0) / span
        wi, wd = -1, -1.0
        for i in range(lo + 1, hi):
            d = abs(points[i]["offset"] - (o0 + slope * (points[i]["time"] - t0)))
            if d > wd:
                wi, wd = i, d
        return wd, wi

    heap: list[tuple[float, int, int, int]] = []
    d, i = worst(0, last)
    if i >= 0:
        heapq.heappush(heap, (-d, i, 0, last))
    while heap:
        neg_d, idx, lo, hi = heapq.heappop(heap)
        if -neg_d < _RDP_EPSILON or len(keep) >= _MAX_RENDER_KEYFRAMES:
            break
        keep.add(idx)
        for a, b in ((lo, idx), (idx, hi)):
            if b - a >= 2:
                sub_d, sub_i = worst(a, b)
                if sub_i >= 0:
                    heapq.heappush(heap, (-sub_d, sub_i, a, b))
    return [points[i] for i in sorted(keep)]


# A kept keyframe must sit at least this far off the line through its neighbours;
# below it the segment is effectively straight and needs no inner point. The
# tracker's trajectory is already smooth, so this thins it to real turns.
_RDP_EPSILON = 0.012


def _tracking_ratio_expression(keyframes: list[dict]) -> str:
    """A flat sum of clamped ramps, not nested if()s: piecewise-linear
    interpolation of the keyframes whose expression length grows linearly and,
    crucially, has no recursion depth for FFmpeg's parser to choke on."""
    points: list[tuple[float, float]] = []
    for item in keyframes:
        try:
            timestamp = max(0.0, float(item["time"]))
            offset = max(-1.0, min(1.0, float(item["offset"])))
        except (KeyError, TypeError, ValueError):
            continue
        points.append((timestamp, (offset + 1.0) / 2.0))
    points.sort(key=lambda item: item[0])
    if not points:
        return "0.5000"
    if len(points) == 1:
        return f"{points[0][1]:.5f}"
    terms = [f"{points[0][1]:.5f}"]
    for (left_time, left_ratio), (right_time, right_ratio) in zip(points, points[1:]):
        duration = max(0.001, right_time - left_time)
        delta = right_ratio - left_ratio
        # clip((t - left)/duration, 0, 1): 0 before the segment, ramps to 1
        # across it, 1 after. Summed, these give the interpolated ratio.
        terms.append(f"({delta:.5f})*clip((t-{left_time:.3f})/{duration:.3f},0,1)")
    return "+".join(terms)


def _escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def detect_nvenc(ffmpeg_path: str, runner: Callable[[list[str], int], ProcessResult] = run_process) -> bool:
    try:
        result = runner([ffmpeg_path, "-hide_banner", "-encoders"], 30)
    except Exception:
        logger.debug("NVENC detection failed", exc_info=True)
        return False
    available = result.returncode == 0 and "h264_nvenc" in (result.stdout + result.stderr)
    logger.info("NVENC detection completed: available=%s", available)
    return available
