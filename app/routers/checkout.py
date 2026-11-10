"""Hosted checkout page shown to the paying customer: /pay/{order_id}"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Merchant, Order
from ..ratelimit import public_limiter
from ..services import orders as svc
from ..templating import templates
from ..utils import to_epoch, utcnow

try:
    import segno
except ImportError:  # QR is optional
    segno = None

router = APIRouter(tags=["Checkout"], include_in_schema=False)

_last_refresh: dict[str, float] = {}


def qr_svg(text: str) -> str | None:
    if not segno or not text:
        return None
    return segno.make(text, error="m").svg_inline(scale=5, border=2, dark="#0e2a25", light="#ffffff")


def _order_or_404(db: Session, order_id: str) -> Order:
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Payment not found")
    return o


def _throttled_refresh(db: Session, o: Order) -> None:
    if o.status == "created" and time.time() - _last_refresh.get(o.id, 0) > 4:
        _last_refresh[o.id] = time.time()
        if len(_last_refresh) > 5000:
            _last_refresh.clear()
        svc.refresh_from_gateway(db, o)


@router.get("/pay/{order_id}")
def checkout(order_id: str, request: Request, db: Session = Depends(get_db)):
    o = _order_or_404(db, order_id)
    _throttled_refresh(db, o)
    merchant = db.get(Merchant, o.merchant_id)
    extra = json.loads(o.gateway_extra or "{}")
    real_address = o.currency == "USDT" and o.mode == "live"
    return templates.TemplateResponse(
        request,
        "checkout.html",
        {
            "o": o,
            "merchant": merchant,
            "extra": extra,
            "qr": qr_svg(o.crypto_address) if real_address else None,
            "expires_ms": int(to_epoch(o.expires_at) * 1000),
            "return_url": svc.merchant_return_url(o),
            "cashfree_mode": "sandbox" if o.gateway_provider == "cashfree" and _cf_sandbox(db, o) else "production",
        },
    )


def _cf_sandbox(db: Session, o: Order) -> bool:
    from sqlalchemy import select

    from ..models import GatewayCredential

    row = db.scalar(select(GatewayCredential).where(GatewayCredential.merchant_id == o.merchant_id, GatewayCredential.provider == "cashfree"))
    return bool(row and row.env == "sandbox")


@router.get("/pay/{order_id}/status")
def status(order_id: str, request: Request, db: Session = Depends(get_db)):
    if not public_limiter.allow("st:" + (request.client.host if request.client else "?")):
        return JSONResponse({"status": "rate_limited"}, status_code=429)
    o = _order_or_404(db, order_id)
    _throttled_refresh(db, o)
    if o.status == "created" and o.expires_at < utcnow():
        svc.expire_due(db)
        db.refresh(o)
    return {"status": o.status, "redirect": svc.merchant_return_url(o) if o.status == "paid" else None}


@router.get("/pay/{order_id}/return")
def gateway_return(order_id: str, db: Session = Depends(get_db)):
    o = _order_or_404(db, order_id)
    svc.refresh_from_gateway(db, o)
    return RedirectResponse(f"/pay/{o.id}", status_code=303)


@router.post("/pay/{order_id}/simulate")
def simulate(order_id: str, db: Session = Depends(get_db)):
    """Test mode only: lets you walk through the whole flow without moving real money."""
    o = _order_or_404(db, order_id)
    if o.mode != "test":
        raise HTTPException(403, "Only available for test-mode payments")
    if o.status == "created":
        svc.mark_paid(db, o, method="test_payment")
    return RedirectResponse(f"/pay/{o.id}", status_code=303)
