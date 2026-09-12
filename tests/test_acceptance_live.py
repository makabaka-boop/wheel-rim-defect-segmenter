import json
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("VERIFY_LIVE"),
    reason="LIVE acceptance is executed by the one-shot docker compose verify service",
)

API_URL = os.getenv("API_URL", "http://api:8000")
WEB_URL = os.getenv("WEB_URL", "http://web:5173")


def payload() -> dict:
    return {
        "threshold": 2.5,
        "samples": [
            {
                "angle": angle,
                "amplitude": 4.8 if angle >= 357 or angle <= 2 else 0.4 + (angle % 7) * 0.1,
            }
            for angle in range(360)
        ],
    }


def compensated_payload() -> dict:
    baseline = [
        {"angle": angle, "value": round(0.3 + (angle % 5) * 0.08, 2)}
        for angle in range(360)
    ]
    values = {entry["angle"]: entry["value"] for entry in baseline}
    return {
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


def test_live_api_merges_wrap_damage_into_one_segment():
    response = httpx.post(f"{API_URL}/api/readings/analyze", json=payload(), timeout=10)
    assert response.status_code == 200
    data = response.json()
    assert data["sampleCount"] == 360
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["startAngle"] == 357
    assert segment["endAngle"] == 2
    assert segment["span"] == 6
    assert segment["angles"] == [357, 358, 359, 0, 1, 2]
    assert segment["peakAngle"] == 0
    assert segment["peakAmplitude"] == 4.8


def test_live_api_rejects_bad_payload_with_field_locations():
    bad = payload()
    bad["threshold"] = -1
    bad["samples"].pop()
    response = httpx.post(f"{API_URL}/api/readings/analyze", json=bad, timeout=10)
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "threshold" in fields
    assert "samples" in fields


def test_live_web_serves_react_application():
    response = httpx.get(WEB_URL, timeout=10)
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert '/src/main.tsx' in response.text


def test_live_compensated_wrap_segment_is_recomputable_point_by_point():
    request = compensated_payload()
    response = httpx.post(f"{API_URL}/api/readings/analyze", json=request, timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert data["baselineApplied"] is True
    assert data["sampleCount"] == 360

    samples = {sample["angle"]: sample["amplitude"] for sample in request["samples"]}
    baselines = {entry["angle"]: entry["value"] for entry in request["baseline"]}
    corrected = {}
    for point in data["points"]:
        assert point["amplitude"] == samples[point["angle"]]
        assert point["baseline"] == baselines[point["angle"]]
        expected = max(0.0, samples[point["angle"]] - baselines[point["angle"]])
        assert point["correctedAmplitude"] == pytest.approx(expected)
        corrected[point["angle"]] = point["correctedAmplitude"]

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


def test_live_payload_without_baseline_keeps_legacy_response():
    response = httpx.post(f"{API_URL}/api/readings/analyze", json=payload(), timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert data["baselineApplied"] is False
    assert "points" not in data
    segment = data["segments"][0]
    assert segment["peakAmplitude"] == 4.8
    assert "peakRawAmplitude" not in segment
    assert "peakBaseline" not in segment


def test_live_valid_baseline_suppresses_background_noise():
    request = compensated_payload()
    for sample in request["samples"]:
        sample["amplitude"] = 3.0
    for entry in request["baseline"]:
        entry["value"] = 1.0

    response = httpx.post(f"{API_URL}/api/readings/analyze", json=request, timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert data["segments"] == []
    assert all(point["correctedAmplitude"] == 2.0 for point in data["points"])


def test_live_compensated_threshold_exact_point_is_single_segment():
    request = compensated_payload()
    request["threshold"] = 0.2
    for angle, sample in enumerate(request["samples"]):
        sample["amplitude"] = 0.3 if angle == 0 else 0.0
    for entry in request["baseline"]:
        entry["value"] = 0.1 if entry["angle"] == 0 else 0.0

    response = httpx.post(f"{API_URL}/api/readings/analyze", json=request, timeout=10)

    assert response.status_code == 200
    segment = response.json()["segments"]
    assert len(segment) == 1
    assert segment[0]["startAngle"] == 0
    assert segment[0]["endAngle"] == 0
    assert segment[0]["span"] == 1
    assert segment[0]["peakAmplitude"] == pytest.approx(0.2)


def test_live_compensated_margin_below_one_billionth_still_detects():
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

    response = httpx.post(
        f"{API_URL}/api/readings/analyze",
        content=body,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    assert response.status_code == 200
    segments = response.json()["segments"]
    assert len(segments) == 1
    assert segments[0]["span"] == 1
    assert segments[0]["peakAmplitude"] == pytest.approx(0.2000000002)


def test_live_huge_integer_baseline_value_returns_field_error():
    bad = compensated_payload()
    bad["baseline"][7]["value"] = 10**400

    response = httpx.post(
        f"{API_URL}/api/readings/analyze",
        content=json.dumps(bad),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "baseline[7].value" in fields


def test_live_illegal_baseline_returns_field_feedback():
    bad = compensated_payload()
    bad["baseline"].pop()  # 359 entries
    bad["baseline"][0]["angle"] = 1  # duplicates baseline[1]
    bad["baseline"][2]["value"] = -0.4

    response = httpx.post(f"{API_URL}/api/readings/analyze", json=bad, timeout=10)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "baseline" in fields
    assert "baseline[0].angle" in fields
    assert "baseline[1].angle" in fields
    assert "baseline[2].value" in fields
