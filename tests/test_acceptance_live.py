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
