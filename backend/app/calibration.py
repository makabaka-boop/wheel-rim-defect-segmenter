"""Sound-path calibration records: ordinary least squares line fit.

After a probe or couplant change the inspector measures round-trip travel
times on a reference block of known thicknesses and fits
``travel_time = slope * thickness + zero_offset``. The fitted sound velocity
is ``2 / slope`` (round trip) and the zero offset is the fitted intercept.

This module is deliberately independent from the defect-segmentation core:
it does not reuse ``Reading``/``Segment`` or the baseline-compensation
objects, and keeps its own validation so the calibration record module can
evolve on its own.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import math

MIN_POINTS = 3
MAX_POINTS = 8

# A record is unevaluated until a fit is requested, then rated pass/fail.
STATUS_UNEVALUATED = "unevaluated"
STATUS_PASS = "pass"
STATUS_FAIL = "fail"

# Inputs may arrive as int, float (direct callers/tests) or Decimal (decoded
# from JSON with decimal-exact parsing), mirroring the analyze endpoint.
Number = Decimal | float | int


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    try:
        return math.isfinite(value)  # type: ignore[arg-type]
    except OverflowError:
        # Ints/Decimals beyond the float range raise instead of returning
        # False; treat them as invalid so validation reports the field.
        return False


@dataclass(frozen=True)
class CalibrationPoint:
    """One measured point: known block thickness and round-trip time."""

    thickness: float
    travel_time: float


@dataclass(frozen=True)
class FittedPoint:
    """A measured point together with its prediction and signed residual."""

    thickness: float
    travel_time: float
    predicted_time: float
    residual: float
    within_tolerance: bool


@dataclass(frozen=True)
class CalibrationRecord:
    """Validated calibration input ready to be fitted."""

    name: str
    tolerance: float
    points: tuple[CalibrationPoint, ...]


@dataclass(frozen=True)
class CalibrationResult:
    """Fitted line plus the pass/fail rating of the record."""

    name: str
    tolerance: float
    slope: float
    zero_offset: float
    sound_velocity: float
    points: tuple[FittedPoint, ...]
    max_abs_residual: float
    max_residual_index: int
    status: str  # STATUS_PASS or STATUS_FAIL once evaluated


def field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def fit_line(points: tuple[CalibrationPoint, ...] | list[CalibrationPoint]) -> tuple[float, float]:
    """Return the ordinary least squares ``(slope, intercept)``.

    Raises ``ValueError`` for degenerate input: fewer than two points,
    identical thickness values (zero variance), or a non-positive or
    non-finite slope, which cannot describe a physical sound path.
    """

    count = len(points)
    if count < 2:
        raise ValueError("at least two points are required to fit a line")
    mean_x = sum(point.thickness for point in points) / count
    mean_y = sum(point.travel_time for point in points) / count
    sxx = sum((point.thickness - mean_x) ** 2 for point in points)
    sxy = sum((point.thickness - mean_x) * (point.travel_time - mean_y) for point in points)
    if sxx <= 0:
        raise ValueError("degenerate fit: thickness values must differ")
    slope = sxy / sxx
    if not math.isfinite(slope) or slope <= 0:
        raise ValueError("degenerate fit: slope must be a positive finite number")
    intercept = mean_y - slope * mean_x
    if not math.isfinite(intercept):
        raise ValueError("degenerate fit: intercept must be finite")
    return slope, intercept


def evaluate_calibration(record: CalibrationRecord) -> CalibrationResult:
    """Fit the record and rate it pass/fail against the allowed residual.

    A point is within tolerance when ``abs(measured - predicted)`` does not
    exceed ``record.tolerance``; the record passes when every point does,
    i.e. when the maximum absolute residual stays within the tolerance.
    """

    slope, intercept = fit_line(record.points)
    fitted = tuple(
        FittedPoint(
            thickness=point.thickness,
            travel_time=point.travel_time,
            predicted_time=slope * point.thickness + intercept,
            residual=point.travel_time - (slope * point.thickness + intercept),
            within_tolerance=abs(point.travel_time - (slope * point.thickness + intercept))
            <= record.tolerance,
        )
        for point in record.points
    )
    # ``max`` keeps the first occurrence, so ties resolve to the lowest index.
    max_index = max(range(len(fitted)), key=lambda index: abs(fitted[index].residual))
    max_abs = abs(fitted[max_index].residual)
    return CalibrationResult(
        name=record.name,
        tolerance=record.tolerance,
        slope=slope,
        zero_offset=intercept,
        sound_velocity=2.0 / slope,
        points=fitted,
        max_abs_residual=max_abs,
        max_residual_index=max_index,
        status=STATUS_PASS if max_abs <= record.tolerance else STATUS_FAIL,
    )


def validate_calibration_payload(raw: object) -> tuple[CalibrationRecord | None, list[dict[str, str]]]:
    """Validate the decoded JSON body, localizing every problem to a field."""

    if not isinstance(raw, Mapping):
        return None, [field_error("$", "请求体必须是 JSON 对象")]

    errors: list[dict[str, str]] = []

    if "name" not in raw:
        errors.append(field_error("name", "缺少记录名称"))
    else:
        name = raw["name"]
        if not isinstance(name, str) or not name.strip():
            errors.append(field_error("name", "记录名称必须是非空字符串"))

    if "tolerance" not in raw:
        errors.append(field_error("tolerance", "缺少允许残差"))
    else:
        tolerance = raw["tolerance"]
        if not _is_finite_number(tolerance):
            errors.append(field_error("tolerance", "允许残差必须是有限数字"))
        elif tolerance <= 0:
            errors.append(field_error("tolerance", "允许残差必须是正数"))

    points_raw = raw.get("points")
    if "points" not in raw:
        errors.append(field_error("points", "缺少 points 测点数组"))
        points_raw = []
    elif not isinstance(points_raw, list):
        errors.append(field_error("points", "points 必须是数组"))
        points_raw = []
    elif not MIN_POINTS <= len(points_raw) <= MAX_POINTS:
        errors.append(
            field_error(
                "points",
                f"points 必须包含 {MIN_POINTS} 至 {MAX_POINTS} 个测点，当前为 {len(points_raw)} 个",
            )
        )

    thickness_positions: dict[Number, list[int]] = {}
    for index, item in enumerate(points_raw):
        base_path = f"points[{index}]"
        if not isinstance(item, Mapping):
            errors.append(field_error(base_path, "该测点必须是 JSON 对象"))
            continue

        if "thickness" not in item:
            errors.append(field_error(f"{base_path}.thickness", "缺少 thickness 字段"))
        else:
            thickness = item["thickness"]
            if not _is_finite_number(thickness):
                errors.append(
                    field_error(f"{base_path}.thickness", "thickness 必须是有限数字（毫米）")
                )
            elif thickness <= 0:
                errors.append(field_error(f"{base_path}.thickness", "thickness 必须是正数"))
            else:
                thickness_positions.setdefault(thickness, []).append(index)

        if "travelTime" not in item:
            errors.append(field_error(f"{base_path}.travelTime", "缺少 travelTime 字段"))
        else:
            travel_time = item["travelTime"]
            if not _is_finite_number(travel_time):
                errors.append(
                    field_error(f"{base_path}.travelTime", "travelTime 必须是有限数字（微秒）")
                )
            elif travel_time <= 0:
                errors.append(field_error(f"{base_path}.travelTime", "travelTime 必须是正数"))

    for positions in sorted(thickness_positions.values(), key=lambda value: value[0]):
        if len(positions) > 1:
            for position in positions:
                thickness = points_raw[position]["thickness"]
                errors.append(
                    field_error(
                        f"points[{position}].thickness",
                        f"厚度 {thickness} 重复，每个测点的厚度必须互异",
                    )
                )

    if errors:
        return None, errors

    points = tuple(
        CalibrationPoint(
            thickness=float(item["thickness"]),
            travel_time=float(item["travelTime"]),
        )
        for item in points_raw
    )
    try:
        fit_line(points)
    except ValueError:
        errors.append(
            field_error(
                "points",
                "拟合斜率退化：往返时间必须随厚度正向增大，无法拟合出正有限声速",
            )
        )
        return None, errors

    return (
        CalibrationRecord(
            name=str(raw["name"]).strip(),
            tolerance=float(raw["tolerance"]),
            points=points,
        ),
        [],
    )
