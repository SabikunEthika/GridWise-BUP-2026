from pydantic import BaseModel, Field
from typing import Literal, Optional


class DirectiveData(BaseModel):
    """Base class for all directive data"""
    pass


class SolarReductionDirective(DirectiveData):
    hours: list[int]
    factor: float = Field(ge=0, le=1)


class MinimumBatteryReserveDirective(DirectiveData):
    hours: list[int]
    minimum_energy_kwh: float = Field(ge=0)


class NoChargeWindowDirective(DirectiveData):
    hours: list[int]


class NoDischargeWindowDirective(DirectiveData):
    hours: list[int]


class MaxGridWindowDirective(DirectiveData):
    hours: list[int]
    max_grid_kwh: float = Field(ge=0)


class ParsedDirective(BaseModel):
    """What the LLM interpreter returns (before guardrails validation)"""
    note_index: int
    directive_type: str
    structured_data: Optional[dict] = None
    explanation: str
