import math

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


def validate_hours(hours):
    if not isinstance(hours, list):
        raise GuardrailError("hours must be a list")

    if not hours:
        raise GuardrailError("hours cannot be empty")

    if any(type(h) is not int for h in hours):
        raise GuardrailError("all hours must be integers")

    if any(h < 0 or h > 23 for h in hours):
        raise GuardrailError("hours must be between 0 and 23")

    if len(hours) != len(set(hours)):
        raise GuardrailError("hours must be unique")

    if hours != sorted(hours):
        raise GuardrailError("hours must be in ascending order")


def validate_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardrailError(f"{field_name} must be numeric")

    if not math.isfinite(float(value)):
        raise GuardrailError(f"{field_name} must be finite")


def validate_structured_fields(data, allowed_fields):
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

    note_count = len(request.operator_notes)
    battery_capacity = request.battery.capacity_kwh

    if directive.note_index < 0 or directive.note_index >= note_count:
        raise GuardrailError(
            f"note_index {directive.note_index} is out of range"
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
            raise GuardrailError(
                "no_op must have null structured_data"
            )

        return DirectiveInterpretation(
            note_index=directive.note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=directive.explanation
        )

    if directive.structured_data is None:
        raise GuardrailError(
            f"{directive_type} requires structured_data"
        )

    data = directive.structured_data

    if "hours" not in data:
        raise GuardrailError(
            f"{directive_type} requires hours"
        )

    validate_hours(data["hours"])

    hours = data["hours"]

    if directive_type == "solar_reduction":

        validate_structured_fields(
            data,
            {"hours", "factor"}
        )

        if "factor" not in data:
            raise GuardrailError(
                "solar_reduction requires factor"
            )

        factor = data["factor"]

        validate_number(factor, "factor")

        if factor < 0 or factor > 1:
            raise GuardrailError(
                "factor must be between 0 and 1"
            )

        adjustment = SolarReductionAdjustment(
            hours=hours,
            factor=float(factor)
        )

    elif directive_type == "minimum_battery_reserve":

        validate_structured_fields(
            data,
            {"hours", "minimum_energy_kwh"}
        )

        if "minimum_energy_kwh" not in data:
            raise GuardrailError(
                "minimum_battery_reserve requires minimum_energy_kwh"
            )

        reserve = data["minimum_energy_kwh"]

        validate_number(
            reserve,
            "minimum_energy_kwh"
        )

        if reserve < 0:
            raise GuardrailError(
                "minimum_energy_kwh cannot be negative"
            )

        if reserve > battery_capacity:
            raise GuardrailError(
                "minimum_energy_kwh cannot exceed battery capacity"
            )

        adjustment = MinimumBatteryReserveAdjustment(
            hours=hours,
            minimum_energy_kwh=float(reserve)
        )

    elif directive_type == "no_charge_window":

        validate_structured_fields(
            data,
            {"hours"}
        )

        adjustment = NoChargeWindowAdjustment(
            hours=hours
        )

    elif directive_type == "no_discharge_window":

        validate_structured_fields(
            data,
            {"hours"}
        )

        adjustment = NoDischargeWindowAdjustment(
            hours=hours
        )

    elif directive_type == "max_grid_window":

        validate_structured_fields(
            data,
            {"hours", "max_grid_kwh"}
        )

        if "max_grid_kwh" not in data:
            raise GuardrailError(
                "max_grid_window requires max_grid_kwh"
            )

        max_grid = data["max_grid_kwh"]

        validate_number(
            max_grid,
            "max_grid_kwh"
        )

        if max_grid < 0:
            raise GuardrailError(
                "max_grid_kwh cannot be negative"
            )

        adjustment = MaxGridWindowAdjustment(
            hours=hours,
            max_grid_kwh=float(max_grid)
        )

    else:
        raise GuardrailError(
            f"Unhandled directive type: {directive_type}"
        )

    return DirectiveInterpretation(
        note_index=directive.note_index,
        applies=True,
        directive_type=directive_type,
        structured_adjustment=adjustment,
        explanation=directive.explanation
    )


def apply_guardrails(
    parsed_directives: list[ParsedDirective],
    request: OptimizeEnergyRequest
) -> list[DirectiveInterpretation]:

    note_count = len(request.operator_notes)

    if len(parsed_directives) != note_count:
        raise GuardrailError(
            f"Expected {note_count} directives, "
            f"but received {len(parsed_directives)}"
        )

    note_indices = [
        directive.note_index
        for directive in parsed_directives
    ]

    expected_indices = list(range(note_count))

    if note_indices != expected_indices:
        raise GuardrailError(
            f"Directive note_index values must be exactly "
            f"{expected_indices} in order, received {note_indices}"
        )

    interpretations = []

    for directive in parsed_directives:
        interpretation = validate_directive(
            directive,
            request
        )

        interpretations.append(interpretation)

    return interpretations
