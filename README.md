# GridWise – BUP Smart Campus Energy Optimization API

> **BUP CSE Fest 2026 Hackathon Submission**
> Intelligent 24-hour energy scheduling with natural-language operator directives, mathematical optimization, and robust guardrails.

---

## Overview

GridWise is a RESTful API that accepts a campus energy scenario (hourly demand, solar generation, tariffs, and battery specifications) along with 1–3 natural-language operator notes. It interprets the notes into structured directives, solves a Mixed-Integer Linear Program (MILP) to minimize grid electricity cost, and returns a validated 24-hour energy schedule.

### Key Features

- **LLM-Powered NLP Interpretation** – Uses Google Gemini API to parse free-text operator notes into structured directives with temperature-0 determinism.
- **Safe Failure Fallback** – Deterministic rule-based interpreter auto-activates when Gemini is unavailable, ensuring the service never crashes.
- **6 Supported Directive Types** – `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`.
- **MILP Optimization** – PuLP/CBC solver with binary variables preventing simultaneous charge/discharge, end-of-day battery neutrality, and directive-aware constraints.
- **Post-Solve Validation** – Independent validator verifies energy balance, battery physics, directive compliance, and numerical consistency.
- **Strict HTTP Contract** – `200` success, `400` malformed requests, `422` semantic errors, `500` controlled internal errors.

---

## Architecture

```
POST /optimize-energy
        │
        ▼
┌─────────────────────┐
│  LLM Interpreter    │  ← Gemini API or deterministic fallback
│  (llm_interpreter)  │
└────────┬────────────┘
         │ ParsedDirective[]
         ▼
┌─────────────────────┐
│  Guardrails Module  │  ← Validates, sanitizes, auto-repairs
│  (guardrails)       │
└────────┬────────────┘
         │ DirectiveInterpretation[]
         ▼
┌─────────────────────┐
│  PuLP Optimizer     │  ← MILP cost minimization
│  (optimizer)        │
└────────┬────────────┘
         │ HourlyPlanEntry[]
         ▼
┌─────────────────────┐
│  Post-Solve         │  ← Independent validation
│  Validator          │
└────────┬────────────┘
         │
         ▼
   200 OK: OptimizeEnergyResponse
```

---

## Project Structure

```
GridWise-BUP-2026/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI entry point & exception handlers
│   ├── llm_interpreter.py         # Gemini NLP + deterministic fallback
│   ├── optimizer.py               # PuLP MILP solver
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request_models.py      # Pydantic request schemas
│   │   ├── response_models.py     # Pydantic response schemas
│   │   └── directive_models.py    # Intermediate directive models
│   └── modules/
│       ├── __init__.py
│       ├── guardrails.py          # Directive validation & auto-repair
│       └── validator.py           # Post-solve plan validation
├── tests/
│   ├── test_interpreter.py        # NLP & guardrail unit tests
│   └── test_e2e_scenarios.py      # End-to-end API tests
├── .env.example                   # Environment variable template
├── .gitignore
├── Dockerfile                     # Production container
├── docker-compose.yml             # Docker Compose configuration
├── requirements.txt               # Python dependencies
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- (Optional) Docker & Docker Compose

### Local Development

```bash
# 1. Clone the repository
git clone https://github.com/SabikunEthika/GridWise-BUP-2026.git
cd GridWise-BUP-2026

# 2. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY (optional – fallback works without it)

# 5. Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Deployment

```bash
# Build and run
docker compose up --build

# The API is accessible at http://localhost:8000
```

---

## API Endpoints

### `GET /health`

Health check endpoint.

**Response**: `200 OK`
```json
{"status": "ok"}
```

### `POST /optimize-energy`

Submit an energy scenario for optimization.

**Request Body**:
```json
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "Do not charge the battery between 2 PM and 4 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {
      "hour": 0,
      "demand_kwh": 40.0,
      "solar_kwh": 0.0,
      "tariff_bdt_per_kwh": 6.0
    }
  ],
  "battery": {
    "capacity_kwh": 300.0,
    "initial_energy_kwh": 100.0,
    "minimum_energy_kwh": 30.0,
    "max_charge_kwh_per_hour": 50.0,
    "max_discharge_kwh_per_hour": 50.0
  }
}
```

**Response**: `200 OK`
```json
{
  "scenario_id": "GRID-101",
  "directive_interpretation": [...],
  "hourly_plan": [...],
  "total_grid_kwh": 1520.0,
  "total_cost_bdt": 12960.0,
  "peak_grid_kwh": 100.0,
  "plan_summary": "Generated a valid 24-hour energy schedule..."
}
```

### Error Responses

| Status | Meaning |
|--------|---------|
| `400` | Malformed JSON or structurally invalid request |
| `422` | Semantically invalid (guardrail violation, infeasible optimization) |
| `500` | Controlled internal error |

---

## Running Tests

```bash
# Install test dependencies
pip install pytest httpx

# Run all tests
pytest tests/ -v
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Google Gemini API key (optional – fallback works without it) | — |
| `LLM_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `PORT` | Server port | `8000` |

---

## Supported Directives

| Directive | Effect | Structured Data |
|-----------|--------|-----------------|
| `solar_reduction` | Reduces usable solar by a factor | `{hours, factor}` |
| `minimum_battery_reserve` | Enforces minimum battery level | `{hours, minimum_energy_kwh}` |
| `no_charge_window` | Prevents battery charging | `{hours}` |
| `no_discharge_window` | Prevents battery discharging | `{hours}` |
| `max_grid_window` | Caps grid import | `{hours, max_grid_kwh}` |
| `no_op` | Irrelevant note (distractor) | `null` |

---

## Team

**BUP CSE Fest 2026 – GridWise Challenge**