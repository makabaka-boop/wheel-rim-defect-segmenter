"""Core circular segmentation algorithm.

Angles use degrees and are represented as integers in the inclusive range
``0..359``. Clockwise adjacency therefore includes both ``(n, n + 1)`` and
``(359, 0)``.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal
import math

# Inputs may arrive as int, float (direct callers/tests) or Decimal (decoded
# from JSON with decimal-exact parsing).
Number = Decimal | float | int


def _to_decimal(value: Number) -> Decimal:
    # Going through ``str`` gives binary floats their intended decimal value
    # (0.3 instead of 0.2999999999999999888977...), which is what the inspector
    # typed into the payload.
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    try:
        return math.isfinite(value)  # type: ignore[arg-type]
    except OverflowError:
        # Decimals larger than the float range raise instead of returning False.
        return False


@dataclass(frozen=True)
class Reading:
    """One ultrasonic sample, with amplitude measured in millimetres.

    ``baseline`` is the optional per-angle coupling noise floor submitted by
    the inspector. When present, the amplitude used by the algorithm is
    ``max(0, amplitude - baseline)`` while the raw amplitude is kept for
    traceability.
    """

    angle: int
    amplitude: Number
    baseline: Number | None = None


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
    peak_amplitude: Number
    angles: tuple[int, ...]
    peak_raw_amplitude: Number | None = None
    peak_baseline: Number | None = None


def corrected_amplitude(amplitude: Number, baseline: Number | None) -> Number:
    """Return the amplitude used for threshold/segment/peak decisions.

    With a baseline the subtraction runs in exact decimal arithmetic so a
    corrected value that exceeds the threshold by a tiny margin (even below
    one billionth) is kept instead of being rounded onto a coarser grid and
    missed. Without a baseline the original value passes through unchanged.
    """

    if baseline is None:
        return amplitude
    difference = _to_decimal(amplitude) - _to_decimal(baseline)
    return difference if difference > 0 else Decimal("0")


def _validate_readings(readings: Sequence[Reading], threshold: Number) -> list[Number]:
    if not isinstance(threshold, (int, float, Decimal)) or isinstance(threshold, bool):
        raise ValueError("threshold must be a number")
    if not _is_finite_number(threshold) or threshold < 0:
        raise ValueError("threshold must be a finite non-negative number")

    amplitudes: list[Number | None] = [None] * 360
    for reading in readings:
        if not isinstance(reading, Reading):
            raise ValueError("each reading must be a Reading instance")
        if not isinstance(reading.angle, int) or isinstance(reading.angle, bool):
            raise ValueError("angle must be an integer")
        if not 0 <= reading.angle <= 359:
            raise ValueError(f"angle {reading.angle} is outside 0..359")
        if not _is_finite_number(reading.amplitude) or reading.amplitude < 0:
            raise ValueError(f"amplitude at angle {reading.angle} is invalid")
        if reading.baseline is not None and (
            not _is_finite_number(reading.baseline) or reading.baseline < 0
        ):
            raise ValueError(f"baseline at angle {reading.angle} is invalid")
        if amplitudes[reading.angle] is not None:
            raise ValueError(f"duplicate angle {reading.angle}")
        amplitudes[reading.angle] = corrected_amplitude(reading.amplitude, reading.baseline)

    if any(value is None for value in amplitudes):
        raise ValueError("readings must contain every angle from 0 to 359 exactly once")
    return list(amplitudes)


def _validate_occluded(occluded: Collection[int] | None) -> frozenset[int]:
    """Return the confirmed unreadable display angles as a set.

    Occluded points (bolt holes, fixture shadows) are excluded from the ring
    segmentation: they never count as defective and segments cannot connect
    across them.
    """

    if occluded is None:
        return frozenset()
    angles: set[int] = set()
    for angle in occluded:
        if not isinstance(angle, int) or isinstance(angle, bool):
            raise ValueError("occluded angle must be an integer")
        if not 0 <= angle <= 359:
            raise ValueError(f"occluded angle {angle} is outside 0..359")
        angles.add(angle)
    return frozenset(angles)


def find_segments(
    readings: Sequence[Reading],
    threshold: Number,
    occluded: Collection[int] | None = None,
) -> list[Segment]:
    """Return defective clockwise segments.

    A sample is defective when its amplitude is greater than or equal to
    ``threshold``. When a reading carries a baseline, the deciding amplitude
    is ``max(0, amplitude - baseline)`` evaluated in exact decimal
    arithmetic; likewise a float threshold is read as its decimal value so
    boundary equality stays exact. For a non-full circle a segment starts at
    the first defective angle after a non-defective angle while moving
    clockwise. This makes a segment crossing zero start in the high-angle
    tail, for example ``358 -> 359 -> 0 -> 1``.

    ``occluded`` holds confirmed unreadable display angles. They are treated
    as non-defective gaps: their amplitudes never enter any segment and a
    segment never connects across them, so a single occluded point splits a
    formerly continuous run deterministically.
    """

    # Compare in decimal space whenever baseline compensation is involved so
    # float residue cannot flip boundary decisions; the legacy float-only
    # path keeps native float comparisons.
    baseline_applied = any(reading.baseline is not None for reading in readings)
    compare_threshold = (
        _to_decimal(threshold) if baseline_applied and not isinstance(threshold, Decimal)
        else threshold
    )
    amplitudes = _validate_readings(readings, threshold)
    occluded_angles = _validate_occluded(occluded)
    raw_by_angle = {reading.angle: reading.amplitude for reading in readings}
    baseline_by_angle = {
        reading.angle: reading.baseline
        for reading in readings
        if reading.baseline is not None
    }
    defective = [
        amplitude >= compare_threshold and angle not in occluded_angles
        for angle, amplitude in enumerate(amplitudes)
    ]

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
