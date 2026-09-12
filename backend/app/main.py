import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core import Segment, corrected_amplitude, find_segments
from .validation import ValidatedPayload, field_error, validate_payload

app = FastAPI(title="轮对超声环形读数判读 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "wheelset-ultrasonic-api", "health": "/health"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def allow_float_constant(value: str) -> float:
    # Keep non-standard JSON numeric constants parseable so validation can
    # report the offending amplitude/threshold field instead of the whole body.
    return float(value)


def segment_to_dict(segment: Segment, baseline_applied: bool) -> dict[str, object]:
    data: dict[str, object] = {
        "startAngle": segment.start_angle,
        "endAngle": segment.end_angle,
        "span": segment.span,
        "peakAngle": segment.peak_angle,
        "peakAmplitude": segment.peak_amplitude,
        "angles": list(segment.angles),
    }
    if baseline_applied:
        # peakAmplitude is the corrected value; keep the raw reading and the
        # subtracted baseline alongside it for traceability.
        data["peakRawAmplitude"] = segment.peak_raw_amplitude
        data["peakBaseline"] = segment.peak_baseline
    return data


def points_to_dict(payload: ValidatedPayload) -> list[dict[str, object]]:
    return [
        {
            "angle": reading.angle,
            "amplitude": reading.amplitude,
            "baseline": reading.baseline,
            "correctedAmplitude": corrected_amplitude(reading.amplitude, reading.baseline),
        }
        for reading in payload.readings
    ]


@app.post("/api/readings/analyze")
async def analyze_readings(request: Request) -> JSONResponse:
    body = await request.body()
    if not body:
        return JSONResponse(
            status_code=422,
            content={"errors": [field_error("request", "请求体不能为空，需要 JSON 数据")]},
        )

    try:
        raw = json.loads(
            body.decode("utf-8"),
            parse_constant=allow_float_constant,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        return JSONResponse(
            status_code=422,
            content={"errors": [field_error("request", f"JSON 格式非法：{exc}")]},
        )

    payload, errors = validate_payload(raw)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    assert payload is not None
    segments = find_segments(payload.readings, payload.threshold)
    content: dict[str, object] = {
        "threshold": payload.threshold,
        "sampleCount": 360,
        "baselineApplied": payload.baseline_applied,
        "segments": [
            segment_to_dict(segment, payload.baseline_applied) for segment in segments
        ],
    }
    if payload.baseline_applied:
        content["points"] = points_to_dict(payload)
    return JSONResponse(content=content)
