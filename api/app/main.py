import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import CrossClientWriteError, UnscopedQueryError
from . import logfilter
from .routers import admin, auth, clients, flags, inbound, invoices, reference, reports, review, uploads, users

# Never log request bodies or invoice contents. Only method, path and status.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("audit.api")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_: FastAPI):
    from . import storage

    logfilter.install()
    startup_checks()
    try:
        storage.ensure_bucket()
    except Exception:  # storage may be unavailable in unit tests
        log.warning("object storage not reachable at startup")
    yield


def startup_checks() -> None:
    """Refuse to start without the AI key the configured provider needs (offline providers need none)."""
    s = get_settings()
    if s.ai_provider == "openai" and not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env, or set AI_PROVIDER=fake for an offline demo.")
    if s.ai_provider == "claude" and not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env, or set AI_PROVIDER=fake for an offline demo.")


app = FastAPI(lifespan=lifespan, title="Repair Invoice Audit API", version="0.1.0", docs_url="/docs" if get_settings().env == "local" else None)


@app.exception_handler(UnscopedQueryError)
@app.exception_handler(CrossClientWriteError)
async def _isolation_error(request: Request, exc: Exception):
    log.error("isolation guard tripped on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "This request touched data outside the selected client and was blocked."}, status_code=500)


@app.middleware("http")
async def keep_public_reports_private(request, call_next):
    """The public report link is a secret address: ask search engines not to index it and browsers not to send it on as a referrer."""
    response = await call_next(request)
    if request.url.path.startswith("/public/"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(users.router)
app.include_router(uploads.router)
app.include_router(invoices.router)
app.include_router(inbound.router)
app.include_router(flags.router)
app.include_router(reference.router)
app.include_router(review.router)
app.include_router(reports.router)
app.include_router(admin.router)
