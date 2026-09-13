import json
import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def exact_line_payload(**overrides):
    # travelTime = 0.5 * thickness + 1.0, exact in binary floats.
    payload = {
        "name": "轴身试块声程校准",
        "tolerance": 0.05,
        "points": [
            {"thickness": 10, "travelTime": 6.0},
            {"thickness": 20, "travelTime": 11.0},
            {"thickness": 30, "travelTime": 16.0},
            {"thickness": 40, "travelTime": 21.0},
        ],
    }
    payload.update(overrides)
    return payload


def outlier_payload(**overrides):
    payload = {
        "name": "耦合剂更换后校准",
        "tolerance": 0.1,
        "points": [
            {"thickness": 25, "travelTime": 9.1},
            {"thickness": 50, "travelTime": 17.6},
            {"thickness": 75, "travelTime": 26.4},
            {"thickness": 100, "travelTime": 34.6},
            {"thickness": 125, "travelTime": 43.1},
        ],
    }
    payload.update(overrides)
    return payload


def test_exact_line_is_rated_pass_and_fitted_exactly():
    response = client.post("/api/calibrations/evaluate", json=exact_line_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "轴身试块声程校准"
    assert data["status"] == "pass"
    assert data["pointCount"] == 4
    assert data["tolerance"] == 0.05
    assert data["slope"] == 0.5
    assert data["zeroOffset"] == 1.0
    assert data["soundVelocity"] == 4.0
    assert data["maxAbsResidual"] == 0.0
    assert len(data["points"]) == 4
    for point, submitted in zip(data["points"], exact_line_payload()["points"]):
        assert point["thickness"] == submitted["thickness"]
        assert point["travelTime"] == submitted["travelTime"]
        assert point["predictedTime"] == submitted["travelTime"]
        assert point["residual"] == 0.0
        assert point["withinTolerance"] is True


def test_single_outlier_is_rated_fail_and_recomputable_from_details():
    response = client.post("/api/calibrations/evaluate", json=outlier_payload())

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "fail"
    assert data["maxResidualIndex"] == 2

    # Recompute the whole conclusion from the returned line and per-point
    # details, the same way the inspector would on the review bench.
    for point in data["points"]:
        predicted = data["slope"] * point["thickness"] + data["zeroOffset"]
        assert point["predictedTime"] == pytest.approx(predicted)
        assert point["residual"] == pytest.approx(point["travelTime"] - predicted)
        assert point["withinTolerance"] == (abs(point["residual"]) <= data["tolerance"])

    residuals = [abs(point["residual"]) for point in data["points"]]
    assert data["maxAbsResidual"] == pytest.approx(max(residuals))
    assert residuals.index(max(residuals)) == data["maxResidualIndex"]
    expected_status = "pass" if data["maxAbsResidual"] <= data["tolerance"] else "fail"
    assert data["status"] == expected_status == "fail"

    worst = data["points"][data["maxResidualIndex"]]
    assert worst["thickness"] == 75
    assert worst["residual"] == pytest.approx(0.24)
    assert worst["withinTolerance"] is False
    # Exactly one point is out of tolerance.
    assert [point["withinTolerance"] for point in data["points"]] == [
        True,
        True,
        False,
        True,
        True,
    ]
    assert data["soundVelocity"] == pytest.approx(2.0 / data["slope"])


def test_same_measurements_pass_with_relaxed_tolerance():
    response = client.post(
        "/api/calibrations/evaluate",
        json=outlier_payload(tolerance=0.25),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pass"
    assert data["maxAbsResidual"] == pytest.approx(0.24)
    assert all(point["withinTolerance"] for point in data["points"])


def test_missing_fields_are_localized():
    response = client.post("/api/calibrations/evaluate", json={})

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert fields == {"name", "tolerance", "points"}


def test_too_few_and_too_many_points_are_localized():
    payload = exact_line_payload()
    payload["points"] = payload["points"][:2]
    response = client.post("/api/calibrations/evaluate", json=payload)
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "points" in fields

    payload = exact_line_payload()
    payload["points"] = [
        {"thickness": 10 * (index + 1), "travelTime": 5.0 * (index + 1) + 1.0}
        for index in range(9)
    ]
    response = client.post("/api/calibrations/evaluate", json=payload)
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "points" in fields


def test_duplicate_thickness_is_localized_to_each_position():
    payload = exact_line_payload()
    payload["points"][3]["thickness"] = 10  # duplicates points[0]

    response = client.post("/api/calibrations/evaluate", json=payload)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "points[0].thickness" in fields
    assert "points[3].thickness" in fields


def test_degenerate_slope_is_localized_to_points():
    payload = exact_line_payload()
    for point in payload["points"]:
        point["travelTime"] = 8.0  # zero slope

    response = client.post("/api/calibrations/evaluate", json=payload)

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert [error["field"] for error in errors] == ["points"]
    assert "退化" in errors[0]["message"]

    payload = exact_line_payload()
    payload["points"] = [
        {"thickness": 10, "travelTime": 21.0},
        {"thickness": 20, "travelTime": 16.0},
        {"thickness": 30, "travelTime": 11.0},
    ]
    response = client.post("/api/calibrations/evaluate", json=payload)
    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["points"]


def test_illegal_tolerance_and_values_are_localized():
    payload = exact_line_payload(tolerance=0)
    payload["points"][1]["thickness"] = -20
    payload["points"][2]["travelTime"] = math.nan

    response = client.post(
        "/api/calibrations/evaluate",
        content=json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "tolerance" in fields
    assert "points[1].thickness" in fields
    assert "points[2].travelTime" in fields


def test_non_numeric_and_boolean_fields_are_rejected():
    payload = exact_line_payload()
    payload["tolerance"] = "0.05"
    payload["points"][0]["thickness"] = True
    payload["points"][1]["travelTime"] = "11.0"

    response = client.post("/api/calibrations/evaluate", json=payload)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "tolerance" in fields
    assert "points[0].thickness" in fields
    assert "points[1].travelTime" in fields


def test_empty_and_malformed_bodies_are_localized_to_request():
    response = client.post("/api/calibrations/evaluate", content=b"")
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "request"

    response = client.post(
        "/api/calibrations/evaluate",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "request"


def test_analyze_endpoint_still_available_alongside_calibration():
    response = client.post(
        "/api/readings/analyze",
        json={
            "threshold": 2.5,
            "samples": [
                {"angle": angle, "amplitude": 4.8 if angle >= 358 else 0.4}
                for angle in range(360)
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["sampleCount"] == 360
    assert data["segments"][0]["startAngle"] == 358
