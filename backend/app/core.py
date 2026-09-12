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
    """One ultrasonic sample, with amplitude measured in millimetres."""

    angle: int
    amplitude: float


@dataclass(frozen=True)
class Segment:
    """A clockwise continuous defective segment."""

    start_angle: int
    end_angle: int
    span: int
    peak_angle: int
    peak_amplitude: float
    angles: tuple[int, ...]


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
        if amplitudes[reading.angle] is not None:
            raise ValueError(f"duplicate angle {reading.angle}")
        amplitudes[reading.angle] = float(reading.amplitude)

    if any(value is None for value in amplitudes):
        raise ValueError("readings must contain every angle from 0 to 359 exactly once")
    return [float(value) for value in amplitudes]


def find_segments(readings: Sequence[Reading], threshold: float) -> list[Segment]:
    """Return defective clockwise segments.

    A sample is defective when its amplitude is greater than or equal to
    ``threshold``. For a non-full circle a segment starts at the first
    defective angle after a non-defective angle while moving clockwise. This
    makes a segment crossing zero start in the high-angle tail, for example
    ``358 -> 359 -> 0 -> 1``.
    """

    amplitudes = _validate_readings(readings, threshold)
    defective = [amplitude >= threshold for amplitude in amplitudes]

    if all(defective):
        peak_angle = min(range(360), key=lambda angle: (-amplitudes[angle], angle))
        return [
            Segment(
                start_angle=0,
                end_angle=359,
                span=360,
                peak_angle=peak_angle,
                peak_amplitude=amplitudes[peak_angle],
                angles=tuple(range(360)),
            )
        ]

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

        # The explicit minimum angle resolves equal peak amplitudes even when
        # the clockwise traversal would meet the higher index first.
        peak_angle = min(angles, key=lambda angle: (-amplitudes[angle], angle))
        segments.append(
            Segment(
                start_angle=start,
                end_angle=angles[-1],
                span=len(angles),
                peak_angle=peak_angle,
                peak_amplitude=amplitudes[peak_angle],
                angles=tuple(angles),
            )
        )

    return segments
