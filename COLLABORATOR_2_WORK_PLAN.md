# Collaborator 2: Optimization Engine, Validation, API & Deployment

**Track**: Track B - Mathematical Optimizer, Battery Accounting, API Compliance & Deployment  
**Target Branch**: `feature/optimizer-deployment` (to be merged into `main`)  
**Primary Files Owned**:
- `app/optimizer.py`
- `app/modules/validator.py`
- `app/main.py`
- `Dockerfile` & `docker-compose.yml` (New)
- `tests/test_e2e_scenarios.py` (New)

---

## 1. Executive Summary & Context

In the GridWise Challenge, the optimizer must compute a mathematically valid, 24-hour cost-minimized energy schedule that respects campus demand, solar availability, battery physics, tariff pricing, and any applicable operator directives.

Your objective as **Collaborator 2** is to:
1. Fix a critical bug in `app/modules/validator.py` where directive reserve limits were ignored during hourly validation.
2. Ensure mathematical correctness and numerical stability in `app/optimizer.py` using PuLP (MILP).
3. Align FastAPI error handling in `app/main.py` to match the exact HTTP status codes mandated by Section 06 of the Problem Statement (`400` for structural/malformed requests, `422` for semantic errors, `500` for controlled internal errors).
4. Build a comprehensive End-to-End Test Suite (`tests/test_e2e_scenarios.py`) testing all 6 directive variations and checking mathematical consistency.
5. Create a production-ready `Dockerfile` and deployment configuration for hosting the public HTTP API.

---

## 2. Identified Bugs & Required Fixes

### 2.1 Critical Bug in `app/modules/validator.py`: Missing Reserve Check
- In `app/modules/validator.py`, lines 49–54 populate `reserve_requirements[hour] = max(reserve_requirements[hour], adjustment.minimum_energy_kwh)` when `minimum_battery_reserve` directives are present.
- **However, in the hourly validation loop (line 126)**:
  ```python
  # BUG: Only checks base minimum, completely ignores reserve_requirements[h]!
  if energy_after < battery.minimum_energy_kwh - 0.01:
      raise ValidationError(f"Battery below minimum at hour {h}")
  ```
- **The Fix**: It MUST validate against `reserve_requirements[h]`:
  ```python
  if energy_after < reserve_requirements[h] - 0.01:
      raise ValidationError(
          f"Battery energy {energy_after:.2f} kWh is below required reserve "
          f"{reserve_requirements[h]:.2f} kWh at hour {h}"
      )
  ```

### 2.2 Numerical Tolerance & False-Positive Bug in `validator.py`
- Lines 149–153 and 167–171 raise `ValidationError` if `battery_kwh <= 0.01` for `"charge"` or `"discharge"`.
- If the solver outputs a microscopic charge (e.g. `0.0002` kWh due to floating-point solver precision), `optimizer.py` labels the action as `"charge"`, but `validator.py` rejects it!
- **The Fix**:
  - In `optimizer.py`: Filter out solver noise by zeroing actions where magnitude $< 10^{-4}$ and marking them as `"idle"`.
  - In `validator.py`: Only check that `battery_action == "idle"` has zero movement. If an action is `"charge"` or `"discharge"`, ensure `battery_kwh > 0`.

### 2.3 HTTP Status Code Contract Discrepancy (Section 06.1)
The problem statement defines exact HTTP response codes:
- **`200`**: Successful health or optimization response.
- **`400`**: Malformed JSON or structurally invalid request (e.g., missing fields, bad types, wrong array length).
  - *Note*: FastAPI returns `422` by default for Pydantic validation errors! You must register an exception handler for `RequestValidationError` that translates it to HTTP `400`.
- **`422`**: Semantically invalid but well-formed request (e.g., `GuardrailError`, `OptimizationError` where physical limits conflict).
- **`500`**: Controlled internal error. Do NOT expose secrets or raw stack traces.

---

## 3. Mathematical Optimization Rules (Section 09)

The solver must enforce the following equations for each hour $h \in \{0 \dots 23\}$:

1. **Solar Usage**:
   $$0 \le \text{solar\_used}[h] \le \text{effective\_solar}[h]$$
   Where $\text{effective\_solar}[h] = \text{solar\_kwh}[h] \times \text{solar\_factors}[h]$.
   Unused solar is curtailed. No grid export.

2. **Energy Balance**:
   $$\text{grid}[h] + \text{solar\_used}[h] + \text{discharge}[h] = \text{demand}[h] + \text{charge}[h]$$

3. **Battery Capacity & Hourly Limits**:
   $$\text{charge}[h] \le \text{max\_charge} \times M[h]$$
   $$\text{discharge}[h] \le \text{max\_discharge} \times (1 - M[h])$$
   $$M[h] \in \{0, 1\} \quad (\text{binary variable preventing simultaneous charge/discharge})$$

4. **Battery Energy Dynamics**:
   $$\text{battery\_energy}[0] = \text{initial\_energy} + \text{charge}[0] - \text{discharge}[0]$$
   $$\text{battery\_energy}[h] = \text{battery\_energy}[h-1] + \text{charge}[h] - \text{discharge}[h] \quad (\forall h \ge 1)$$
   $$\text{reserve\_requirements}[h] \le \text{battery\_energy}[h] \le \text{capacity}$$

5. **Directives Constraints**:
   - `no_charge_window`: $\text{charge}[h] = 0$
   - `no_discharge_window`: $\text{discharge}[h] = 0$
   - `max_grid_window`: $\text{grid}[h] \le \text{max\_grid\_kwh}$

6. **End-of-Day Neutrality**:
   $$\text{battery\_energy}[23] = \text{initial\_energy}$$

7. **Objective Function**:
   $$\min \sum_{h=0}^{23} \text{grid}[h] \times \text{tariff\_bdt\_per\_kwh}[h]$$

---

## 4. Step-by-Step Implementation Instructions

### Step 4.1: Patch `app/modules/validator.py`
Update `app/modules/validator.py` to fix the reserve check and align tolerances:
```python
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
        raise ValidationError("Plan hours must be exactly 0 through 23 in order")

    battery = request.battery
    solar_factors = [1.0] * 24
    reserve_requirements = [battery.minimum_energy_kwh] * 24
    no_charge = [False] * 24
    no_discharge = [False] * 24
    grid_caps = [None] * 24

    # Apply directives
    for interp in interpretations:
        if not interp.applies:
            continue
        adj = interp.structured_adjustment
        if adj is None:
            raise ValidationError(f"Directive {interp.note_index} marked applies=True but structured_adjustment is None")

        if interp.directive_type == "solar_reduction":
            for h in adj.hours:
                solar_factors[h] *= adj.factor
        elif interp.directive_type == "minimum_battery_reserve":
            for h in adj.hours:
                reserve_requirements[h] = max(reserve_requirements[h], adj.minimum_energy_kwh)
        elif interp.directive_type == "no_charge_window":
            for h in adj.hours:
                no_charge[h] = True
        elif interp.directive_type == "no_discharge_window":
            for h in adj.hours:
                no_discharge[h] = True
        elif interp.directive_type == "max_grid_window":
            for h in adj.hours:
                grid_caps[h] = adj.max_grid_kwh if grid_caps[h] is None else min(grid_caps[h], adj.max_grid_kwh)

    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0
    prev_energy = battery.initial_energy_kwh

    for h in range(24):
        entry = plan[h]
        hour_in = request.hours[h]

        grid = entry.grid_kwh
        solar_used = entry.solar_used_kwh
        action = entry.battery_action
        bat_kwh = entry.battery_kwh
        energy_after = entry.battery_energy_after_kwh

        # 1. Finite and non-negative
        for val, name in [(grid, "grid_kwh"), (solar_used, "solar_used_kwh"), (bat_kwh, "battery_kwh"), (energy_after, "battery_energy_after_kwh")]:
            if not math.isfinite(val) or val < -1e-4:
                raise ValidationError(f"Invalid non-finite or negative {name} at hour {h}: {val}")

        # 2. Solar limit
        effective_solar = hour_in.solar_kwh * solar_factors[h]
        if solar_used > effective_solar + 0.01:
            raise ValidationError(f"Solar used ({solar_used:.2f}) exceeds effective solar ({effective_solar:.2f}) at hour {h}")

        # 3. Battery bounds (CRITICAL FIX: checks directive reserve_requirements!)
        if energy_after < reserve_requirements[h] - 0.01:
            raise ValidationError(f"Battery energy ({energy_after:.2f}) below required reserve ({reserve_requirements[h]:.2f}) at hour {h}")
        if energy_after > battery.capacity_kwh + 0.01:
            raise ValidationError(f"Battery energy ({energy_after:.2f}) exceeds capacity ({battery.capacity_kwh:.2f}) at hour {h}")

        # 4. Battery action semantics
        if action == "charge":
            if no_charge[h]:
                raise ValidationError(f"Charging forbidden at hour {h}")
            if bat_kwh > battery.max_charge_kwh_per_hour + 0.01:
                raise ValidationError(f"Charge exceeds rate limit at hour {h}")
            expected_energy = prev_energy + bat_kwh
            b_charge, b_discharge = bat_kwh, 0.0
        elif action == "discharge":
            if no_discharge[h]:
                raise ValidationError(f"Discharging forbidden at hour {h}")
            if bat_kwh > battery.max_discharge_kwh_per_hour + 0.01:
                raise ValidationError(f"Discharge exceeds rate limit at hour {h}")
            expected_energy = prev_energy - bat_kwh
            b_charge, b_discharge = 0.0, bat_kwh
        elif action == "idle":
            if bat_kwh > 0.01:
                raise ValidationError(f"Idle action must have zero battery_kwh at hour {h}")
            expected_energy = prev_energy
            b_charge, b_discharge = 0.0, 0.0
        else:
            raise ValidationError(f"Unknown battery action '{action}' at hour {h}")

        # 5. Battery transition check
        if abs(energy_after - expected_energy) > 0.01:
            raise ValidationError(f"Battery energy state mismatch at hour {h}: after={energy_after:.2f}, expected={expected_energy:.2f}")

        # 6. Grid cap check
        if grid_caps[h] is not None and grid > grid_caps[h] + 0.01:
            raise ValidationError(f"Grid import ({grid:.2f}) exceeds cap ({grid_caps[h]:.2f}) at hour {h}")

        # 7. Energy balance check
        supply = grid + solar_used + b_discharge
        demand = hour_in.demand_kwh + b_charge
        if abs(supply - demand) > 0.01:
            raise ValidationError(f"Energy balance mismatch at hour {h}: supply={supply:.2f}, demand={demand:.2f}")

        total_grid_kwh += grid
        total_cost_bdt += grid * hour_in.tariff_bdt_per_kwh
        peak_grid_kwh = max(peak_grid_kwh, grid)
        prev_energy = energy_after

    # 8. End-of-day neutrality check
    if abs(prev_energy - battery.initial_energy_kwh) > 0.01:
        raise ValidationError(f"Final battery energy ({prev_energy:.2f}) must equal initial ({battery.initial_energy_kwh:.2f})")

    return total_grid_kwh, total_cost_bdt, peak_grid_kwh
```

### Step 4.2: Harden `app/optimizer.py`
In `app/optimizer.py`:
1. Clean small values below $10^{-4}$ to avoid floating-point artifacts.
2. Configure solver parameters with `timeLimit=10` to avoid timeouts.
3. Cleanly format plan entries:
```python
        # Precision rounding & action assignment
        if charge_val > 1e-4:
            action = "charge"
            bat_val = round(charge_val, 4)
        elif discharge_val > 1e-4:
            action = "discharge"
            bat_val = round(discharge_val, 4)
        else:
            action = "idle"
            bat_val = 0.0

        plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(grid_val, 4),
                solar_used_kwh=round(solar_val, 4),
                battery_action=action,
                battery_kwh=bat_val,
                battery_energy_after_kwh=round(energy_val, 4)
            )
        )
```

### Step 4.3: Update `app/main.py` for Strict HTTP Status Codes
Update `app/main.py` with custom exception handlers:
```python
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.llm_interpreter import interpret_operator_notes
from app.modules.guardrails import apply_guardrails, GuardrailError
from app.modules.validator import validate_final_plan, ValidationError
from app.models.request_models import OptimizeEnergyRequest
from app.models.response_models import OptimizeEnergyResponse
from app.optimizer import optimize_energy, OptimizationError

app = FastAPI(title="GridWise Energy Optimization API", version="1.0.0")


# SECTION 06.1: HTTP 400 for malformed JSON or structurally invalid requests
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed JSON or structurally invalid request", "errors": exc.errors()}
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy_endpoint(request: OptimizeEnergyRequest):
    try:
        parsed_directives = interpret_operator_notes(request.operator_notes)
        interpretations = apply_guardrails(parsed_directives, request)
        plan, total_grid, total_cost, peak_grid = optimize_energy(request, interpretations)
        val_grid, val_cost, val_peak = validate_final_plan(request, interpretations, plan)

        return OptimizeEnergyResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=interpretations,
            hourly_plan=plan,
            total_grid_kwh=val_grid,
            total_cost_bdt=val_cost,
            peak_grid_kwh=val_peak,
            plan_summary=(
                f"Generated valid 24-hour energy schedule using {val_grid:.2f} kWh "
                f"grid electricity at total cost of {val_cost:.2f} BDT (peak {val_peak:.2f} kWh)."
            )
        )
    except GuardrailError as e:
        raise HTTPException(status_code=422, detail=f"Directive guardrail error: {str(e)}")
    except OptimizationError as e:
        raise HTTPException(status_code=422, detail=f"Optimization error: {str(e)}")
    except ValidationError as e:
        raise HTTPException(status_code=500, detail="Controlled internal validation error.")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Controlled internal error.")
```

### Step 4.4: Create `Dockerfile` & `docker-compose.yml`
Create a clean, lightweight `Dockerfile`:
```dockerfile
FROM python:3.11-slim

# Install CBC solver and basic build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    coinor-cbc \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

And `docker-compose.yml`:
```yaml
version: '3.8'

services:
  gridwise-api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
```

---

## 5. End-to-End Test Suite (`tests/test_e2e_scenarios.py`)

Create `tests/test_e2e_scenarios.py` to simulate the official Judge Harness:
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_structurally_invalid_request_returns_400():
    # Invalid request: empty object
    response = client.post("/optimize-energy", json={})
    assert response.status_code == 400


def test_full_scenario_with_directives():
    payload = {
        "scenario_id": "GRID-101",
        "operator_notes": [
            "Solar output will drop to about 20% from 1 PM to 3 PM.",
            "Do not charge the battery between 2 PM and 4 PM.",
            "The cafeteria menu changes tomorrow."
        ],
        "hours": [
            {
                "hour": h,
                "demand_kwh": 100.0 if (8 <= h <= 18) else 40.0,
                "solar_kwh": 80.0 if (10 <= h <= 16) else 0.0,
                "tariff_bdt_per_kwh": 12.0 if (17 <= h <= 21) else 6.0
            }
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 300.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 30.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0
        }
    }

    response = client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["scenario_id"] == "GRID-101"
    assert len(data["hourly_plan"]) == 24
    assert len(data["directive_interpretation"]) == 3
    
    # Verify directive 0 is solar_reduction
    assert data["directive_interpretation"][0]["directive_type"] == "solar_reduction"
    assert data["directive_interpretation"][0]["applies"] is True

    # Verify directive 2 is no_op
    assert data["directive_interpretation"][2]["directive_type"] == "no_op"
    assert data["directive_interpretation"][2]["applies"] is False

    # Check metrics
    assert data["total_grid_kwh"] >= 0
    assert data["total_cost_bdt"] >= 0
    assert data["peak_grid_kwh"] >= 0
```

---

## 6. Definition of Done for Collaborator 2

- [ ] `validator.py` bug fixed to enforce `reserve_requirements[h]`.
- [ ] Tiny floating-point actions in `optimizer.py` cleaned up.
- [ ] Custom exception handlers in `app/main.py` return `400` for structural/malformed requests, `422` for semantic errors, and `500` for internal errors without leaking stack traces.
- [ ] `tests/test_e2e_scenarios.py` passes all test cases.
- [ ] `Dockerfile` builds cleanly and starts the FastAPI server.
- [ ] Ready to merge with Collaborator 1!
