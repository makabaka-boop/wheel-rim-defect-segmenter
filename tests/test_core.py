import math

import pytest

from app.core import Reading, corrected_amplitude, find_segments


def make_readings(values: dict[int, float] | None = None, default: float = 0.0) -> list[Reading]:
    values = values or {}
    return [Reading(angle=angle, amplitude=float(values.get(angle, default))) for angle in range(360)]


def make_baselines(values: dict[int, float] | None = None, default: float = 0.0) -> dict[int, float]:
    values = values or {}
    return {angle: float(values.get(angle, default)) for angle in range(360)}


def make_compensated_readings(
    values: dict[int, float] | None = None,
    baselines: dict[int, float] | None = None,
    default: float = 0.0,
    default_baseline: float = 0.0,
) -> list[Reading]:
    values = values or {}
    baselines = baselines or {}
    return [
        Reading(
            angle=angle,
            amplitude=float(values.get(angle, default)),
            baseline=float(baselines.get(angle, default_baseline)),
        )
        for angle in range(360)
    ]


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


def test_corrected_amplitude_clamps_at_zero_and_passes_through_without_baseline():
    assert corrected_amplitude(4.8, None) == 4.8
    assert corrected_amplitude(4.8, 1.2) == pytest.approx(3.6)
    assert corrected_amplitude(0.5, 1.2) == 0.0
    assert corrected_amplitude(1.2, 1.2) == 0.0


def test_corrected_amplitude_subtraction_is_decimal_exact():
    from decimal import Decimal

    assert corrected_amplitude(0.3, 0.1) == Decimal("0.2")
    assert corrected_amplitude(0.3, 0.0999999998) == Decimal("0.2000000002")
    assert isinstance(corrected_amplitude(0.3, None), float)


def test_baseline_suppresses_background_noise_below_threshold():
    readings = make_compensated_readings(
        default=2.9,
        baselines=make_baselines(default=1.0),
    )

    assert find_segments(readings, 2.5) == []
    assert len(find_segments(make_readings(default=2.9), 2.5)) == 1


def test_baseline_wrap_segment_uses_corrected_amplitudes_and_keeps_raw_peak():
    baselines = make_baselines({angle: 1.0 for angle in (358, 359, 0, 1)})
    readings = make_compensated_readings(
        {358: 4.1, 359: 5.9, 0: 6.6, 1: 4.4},
        baselines=baselines,
    )

    segments = find_segments(readings, 2.5)

    assert len(segments) == 1
    segment = segments[0]
    assert segment.start_angle == 358
    assert segment.end_angle == 1
    assert segment.span == 4
    assert segment.angles == (358, 359, 0, 1)
    assert segment.peak_angle == 0
    assert segment.peak_amplitude == pytest.approx(5.6)
    assert segment.peak_raw_amplitude == pytest.approx(6.6)
    assert segment.peak_baseline == pytest.approx(1.0)


def test_peak_is_selected_by_corrected_not_raw_amplitude():
    readings = make_compensated_readings(
        {10: 9.0, 11: 5.0},
        baselines=make_baselines({10: 7.0, 11: 1.0}),
    )

    segment = find_segments(readings, 2.0)[0]

    assert segment.peak_angle == 11
    assert segment.peak_amplitude == pytest.approx(4.0)
    assert segment.peak_raw_amplitude == pytest.approx(5.0)
    assert segment.peak_baseline == pytest.approx(1.0)


def test_baseline_equal_to_amplitude_drops_point_out_of_segment():
    readings = make_compensated_readings(
        {10: 3.0, 11: 3.0, 12: 3.0},
        baselines=make_baselines({11: 3.0}),
    )

    segments = find_segments(readings, 2.5)

    assert [(segment.start_angle, segment.end_angle, segment.span) for segment in segments] == [
        (10, 10, 1),
        (12, 12, 1),
    ]


def test_readings_without_baseline_report_no_peak_extras():
    segment = find_segments(make_readings({0: 3.0}), 2.0)[0]

    assert segment.peak_raw_amplitude is None
    assert segment.peak_baseline is None


def test_corrected_amplitude_threshold_exact_boundary_survives_float_residue():
    # 0.3 - 0.1 is 0.19999999999999998 in binary floats; the threshold-exact
    # critical point must still count as a single-point defective segment.
    # Baseline subtraction therefore runs in exact decimal arithmetic.
    readings = [
        Reading(angle=0, amplitude=0.3, baseline=0.1),
        *[
            Reading(angle=angle, amplitude=0.0, baseline=0.0)
            for angle in range(1, 360)
        ],
    ]

    segments = find_segments(readings, 0.2)

    assert len(segments) == 1
    segment = segments[0]
    assert segment.start_angle == 0
    assert segment.end_angle == 0
    assert segment.span == 1
    assert segment.peak_angle == 0
    assert segment.peak_amplitude == pytest.approx(0.2)
    assert segment.peak_raw_amplitude == pytest.approx(0.3)
    assert segment.peak_baseline == pytest.approx(0.1)


def test_corrected_amplitude_barely_above_threshold_below_one_billionth():
    # Exceeding the threshold by less than 1e-9 must still open a segment;
    # coarse rounding onto a 1e-9 grid previously erased the difference.
    readings = [
        Reading(angle=0, amplitude=0.3, baseline=0.0999999998),
        *[
            Reading(angle=angle, amplitude=0.0, baseline=0.0)
            for angle in range(1, 360)
        ],
    ]

    segments = find_segments(readings, 0.2000000001)

    assert len(segments) == 1
    segment = segments[0]
    assert segment.span == 1
    assert segment.start_angle == 0
    assert segment.peak_amplitude == pytest.approx(0.2000000002)
    assert segment.peak_amplitude > 0.2000000001


def test_corrected_amplitude_barely_below_threshold_does_not_false_alarm():
    readings = [
        Reading(angle=0, amplitude=0.3, baseline=0.0999999998),
        *[
            Reading(angle=angle, amplitude=0.0, baseline=0.0)
            for angle in range(1, 360)
        ],
    ]

    # corrected = 0.2000000002, threshold 1e-10 higher -> still non-defective
    assert find_segments(readings, 0.2000000003) == []


def test_core_rejects_illegal_baseline():
    with pytest.raises(ValueError, match="baseline"):
        find_segments(make_compensated_readings(baselines=make_baselines({0: -0.5})), 1.0)

    with pytest.raises(ValueError, match="baseline"):
        find_segments(make_compensated_readings(baselines=make_baselines({0: math.nan})), 1.0)
