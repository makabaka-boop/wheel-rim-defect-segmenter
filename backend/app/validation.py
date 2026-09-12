"""Request validation with field-localized error messages."""

from collections.abc import Mapping
from dataclasses import dataclass
import math

from .core import Reading


@dataclass(frozen=True)
class ValidatedPayload:
    threshold: float
    readings: list[Reading]


def field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_payload(
    raw: object,
) -> tuple[ValidatedPayload | None, list[dict[str, str]]]:
    if not isinstance(raw, Mapping):
        return None, [field_error("$", "请求体必须是 JSON 对象")]

    errors: list[dict[str, str]] = []

    if "threshold" not in raw:
        errors.append(field_error("threshold", "缺少阈值"))
    else:
        threshold = raw["threshold"]
        if not is_finite_number(threshold):
            errors.append(field_error("threshold", "阈值必须是有限数字"))
        elif threshold < 0:
            errors.append(field_error("threshold", "阈值必须是非负数"))

    samples = raw.get("samples")
    if "samples" not in raw:
        errors.append(field_error("samples", "缺少 samples 采样数组"))
        samples = []
    elif not isinstance(samples, list):
        errors.append(field_error("samples", "samples 必须是数组"))
        samples = []
    elif len(samples) != 360:
        errors.append(
            field_error("samples", f"samples 必须恰好包含 360 条，当前为 {len(samples)} 条")
        )

    angle_positions: dict[int, list[int]] = {}

    for index, item in enumerate(samples):
        base_path = f"samples[{index}]"
        if not isinstance(item, Mapping):
            errors.append(field_error(base_path, "该采样必须是 JSON 对象"))
            continue

        if "angle" not in item:
            errors.append(field_error(f"{base_path}.angle", "缺少 angle 字段"))
        else:
            angle = item["angle"]
            if not isinstance(angle, int) or isinstance(angle, bool):
                errors.append(field_error(f"{base_path}.angle", "angle 必须是整数"))
            elif not 0 <= angle <= 359:
                errors.append(field_error(f"{base_path}.angle", "angle 必须在 0 至 359 之间"))
            else:
                angle_positions.setdefault(angle, []).append(index)

        if "amplitude" not in item:
            errors.append(field_error(f"{base_path}.amplitude", "缺少 amplitude 字段"))
        else:
            amplitude = item["amplitude"]
            if not is_finite_number(amplitude):
                errors.append(
                    field_error(f"{base_path}.amplitude", "amplitude 必须是有限数字（毫米）")
                )
            elif amplitude < 0:
                errors.append(
                    field_error(f"{base_path}.amplitude", "amplitude 必须是非负数")
                )

    if isinstance(samples, list):
        for positions in sorted(angle_positions.values(), key=lambda value: value[0]):
            if len(positions) > 1:
                for position in positions:
                    angle = samples[position]["angle"]
                    errors.append(
                        field_error(
                            f"samples[{position}].angle",
                            f"角度 {angle} 重复，0 至 359 每个角度只能出现一次",
                        )
                    )

    if errors:
        return None, errors

    readings = sorted(
        (
            Reading(angle=int(item["angle"]), amplitude=float(item["amplitude"]))
            for item in samples
        ),
        key=lambda reading: reading.angle,
    )
    return ValidatedPayload(threshold=float(raw["threshold"]), readings=readings), []
