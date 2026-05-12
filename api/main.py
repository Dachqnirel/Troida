from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from api.routers import bybit, tinkoff

app = FastAPI(title="Troida Data API", version="1.0.0")
app.include_router(bybit.router, prefix="/bybit")
app.include_router(tinkoff.router, prefix="/tinkoff")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "message": str(detail)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first_msg = errors[0]["msg"] if errors else "Validation failed"
    safe_errors = [
        {k: ({ck: str(cv) for ck, cv in v.items()} if k == "ctx" else v)
         for k, v in err.items()}
        for err in errors
    ]
    return JSONResponse(status_code=422, content={"error": "validation_error", "message": first_msg, "details": safe_errors})


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["System"])
def health() -> dict:
    return {"status": "ok"}
