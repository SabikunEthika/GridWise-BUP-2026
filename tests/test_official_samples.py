import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.directive_models import ParsedDirective

client = TestClient(app)

with open("data/public_sample_cases.json", "r") as f:
    PUBLIC_DATA = json.load(f)

CASES = PUBLIC_DATA["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_official_sample_case_optimizer(monkeypatch, case):
    """
    Verifies that for each official sample case, applying the ground-truth
    directive yields an hourly plan and total cost that match the official reference
    solution within tolerance.
    """
    import app.main as main_module

    expected_directives = case["expected_output"]["directive_interpretation"]
    parsed_list = []
    for d in expected_directives:
        parsed_list.append(
            ParsedDirective(
                note_index=d["note_index"],
                directive_type=d["directive_type"],
                structured_data=d["structured_adjustment"],
                explanation=d["explanation"],
            )
        )

    monkeypatch.setattr(main_module, "interpret_operator_notes", lambda notes, cap=None: parsed_list)

    response = client.post("/optimize-energy", json=case["input"])
    assert response.status_code == 200, response.text
    data = response.json()

    exp = case["expected_output"]
    assert data["scenario_id"] == exp["scenario_id"]
    assert len(data["hourly_plan"]) == 24
    assert len(data["directive_interpretation"]) == len(exp["directive_interpretation"])

    # Verify total cost and grid kwh within floating point tolerance
    assert abs(data["total_cost_bdt"] - exp["total_cost_bdt"]) <= 0.05, (
        f"Cost mismatch in {case['id']}: got {data['total_cost_bdt']}, expected {exp['total_cost_bdt']}"
    )
    assert abs(data["total_grid_kwh"] - exp["total_grid_kwh"]) <= 0.05, (
        f"Grid mismatch in {case['id']}: got {data['total_grid_kwh']}, expected {exp['total_grid_kwh']}"
    )
    assert abs(data["peak_grid_kwh"] - exp["peak_grid_kwh"]) <= 0.05, (
        f"Peak mismatch in {case['id']}: got {data['peak_grid_kwh']}, expected {exp['peak_grid_kwh']}"
    )


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_official_sample_case_fallback_interpreter(case):
    """
    Verifies that the deterministic fallback rule engine accurately parses
    natural language notes in the official sample cases when Gemini is offline.
    """
    from app.llm_interpreter import fallback_interpret_notes

    notes = case["input"]["operator_notes"]
    capacity = case["input"]["battery"]["capacity_kwh"]
    parsed = fallback_interpret_notes(notes, capacity)

    expected = case["expected_output"]["directive_interpretation"]
    assert len(parsed) == len(expected)

    for p, exp in zip(parsed, expected):
        assert p.directive_type == exp["directive_type"], (
            f"Case {case['id']}: expected directive_type {exp['directive_type']}, got {p.directive_type}"
        )
        if exp["directive_type"] == "no_op":
            assert p.structured_data is None
        else:
            assert p.structured_data is not None
            exp_adj = exp["structured_adjustment"]
            # Check hours
            assert p.structured_data["hours"] == exp_adj["hours"], (
                f"Case {case['id']}: expected hours {exp_adj['hours']}, got {p.structured_data['hours']}"
            )
            # Check directive specific fields
            if "factor" in exp_adj:
                assert abs(p.structured_data["factor"] - exp_adj["factor"]) <= 0.01, (
                    f"Case {case['id']}: expected factor {exp_adj['factor']}, got {p.structured_data['factor']}"
                )
            if "minimum_energy_kwh" in exp_adj:
                assert abs(p.structured_data["minimum_energy_kwh"] - exp_adj["minimum_energy_kwh"]) <= 0.01, (
                    f"Case {case['id']}: expected reserve {exp_adj['minimum_energy_kwh']}, got {p.structured_data['minimum_energy_kwh']}"
                )
            if "max_grid_kwh" in exp_adj:
                assert abs(p.structured_data["max_grid_kwh"] - exp_adj["max_grid_kwh"]) <= 0.01, (
                    f"Case {case['id']}: expected max_grid {exp_adj['max_grid_kwh']}, got {p.structured_data['max_grid_kwh']}"
                )

