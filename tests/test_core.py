import math

import pytest

from app.core import Reading, find_segments


def make_readings(values: dict[int, float] | None = None, default: float = 0.0) -> list[Reading]:
    values = values or {}
    return [Reading(angle=angle, amplitude=float(values.get(angle, default))) for angle in range(360)]


def test_threshold_is_inclusive_at_fixed_zero_boundary():
    readings = make_readings({0: 2.0})

    segments = find_segments(readings, 2.0)

    assert len(segments) == 1
    assert segments[0].start_angle == 0
    assert segments[0].end_angle == 0
    assert segments[0].span == 1
    assert segments[0].peak_angle == 0
    assert segments[0].peak_amplitude == 2.0
    assert segments[0].angles == (0,)


def test_non_defective_samples_return_no_segments():
    assert find_segments(make_readings(default=0.99), 1.0) == []


def test_wrapping_segment_has_one_clockwise_start_and_mergeable_span():
    readings = make_readings(
        {
            357: 1.1,
            358: 3.2,
            359: 4.4,
            0: 5.6,
            1: 4.2,
            2: 3.8,
            3: 0.2,
            356: 0.1,
        }
    )

    segments = find_segments(readings, 2.5)

    assert len(segments) == 1
    segment = segments[0]
    assert segment.start_angle == 358
    assert segment.end_angle == 2
    assert segment.span == 5
    assert segment.angles == (358, 359, 0, 1, 2)
    assert segment.peak_angle == 0
    assert segment.peak_amplitude == 5.6


def test_adjacent_boundary_359_to_0_is_connected():
    readings = make_readings({359: 1.0, 0: 1.0, 1: 0.0, 358: 0.0})

    segments = find_segments(readings, 1.0)

    assert len(segments) == 1
    assert segments[0].start_angle == 359
    assert segments[0].end_angle == 0
    assert segments[0].span == 2
    assert segments[0].angles == (359, 0)


def test_adjacent_boundary_0_to_1_starts_at_zero():
    readings = make_readings({0: 1.0, 1: 1.0, 359: 0.0, 2: 0.0})

    segments = find_segments(readings, 1.0)

    assert len(segments) == 1
    assert segments[0].start_angle == 0
    assert segments[0].end_angle == 1
    assert segments[0].span == 2
    assert segments[0].angles == (0, 1)


def test_normal_and_wrapping_segments_remain_distinct():
    readings = make_readings({10: 2.0, 11: 3.0, 12: 2.0, 359: 4.0, 0: 5.0})

    segments = find_segments(readings, 2.0)

    assert [(segment.start_angle, segment.end_angle, segment.span) for segment in segments] == [
        (10, 12, 3),
        (359, 0, 2),
    ]
    assert segments[0].peak_angle == 11
    assert segments[1].peak_angle == 0


def test_equal_peak_amplitudes_selects_smallest_angle_including_wrap():
    readings = make_readings({359: 3.0, 0: 3.0, 1: 2.0})

    segments = find_segments(readings, 2.0)

    assert len(segments) == 1
    assert segments[0].peak_angle == 0
    assert segments[0].peak_amplitude == 3.0


def test_full_circle_has_single_unique_zero_to_359_result():
    readings = make_readings(default=2.5)

    segments = find_segments(readings, 2.5)

    assert len(segments) == 1
    segment = segments[0]
    assert segment.start_angle == 0
    assert segment.end_angle == 359
    assert segment.span == 360
    assert segment.angles == tuple(range(360))


def test_full_circle_equal_peak_uses_smallest_angle():
    readings = make_readings(default=1.0)

    segment = find_segments(readings, 1.0)[0]

    assert segment.peak_angle == 0
    assert segment.peak_amplitude == 1.0


def test_core_rejects_missing_duplicate_out_of_range_and_illegal_amplitude():
    with pytest.raises(ValueError, match="every angle"):
        find_segments([Reading(angle=angle, amplitude=0.0) for angle in range(359)], 1.0)

    duplicate = make_readings()
    duplicate.append(Reading(angle=0, amplitude=1.0))
    with pytest.raises(ValueError, match="duplicate"):
        find_segments(duplicate, 1.0)

    with pytest.raises(ValueError, match="outside"):
        find_segments(make_readings() + [Reading(angle=360, amplitude=1.0)], 1.0)

    with pytest.raises(ValueError, match="invalid"):
        find_segments(make_readings({0: math.nan}), 1.0)

    with pytest.raises(ValueError, match="non-negative"):
        find_segments(make_readings(), -1.0)
