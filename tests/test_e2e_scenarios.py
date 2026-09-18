from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models.directive_models import ParsedDirective


client = TestClient(app)


def make_payload(notes=None):
    return {
        "scenario_id": "GRID-101",
        "operator_notes": notes or [
            "Solar output will drop to about 20% from 1 PM to 3 PM.",
            "Do not charge the battery between 2 PM and 4 PM.",
            "The cafeteria menu changes tomorrow.",
        ],
        "hours": [
            {
                "hour": hour,
                "demand_kwh": 100.0 if 8 <= hour <= 18 else 40.0,
                "solar_kwh": 80.0 if 10 <= hour <= 16 else 0.0,
                "tariff_bdt_per_kwh": 12.0 if 17 <= hour <= 21 else 6.0,
            }
            for hour in range(24)
        ],
        "battery": {
            "capacity_kwh": 300.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 30.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0,
        },
    }


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_structurally_invalid_request_returns_400():
    assert client.post("/optimize-energy", json={}).status_code == 400
    assert client.post("/optimize-energy", content="not-json").status_code == 400


def test_full_scenario_with_directives_and_consistent_metrics(monkeypatch):
    # Keep the E2E suite deterministic and offline; the production interpreter
    # may use Gemini, while this suite exercises the API/optimizer contract.
    import app.main as main_module

    monkeypatch.setattr(main_module, "interpret_operator_notes", lambda notes: [
        ParsedDirective(note_index=0, directive_type="solar_reduction", structured_data={"hours": [13, 14], "factor": 0.2}, explanation="solar reduction"),
        ParsedDirective(note_index=1, directive_type="no_charge_window", structured_data={"hours": [14, 15],}, explanation="no charging"),
        ParsedDirective(note_index=2, directive_type="no_op", structured_data=None, explanation="irrelevant note"),
    ])
    response = client.post("/optimize-energy", json=make_payload())
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["scenario_id"] == "GRID-101"
    assert len(data["hourly_plan"]) == 24
    assert len(data["directive_interpretation"]) == 3
    assert data["total_grid_kwh"] >= 0
    assert data["total_cost_bdt"] >= 0
    assert data["peak_grid_kwh"] >= 0

    plan = data["hourly_plan"]
    assert [entry["hour"] for entry in plan] == list(range(24))
    assert abs(data["total_grid_kwh"] - sum(e["grid_kwh"] for e in plan)) <= 0.01
    assert abs(data["peak_grid_kwh"] - max(e["grid_kwh"] for e in plan)) <= 0.01


@pytest.mark.parametrize(
    ("directive", "structured_data"),
    [
        ("solar_reduction", {"hours": [10], "factor": 0.2}),
        ("minimum_battery_reserve", {"hours": [11], "minimum_energy_kwh": 80}),
        ("no_charge_window", {"hours": [12]}),
        ("no_discharge_window", {"hours": [12]}),
        ("max_grid_window", {"hours": [12], "max_grid_kwh": 120}),
        ("no_op", None),
    ],
)
def test_each_supported_directive_variation_is_accepted(monkeypatch, directive, structured_data):
    """Exercise all six supported directive types without a remote LLM."""
    import app.main as main_module

    parsed = ParsedDirective(
        note_index=0,
        directive_type=directive,
        structured_data=structured_data,
        explanation=f"{directive} test",
    )
    monkeypatch.setattr(main_module, "interpret_operator_notes", lambda notes: [parsed])
    response = client.post("/optimize-energy", json=make_payload(["test directive"]))
    assert response.status_code == 200, response.text
