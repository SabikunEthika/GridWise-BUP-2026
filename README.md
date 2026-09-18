# GridWise – BUP Smart Campus Energy Optimization API

## 1. Project Overview

GridWise is a REST API for intelligent 24-hour campus energy scheduling. It accepts hourly demand, solar generation, electricity tariffs, battery specifications, and one to three natural-language operator notes.

The service interprets operator notes into supported energy directives, solves a cost-minimization Mixed-Integer Linear Program (MILP), and independently validates the resulting schedule before returning it.

The project was developed for the BUP CSE Fest 2026 GridWise Challenge by team Kronos.

Source repository: https://github.com/SabikunEthika/GridWise-BUP-2026

## 2. Architecture / Solution Flow

~~~text
Client request
     |
     v
FastAPI request-schema validation
     |
     v
LLM interpreter or deterministic fallback
     |
     v
Directive guardrails and sanitization
     |
     v
PuLP/CBC MILP optimizer
     |
     v
Independent schedule validator
     |
     v
Validated 24-hour response
~~~

The optimizer enforces demand balance, solar availability, battery capacity, charge/discharge limits, directive constraints, and end-of-day battery neutrality.

## 3. Technology Stack

- Python 3.11+
- FastAPI and Uvicorn
- Pydantic v2
- Google Gemini through google-genai
- PuLP with the COIN-OR CBC solver
- Pytest and HTTPX
- Docker and Docker Compose

## 4. Setup & Installation

Clone the repository and enter the project directory:

~~~bash
git clone https://github.com/SabikunEthika/GridWise-BUP-2026.git
cd GridWise-BUP-2026
~~~

Create and activate a virtual environment.

Windows PowerShell:

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
~~~

Git Bash:

~~~bash
python -m venv .venv
source .venv/Scripts/activate
~~~

Install dependencies:

~~~bash
pip install -r requirements.txt
~~~

## 5. Environment Variables

Copy the environment template:

~~~bash
cp .env.example .env
~~~

| Variable | Description | Default | Required |
|---|---|---:|---|
| LLM_PROVIDER | LLM provider | gemini | No |
| GEMINI_API_KEY | Google Gemini API key | empty | Optional when fallback is available |
| LLM_MODEL | Gemini model name | gemini-3.5-flash-lite | No |
| PORT | HTTP server port | 8000 locally | No |

Never commit .env or API keys to the repository.

## 6. LLM Provider & Model

The configured LLM provider is Google Gemini. The deployed service uses gemini-3.5-flash-lite; the model name can be changed with LLM_MODEL. Gemini supports structured outputs for this model, which is required for directive interpretation.

If Gemini is unavailable and the checked-out version includes the fallback interpreter, the service uses deterministic rule-based interpretation instead.

## 7. LLM Role in Directive Interpretation

The LLM interprets natural-language operator notes and maps each note to exactly one supported directive:

- solar_reduction
- minimum_battery_reserve
- no_charge_window
- no_discharge_window
- max_grid_window
- no_op

The LLM does not directly create the energy schedule. It only produces structured directive data. Guardrails validate that data before it reaches the optimizer.

## 8. Guardrails & Validation

Guardrails validate directive types, hours, numeric values, supported fields, note ordering, and battery-related limits. The final-plan validator independently checks:

- Exactly 24 ordered hours
- Non-negative and finite energy values
- Solar usage within effective solar availability
- Battery capacity and minimum reserve requirements
- Charge/discharge rate limits
- No-charge and no-discharge windows
- Maximum grid-import windows
- Hourly energy balance
- End-of-day battery neutrality

The API uses this error contract:

| Status | Meaning |
|---:|---|
| 200 | Successful health or optimization response |
| 400 | Malformed JSON or structurally invalid request |
| 422 | Semantically invalid request or infeasible optimization |
| 500 | Controlled internal validation or server error |

## 9. Optimization Approach / Solver

The optimizer uses PuLP to formulate a 24-hour MILP and CBC to solve it. The model minimizes total grid electricity cost while enforcing:

- Grid, solar, charge, and discharge energy balance
- Solar availability limits
- Battery state transitions
- Battery capacity and reserve limits
- Binary charge/discharge mode selection
- Operator directive constraints
- Final battery energy equal to initial battery energy

## 10. API Endpoints

### GET /health

Returns:

~~~json
{"status": "ok"}
~~~

### POST /optimize-energy

Accepts an energy scenario and returns a validated schedule. Interactive documentation is available at /docs when the server is running.

## 11. API Request & Response Examples

The repository includes a complete valid request at data/sample_01_request.json.

~~~bash
curl -X POST http://127.0.0.1:8000/optimize-energy \
  -H "Content-Type: application/json" \
  --data-binary @data/sample_01_request.json
~~~

Successful response fields include:

~~~json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [],
  "hourly_plan": [],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "Generated a valid 24-hour energy schedule..."
}
~~~

The actual hourly_plan contains 24 entries. Equivalent optimal schedules may differ in their hourly actions while remaining mathematically valid.

## 12. How to Run Locally

Start the development server:

~~~bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
~~~

Open these URLs:

- Health check: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

## 13. How to Test

Run the complete test suite:

~~~bash
pytest tests/ -v
~~~

Run the official public sample tests:

~~~bash
pytest tests/test_official_samples.py -v
~~~

The public benchmark data is stored in data/public_sample_cases.json.

## 14. Docker Setup & Usage

Build and start the service with Docker Compose:

~~~bash
docker compose up --build
~~~

Or build and run the image directly:

~~~bash
docker build -t gridwise-api:latest .
docker run --rm -p 8000:10000 --env-file .env gridwise-api:latest
~~~

Verify the container:

~~~bash
curl http://127.0.0.1:8000/health
~~~

## 15. Public Deployment

The application can be deployed as a Docker web service on Render or another container-hosting platform.

Required deployment settings:

- Runtime: Docker
- Bind host: 0.0.0.0
- Health check path: /health
- Environment variables: GEMINI_API_KEY, LLM_MODEL, and PORT

After deployment, the public URLs will be:

~~~text
https://gridwise-bup-2026-i1n0.onrender.com/health
https://gridwise-bup-2026-i1n0.onrender.com/docs
~~~

Submission deployment URL:

~~~text
https://gridwise-bup-2026-i1n0.onrender.com/docs
~~~

## 16. Sample Test Cases / Results

The official sample pack contains ten public cases, SAMPLE-01 through SAMPLE-10, in data/public_sample_cases.json.

For SAMPLE-01, the expected directive interpretation includes:

~~~json
{
  "directive_type": "solar_reduction",
  "hours": [12, 13],
  "factor": 0.25
}
~~~

The unrelated second note should be classified as no_op. Reference metrics are:

~~~text
total_grid_kwh: 2692.5
total_cost_bdt: 38365.0
peak_grid_kwh: 175.0
~~~

The returned plan is valid when it satisfies all physical, directive, and accounting constraints. It does not need to match the reference action sequence byte-for-byte.

## 17. Dependencies

Runtime and testing dependencies are listed in requirements.txt:

- fastapi
- uvicorn
- pydantic
- python-dotenv
- google-genai
- pulp
- pytest
- httpx

The Docker image also installs the COIN-OR CBC system solver.

## 18. Limitations

- The planning horizon is exactly 24 one-hour periods.
- Hours must be supplied in ascending order from 0 to 23.
- Grid export is not modeled; unused solar is curtailed.
- Battery energy must return to its initial value at hour 23.
- Contradictory or physically infeasible directives are rejected.
- Gemini interpretation quality depends on the configured model and API availability; the deterministic fallback is used when supported by the current implementation.

## 19. Team / Contributors

### Team Kronos

1. MD. Mushfiqur Rahman
2. Sabikun Alam
3. Abdullah Al Noman
4. Mahedi Hasan Oni

BUP CSE Fest 2026 – GridWise Challenge
