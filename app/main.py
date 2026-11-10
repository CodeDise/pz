import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import worker
from .config import settings
from .db import Base, engine
from .errors import ApiError
from .routers import admin, api, checkout, dashboard, hooks, pages
from .services import telegram
from .templating import BASE_DIR, templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("paygate")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if settings.insecure_secret:
        log.warning("SECRET_KEY is not set. Using an insecure development key. Set SECRET_KEY before going live!")
    telegram.setup()
    stop = worker.start()
    yield
    stop.set()


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    version="1.0.0",
    description="Create payment orders and receive signed webhooks. Money goes straight to your own gateway account or wallet.",
    docs_url="/api/swagger",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

for r in (pages.router, api.router, checkout.router, hooks.router, dashboard.router, admin.router):
    app.include_router(r)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/"):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": f"{where}: {first.get('msg', 'invalid value')}".strip(": ")}},
            status_code=422,
        )
    return JSONResponse({"detail": "Invalid request"}, status_code=422)


@app.exception_handler(dashboard.LoginRequired)
async def login_required_handler(request: Request, exc: dashboard.LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": {"code": "not_found", "message": "Unknown endpoint"}}, status_code=404)
    return templates.TemplateResponse(request, "error.html", {"code": 404, "title": "Page not found", "text": "This link doesn't lead anywhere."}, status_code=404)


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html", {"code": 403, "title": "Not allowed", "text": getattr(exc, "detail", "") or "You can't do that."}, status_code=403
    )
