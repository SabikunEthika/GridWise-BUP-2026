import math

from app.models.request_models import OptimizeEnergyRequest
from app.models.response_models import DirectiveInterpretation, HourlyPlanEntry


class ValidationError(Exception):
    pass


def validate_final_plan(
    request: OptimizeEnergyRequest,
    interpretations: list[DirectiveInterpretation],
    plan: list[HourlyPlanEntry]
) -> tuple[float, float, float]:

    if len(plan) != 24:
        raise ValidationError("Plan must contain exactly 24 hours")

    expected_hours = list(range(24))
    actual_hours = [entry.hour for entry in plan]

    if actual_hours != expected_hours:
        raise ValidationError("Plan hours must be exactly 0 through 23")

    battery = request.battery

    solar_factors = [1.0] * 24
    reserve_requirements = [battery.minimum_energy_kwh] * 24
    no_charge = [False] * 24
    no_discharge = [False] * 24
    grid_caps = [None] * 24

    for interpretation in interpretations:
        if not interpretation.applies:
            continue

        adjustment = interpretation.structured_adjustment

        if adjustment is None:
            raise ValidationError(
                f"Directive {interpretation.note_index} has no adjustment"
            )

        if interpretation.directive_type == "solar_reduction":
            for hour in adjustment.hours:
                solar_factors[hour] *= adjustment.factor

        elif interpretation.directive_type == "minimum_battery_reserve":
            for hour in adjustment.hours:
                reserve_requirements[hour] = max(
                    reserve_requirements[hour],
                    adjustment.minimum_energy_kwh
                )

        elif interpretation.directive_type == "no_charge_window":
            for hour in adjustment.hours:
                no_charge[hour] = True

        elif interpretation.directive_type == "no_discharge_window":
            for hour in adjustment.hours:
                no_discharge[hour] = True

        elif interpretation.directive_type == "max_grid_window":
            for hour in adjustment.hours:
                if grid_caps[hour] is None:
                    grid_caps[hour] = adjustment.max_grid_kwh
                else:
                    grid_caps[hour] = min(
                        grid_caps[hour],
                        adjustment.max_grid_kwh
                    )

    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0

    previous_energy = battery.initial_energy_kwh

    for h in range(24):
        entry = plan[h]
        hour_input = request.hours[h]

        grid = entry.grid_kwh
        solar_used = entry.solar_used_kwh
        battery_action = entry.battery_action
        battery_kwh = entry.battery_kwh
        energy_after = entry.battery_energy_after_kwh

        values = [
            grid,
            solar_used,
            battery_kwh,
            energy_after
        ]

        if any(not math.isfinite(value) for value in values):
            raise ValidationError(
                f"Non-finite value at hour {h}"
            )

        if grid < -1e-6:
            raise ValidationError(
                f"Negative grid energy at hour {h}"
            )

        if solar_used < -1e-6:
            raise ValidationError(
                f"Negative solar usage at hour {h}"
            )

        if battery_kwh < -1e-6:
            raise ValidationError(
                f"Negative battery action at hour {h}"
            )

        effective_solar = (
            hour_input.solar_kwh * solar_factors[h]
        )

        if solar_used > effective_solar + 0.01:
            raise ValidationError(
                f"Solar usage exceeds available solar at hour {h}"
            )

        if energy_after < battery.minimum_energy_kwh - 0.01:
            raise ValidationError(
                f"Battery below minimum at hour {h}"
            )

        if energy_after > battery.capacity_kwh + 0.01:
            raise ValidationError(
                f"Battery exceeds capacity at hour {h}"
            )

        if battery_action == "charge":
            if no_charge[h]:
                raise ValidationError(
                    f"Charging is forbidden at hour {h}"
                )

            if battery_kwh > battery.max_charge_kwh_per_hour + 0.01:
                raise ValidationError(
                    f"Charge limit exceeded at hour {h}"
                )

            expected_energy = previous_energy + battery_kwh

            if battery_kwh <= 0.01:
                raise ValidationError(
                    f"Charge action has zero battery movement at hour {h}"
                )

        elif battery_action == "discharge":
            if no_discharge[h]:
                raise ValidationError(
                    f"Discharging is forbidden at hour {h}"
                )

            if battery_kwh > battery.max_discharge_kwh_per_hour + 0.01:
                raise ValidationError(
                    f"Discharge limit exceeded at hour {h}"
                )

            expected_energy = previous_energy - battery_kwh

            if battery_kwh <= 0.01:
                raise ValidationError(
                    f"Discharge action has zero battery movement at hour {h}"
                )

        elif battery_action == "idle":
            if battery_kwh > 0.01:
                raise ValidationError(
                    f"Idle action must have zero battery movement at hour {h}"
                )

            expected_energy = previous_energy

        else:
            raise ValidationError(
                f"Invalid battery action at hour {h}"
            )

        if abs(energy_after - expected_energy) > 0.01:
            raise ValidationError(
                f"Battery energy transition invalid at hour {h}"
            )

        if grid_caps[h] is not None:
            if grid > grid_caps[h] + 0.01:
                raise ValidationError(
                    f"Grid cap exceeded at hour {h}"
                )

        if battery_action == "charge":
            battery_charge = battery_kwh
            battery_discharge = 0.0
        elif battery_action == "discharge":
            battery_charge = 0.0
            battery_discharge = battery_kwh
        else:
            battery_charge = 0.0
            battery_discharge = 0.0

        expected_demand_side = (
            hour_input.demand_kwh + battery_charge
        )

        actual_supply_side = (
            grid + solar_used + battery_discharge
        )

        if abs(actual_supply_side - expected_demand_side) > 0.01:
            raise ValidationError(
                f"Energy balance violated at hour {h}"
            )

        total_grid_kwh += grid
        total_cost_bdt += (
            grid * hour_input.tariff_bdt_per_kwh
        )
        peak_grid_kwh = max(
            peak_grid_kwh,
            grid
        )

        previous_energy = energy_after

    if abs(previous_energy - battery.initial_energy_kwh) > 0.01:
        raise ValidationError(
            "Final battery energy must equal initial battery energy"
        )

    if abs(
        total_grid_kwh
        - sum(entry.grid_kwh for entry in plan)
    ) > 0.01:
        raise ValidationError(
            "Total grid energy calculation is inconsistent"
        )

    if not math.isfinite(total_grid_kwh):
        raise ValidationError("Invalid total grid energy")

    if not math.isfinite(total_cost_bdt):
        raise ValidationError("Invalid total cost")

    if not math.isfinite(peak_grid_kwh):
        raise ValidationError("Invalid peak grid energy")

    return (
        total_grid_kwh,
        total_cost_bdt,
        peak_grid_kwh
    )