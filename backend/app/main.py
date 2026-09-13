import json
from dataclasses import replace
from decimal import Decimal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .calibration import (
    CalibrationResult,
    evaluate_calibration,
    validate_calibration_payload,
)
from .core import Number, Reading, Segment, corrected_amplitude, find_segments
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


def normalize_angle(angle: int, offset: int) -> int:
    """Apply the field zero re-mark offset as a circular 0..359 rotation.

    The displayed angle is the encoder (source) angle shifted by the offset;
    Python ``%`` keeps negative offsets on the circle instead of drifting to
    negative values.
    """

    return (angle + offset) % 360


def rotate_readings(readings: list[Reading], offset: int) -> list[Reading]:
    """Move readings onto the on-site marked coordinates.

    Rotation runs strictly after baseline pairing and corrected-amplitude
    computation, so the values riding each angle are untouched and only their
    angle coordinate changes.
    """

    if offset == 0:
        return readings
    return [
        replace(reading, angle=normalize_angle(reading.angle, offset))
        for reading in readings
    ]


def occluded_angle_set(occlusions: list[tuple[int, int]] | None) -> set[int]:
    """Merge clockwise closed occlusion intervals into one display-angle set.

    Each interval walks clockwise from ``start`` to ``end`` inclusive, so a
    start past its end wraps through 0° and ``start == end`` occludes exactly
    that one point. Overlapping and cross-zero intervals merge naturally in
    the set.
    """

    angles: set[int] = set()
    for start, end in occlusions or []:
        angle = start
        while True:
            angles.add(angle)
            if angle == end:
                break
            angle = (angle + 1) % 360
    return angles


def segment_to_dict(
    segment: Segment,
    baseline_applied: bool,
    offset: int | None = None,
) -> dict[str, object]:
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
    if offset:
        # The angles above are displayed (on-site marked) angles; the source*
        # fields map every boundary and the peak back onto encoder coordinates
        # so the original sample stays traceable.
        data["sourceStartAngle"] = normalize_angle(segment.start_angle, -offset)
        data["sourceEndAngle"] = normalize_angle(segment.end_angle, -offset)
        data["sourcePeakAngle"] = normalize_angle(segment.peak_angle, -offset)
        data["sourceAngles"] = [normalize_angle(angle, -offset) for angle in segment.angles]
    return data


def points_to_dict(
    payload: ValidatedPayload,
    offset: int | None = None,
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for reading in payload.readings:
        point: dict[str, object] = {
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
        if offset:
            # Baseline and values stay paired by source angle; only the angle
            # coordinate is reported in display space, with sourceAngle kept.
            point["sourceAngle"] = reading.angle
            point["angle"] = normalize_angle(reading.angle, offset)
        else:
            point["angle"] = reading.angle
        points.append(point)
    # Points are always reported walking the display circle 0..359. Readings
    # arrive sorted by source angle, so a zero re-mark rotation would
    # otherwise wrap the tail (e.g. 5..359, 0..4) instead of starting at 0.
    points.sort(key=lambda point: point["angle"])
    return points


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
    # Baseline is paired against the original (source) angles and corrected
    # amplitudes are computed first; only then are readings rotated onto the
    # on-site marked coordinates, so compensation never follows display space.
    offset = payload.angle_offset or 0
    rotated = rotate_readings(payload.readings, offset)
    # Occlusion intervals are already expressed in display angles, so they
    # apply after the rotation, on the same coordinates the segments use.
    occluded = occluded_angle_set(payload.occlusions)
    segments = find_segments(rotated, payload.threshold, occluded=occluded)
    content: dict[str, object] = {
        "threshold": response_number(payload.threshold),
        "sampleCount": 360,
        "baselineApplied": payload.baseline_applied,
        "segments": [
            segment_to_dict(segment, payload.baseline_applied, payload.angle_offset)
            for segment in segments
        ],
    }
    if payload.occlusions is not None:
        # The merged unreadable angles, sorted 0..359, so the page can mark
        # the occluded range independently of the defective segments.
        content["occludedAngles"] = sorted(occluded)
    if payload.angle_offset:
        content["angleOffset"] = payload.angle_offset
    if payload.baseline_applied:
        content["points"] = points_to_dict(payload, payload.angle_offset)
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
