from pydantic import BaseModel, Field
from typing import Literal, Optional


class SolarReductionAdjustment(BaseModel):
    hours: list[int]
    factor: float = Field(ge=0, le=1)


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: list[int]
    minimum_energy_kwh: float = Field(ge=0)


class NoChargeWindowAdjustment(BaseModel):
    hours: list[int]


class NoDischargeWindowAdjustment(BaseModel):
    hours: list[int]


class MaxGridWindowAdjustment(BaseModel):
    hours: list[int]
    max_grid_kwh: float = Field(ge=0)


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(ge=0)
    applies: bool
    directive_type: Literal[
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op"
    ]
    structured_adjustment: Optional[
        SolarReductionAdjustment
        | MinimumBatteryReserveAdjustment
        | NoChargeWindowAdjustment
        | NoDischargeWindowAdjustment
        | MaxGridWindowAdjustment
    ] = None
    explanation: str = Field(min_length=1)


class HourlyPlanEntry(BaseModel):
    hour: int = Field(ge=0, le=23)
    grid_kwh: float = Field(ge=0)
    solar_used_kwh: float = Field(ge=0)
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float = Field(ge=0)
    battery_energy_after_kwh: float = Field(ge=0)


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourlyPlanEntry]
    total_grid_kwh: float = Field(ge=0)
    total_cost_bdt: float = Field(ge=0)
    peak_grid_kwh: float = Field(ge=0)
    plan_summary: str = Field(min_length=1)
