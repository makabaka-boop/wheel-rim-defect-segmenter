import json
import math

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
