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
        f'"baseline": {json.dumps(baseline)}}'
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
        f'"baseline": {json.dumps(baseline)}}'
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
