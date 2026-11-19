import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import CrossClientWriteError, UnscopedQueryError
from .routers import auth, clients, inbound, invoices, uploads, users

# Never log request bodies or invoice contents. Only method, path and status.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("audit.api")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_: FastAPI):
    from . import storage

    try:
        storage.ensure_bucket()
    except Exception:  # storage may be unavailable in unit tests
        log.warning("object storage not reachable at startup")
    yield


app = FastAPI(lifespan=lifespan, title="Repair Invoice Audit API", version="0.1.0", docs_url="/docs" if get_settings().env == "local" else None)


@app.exception_handler(UnscopedQueryError)
@app.exception_handler(CrossClientWriteError)
async def _isolation_error(request: Request, exc: Exception):
    log.error("isolation guard tripped on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "This request touched data outside the selected client and was blocked."}, status_code=500)


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(users.router)
app.include_router(uploads.router)
app.include_router(invoices.router)
app.include_router(inbound.router)
