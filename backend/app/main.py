import json
from decimal import Decimal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .calibration import (
    CalibrationResult,
    evaluate_calibration,
    validate_calibration_payload,
)
from .core import Number, Segment, corrected_amplitude, find_segments
from .validation import ValidatedPayload, field_error, validate_payload


def response_number(value: Number) -> float | int:
    # Internal arithmetic may keep Decimal for exactness; responses stay JSON
    # numbers, converting only at the output boundary.
    return float(value) if isinstance(value, Decimal) else value

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


def parse_json_numbers(value: str) -> Decimal:
    # Decimal text (including 0.1, 0.3) keeps the exact decimal value the
    # operator submitted so baseline subtraction is not blurred by binary
    # floats.
    return Decimal(value)


def parse_json_constant(value: str) -> float:
    # Non-standard constants (NaN/Infinity) still parse into floats so field
    # validation reports the offending amplitude/value rather than the body.
    return float(value)


def segment_to_dict(segment: Segment, baseline_applied: bool) -> dict[str, object]:
    data: dict[str, object] = {
        "startAngle": segment.start_angle,
        "endAngle": segment.end_angle,
        "span": segment.span,
        "peakAngle": segment.peak_angle,
        "peakAmplitude": response_number(segment.peak_amplitude),
        "angles": list(segment.angles),
    }
    if baseline_applied:
        # peakAmplitude is the corrected value; keep the raw reading and the
        # subtracted baseline alongside it for traceability.
        data["peakRawAmplitude"] = (
            response_number(segment.peak_raw_amplitude)
            if segment.peak_raw_amplitude is not None
            else None
        )
        data["peakBaseline"] = (
            response_number(segment.peak_baseline)
            if segment.peak_baseline is not None
            else None
        )
    return data


def points_to_dict(payload: ValidatedPayload) -> list[dict[str, object]]:
    return [
        {
            "angle": reading.angle,
            "amplitude": response_number(reading.amplitude),
            "baseline": (
                response_number(reading.baseline)
                if reading.baseline is not None
                else None
            ),
            "correctedAmplitude": response_number(
                corrected_amplitude(reading.amplitude, reading.baseline)
            ),
        }
        for reading in payload.readings
    ]


async def parse_json_body(request: Request) -> tuple[object | None, JSONResponse | None]:
    """Read and decode the request body as JSON.

    Returns ``(raw, None)`` on success, otherwise ``(None, response)`` with a
    422 field error localized to ``request`` so both endpoints report empty
    and malformed bodies identically.
    """

    body = await request.body()
    if not body:
        return None, JSONResponse(
            status_code=422,
            content={"errors": [field_error("request", "请求体不能为空，需要 JSON 数据")]},
        )

    try:
        raw = json.loads(
            body.decode("utf-8"),
            parse_float=parse_json_numbers,
            parse_constant=parse_json_constant,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        return None, JSONResponse(
            status_code=422,
            content={"errors": [field_error("request", f"JSON 格式非法：{exc}")]},
        )
    return raw, None


@app.post("/api/readings/analyze")
async def analyze_readings(request: Request) -> JSONResponse:
    raw, error_response = await parse_json_body(request)
    if error_response is not None:
        return error_response

    payload, errors = validate_payload(raw)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    assert payload is not None
    segments = find_segments(payload.readings, payload.threshold)
    content: dict[str, object] = {
        "threshold": response_number(payload.threshold),
        "sampleCount": 360,
        "baselineApplied": payload.baseline_applied,
        "segments": [
            segment_to_dict(segment, payload.baseline_applied) for segment in segments
        ],
    }
    if payload.baseline_applied:
        content["points"] = points_to_dict(payload)
    return JSONResponse(content=content)


def calibration_to_dict(result: CalibrationResult) -> dict[str, object]:
    return {
        "name": result.name,
        "pointCount": len(result.points),
        "tolerance": result.tolerance,
        "slope": result.slope,
        "zeroOffset": result.zero_offset,
        "soundVelocity": result.sound_velocity,
        "maxAbsResidual": result.max_abs_residual,
        "maxResidualIndex": result.max_residual_index,
        "status": result.status,
        "points": [
            {
                "thickness": point.thickness,
                "travelTime": point.travel_time,
                "predictedTime": point.predicted_time,
                "residual": point.residual,
                "withinTolerance": point.within_tolerance,
            }
            for point in result.points
        ],
    }


@app.post("/api/calibrations/evaluate")
async def evaluate_calibration_record(request: Request) -> JSONResponse:
    raw, error_response = await parse_json_body(request)
    if error_response is not None:
        return error_response

    record, errors = validate_calibration_payload(raw)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    assert record is not None
    return JSONResponse(content=calibration_to_dict(evaluate_calibration(record)))
