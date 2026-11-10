"""Tiny owner-only panel at /admin to review merchants. Protected by ADMIN_TOKEN."""
import hmac
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Merchant, Order
from ..ratelimit import RateLimiter
from ..security import csrf_token, make_token, read_token
from ..services import telegram
from ..templating import templates

COOKIE = "pg_admin"
router = APIRouter(include_in_schema=False)
_login_limiter = RateLimiter(limit=8, window=300)


def _enabled() -> None:
    if not settings.ADMIN_TOKEN:
        raise HTTPException(404)


def _is_admin(request: Request) -> bool:
    return read_token(request.cookies.get(COOKIE), "admin") == "1"


@router.get("/admin")
def admin_home(request: Request, db: Session = Depends(get_db)):
    _enabled()
    if not _is_admin(request):
        return templates.TemplateResponse(request, "admin_login.html", {"err": request.query_params.get("err")})
    merchants = db.scalars(select(Merchant).order_by((Merchant.kyc_status == "pending").desc(), Merchant.created_at.desc()).limit(200)).all()
    totals = {
        "merchants": db.scalar(select(func.count()).select_from(Merchant)),
        "orders": db.scalar(select(func.count()).select_from(Order)),
        "paid": db.scalar(select(func.count()).select_from(Order).where(Order.status == "paid", Order.mode == "live")),
    }
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"merchants": merchants, "totals": totals, "csrf": csrf_token(request.cookies.get(COOKIE, "")), "ok": request.query_params.get("ok")},
    )


@router.post("/admin/login")
def admin_login(request: Request, token: str = Form("")):
    _enabled()
    ip = request.client.host if request.client else "?"
    if not _login_limiter.allow(ip):
        return RedirectResponse("/admin?err=Too+many+attempts.+Wait+a+few+minutes.", status_code=303)
    if not hmac.compare_digest(token.strip(), settings.ADMIN_TOKEN):
        return RedirectResponse("/admin?err=Wrong+token", status_code=303)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(COOKIE, make_token("admin", "1", 8 * 3600), max_age=8 * 3600, httponly=True, samesite="lax", secure=settings.https)
    return resp


@router.post("/admin/merchants/{merchant_id}/{action}")
def admin_action(merchant_id: int, action: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    _enabled()
    if not _is_admin(request) or not hmac.compare_digest(csrf, csrf_token(request.cookies.get(COOKIE, ""))):
        raise HTTPException(403)
    status = {"approve": "approved", "reject": "rejected", "reset": "pending"}.get(action)
    m = db.get(Merchant, merchant_id)
    if not status or not m:
        raise HTTPException(404)
    m.kyc_status = status
    db.commit()
    if status in ("approved", "rejected"):
        telegram.notify_kyc(m, status)
    return RedirectResponse("/admin?ok=" + quote(f"{m.business_name or m.tg_name or 'Merchant'} is now {status}."), status_code=303)
