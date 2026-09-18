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

### Docker Deployment & Fallback Instructions

```bash
# Option A: Run via Docker Compose (Recommended)
docker compose up --build -d

# Option B: Run via verified Docker Run command
docker build -t gridwise-api:latest .
docker run -d -p 8000:8000 --env-file .env.example --name gridwise-service gridwise-api:latest

# Verify health endpoint
curl -X GET http://localhost:8000/health
# Returns: {"status": "ok"}
```

---

## Public Sample Verification & Expected Results

The repository includes the official benchmark dataset in `data/public_sample_cases.json`.

### 1. Automated Benchmark Test
Run all 10 official public sample benchmark cases with one command:
```bash
pytest tests/test_official_samples.py -v
```
All 10 benchmark cases validate:
- 100% accurate directive interpretation (directive_type, hours, factors, reserves, caps)
- 100% accurate cost minimization matching the organizer optimal cost benchmark ($38,365.00 for SAMPLE-01, $42,885.00 for SAMPLE-02, etc.)

### 2. Live cURL Test (SAMPLE-01)
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next month'\''s registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
      {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
      {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
      {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
      {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
      {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
      {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
      {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
      {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
      {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
      {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
      {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
      "capacity_kwh": 220,
      "initial_energy_kwh": 110,
      "minimum_energy_kwh": 40,
      "max_charge_kwh_per_hour": 50,
      "max_discharge_kwh_per_hour": 50
    }
  }'
```

**Expected Result**:
- `total_grid_kwh`: `2692.5`
- `total_cost_bdt`: `38365.0`
- `peak_grid_kwh`: `175.0`
- `directive_interpretation[0]`: `solar_reduction` with `hours: [12, 13]` and `factor: 0.25`
- `directive_interpretation[1]`: `no_op` with `applies: false` and `structured_adjustment: null`

---

## API Endpoints

### `GET /health`

Health check endpoint.

**Response**: `200 OK`
```json
{"status": "ok"}
```

### `POST /optimize-energy`

Main LLM-assisted energy optimization endpoint.

### Error Responses

| Status | Meaning |
|--------|---------|
| `400` | Malformed JSON or structurally invalid request |
| `422` | Semantically invalid (guardrail violation, infeasible optimization) |
| `500` | Controlled internal error |

---

## Running Tests

```bash
# Run the complete test suite (36 tests)
pytest tests/ -v
```

---

## Environment Variables & Secrets Policy

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | `""` | Optional (safe fallback activates if empty) |
| `LLM_MODEL` | Gemini generative model | `gemini-2.5-flash` | No |
| `PORT` | HTTP port | `8000` | No |

### Secret Handling Guidance
- **No secrets in repository**: `.env` is explicitly ignored by `.gitignore`. Only `.env.example` is tracked.
- **No secrets in responses or logs**: The API never logs or echoes API keys, prompts containing secrets, or sensitive system credentials.

---

## Supported Directives

| Directive | Effect | Structured Data |
|-----------|--------|-----------------|
| `solar_reduction` | Reduces usable solar by a factor | `{"hours": [int, ...], "factor": float}` |
| `minimum_battery_reserve` | Enforces minimum battery level | `{"hours": [int, ...], "minimum_energy_kwh": float}` |
| `no_charge_window` | Prevents battery charging | `{"hours": [int, ...]}` |
| `no_discharge_window` | Prevents battery discharging | `{"hours": [int, ...]}` |
| `max_grid_window` | Caps grid import | `{"hours": [int, ...], "max_grid_kwh": float}` |
| `no_op` | Irrelevant note (distractor) | `null` |

---

## Known Limitations & Design Assumptions

1. **Horizon**: Exactly 24 hourly periods (hours 0 through 23).
2. **Discrete Time**: Energy flows and battery states are scheduled in 1-hour time intervals.
3. **Neutrality**: End-of-day battery energy must return to starting energy level (`battery_energy_after_kwh[23] == initial_energy_kwh`).
4. **Feasibility**: Contradictory operator directives that make physics impossible (e.g. reserve exceeding battery capacity) are rejected by deterministic guardrails with HTTP 422.

---

## Dependencies & Credits

- **FastAPI** & **Uvicorn** – High-performance asynchronous HTTP REST API
- **PuLP** & **COIN-OR CBC Solver** – Industrial Mixed-Integer Linear Programming (MILP) solver
- **Google GenAI SDK (`google-genai`)** – Gemini 2.5 Flash for natural language directive interpretation
- **Pydantic v2** – Robust schema validation and contract serialization
- **Pytest** & **HTTPX** – End-to-end automated test suites

---

## Team

**BUP CSE Fest 2026 – GridWise Challenge**