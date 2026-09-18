from fastapi import FastAPI

app = FastAPI(
    title="GridWise Energy Optimization API",
    version="1.0.0"
)


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/optimize-energy")
def optimize_energy():
    return {
        "message": "Optimization endpoint is not implemented yet."
    }