import math

import pytest

from app.calibration import (
    MAX_POINTS,
    MIN_POINTS,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_UNEVALUATED,
    CalibrationPoint,
    CalibrationRecord,
    evaluate_calibration,
    fit_line,
    validate_calibration_payload,
)


def make_record(
    points: list[tuple[float, float]],
    tolerance: float = 0.05,
    name: str = "参考试块校准",
) -> CalibrationRecord:
    return CalibrationRecord(
        name=name,
        tolerance=tolerance,
        points=tuple(
            CalibrationPoint(thickness=thickness, travel_time=travel_time)
            for thickness, travel_time in points
        ),
    )


def exact_line_points() -> list[tuple[float, float]]:
    # travel_time = 0.5 * thickness + 1.0 is exact in binary floats, so the
    # fit must reproduce slope/intercept and zero residuals bit-for-bit.
    return [(10.0, 6.0), (20.0, 11.0), (30.0, 16.0), (40.0, 21.0)]


def test_exact_straight_line_is_fitted_bit_for_bit():
    result = evaluate_calibration(make_record(exact_line_points(), tolerance=0.05))

    assert result.status == STATUS_PASS
    assert result.slope == 0.5
    assert result.zero_offset == 1.0
    assert result.sound_velocity == 4.0
    assert result.max_abs_residual == 0.0
    assert result.max_residual_index == 0
    assert len(result.points) == 4
    for point, (_, travel_time) in zip(result.points, exact_line_points()):
        assert point.predicted_time == travel_time
        assert point.residual == 0.0
        assert point.within_tolerance is True


def test_minimum_and_maximum_point_counts_are_accepted():
    for count in (MIN_POINTS, MAX_POINTS):
        points = [(10.0 * (index + 1), 0.5 * 10.0 * (index + 1) + 1.0) for index in range(count)]
        result = evaluate_calibration(make_record(points))
        assert result.status == STATUS_PASS
        assert result.sound_velocity == 4.0


def test_single_out_of_tolerance_point_fails_and_is_located():
    points = [(25.0, 9.1), (50.0, 17.6), (75.0, 26.4), (100.0, 34.6), (125.0, 43.1)]

    result = evaluate_calibration(make_record(points, tolerance=0.1))

    assert result.status == STATUS_FAIL
    # The perturbed 75 mm point carries the maximum absolute residual; the
    # refit spreads only ±0.06 onto the other points, which stays within the
    # 0.1 tolerance, so exactly one point is out of tolerance.
    assert result.max_residual_index == 2
    assert result.max_abs_residual == pytest.approx(0.24)
    assert result.points[2].within_tolerance is False
    assert result.points[2].residual == pytest.approx(0.24)
    for index in (0, 1, 3, 4):
        assert result.points[index].within_tolerance is True
        assert result.points[index].residual == pytest.approx(-0.06)
    # Every returned prediction must be reproducible from slope/intercept.
    for point in result.points:
        assert point.predicted_time == pytest.approx(
            result.slope * point.thickness + result.zero_offset
        )
        assert point.residual == pytest.approx(point.travel_time - point.predicted_time)

    # The same measurements pass once the allowed residual covers 0.24.
    relaxed = evaluate_calibration(make_record(points, tolerance=0.25))
    assert relaxed.status == STATUS_PASS
    assert relaxed.max_abs_residual == pytest.approx(0.24)


def test_sound_velocity_and_zero_offset_follow_round_trip_relation():
    # Steel-like reference block: t = 0.34 * d + 0.6 -> v = 2 / 0.34 mm/µs.
    points = [(25.0, 9.1), (50.0, 17.6), (75.0, 26.1), (100.0, 34.6), (125.0, 43.1)]

    result = evaluate_calibration(make_record(points, tolerance=0.1))

    assert result.status == STATUS_PASS
    assert result.slope == pytest.approx(0.34)
    assert result.zero_offset == pytest.approx(0.6)
    assert result.sound_velocity == pytest.approx(2.0 / 0.34)
    assert result.max_abs_residual == pytest.approx(0.0, abs=1e-9)


def test_fit_line_rejects_degenerate_inputs():
    with pytest.raises(ValueError, match="at least two"):
        fit_line([CalibrationPoint(thickness=10.0, travel_time=6.0)])

    with pytest.raises(ValueError, match="thickness values must differ"):
        fit_line(
            [
                CalibrationPoint(thickness=10.0, travel_time=6.0),
                CalibrationPoint(thickness=10.0, travel_time=7.0),
            ]
        )

    with pytest.raises(ValueError, match="positive finite"):
        # Zero slope: travel time does not grow with thickness.
        fit_line(
            [
                CalibrationPoint(thickness=10.0, travel_time=6.0),
                CalibrationPoint(thickness=20.0, travel_time=6.0),
            ]
        )

    with pytest.raises(ValueError, match="positive finite"):
        # Negative slope: thicker block, shorter time.
        fit_line(
            [
                CalibrationPoint(thickness=10.0, travel_time=16.0),
                CalibrationPoint(thickness=20.0, travel_time=6.0),
            ]
        )


def test_status_constants_cover_the_three_ratings():
    assert {STATUS_UNEVALUATED, STATUS_PASS, STATUS_FAIL} == {"unevaluated", "pass", "fail"}


def test_validation_reports_missing_fields():
    record, errors = validate_calibration_payload({})

    assert record is None
    fields = {error["field"] for error in errors}
    assert fields == {"name", "tolerance", "points"}


def test_validation_rejects_non_object_body():
    record, errors = validate_calibration_payload([1, 2, 3])

    assert record is None
    assert errors[0]["field"] == "$"


def valid_payload() -> dict:
    return {
        "name": "探头更换后校准",
        "tolerance": 0.05,
        "points": [
            {"thickness": 25, "travelTime": 9.1},
            {"thickness": 50, "travelTime": 17.6},
            {"thickness": 75, "travelTime": 26.1},
        ],
    }


def test_validation_accepts_valid_payload_and_converts_to_floats():
    record, errors = validate_calibration_payload(valid_payload())

    assert errors == []
    assert record is not None
    assert record.name == "探头更换后校准"
    assert record.tolerance == 0.05
    assert len(record.points) == 3
    assert all(isinstance(point.thickness, float) for point in record.points)


def test_validation_rejects_blank_and_non_string_names():
    for bad_name in ("", "   ", 12, None):
        payload = valid_payload()
        payload["name"] = bad_name
        record, errors = validate_calibration_payload(payload)
        assert record is None
        assert {error["field"] for error in errors} == {"name"}


def test_validation_counts_points_and_localizes_short_and_long_lists():
    payload = valid_payload()
    payload["points"] = payload["points"][:2]
    record, errors = validate_calibration_payload(payload)
    assert record is None
    assert [(error["field"], "3 至 8" in error["message"]) for error in errors] == [
        ("points", True)
    ]

    payload = valid_payload()
    payload["points"] = [
        {"thickness": 10 * (index + 1), "travelTime": 5.0 * (index + 1) + 1.0}
        for index in range(9)
    ]
    record, errors = validate_calibration_payload(payload)
    assert record is None
    assert [error["field"] for error in errors] == ["points"]


def test_validation_localizes_duplicate_thickness_to_both_positions():
    payload = valid_payload()
    payload["points"][2]["thickness"] = 25  # duplicates points[0]

    record, errors = validate_calibration_payload(payload)

    assert record is None
    fields = {error["field"] for error in errors}
    assert fields == {"points[0].thickness", "points[2].thickness"}
    assert all("重复" in error["message"] for error in errors)


def test_validation_localizes_non_positive_and_non_finite_values():
    payload = valid_payload()
    payload["points"][0]["thickness"] = 0
    payload["points"][1]["thickness"] = -5
    payload["points"][2]["travelTime"] = math.nan

    record, errors = validate_calibration_payload(payload)

    assert record is None
    fields = {error["field"] for error in errors}
    assert fields == {
        "points[0].thickness",
        "points[1].thickness",
        "points[2].travelTime",
    }


def test_validation_localizes_wrong_types_and_missing_point_fields():
    payload = valid_payload()
    payload["points"][0] = {}
    payload["points"][1]["thickness"] = "50"
    payload["points"][2]["travelTime"] = True

    record, errors = validate_calibration_payload(payload)

    assert record is None
    fields = {error["field"] for error in errors}
    assert fields == {
        "points[0].thickness",
        "points[0].travelTime",
        "points[1].thickness",
        "points[2].travelTime",
    }


def test_validation_rejects_illegal_tolerances():
    for bad_tolerance in (0, -0.1, math.nan, math.inf, "0.05", True, None):
        payload = valid_payload()
        payload["tolerance"] = bad_tolerance
        record, errors = validate_calibration_payload(payload)
        assert record is None, bad_tolerance
        assert {error["field"] for error in errors} == {"tolerance"}


def test_validation_localizes_degenerate_slope_to_points():
    payload = valid_payload()
    # Constant travel time -> zero slope, no physical sound velocity.
    for point in payload["points"]:
        point["travelTime"] = 10.0

    record, errors = validate_calibration_payload(payload)

    assert record is None
    assert [error["field"] for error in errors] == ["points"]
    assert "退化" in errors[0]["message"]


def test_validation_rejects_non_list_points():
    payload = valid_payload()
    payload["points"] = {"thickness": 25}

    record, errors = validate_calibration_payload(payload)

    assert record is None
    assert [error["field"] for error in errors] == ["points"]
