from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np

from app.media.character_recognition import (
    CharacterProfile,
    FaceObservation,
    LocalFaceRecognizer,
    best_character_match,
    build_reference_vectors,
    mouth_motion_score,
)


@dataclass(frozen=True)
class SpeechRange:
    start_time: float
    end_time: float
    source_label: str | None = None
    character_id: int | None = None


@dataclass(frozen=True)
class FaceTrackingResult:
    offset_x: float
    faces_detected: int
    frames_sampled: int
    keyframes: list[dict[str, float]]
    active_speaker_frames: int
    identified_speaker_frames: int
    lip_motion_frames: int
    face_model: str
    held_frames: int
    largest_face_frames: int
    average_confidence: float
    face_detection_available: bool = True


# Kept for the render/preview contract: keyframes closer than this were a hard
# cut. The tracker no longer emits them — it glides — but downstream code and a
# few callers still import the name.
CUT_GAP_SECONDS = 0.08
# A speaker turn shorter than this (backchannel "да", "угу") is folded into the
# surrounding shot instead of pulling the camera away and back.
_MIN_DWELL_SECONDS = 0.7
# A lip-motion winner must beat the runner-up face by this margin to be trusted
# for a frame-level switch (aggregate voting uses a lower bar).
_LIP_REL_MARGIN = 0.06
# Fraction of a run's samples that must resolve to a real talking subject for the
# shot to frame that face; below this the shot is just centred.
_CONFIDENT_RUN_FRACTION = 0.34
# Frame the face this far toward dead-centre of the window (1.0 = perfectly
# centred). Under 1 keeps the pans gentle and less sensitive to detector wobble.
_CENTERING_FRACTION = 0.7
# Zero-lag pre-smoothing of the raw face track: a centred moving average this
# wide (seconds) wipes out detector jitter before anything else touches it.
_PRESMOOTH_SECONDS = 0.9
# Then a critically-damped spring adds the operator feel: a calm ~0.9 s settle
# on a speaker change, no overshoot, and it glues to a steady face.
_FOLLOW_FREQ_HZ = 0.62
# Trajectory is resampled onto this grid so the render's piecewise-linear
# interpolation between keyframes has no visible corners.
_GRID_SECONDS = 0.10
# Emit a keyframe once the smoothed crop has moved this much, or after a gap.
# The render pass thins further (RDP); this just keeps the stored list sane.
_EMIT_DELTA = 0.02
_EMIT_MAX_GAP = 2.0


def estimate_face_offset(
    video_path: Path,
    start_time: float,
    end_time: float,
    samples: int | None = None,
    speech_ranges: list[SpeechRange] | None = None,
    character_profiles: list[CharacterProfile] | None = None,
    detector_model: Path | None = None,
    recognizer_model: Path | None = None,
    audio_path: Path | None = None,
) -> FaceTrackingResult:
    import cv2

    engine = LocalFaceRecognizer(detector_model, recognizer_model)
    if not engine.can_detect:
        # No YuNet/SFace weights and this OpenCV build has no Haar fallback:
        # there is nothing to track, so say so instead of silently centering.
        return FaceTrackingResult(
            offset_x=0.0,
            faces_detected=0,
            frames_sampled=0,
            keyframes=[],
            active_speaker_frames=0,
            identified_speaker_frames=0,
            lip_motion_frames=0,
            face_model=engine.model_name,
            held_frames=0,
            largest_face_frames=0,
            average_confidence=0.0,
            face_detection_available=False,
        )
    ranges = list(speech_ranges or [])
    references = build_reference_vectors(engine, character_profiles or [])
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Не удалось открыть видео для анализа лиц")

    sample_times = _sample_times(start_time, end_time, ranges, samples)
    audio = _load_audio(audio_path)
    wanted = sample_times + [max(start_time, t - 0.1) for t in sample_times]
    frames = _prefetch_frames(capture, wanted, cv2)
    _seed = next(iter(frames.values()), None)
    source_aspect = (_seed.shape[1] / _seed.shape[0]) if _seed is not None else 16 / 9

    samples_data: list[_Sample] = []
    faces_detected = 0
    tracker = _CentroidTracker()
    try:
        for timestamp in sample_times:
            current = frames.get(round(timestamp, 2))
            previous = frames.get(round(max(start_time, timestamp - 0.1), 2))
            if current is None:
                continue
            width = current.shape[1]
            current_faces = engine.detect(current)
            faces_detected += len(current_faces)
            rel_time = round(timestamp - start_time, 3)
            active = _active_speech(timestamp, ranges)
            audio_energy = _audio_activity(audio, timestamp)
            if not current_faces:
                samples_data.append(_Sample(rel_time, [], [], [], {}, active, audio_energy, None))
                continue

            centers = [face.center_x / max(1, width) for face in current_faces]
            areas = [float(face.width * face.height) for face in current_faces]
            track_ids = tracker.assign(centers)
            lip_scores: dict[int, float] = {}
            if previous is not None:
                previous_faces = engine.detect(previous)
                if previous_faces:
                    for index, face in enumerate(current_faces):
                        near = min(
                            previous_faces,
                            key=lambda p: np.hypot(face.center_x - p.center_x, face.center_y - p.center_y),
                        )
                        diag = float(np.hypot(current.shape[1], current.shape[0]))
                        if float(np.hypot(face.center_x - near.center_x, face.center_y - near.center_y)) / diag <= 0.2:
                            lip_scores[index] = mouth_motion_score(current, face, previous, near, cv2)

            identified_center: float | None = None
            if active is not None and active.character_id is not None and references:
                selected, _ = _face_for_character(current_faces, references, active.character_id)
                if selected is not None:
                    identified_center = selected.center_x / max(1, width)

            samples_data.append(
                _Sample(
                    rel_time=rel_time,
                    centers=centers,
                    areas=areas,
                    track_ids=track_ids,
                    lip_scores=lip_scores,
                    active=active,
                    audio_energy=audio_energy,
                    identified_center=identified_center,
                )
            )
    finally:
        capture.release()

    label_positions = _aggregate_label_positions(samples_data)
    keyframes, stats = _build_trajectory(samples_data, label_positions, source_aspect)

    return FaceTrackingResult(
        offset_x=round(float(median(k["offset"] for k in keyframes)) if keyframes else 0.0, 3),
        faces_detected=faces_detected,
        frames_sampled=sum(1 for s in samples_data if s.centers),
        keyframes=keyframes,
        active_speaker_frames=stats["active_speaker"],
        identified_speaker_frames=stats["identified"],
        lip_motion_frames=stats["lip"],
        face_model=engine.model_name,
        held_frames=stats["held"],
        largest_face_frames=stats["largest"],
        average_confidence=round(stats["avg_lip"], 3),
    )


@dataclass
class _Sample:
    rel_time: float
    centers: list[float]  # face x-centres, 0..1
    areas: list[float]  # face pixel areas, same order as centers
    track_ids: list[int]  # persistent per-face id, same order as centers
    lip_scores: dict[int, float]  # index into centers -> mouth-motion score
    active: SpeechRange | None
    audio_energy: float
    identified_center: float | None


class _CentroidTracker:
    """Cheap nearest-centroid face tracker: keeps one id per person across
    samples so the trajectory only cuts when the *subject* changes, not when a
    single moving face crosses a spatial bucket."""

    def __init__(self, max_jump: float = 0.16) -> None:
        self._max_jump = max_jump
        self._next_id = 0
        self._tracks: list[tuple[int, float]] = []  # (id, last_center)

    def assign(self, centers: list[float]) -> list[int]:
        result: list[int] = []
        available = list(self._tracks)
        for center in centers:
            best = None
            for track in available:
                gap = abs(track[1] - center)
                if gap <= self._max_jump and (best is None or gap < abs(best[1] - center)):
                    best = track
            if best is not None:
                available.remove(best)
                result.append(best[0])
            else:
                result.append(self._next_id)
                self._next_id += 1
        self._tracks = list(zip(result, centers))
        return result


def _sample_times(
    start_time: float, end_time: float, ranges: list[SpeechRange], samples: int | None
) -> list[float]:
    """A steady cadence plus a tight cluster right after every speech-segment
    start, so a cut to the next speaker is caught within ~0.1 s instead of a
    frame or more late."""
    duration = max(0.1, end_time - start_time)
    # ~5 detections/s: dense enough that the raw face track is a curve, not steps.
    base_n = samples or min(360, max(40, round(duration * 5.0)))
    times = {start_time + duration * (index + 0.5) / base_n for index in range(base_n)}
    for item in ranges:
        segment_start = max(start_time, item.start_time)
        if segment_start >= end_time:
            continue
        for delta in (0.12, 0.32, 0.6):
            probe = segment_start + delta
            if start_time < probe < end_time:
                times.add(probe)
    return sorted(times)


def _bucket(center: float) -> int:
    return int(round(center * 6))


def _aggregate_label_positions(samples: list[_Sample]) -> dict[str, float]:
    """Per-clip vote: which screen position does each diarised speaker label
    occupy? Aggregating the lip-motion winner over all of a label's segments is
    far steadier than trusting any single frame."""
    votes: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    centers: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        if sample.active is None or sample.active.source_label is None:
            continue
        if sample.audio_energy < 0.12 or not sample.lip_scores:
            continue
        winner_index = max(sample.lip_scores, key=sample.lip_scores.get)
        score = sample.lip_scores[winner_index]
        if score <= 0.0:
            continue
        label = sample.active.source_label
        bucket = _bucket(sample.centers[winner_index])
        weight = score * sample.audio_energy
        votes[label][bucket] += weight
        centers[label][bucket].append(sample.centers[winner_index])
    positions: dict[str, float] = {}
    for label, bucket_votes in votes.items():
        ranked = sorted(bucket_votes.items(), key=lambda kv: kv[1], reverse=True)
        top_bucket, top_weight = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_weight < 0.03 or top_weight < runner_up * 1.4:
            continue
        positions[label] = float(median(centers[label][top_bucket]))
    return positions


def _nearest_center(centers: list[float], target: float) -> tuple[int, float] | None:
    if not centers:
        return None
    index = min(range(len(centers)), key=lambda i: abs(centers[i] - target))
    return index, centers[index]


@dataclass
class _Point:
    rel_time: float
    target: float
    owner: str | None
    kind: str
    lip: float


def _build_trajectory(
    samples: list[_Sample], label_positions: dict[str, float], source_aspect: float = 16 / 9
) -> tuple[list[dict[str, float]], dict[str, float]]:
    stats = {k: 0.0 for k in ("active_speaker", "identified", "lip", "held", "largest", "avg_lip")}

    # Pass 1 — per-sample intent.
    points: list[_Point] = []
    for sample in samples:
        prev_target = points[-1].target if points else None
        prev_owner = points[-1].owner if points else None
        target, owner, kind = _resolve_target(sample, label_positions, prev_target, prev_owner)
        if target is None:
            if not points:
                continue
            target, owner, kind = points[-1].target, points[-1].owner, "held"
        points.append(
            _Point(sample.rel_time, target, owner, kind, max(sample.lip_scores.values(), default=0.0))
        )
    if not points:
        return [], stats

    # Pass 2 — group into owner runs, then fold away runs shorter than the
    # minimum on-screen dwell so a one-word interjection never yanks the camera.
    runs: list[list[int]] = []
    for index, point in enumerate(points):
        if runs and points[runs[-1][0]].owner == point.owner:
            runs[-1][1] = index
        else:
            runs.append([index, index])
    kept: list[list[int]] = []
    for run in runs:
        span = points[run[1]].rel_time - points[run[0]].rel_time
        long_enough = span >= _MIN_DWELL_SECONDS
        if kept and not long_enough:
            anchor = points[kept[-1][1]].target
            for i in range(run[0], run[1] + 1):
                points[i] = _Point(points[i].rel_time, anchor, points[kept[-1][0]].owner,
                                   "held", points[i].lip)
            kept[-1][1] = run[1]
        else:
            kept.append(run)

    # Pass 3 — smooth follow. Per-sample target (the tracked face centre for a
    # confident run, the frame centre otherwise), resampled onto a fine even grid
    # and pushed through a One-Euro filter: heavy smoothing while the face is
    # still (no detector jitter reaches the crop), light while it moves (the crop
    # stays glued). No dead zone, no cuts — one continuous fluid trajectory.
    raw: list[tuple[float, float]] = []
    for start, end in kept:
        run = points[start : end + 1]
        talking = sum(1 for p in run if p.kind in ("identified", "active_speaker", "lip"))
        confident = talking >= max(1, round(len(run) * _CONFIDENT_RUN_FRACTION))
        for point in run:
            centre = point.target if confident else 0.5
            raw.append((point.rel_time, _center_offset(centre, source_aspect)))
            _tally(stats, point.kind)
    stats["avg_lip"] = sum(p.lip for p in points) / len(points) if points else 0.0
    if not raw:
        return [], stats

    grid = _resample_even(raw, _GRID_SECONDS)
    window = max(1, round(_PRESMOOTH_SECONDS / _GRID_SECONDS) | 1)  # odd
    values = _moving_average([v for _, v in grid], window)
    smoothed = _critically_damped(values, _GRID_SECONDS, _FOLLOW_FREQ_HZ)

    keyframes: list[dict[str, float]] = []
    last_x: float | None = None
    last_t: float | None = None
    for (rel_time, _), x in zip(grid, smoothed):
        x = max(-1.0, min(1.0, x))
        if (
            last_x is None
            or last_t is None
            or abs(x - last_x) >= _EMIT_DELTA
            or rel_time - last_t >= _EMIT_MAX_GAP
        ):
            keyframes.append(_kf_offset(rel_time, x, 0.0))
            last_x, last_t = x, rel_time
    if last_t is not None and grid[-1][0] - last_t > 0.01:
        keyframes.append(_kf_offset(grid[-1][0], max(-1.0, min(1.0, smoothed[-1])), 0.0))
    return _dedupe_keyframes(keyframes), stats


def _resample_even(series: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """Linear-interpolate an unevenly sampled (time, value) series onto a fixed grid."""
    t0, t1 = series[0][0], series[-1][0]
    if t1 - t0 < step or len(series) < 2:
        return list(series)
    out: list[tuple[float, float]] = []
    j = 0
    t = t0
    while t <= t1 + 1e-6:
        while j + 1 < len(series) and series[j + 1][0] < t:
            j += 1
        (ta, va), (tb, vb) = series[j], series[min(j + 1, len(series) - 1)]
        r = 0.0 if tb == ta else max(0.0, min(1.0, (t - ta) / (tb - ta)))
        out.append((round(t, 3), va + (vb - va) * r))
        t += step
    return out


def _moving_average(values: list[float], window: int) -> list[float]:
    """Centred (zero-lag) moving average; edges shrink the window."""
    if window <= 1 or len(values) <= 2:
        return list(values)
    half = window // 2
    out: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _critically_damped(values: list[float], dt: float, freq_hz: float) -> list[float]:
    """Run a no-overshoot spring over a value grid: adds the operator settle and
    the swing on a speaker change without ever passing the target."""
    omega = 2.0 * math.pi * freq_hz
    decay = math.exp(-omega * dt)
    x, v = values[0], 0.0
    out = [x]
    for goal in values[1:]:
        y0 = x - goal
        c = v + omega * y0
        x = goal + (y0 + c * dt) * decay
        v = (v - omega * c * dt) * decay
        out.append(x)
    return out


def _center_offset(centre: float, source_aspect: float = 16 / 9) -> float:
    """Crop pan (-1..1) that sits a face at source-x ``centre`` in the middle of
    the 1080x1280 foreground window (rendering.FOREGROUND_HEIGHT_FRACTION)."""
    window_w, window_h = 1080.0, 1280.0
    scaled_w = max(window_w, window_h * max(0.2, source_aspect))
    span = scaled_w - window_w
    if span < 1.0:  # portrait source — horizontal barely moves
        return max(-1.0, min(1.0, (centre - 0.5) * 2.0))
    perfect_centre_gain = 2.0 * scaled_w / span
    gain = min(4.0, _CENTERING_FRACTION * perfect_centre_gain)
    return max(-1.0, min(1.0, (centre - 0.5) * gain))


def _dedupe_keyframes(keyframes: list[dict[str, float]]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for kf in sorted(keyframes, key=lambda k: k["time"]):
        if out and abs(out[-1]["time"] - kf["time"]) < 0.02 and abs(out[-1]["offset"] - kf["offset"]) < 0.02:
            continue
        out.append(kf)
    return out


def _resolve_target(
    sample: _Sample,
    label_positions: dict[str, float],
    current: float | None,
    owner: str | None,
) -> tuple[float | None, str | None, str]:
    if not sample.centers:
        return None, None, "held"

    # 1. Confirmed character (photo/voiceprint match) — strongest signal.
    if sample.identified_center is not None:
        return sample.identified_center, f"id:{sample.active.character_id}", "identified"

    # 2. Diarised speaker label with a confident per-clip position: follow the
    #    face nearest that position so a slow drift still tracks it.
    if sample.active is not None and sample.active.source_label in label_positions:
        anchor = label_positions[sample.active.source_label]
        near = _nearest_center(sample.centers, anchor)
        center = near[1] if near is not None and abs(near[1] - anchor) < 0.22 else anchor
        return center, f"label:{sample.active.source_label}", "active_speaker"

    # 3. This frame's lip-motion winner, if it clearly beats the other faces.
    if sample.active is not None and sample.audio_energy >= 0.15 and len(sample.lip_scores) >= 1:
        ranked = sorted(sample.lip_scores.items(), key=lambda kv: kv[1], reverse=True)
        best_index, best_score = ranked[0]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score > 0.008 and best_score >= runner + _LIP_REL_MARGIN:
            return sample.centers[best_index], _track_owner(sample, best_index), "lip"

    # 4. Hold on the face we are already following (matched by its track id), or
    #    failing that the nearest face, so a single moving person keeps one owner.
    if current is not None:
        held = _index_for_owner(sample, owner)
        if held is None:
            near = _nearest_center(sample.centers, current)
            held = near[0] if near is not None and abs(near[1] - current) <= 0.2 else None
        if held is not None:
            return sample.centers[held], _track_owner(sample, held), "held"

    # 5. Nothing better: the biggest face on screen.
    if sample.areas:
        widest = max(range(len(sample.centers)), key=lambda i: sample.areas[i])
    else:
        widest = min(range(len(sample.centers)), key=lambda i: abs(sample.centers[i] - 0.5))
    return sample.centers[widest], _track_owner(sample, widest), "largest"


def _track_owner(sample: _Sample, index: int) -> str:
    if 0 <= index < len(sample.track_ids):
        return f"track:{sample.track_ids[index]}"
    return f"pos:{_bucket(sample.centers[index])}"


def _index_for_owner(sample: _Sample, owner: str | None) -> int | None:
    if owner is None or not owner.startswith("track:"):
        return None
    try:
        track_id = int(owner.split(":", 1)[1])
    except ValueError:
        return None
    for index, value in enumerate(sample.track_ids):
        if value == track_id:
            return index
    return None


def _tally(stats: dict[str, float], kind: str) -> None:
    stats[{
        "identified": "identified",
        "active_speaker": "active_speaker",
        "lip": "lip",
        "held": "held",
        "largest": "largest",
    }.get(kind, "held")] += 1


def _kf_offset(rel_time: float, offset: float, lip: float) -> dict[str, float]:
    return {
        "time": round(max(0.0, rel_time), 3),
        "offset": round(max(-1.0, min(1.0, offset)), 3),
        "lip_activity": round(max(0.0, lip), 3),
    }


def _load_audio(audio_path: Path | None):
    if audio_path is None or not audio_path.exists():
        return None
    try:
        from app.media.speakers import _read_mono_pcm

        return _read_mono_pcm(audio_path)
    except Exception:
        return None


def _audio_activity(audio, timestamp: float) -> float:
    if audio is None:
        return 1.0
    sample_rate, samples = audio
    left = max(0, round((timestamp - 0.12) * sample_rate))
    right = min(len(samples), round((timestamp + 0.12) * sample_rate))
    if right <= left:
        return 0.0
    energy = float(np.sqrt(np.mean(samples[left:right] ** 2)))
    return max(0.0, min(1.0, energy / 0.025))


def _active_speech(timestamp: float, ranges: list[SpeechRange]) -> SpeechRange | None:
    active = [item for item in ranges if item.start_time - 0.08 <= timestamp <= item.end_time + 0.08]
    if not active:
        return None
    identified = [item for item in active if item.character_id is not None]
    candidates = identified or active
    return min(candidates, key=lambda item: item.end_time - item.start_time)


def _face_for_character(
    faces: list[FaceObservation],
    references: list[tuple[int, str, np.ndarray]],
    character_id: int,
) -> tuple[FaceObservation | None, float]:
    matches: list[tuple[FaceObservation, float]] = []
    for face in faces:
        match = best_character_match(face.embedding, references, character_id=character_id)
        if match is not None:
            matches.append((face, match[2]))
    if not matches:
        return None, 0.0
    return max(matches, key=lambda item: item[1])


def _downscale720(frame, cv2_module):
    height, width = frame.shape[:2]
    if width > 720:
        scale = 720 / width
        return cv2_module.resize(frame, (720, max(1, round(height * scale))))
    return frame


def _prefetch_frames(capture, timestamps: list[float], cv2_module) -> dict[float, object]:
    """One sequential decode over the sampled window instead of ~2N keyframe seeks.

    `CAP_PROP_POS_MSEC` seeking re-decodes from the nearest keyframe every call,
    which is slow on long-GOP H.264. Here we seek once to the first wanted
    timestamp and read forward, `retrieve()`-ing only the frames we need.
    """
    wanted = sorted({round(t, 2) for t in timestamps})
    if not wanted:
        return {}
    fps = float(capture.get(cv2_module.CAP_PROP_FPS) or 0.0) or 25.0
    # Track position by frame index (increments reliably on grab() on every
    # backend, unlike CAP_PROP_POS_MSEC).
    capture.set(cv2_module.CAP_PROP_POS_FRAMES, max(0, int(wanted[0] * fps)))
    frame_no = int(capture.get(cv2_module.CAP_PROP_POS_FRAMES) or 0)  # where the seek actually landed
    start_frame = frame_no
    wanted_frames = [max(0, int(round(t * fps))) for t in wanted]
    out: dict[float, object] = {}
    index = 0
    guard = 0
    max_reads = (wanted_frames[-1] - start_frame) + len(wanted) + 64
    while index < len(wanted) and guard < max_reads:
        guard += 1
        if not capture.grab():
            break
        if frame_no < wanted_frames[index]:
            frame_no += 1
            continue
        ok, frame = capture.retrieve()
        scaled = _downscale720(frame, cv2_module) if ok and frame is not None else None
        while index < len(wanted) and frame_no >= wanted_frames[index]:
            if scaled is not None:
                out[wanted[index]] = scaled
            index += 1
        frame_no += 1
    return out
