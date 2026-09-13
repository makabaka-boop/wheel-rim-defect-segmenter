import json
import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def valid_payload(**overrides):
    payload = {
        "threshold": 2.5,
        "samples": [
            {
                "angle": angle,
                "amplitude": 4.8 if angle >= 358 or angle <= 1 else 0.4 + (angle % 5) * 0.1,
            }
            for angle in range(360)
        ],
    }
    payload.update(overrides)
    return payload


def baseline_entry(angle: int) -> dict:
    return {"angle": angle, "value": round(0.3 + (angle % 5) * 0.08, 2)}


def compensated_payload(**overrides):
    baseline = [baseline_entry(angle) for angle in range(360)]
    values = {entry["angle"]: entry["value"] for entry in baseline}
    payload = {
        "threshold": 2.5,
        "samples": [
            {
                "angle": angle,
                "amplitude": round(
                    values[angle] + (4.8 if angle >= 357 or angle <= 2 else 0.2),
                    2,
                ),
            }
            for angle in range(360)
        ],
        "baseline": baseline,
    }
    payload.update(overrides)
    return payload


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_wrapping_payload_returns_one_recomputable_segment():
    response = client.post("/api/readings/analyze", json=valid_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["sampleCount"] == 360
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["startAngle"] == 358
    assert segment["endAngle"] == 1
    assert segment["span"] == 4
    assert segment["angles"] == [358, 359, 0, 1]
    assert segment["peakAngle"] == 0


def test_zero_amplitude_and_threshold_are_accepted():
    payload = valid_payload(threshold=0)
    response = client.post("/api/readings/analyze", json=payload)
    assert response.status_code == 200
    assert len(response.json()["segments"]) == 1
    assert response.json()["segments"][0]["span"] == 360


def test_missing_payload_fields_are_localized():
    response = client.post("/api/readings/analyze", json={})
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "threshold" in fields
    assert "samples" in fields


def test_missing_duplicate_out_of_range_and_amplitude_errors_are_localized():
    payload = valid_payload()
    payload["threshold"] = -1
    samples = payload["samples"]
    samples.pop(10)
    samples[0]["angle"] = 1  # duplicates samples[1]
    samples[2]["angle"] = 360
    samples[3]["amplitude"] = -0.2
    samples[4]["amplitude"] = math.nan

    response = client.post(
        "/api/readings/analyze",
        content=json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    errors = response.json()["errors"]
    fields = {error["field"] for error in errors}
    assert "threshold" in fields
    assert "samples" in fields  # 359 records
    assert "samples[0].angle" in fields
    assert "samples[1].angle" in fields
    assert "samples[2].angle" in fields
    assert "samples[3].amplitude" in fields
    assert "samples[4].amplitude" in fields


def test_missing_sample_properties_are_localized():
    payload = valid_payload()
    payload["samples"][5] = {}
    response = client.post("/api/readings/analyze", json=payload)
    fields = {error["field"] for error in response.json()["errors"]}
    assert "samples[5].angle" in fields
    assert "samples[5].amplitude" in fields


def test_boolean_and_non_numeric_values_are_rejected():
    payload = valid_payload()
    payload["threshold"] = True
    payload["samples"][6]["angle"] = True
    payload["samples"][7]["amplitude"] = "8"
    response = client.post("/api/readings/analyze", json=payload)
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "threshold" in fields
    assert "samples[6].angle" in fields
    assert "samples[7].amplitude" in fields


def test_malformed_json_is_localized_to_request():
    response = client.post(
        "/api/readings/analyze",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "request"


def test_empty_body_is_localized_to_request():
    response = client.post("/api/readings/analyze", content=b"")
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "request"


def test_payload_without_baseline_keeps_legacy_response_shape():
    response = client.post("/api/readings/analyze", json=valid_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["baselineApplied"] is False
    assert "points" not in data
    segment = data["segments"][0]
    assert segment["peakAmplitude"] == 4.8
    assert "peakRawAmplitude" not in segment
    assert "peakBaseline" not in segment


def test_compensated_wrap_segment_is_recomputable_point_by_point():
    payload = compensated_payload()
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["baselineApplied"] is True
    assert data["sampleCount"] == 360

    points = data["points"]
    assert len(points) == 360
    samples = {sample["angle"]: sample["amplitude"] for sample in payload["samples"]}
    baselines = {entry["angle"]: entry["value"] for entry in payload["baseline"]}
    corrected = {}
    for point in points:
        assert point["amplitude"] == samples[point["angle"]]
        assert point["baseline"] == baselines[point["angle"]]
        expected = max(0.0, samples[point["angle"]] - baselines[point["angle"]])
        assert point["correctedAmplitude"] == pytest.approx(expected)
        corrected[point["angle"]] = point["correctedAmplitude"]

    # Recompute the defective run across zero from the per-point corrections.
    defective = {angle for angle, value in corrected.items() if value >= data["threshold"]}
    assert defective == {357, 358, 359, 0, 1, 2}

    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["startAngle"] == 357
    assert segment["endAngle"] == 2
    assert segment["span"] == 6
    assert segment["angles"] == [357, 358, 359, 0, 1, 2]

    expected_peak = min(defective, key=lambda angle: (-corrected[angle], angle))
    assert segment["peakAngle"] == expected_peak
    assert segment["peakAmplitude"] == pytest.approx(corrected[expected_peak])
    assert segment["peakRawAmplitude"] == pytest.approx(samples[expected_peak])
    assert segment["peakBaseline"] == pytest.approx(baselines[expected_peak])


def test_valid_baseline_suppresses_background_noise():
    payload = compensated_payload()
    for sample in payload["samples"]:
        sample["amplitude"] = 3.0  # raw reading everywhere above threshold
    for entry in payload["baseline"]:
        entry["value"] = 1.0  # coupling floor pushes corrected values to 2.0

    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["baselineApplied"] is True
    assert data["segments"] == []
    assert all(point["correctedAmplitude"] == 2.0 for point in data["points"])

    legacy = client.post(
        "/api/readings/analyze",
        json={"threshold": payload["threshold"], "samples": payload["samples"]},
    )
    assert legacy.status_code == 200
    assert legacy.json()["segments"][0]["span"] == 360


def test_baseline_missing_duplicate_and_illegal_values_are_localized():
    payload = compensated_payload()
    baseline = payload["baseline"]
    baseline.pop(9)  # now 359 entries
    baseline[0]["angle"] = 1  # duplicates baseline[1]
    baseline[2]["angle"] = 360
    baseline[3]["value"] = -0.1
    baseline[4]["value"] = math.nan

    response = client.post(
        "/api/readings/analyze",
        content=json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "baseline" in fields  # 359 records
    assert "baseline[0].angle" in fields
    assert "baseline[1].angle" in fields
    assert "baseline[2].angle" in fields
    assert "baseline[3].value" in fields
    assert "baseline[4].value" in fields


def test_baseline_missing_fields_and_wrong_types_are_localized():
    payload = compensated_payload()
    payload["baseline"][5] = {}
    payload["baseline"][6]["angle"] = True
    payload["baseline"][7]["value"] = "0.5"

    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "baseline[5].angle" in fields
    assert "baseline[5].value" in fields
    assert "baseline[6].angle" in fields
    assert "baseline[7].value" in fields


def test_compensated_threshold_exact_point_detects_single_point_segment():
    payload = compensated_payload()
    # Flatten every reading to raw 0.3 with baseline 0.1 except one angle; the
    # corrected 0.2 equals the threshold and must form a single-point segment.
    payload["threshold"] = 0.2
    for angle, sample in enumerate(payload["samples"]):
        sample["amplitude"] = 0.3 if angle == 0 else 0.0
    for entry in payload["baseline"]:
        entry["value"] = 0.1 if entry["angle"] == 0 else 0.0

    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["startAngle"] == 0
    assert segment["endAngle"] == 0
    assert segment["span"] == 1
    assert segment["angles"] == [0]
    assert segment["peakAmplitude"] == pytest.approx(0.2)
    assert segment["peakRawAmplitude"] == pytest.approx(0.3)
    assert segment["peakBaseline"] == pytest.approx(0.1)
    point = data["points"][0]
    assert point["correctedAmplitude"] == pytest.approx(0.2)


def test_compensated_margin_below_one_billionth_still_detects_segment():
    # Build the body as raw text so the 10-decimal tokens reach the API
    # without a round-trip through Python binary floats.
    samples = [
        {"angle": angle, "amplitude": 0.3 if angle == 0 else 0.0}
        for angle in range(360)
    ]
    baseline = [
        {"angle": angle, "value": 0.0999999998 if angle == 0 else 0.0}
        for angle in range(360)
    ]
    body = (
        '{"threshold": 0.2000000001, '
        f'"samples": {json.dumps(samples)}, '
        f'"baseline": {json.dumps(baseline)}'
        '}'
    )

    response = client.post(
        "/api/readings/analyze",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["span"] == 1
    assert segment["startAngle"] == 0
    assert segment["peakAmplitude"] == pytest.approx(0.2000000002)
    assert data["points"][0]["correctedAmplitude"] == pytest.approx(0.2000000002)


def test_compensated_margin_below_threshold_does_not_false_alarm():
    samples = [
        {"angle": angle, "amplitude": 0.3 if angle == 0 else 0.0}
        for angle in range(360)
    ]
    baseline = [
        {"angle": angle, "value": 0.0999999998 if angle == 0 else 0.0}
        for angle in range(360)
    ]
    body = (
        '{"threshold": 0.2000000003, '
        f'"samples": {json.dumps(samples)}, '
        f'"baseline": {json.dumps(baseline)}'
        '}'
    )

    response = client.post(
        "/api/readings/analyze",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["segments"] == []


def test_huge_integer_baseline_value_is_localized_not_crashing():
    payload = compensated_payload()
    payload["baseline"][7]["value"] = 10**400

    response = client.post(
        "/api/readings/analyze",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    errors = response.json()["errors"]
    fields = {error["field"] for error in errors}
    assert "baseline[7].value" in fields


def test_huge_integer_amplitude_and_threshold_are_localized():
    payload = valid_payload()
    payload["threshold"] = 10**400
    payload["samples"][3]["amplitude"] = 10**400

    response = client.post(
        "/api/readings/analyze",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "threshold" in fields
    assert "samples[3].amplitude" in fields


def test_baseline_must_be_an_array():
    response = client.post(
        "/api/readings/analyze",
        json=compensated_payload(baseline={"angle": 0, "value": 0.3}),
    )

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "baseline" in fields


def test_angle_offset_turns_wrap_defect_into_ordinary_segment_and_maps_peak():
    # A six-point run straddling zero at source 357..2 moves by +5 into the
    # fully interior run 2..7, so the zero crossing disappears without
    # changing span or amplitudes.
    wrap_payload = {
        "threshold": 2.5,
        "samples": [
            {"angle": angle, "amplitude": 4.8 if 357 <= angle <= 359 or angle <= 2 else 0.4}
            for angle in range(360)
        ],
        "angleOffset": 5,
    }
    response = client.post("/api/readings/analyze", json=wrap_payload)

    assert response.status_code == 200
    data = response.json()
    assert data["angleOffset"] == 5
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["startAngle"] == 2
    assert segment["endAngle"] == 7
    assert segment["span"] == 6
    assert segment["angles"] == [2, 3, 4, 5, 6, 7]
    assert segment["startAngle"] <= segment["endAngle"]  # no longer wraps zero
    # Equal peak amplitudes tie on the smallest displayed angle (2), which maps
    # back to source 357.
    assert segment["peakAngle"] == 2
    assert segment["sourcePeakAngle"] == 357
    assert segment["sourceStartAngle"] == 357
    assert segment["sourceEndAngle"] == 2
    assert segment["sourceAngles"] == [357, 358, 359, 0, 1, 2]


def test_negative_angle_offset_keeps_a_wrapping_run_and_maps_back_to_source():
    # Source run 359,0,1 shifted by -1 becomes 358,359,0: it still crosses
    # zero, with boundaries mapped back to encoder coordinates.
    wrap_payload = {
        "threshold": 2.5,
        "samples": [
            {"angle": angle, "amplitude": 4.8 if angle == 359 or angle <= 1 else 0.4}
            for angle in range(360)
        ],
        "angleOffset": -1,
    }
    response = client.post("/api/readings/analyze", json=wrap_payload)

    assert response.status_code == 200
    segment = response.json()["segments"][0]
    assert segment["startAngle"] == 358
    assert segment["endAngle"] == 0
    assert segment["span"] == 3
    assert segment["angles"] == [358, 359, 0]
    assert segment["sourceStartAngle"] == 359
    assert segment["sourceEndAngle"] == 1
    assert segment["sourceAngles"] == [359, 0, 1]


def test_angle_offset_matches_baseline_by_source_angle_before_rotation():
    # Raw defect exists only at source 0; the large baseline sits at source 5.
    # Pairing on source angles leaves the defect uncompensated at display 5; a
    # display-first (wrong) order would subtract the source-5 baseline from it.
    samples = [
        {"angle": angle, "amplitude": 3.0 if angle == 0 else 0.0}
        for angle in range(360)
    ]
    baseline = [
        {"angle": angle, "value": 1.0 if angle == 5 else 0.0}
        for angle in range(360)
    ]
    payload = {
        "threshold": 2.5,
        "samples": samples,
        "baseline": baseline,
        "angleOffset": 5,
    }

    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["angleOffset"] == 5
    segment = data["segments"][0]
    assert segment["peakAngle"] == 5
    assert segment["sourcePeakAngle"] == 0
    assert segment["peakAmplitude"] == pytest.approx(3.0)
    assert segment["peakBaseline"] == pytest.approx(0.0)

    by_display = {point["angle"]: point for point in data["points"]}
    peak_point = by_display[5]
    assert peak_point["sourceAngle"] == 0
    assert peak_point["baseline"] == 0.0
    assert peak_point["correctedAmplitude"] == pytest.approx(3.0)
    rotated_baseline_point = by_display[10]
    assert rotated_baseline_point["sourceAngle"] == 5
    assert rotated_baseline_point["baseline"] == 1.0


def test_compensated_wrap_sample_with_offset_keeps_pointwise_recomputability():
    payload = compensated_payload()
    payload["angleOffset"] = 5
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    samples = {sample["angle"]: sample["amplitude"] for sample in payload["samples"]}
    baselines = {entry["angle"]: entry["value"] for entry in payload["baseline"]}

    for point in data["points"]:
        source = point["sourceAngle"]
        assert point["angle"] == (source + 5) % 360
        assert point["amplitude"] == samples[source]
        assert point["baseline"] == baselines[source]
        expected = max(0.0, samples[source] - baselines[source])
        assert point["correctedAmplitude"] == pytest.approx(expected)

    segment = data["segments"][0]
    assert (segment["startAngle"], segment["endAngle"], segment["span"]) == (2, 7, 6)
    # All six corrected values equal 4.8, so the tie resolves on the smallest
    # displayed angle (2), whose source angle is 357 — proving ties follow
    # display space while the source mapping stays traceable.
    assert segment["peakAngle"] == 2
    assert segment["sourcePeakAngle"] == 357
    assert segment["peakAmplitude"] == pytest.approx(4.8)
    assert segment["peakRawAmplitude"] == pytest.approx(samples[357])
    assert segment["peakBaseline"] == pytest.approx(baselines[357])


def test_illegal_angle_offset_is_localized_to_the_field():
    cases = [
        (1.5, "整数"),
        (360, "359"),
        (-360, "359"),
        ("3", "整数"),
        (True, "整数"),
    ]
    for offset, expected_message in cases:
        response = client.post(
            "/api/readings/analyze",
            json=valid_payload(angleOffset=offset),
        )
        assert response.status_code == 422, offset
        errors = response.json()["errors"]
        assert [error["field"] for error in errors] == ["angleOffset"]
        assert expected_message in errors[0]["message"]


def test_explicit_zero_and_omitted_angle_offset_keep_legacy_shape():
    for body in (valid_payload(), valid_payload(angleOffset=0)):
        response = client.post("/api/readings/analyze", json=body)
        assert response.status_code == 200
        data = response.json()
        assert "angleOffset" not in data
        segment = data["segments"][0]
        assert "sourcePeakAngle" not in segment
        assert "sourceAngles" not in segment

