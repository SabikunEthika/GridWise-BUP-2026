from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.llm_interpreter import interpret_operator_notes
from app.modules.guardrails import apply_guardrails, GuardrailError
from app.modules.validator import validate_final_plan, ValidationError
from app.models.request_models import OptimizeEnergyRequest
from app.models.response_models import OptimizeEnergyResponse
from app.optimizer import optimize_energy, OptimizationError


app = FastAPI(
    title="GridWise Energy Optimization API",
    version="1.0.0"
)


from fastapi.encoders import jsonable_encoder


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    """Map Pydantic/request-shape failures to the API's documented 400."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": "Malformed JSON or structurally invalid request",
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/optimize-energy",
    response_model=OptimizeEnergyResponse
)
def optimize_energy_endpoint(request: OptimizeEnergyRequest):

    try:
        try:
            parsed_directives = interpret_operator_notes(
                request.operator_notes,
                battery_capacity_kwh=request.battery.capacity_kwh
            )
        except TypeError:
            parsed_directives = interpret_operator_notes(
                request.operator_notes
            )

        interpretations = apply_guardrails(
            parsed_directives,
            request
        )

        plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh = optimize_energy(
            request,
            interpretations
        )

        validated_grid, validated_cost, validated_peak = validate_final_plan(
            request,
            interpretations,
            plan
        )

        return OptimizeEnergyResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=interpretations,
            hourly_plan=plan,
            total_grid_kwh=validated_grid,
            total_cost_bdt=validated_cost,
            peak_grid_kwh=validated_peak,
            plan_summary=(
                f"Generated a valid 24-hour energy schedule using "
                f"{validated_grid:.2f} kWh of grid electricity at a "
                f"total cost of {validated_cost:.2f} BDT."
            )
        )

    except GuardrailError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Directive validation failed: {str(e)}"
        )

    except OptimizationError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Optimization failed: {str(e)}"
        )

    except ValidationError:
        raise HTTPException(
            status_code=500,
            detail="Controlled internal validation error."
        )

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Controlled internal error."
        )
