"""Acceptance tests for the occlusion-interval (遮挡区间) feature.

Bolt holes or fixture shadows mark confirmed unreadable angle ranges. Each
interval is a clockwise closed pair of integer display angles; cross-zero and
overlapping intervals merge into one angle set whose points are excluded from
the ring segmentation.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def wrap_payload(**overrides):
    """Defect run 357..2 with distinct amplitudes, everything else quiet."""
    amplitudes = {357: 4.8, 358: 5.9, 359: 5.5, 0: 5.1, 1: 4.6, 2: 4.4}
    payload = {
        "threshold": 2.5,
        "samples": [
            {"angle": angle, "amplitude": amplitudes.get(angle, 0.4)}
            for angle in range(360)
        ],
    }
    payload.update(overrides)
    return payload


def test_cross_zero_occlusion_merges_both_ends_and_drops_high_amplitudes():
    # The interval 358 -> 0 wraps through zero and merges into the single
    # angle set {358, 359, 0}; the loudest readings (5.9/5.5/5.1) sit inside
    # it and must not enter any segment or peak.
    payload = wrap_payload(occlusions=[{"start": 358, "end": 0}])
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["occludedAngles"] == [0, 358, 359]

    segments = data["segments"]
    # Segments are ordered by ascending start angle, as in the legacy rules.
    assert [(s["startAngle"], s["endAngle"], s["span"]) for s in segments] == [
        (1, 2, 2),
        (357, 357, 1),
    ]
    covered = {angle for segment in segments for angle in segment["angles"]}
    assert covered.isdisjoint({0, 358, 359})
    # Without occlusion the peak would be 5.9 at 358; the remaining peaks are
    # recomputed from the readable points only.
    assert segments[0]["peakAngle"] == 1
    assert segments[0]["peakAmplitude"] == pytest.approx(4.6)
    assert segments[1]["peakAngle"] == 357
    assert segments[1]["peakAmplitude"] == pytest.approx(4.8)
    assert all(segment["peakAmplitude"] < 5.0 for segment in segments)


def test_single_point_occlusion_splits_segment_deterministically():
    # Occluding exactly angle 0 (start == end) breaks the wrap run 357..2
    # into the two deterministic runs 357..359 and 1..2.
    payload = wrap_payload(occlusions=[{"start": 0, "end": 0}])
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["occludedAngles"] == [0]
    segments = data["segments"]
    assert [(s["startAngle"], s["endAngle"], s["span"]) for s in segments] == [
        (1, 2, 2),
        (357, 359, 3),
    ]
    assert segments[1]["angles"] == [357, 358, 359]
    assert segments[1]["peakAngle"] == 358
    assert segments[1]["peakAmplitude"] == pytest.approx(5.9)
    assert segments[0]["angles"] == [1, 2]


def test_overlapping_intervals_merge_into_one_angle_set():
    payload = wrap_payload(
        occlusions=[{"start": 10, "end": 20}, {"start": 18, "end": 25}, {"start": 40, "end": 40}],
    )
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["occludedAngles"] == list(range(10, 26)) + [40]


def test_occlusion_applies_in_display_space_after_angle_offset():
    # Source run 357..2 rotates by +5 into display 2..7; the occlusion
    # interval is expressed in display angles and splits that run there.
    payload = wrap_payload(angleOffset=5, occlusions=[{"start": 4, "end": 5}])
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["angleOffset"] == 5
    assert data["occludedAngles"] == [4, 5]
    segments = data["segments"]
    assert [(s["startAngle"], s["endAngle"], s["span"]) for s in segments] == [
        (2, 3, 2),
        (6, 7, 2),
    ]
    # Source mapping stays traceable for the split segments.
    assert segments[0]["sourceAngles"] == [357, 358]
    assert segments[1]["sourceAngles"] == [1, 2]


def test_occlusion_with_baseline_keeps_pointwise_response():
    baseline = [{"angle": angle, "value": 0.3} for angle in range(360)]
    samples = [
        {"angle": angle, "amplitude": 5.1 if 357 <= angle or angle <= 2 else 0.4}
        for angle in range(360)
    ]
    payload = {
        "threshold": 2.5,
        "samples": samples,
        "baseline": baseline,
        "occlusions": [{"start": 359, "end": 0}],
    }
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["baselineApplied"] is True
    assert data["occludedAngles"] == [0, 359]
    assert len(data["points"]) == 360
    segments = data["segments"]
    assert [(s["startAngle"], s["endAngle"], s["span"]) for s in segments] == [
        (1, 2, 2),
        (357, 358, 2),
    ]
    for segment in segments:
        assert "peakRawAmplitude" in segment
        assert "peakBaseline" in segment


def test_occluding_every_defective_point_returns_no_segments():
    payload = wrap_payload(occlusions=[{"start": 357, "end": 2}])
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["segments"] == []
    assert data["occludedAngles"] == [0, 1, 2, 357, 358, 359]


def test_full_circle_minus_one_occluded_point_is_one_open_segment():
    payload = {
        "threshold": 2.5,
        "samples": [{"angle": angle, "amplitude": 3.0} for angle in range(360)],
        "occlusions": [{"start": 100, "end": 100}],
    }
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert segment["startAngle"] == 101
    assert segment["endAngle"] == 99
    assert segment["span"] == 359
    assert 100 not in segment["angles"]


def test_illegal_occlusion_endpoints_are_localized_to_their_fields():
    payload = wrap_payload(
        occlusions=[
            {"start": 1.5, "end": 10},
            {"start": 5, "end": 360},
            {"start": "7", "end": 8},
            {"start": True, "end": -1},
        ]
    )
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "occlusions[0].start" in fields
    assert "occlusions[1].end" in fields
    assert "occlusions[2].start" in fields
    assert "occlusions[3].start" in fields
    assert "occlusions[3].end" in fields


def test_occlusion_structure_errors_are_localized():
    payload = wrap_payload(occlusions=[{"start": 5}, "not-an-object", {}])
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "occlusions[0].end" in fields
    assert "occlusions[1]" in fields
    assert "occlusions[2].start" in fields
    assert "occlusions[2].end" in fields

    response = client.post(
        "/api/readings/analyze",
        json=wrap_payload(occlusions={"start": 1, "end": 2}),
    )
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert "occlusions" in fields


def test_more_than_eight_occlusion_intervals_are_rejected():
    payload = wrap_payload(
        occlusions=[{"start": angle, "end": angle} for angle in range(9)]
    )
    response = client.post("/api/readings/analyze", json=payload)

    assert response.status_code == 422
    errors = response.json()["errors"]
    assert [error["field"] for error in errors] == ["occlusions"]
    assert "8" in errors[0]["message"]

    payload = wrap_payload(
        occlusions=[{"start": angle, "end": angle} for angle in range(8)]
    )
    response = client.post("/api/readings/analyze", json=payload)
    assert response.status_code == 200
    assert response.json()["occludedAngles"] == list(range(8))


def test_omitted_occlusions_keep_legacy_response_field_by_field():
    legacy = client.post("/api/readings/analyze", json=wrap_payload())
    assert legacy.status_code == 200
    data = legacy.json()
    assert set(data.keys()) == {"threshold", "sampleCount", "baselineApplied", "segments"}
    assert "occludedAngles" not in data
    assert data["baselineApplied"] is False
    assert len(data["segments"]) == 1
    segment = data["segments"][0]
    assert set(segment.keys()) == {
        "startAngle",
        "endAngle",
        "span",
        "peakAngle",
        "peakAmplitude",
        "angles",
    }
    assert segment["startAngle"] == 357
    assert segment["endAngle"] == 2
    assert segment["span"] == 6
    assert segment["angles"] == [357, 358, 359, 0, 1, 2]
    assert segment["peakAngle"] == 358
    assert segment["peakAmplitude"] == pytest.approx(5.9)

    # An explicit null also keeps the legacy shape.
    response = client.post("/api/readings/analyze", json=wrap_payload(occlusions=None))
    assert response.status_code == 200
    assert response.json() == data


def test_empty_occlusion_list_is_reported_with_empty_angle_set():
    response = client.post("/api/readings/analyze", json=wrap_payload(occlusions=[]))

    assert response.status_code == 200
    data = response.json()
    assert data["occludedAngles"] == []
    assert len(data["segments"]) == 1
    assert data["segments"][0]["span"] == 6
