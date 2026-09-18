import math
import pulp

from app.models.request_models import OptimizeEnergyRequest
from app.models.response_models import DirectiveInterpretation, HourlyPlanEntry


class OptimizationError(Exception):
    pass


def optimize_energy(
    request: OptimizeEnergyRequest,
    interpretations: list[DirectiveInterpretation]
) -> tuple[list[HourlyPlanEntry], float, float, float]:

    hours = request.hours
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
            raise OptimizationError(
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

    problem = pulp.LpProblem(
        "GridWise_Energy_Optimization",
        pulp.LpMinimize
    )

    grid = {
        h: pulp.LpVariable(f"grid_{h}", lowBound=0)
        for h in range(24)
    }

    solar_used = {
        h: pulp.LpVariable(f"solar_used_{h}", lowBound=0)
        for h in range(24)
    }

    charge = {
        h: pulp.LpVariable(
            f"charge_{h}",
            lowBound=0,
            upBound=battery.max_charge_kwh_per_hour
        )
        for h in range(24)
    }

    discharge = {
        h: pulp.LpVariable(
            f"discharge_{h}",
            lowBound=0,
            upBound=battery.max_discharge_kwh_per_hour
        )
        for h in range(24)
    }

    battery_energy = {
        h: pulp.LpVariable(
            f"battery_energy_{h}",
            lowBound=0,
            upBound=battery.capacity_kwh
        )
        for h in range(24)
    }

    charging_mode = {
        h: pulp.LpVariable(
            f"charging_mode_{h}",
            cat=pulp.LpBinary
        )
        for h in range(24)
    }

    for h in range(24):
        effective_solar = hours[h].solar_kwh * solar_factors[h]

        problem += solar_used[h] <= effective_solar

        problem += (
            grid[h]
            + solar_used[h]
            + discharge[h]
            == hours[h].demand_kwh + charge[h]
        )

        problem += (
            charge[h]
            <= battery.max_charge_kwh_per_hour * charging_mode[h]
        )

        problem += (
            discharge[h]
            <= battery.max_discharge_kwh_per_hour
            * (1 - charging_mode[h])
        )

        if h == 0:
            problem += (
                battery_energy[h]
                == battery.initial_energy_kwh
                + charge[h]
                - discharge[h]
            )
        else:
            problem += (
                battery_energy[h]
                == battery_energy[h - 1]
                + charge[h]
                - discharge[h]
            )

        problem += battery_energy[h] >= reserve_requirements[h]

        if no_charge[h]:
            problem += charge[h] == 0

        if no_discharge[h]:
            problem += discharge[h] == 0

        if grid_caps[h] is not None:
            problem += grid[h] <= grid_caps[h]

    problem += battery_energy[23] == battery.initial_energy_kwh

    problem += pulp.lpSum(
        grid[h] * hours[h].tariff_bdt_per_kwh
        for h in range(24)
    )

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=10)

    status = problem.solve(solver)

    if pulp.LpStatus[status] != "Optimal":
        raise OptimizationError(
            f"Optimization failed with status: {pulp.LpStatus[status]}"
        )

    plan = []

    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0

    for h in range(24):
        grid_value = float(pulp.value(grid[h]) or 0.0)
        solar_value = float(pulp.value(solar_used[h]) or 0.0)
        charge_value = float(pulp.value(charge[h]) or 0.0)
        discharge_value = float(pulp.value(discharge[h]) or 0.0)
        energy_value = float(pulp.value(battery_energy[h]) or 0.0)

        # CBC can return tiny residual values around zero. Treat them as idle
        # so the serialized action and battery transition remain consistent.
        if charge_value > 1e-4:
            action = "charge"
            battery_value = round(charge_value, 4)
        elif discharge_value > 1e-4:
            action = "discharge"
            battery_value = round(discharge_value, 4)
        else:
            action = "idle"
            battery_value = 0.0

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(grid_value, 4),
                solar_used_kwh=round(solar_value, 4),
                battery_action=action,
                battery_kwh=battery_value,
                battery_energy_after_kwh=round(energy_value, 4)
            )
        )

        total_grid_kwh += grid_value
        total_cost_bdt += (
            grid_value * hours[h].tariff_bdt_per_kwh
        )
        peak_grid_kwh = max(
            peak_grid_kwh,
            grid_value
        )

    if not math.isfinite(total_grid_kwh):
        raise OptimizationError("Invalid total grid energy")

    if not math.isfinite(total_cost_bdt):
        raise OptimizationError("Invalid total cost")

    if not math.isfinite(peak_grid_kwh):
        raise OptimizationError("Invalid peak grid energy")

    return (
        plan,
        total_grid_kwh,
        total_cost_bdt,
        peak_grid_kwh
    )
