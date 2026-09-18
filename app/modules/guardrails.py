import math
from typing import Any

from app.models.directive_models import ParsedDirective
from app.models.request_models import OptimizeEnergyRequest
from app.models.response_models import (
    DirectiveInterpretation,
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment
)

SUPPORTED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}


class GuardrailError(Exception):
    pass


def sanitize_and_validate_hours(hours: Any) -> list[int]:
    """
    Auto-repairs minor formatting glitches (floats, unsorted, duplicate hours)
    and strictly validates that hours are unique integers between 0 and 23.
    """
    if not isinstance(hours, list):
        raise GuardrailError("hours must be a list")

    if not hours:
        raise GuardrailError("hours cannot be empty")

    sanitized = []
    for h in hours:
        if isinstance(h, bool):
            raise GuardrailError("boolean values are not valid hours")
        if isinstance(h, (int, float)):
            if not math.isfinite(h):
                raise GuardrailError("non-finite value in hours")
            sanitized.append(int(h))
        elif isinstance(h, str) and h.strip().isdigit():
            sanitized.append(int(h.strip()))
        else:
            raise GuardrailError(f"hour element '{h}' must be an integer")

    for h in sanitized:
        if h < 0 or h > 23:
            raise GuardrailError(f"hour {h} is outside allowed range 0..23")

    # Deduplicate and sort ascending (Section 08 Requirement)
    sorted_unique = sorted(list(set(sanitized)))
    return sorted_unique


def validate_number(value: Any, field_name: str) -> float:
    """Validates that a field is a finite, real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardrailError(f"{field_name} must be numeric")

    if not math.isfinite(float(value)):
        raise GuardrailError(f"{field_name} must be finite")

    return float(value)


def validate_structured_fields(data: dict, allowed_fields: set[str]):
    """Ensures no unsupported fields exist in structured_data."""
    if not isinstance(data, dict):
        raise GuardrailError("structured_data must be an object")

    unexpected = set(data.keys()) - set(allowed_fields)
    if unexpected:
        raise GuardrailError(
            f"Unsupported fields in structured_data: {sorted(unexpected)}"
        )


def validate_directive(
    directive: ParsedDirective,
    request: OptimizeEnergyRequest
) -> DirectiveInterpretation:
    """Validates and coerces a single parsed directive into a DirectiveInterpretation."""
    note_count = len(request.operator_notes)
    battery_capacity = request.battery.capacity_kwh

    if directive.note_index < 0 or directive.note_index >= note_count:
        raise GuardrailError(
            f"note_index {directive.note_index} is out of range 0..{note_count-1}"
        )

    directive_type = directive.directive_type.strip().lower()
    if directive_type not in SUPPORTED_DIRECTIVES:
        raise GuardrailError(
            f"Unsupported directive_type: {directive.directive_type}"
        )

    if not directive.explanation or not directive.explanation.strip():
        raise GuardrailError("explanation cannot be empty")

    if directive_type == "no_op":
        if directive.structured_data is not None:
            raise GuardrailError("no_op must have null structured_data")

        return DirectiveInterpretation(
            note_index=directive.note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=directive.explanation.strip()
        )

    if directive.structured_data is None:
        raise GuardrailError(f"{directive_type} requires structured_data")

    data = directive.structured_data

    if "hours" not in data:
        raise GuardrailError(f"{directive_type} requires hours")

    hours = sanitize_and_validate_hours(data["hours"])

    if directive_type == "solar_reduction":
        validate_structured_fields(data, {"hours", "factor"})
        if "factor" not in data:
            raise GuardrailError("solar_reduction requires factor")

        factor = validate_number(data["factor"], "factor")
        if factor < 0.0 or factor > 1.0:
            raise GuardrailError(
                f"factor must be between 0.0 and 1.0, got {factor}"
            )

        adjustment = SolarReductionAdjustment(
            hours=hours,
            factor=factor
        )

    elif directive_type == "minimum_battery_reserve":
        validate_structured_fields(data, {"hours", "minimum_energy_kwh"})
        if "minimum_energy_kwh" not in data:
            raise GuardrailError("minimum_battery_reserve requires minimum_energy_kwh")

        reserve = validate_number(data["minimum_energy_kwh"], "minimum_energy_kwh")
        if reserve < 0.0:
            raise GuardrailError("minimum_energy_kwh cannot be negative")
        if reserve > battery_capacity:
            raise GuardrailError(
                f"minimum_energy_kwh ({reserve}) cannot exceed battery capacity ({battery_capacity})"
            )

        adjustment = MinimumBatteryReserveAdjustment(
            hours=hours,
            minimum_energy_kwh=reserve
        )

    elif directive_type == "no_charge_window":
        validate_structured_fields(data, {"hours"})
        adjustment = NoChargeWindowAdjustment(hours=hours)

    elif directive_type == "no_discharge_window":
        validate_structured_fields(data, {"hours"})
        adjustment = NoDischargeWindowAdjustment(hours=hours)

    elif directive_type == "max_grid_window":
        validate_structured_fields(data, {"hours", "max_grid_kwh"})
        if "max_grid_kwh" not in data:
            raise GuardrailError("max_grid_window requires max_grid_kwh")

        max_grid = validate_number(data["max_grid_kwh"], "max_grid_kwh")
        if max_grid < 0.0:
            raise GuardrailError("max_grid_kwh cannot be negative")

        adjustment = MaxGridWindowAdjustment(
            hours=hours,
            max_grid_kwh=max_grid
        )

    else:
        raise GuardrailError(f"Unhandled directive type: {directive_type}")

    return DirectiveInterpretation(
        note_index=directive.note_index,
        applies=True,
        directive_type=directive_type,
        structured_adjustment=adjustment,
        explanation=directive.explanation.strip()
    )


def apply_guardrails(
    parsed_directives: list[ParsedDirective],
    request: OptimizeEnergyRequest
) -> list[DirectiveInterpretation]:
    """Applies strict guardrails to all parsed directives in order."""
    note_count = len(request.operator_notes)

    if len(parsed_directives) != note_count:
        raise GuardrailError(
            f"Expected {note_count} directives, but received {len(parsed_directives)}"
        )

    note_indices = [directive.note_index for directive in parsed_directives]
    expected_indices = list(range(note_count))

    if note_indices != expected_indices:
        raise GuardrailError(
            f"Directive note_index values must be exactly {expected_indices} in order, received {note_indices}"
        )

    interpretations = []
    for directive in parsed_directives:
        interpretation = validate_directive(directive, request)
        interpretations.append(interpretation)

    return interpretations
