from fastapi import APIRouter, Request
from sqlalchemy import text

from ..config import settings
from ..db import engine
from ..services.gateways.meta import PROVIDERS
from ..templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/")
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html", {"providers": PROVIDERS, "bot": settings.BOT_USERNAME})


@router.get("/docs")
def api_docs(request: Request):
    return templates.TemplateResponse(request, "docs.html", {"base": settings.BASE_URL})


@router.get("/healthz")
def healthz():
    with engine.connect() as c:
        c.execute(text("select 1"))
    return {"ok": True}
