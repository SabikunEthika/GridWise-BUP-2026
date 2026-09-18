import pytest

from app.llm_interpreter import (
    fallback_interpret_notes,
    extract_hours_from_text,
    parse_gemini_response
)
from app.modules.guardrails import (
    apply_guardrails,
    sanitize_and_validate_hours,
    GuardrailError
)
from app.models.directive_models import ParsedDirective
from app.models.request_models import OptimizeEnergyRequest, HourInput, BatteryInput


def make_dummy_request(notes: list[str]) -> OptimizeEnergyRequest:
    return OptimizeEnergyRequest(
        scenario_id="TEST-SCENARIO-001",
        operator_notes=notes,
        hours=[
            HourInput(
                hour=i,
                demand_kwh=100.0,
                solar_kwh=50.0,
                tariff_bdt_per_kwh=5.0
            )
            for i in range(24)
        ],
        battery=BatteryInput(
            capacity_kwh=500.0,
            initial_energy_kwh=200.0,
            minimum_energy_kwh=50.0,
            max_charge_kwh_per_hour=100.0,
            max_discharge_kwh_per_hour=100.0
        )
    )


def test_time_window_extraction_24h():
    assert extract_hours_from_text("PV drop between 13:00 and 15:00.") == [13, 14]
    assert extract_hours_from_text("Outage 08:00 to 10:00.") == [8, 9]


def test_time_window_extraction_12h():
    assert extract_hours_from_text("Solar drop from 1 PM to 3 PM.") == [13, 14]
    assert extract_hours_from_text("Do not charge from 2 PM to 4 PM.") == [14, 15]
    assert extract_hours_from_text("Reserve from 6 PM until 9 PM.") == [18, 19, 20]
    assert extract_hours_from_text("1-3 PM maintenance window") == [13, 14]


def test_time_window_extraction_words():
    assert extract_hours_from_text("Panel washing from one until three.") == [13, 14]
    assert extract_hours_from_text("Do not discharge from noon until 2 PM.") == [12, 13]
    assert extract_hours_from_text("Night test from midnight to 4 AM.") == [0, 1, 2, 3]


def test_fallback_directives_comprehensive():
    notes = [
        "PV production will drop to about 20% between 13:00 and 15:00.",
        "Do not charge the battery between 2 PM and 4 PM.",
        "The cafeteria menu changes tomorrow."
    ]
    parsed = fallback_interpret_notes(notes)
    assert len(parsed) == 3

    # Note 0: solar_reduction
    assert parsed[0].note_index == 0
    assert parsed[0].directive_type == "solar_reduction"
    assert parsed[0].structured_data["hours"] == [13, 14]
    assert parsed[0].structured_data["factor"] == 0.2

    # Note 1: no_charge_window
    assert parsed[1].note_index == 1
    assert parsed[1].directive_type == "no_charge_window"
    assert parsed[1].structured_data["hours"] == [14, 15]

    # Note 2: no_op (distractor)
    assert parsed[2].note_index == 2
    assert parsed[2].directive_type == "no_op"
    assert parsed[2].structured_data is None


def test_guardrails_validation_and_repair():
    notes = [
        "Solar output drop",
        "Keep 120 kWh reserve",
        "Distractor"
    ]
    req = make_dummy_request(notes)

    # Test auto-sorting of unsorted hours and float conversion
    parsed = [
        ParsedDirective(
            note_index=0,
            directive_type="solar_reduction",
            structured_data={"hours": [14.0, 13.0, 14.0], "factor": 0.2},
            explanation="Solar cleaning"
        ),
        ParsedDirective(
            note_index=1,
            directive_type="minimum_battery_reserve",
            structured_data={"hours": [18, 19, 20], "minimum_energy_kwh": 120.0},
            explanation="Evening peak reserve"
        ),
        ParsedDirective(
            note_index=2,
            directive_type="no_op",
            structured_data=None,
            explanation="Unrelated"
        )
    ]

    interpretations = apply_guardrails(parsed, req)
    assert len(interpretations) == 3

    # Check auto-repaired hours
    assert interpretations[0].structured_adjustment.hours == [13, 14]
    assert interpretations[0].applies is True

    # Check reserve
    assert interpretations[1].applies is True
    assert interpretations[1].structured_adjustment.minimum_energy_kwh == 120.0

    # Check no_op
    assert interpretations[2].applies is False
    assert interpretations[2].structured_adjustment is None


def test_guardrails_rejects_exceeded_reserve():
    req = make_dummy_request(["Keep reserve"])
    # Capacity is 500, reserve 600 should fail
    parsed = [
        ParsedDirective(
            note_index=0,
            directive_type="minimum_battery_reserve",
            structured_data={"hours": [10, 11], "minimum_energy_kwh": 600.0},
            explanation="Exceeds capacity"
        )
    ]
    with pytest.raises(GuardrailError):
        apply_guardrails(parsed, req)


def test_parse_gemini_response_with_markdown_fences():
    raw_markdown = """```json
[
  {
    "note_index": 0,
    "directive_type": "solar_reduction",
    "structured_data": {"hours": [13, 14], "factor": 0.2},
    "explanation": "Valid test"
  }
]
```"""
    parsed = parse_gemini_response(raw_markdown, 1)
    assert len(parsed) == 1
    assert parsed[0].directive_type == "solar_reduction"
    assert parsed[0].structured_data["factor"] == 0.2
