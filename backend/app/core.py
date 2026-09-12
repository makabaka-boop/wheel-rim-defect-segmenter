"""Core circular segmentation algorithm.

Angles use degrees and are represented as integers in the inclusive range
``0..359``. Clockwise adjacency therefore includes both ``(n, n + 1)`` and
``(359, 0)``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Reading:
    """One ultrasonic sample, with amplitude measured in millimetres.

    ``baseline`` is the optional per-angle coupling noise floor submitted by
    the inspector. When present, the amplitude used by the algorithm is
    ``max(0, amplitude - baseline)`` while the raw amplitude is kept for
    traceability.
    """

    angle: int
    amplitude: float
    baseline: float | None = None


@dataclass(frozen=True)
class Segment:
    """A clockwise continuous defective segment.

    ``peak_amplitude`` is the amplitude that drove peak selection, i.e. the
    corrected amplitude when a baseline was applied. ``peak_raw_amplitude``
    and ``peak_baseline`` are only populated in that case so the original
    reading stays traceable.
    """

    start_angle: int
    end_angle: int
    span: int
    peak_angle: int
    peak_amplitude: float
    angles: tuple[int, ...]
    peak_raw_amplitude: float | None = None
    peak_baseline: float | None = None


def corrected_amplitude(amplitude: float, baseline: float | None) -> float:
    """Return the amplitude used for threshold/segment/peak decisions."""

    if baseline is None:
        return amplitude
    # Decimal inputs such as 0.3 - 0.1 carry binary-float residue
    # (0.19999999999999998), which would wrongly push a threshold-exact point
    # just below the boundary. Round the residual away before clamping so a
    # corrected value mathematically equal to the threshold stays inclusive.
    return max(0.0, round(amplitude - baseline, 9))


def _validate_readings(readings: Sequence[Reading], threshold: float) -> list[float]:
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise ValueError("threshold must be a number")
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be a finite non-negative number")

    amplitudes: list[float | None] = [None] * 360
    for reading in readings:
        if not isinstance(reading, Reading):
            raise ValueError("each reading must be a Reading instance")
        if not isinstance(reading.angle, int) or isinstance(reading.angle, bool):
            raise ValueError("angle must be an integer")
        if not 0 <= reading.angle <= 359:
            raise ValueError(f"angle {reading.angle} is outside 0..359")
        if (
            not isinstance(reading.amplitude, (int, float))
            or isinstance(reading.amplitude, bool)
            or not math.isfinite(reading.amplitude)
            or reading.amplitude < 0
        ):
            raise ValueError(f"amplitude at angle {reading.angle} is invalid")
        if reading.baseline is not None and (
            not isinstance(reading.baseline, (int, float))
            or isinstance(reading.baseline, bool)
            or not math.isfinite(reading.baseline)
            or reading.baseline < 0
        ):
            raise ValueError(f"baseline at angle {reading.angle} is invalid")
        if amplitudes[reading.angle] is not None:
            raise ValueError(f"duplicate angle {reading.angle}")
        amplitudes[reading.angle] = corrected_amplitude(
            float(reading.amplitude),
            None if reading.baseline is None else float(reading.baseline),
        )

    if any(value is None for value in amplitudes):
        raise ValueError("readings must contain every angle from 0 to 359 exactly once")
    return [float(value) for value in amplitudes]


def find_segments(readings: Sequence[Reading], threshold: float) -> list[Segment]:
    """Return defective clockwise segments.

    A sample is defective when its amplitude is greater than or equal to
    ``threshold``. When a reading carries a baseline, the deciding amplitude
    is ``max(0, amplitude - baseline)``. For a non-full circle a segment
    starts at the first defective angle after a non-defective angle while
    moving clockwise. This makes a segment crossing zero start in the
    high-angle tail, for example ``358 -> 359 -> 0 -> 1``.
    """

    amplitudes = _validate_readings(readings, threshold)
    raw_by_angle = {reading.angle: float(reading.amplitude) for reading in readings}
    baseline_by_angle = {
        reading.angle: float(reading.baseline)
        for reading in readings
        if reading.baseline is not None
    }
    defective = [amplitude >= threshold for amplitude in amplitudes]

    def build_segment(start: int, end: int, angles: list[int]) -> Segment:
        # The explicit minimum angle resolves equal peak amplitudes even when
        # the clockwise traversal would meet the higher index first.
        peak_angle = min(angles, key=lambda angle: (-amplitudes[angle], angle))
        peak_baseline = baseline_by_angle.get(peak_angle)
        return Segment(
            start_angle=start,
            end_angle=end,
            span=len(angles),
            peak_angle=peak_angle,
            peak_amplitude=amplitudes[peak_angle],
            angles=tuple(angles),
            peak_raw_amplitude=raw_by_angle[peak_angle] if peak_baseline is not None else None,
            peak_baseline=peak_baseline,
        )

    if all(defective):
        return [build_segment(0, 359, list(range(360)))]

    starts = [
        angle
        for angle in range(360)
        if defective[angle] and not defective[(angle - 1) % 360]
    ]

    segments: list[Segment] = []
    for start in starts:
        angles: list[int] = []
        current = start
        while defective[current]:
            angles.append(current)
            current = (current + 1) % 360

        segments.append(build_segment(start, angles[-1], angles))

    return segments
