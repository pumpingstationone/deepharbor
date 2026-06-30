import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dhs_logging import logger

###############################################################################
# Configuration
###############################################################################

# Our one and only fastapi app
app = FastAPI()


###############################################################################
# Global exception handlers
#
# Registered here, on the shared app object, so they apply to every endpoint
# regardless of import order (both main.py and v1.py do `from fastapiapp import
# app`). FastAPI registers its own HTTPException and RequestValidationError
# handlers as more-specific keys in the same handler dict, so Starlette's
# exception-class MRO walk resolves them before this broad Exception handler —
# the real 401/403/404/422 responses are unaffected. This relies on Starlette's
# current MRO-walk dispatch (verified live on dev), not a guaranteed public
# contract; re-verify these status codes if Starlette/FastAPI is upgraded.
###############################################################################


@app.exception_handler(json.JSONDecodeError)
async def json_decode_exception_handler(request: Request, exc: json.JSONDecodeError):
    """Return 400 (not 500) when a request body is empty or not valid JSON.

    The member-mutating POSTs read the body via `await request.json()`; an
    unparseable body raises JSONDecodeError, which otherwise crashes to a 500.
    JSONDecodeError subclasses ValueError, so Starlette's MRO match picks this
    handler over the broad Exception handler below for decode errors.
    """
    # INFO, not WARNING: a malformed body is routine client error, not an
    # operator-actionable condition, and the endpoint is publicly reachable.
    logger.info(f"Malformed request body: {exc}")
    return JSONResponse(status_code=400, content={"detail": "Malformed request body"})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Catch-all backstop: log the error and return a generic 500 body with no
    internal detail (defense-in-depth + consistent error shape + guaranteed
    logging via the project logger)."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
