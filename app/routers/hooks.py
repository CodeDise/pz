"""Inbound webhooks: Telegram updates and optional instant-confirmation pings from payment gateways."""
import hmac
import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..db import get_db
from ..models import Merchant, Order
from ..ratelimit import public_limiter
from ..services import orders as svc
from ..services import telegram

log = logging.getLogger("paygate.hooks")
router = APIRouter(include_in_schema=False)


@router.post("/telegram/webhook/{secret}")
def telegram_webhook(secret: str, update: dict = Body(...)):
    if not hmac.compare_digest(secret, settings.telegram_webhook_secret):
        raise HTTPException(404)
    try:
        telegram.handle_update(update)
    except Exception:
        log.exception("telegram update failed")
    return {"ok": True}


def _extract_ref(provider: str, payload: dict) -> str | None:
    try:
        if provider == "razorpay":
            return payload["payload"]["payment_link"]["entity"]["reference_id"]
        if provider == "cashfree":
            return payload["data"]["order"]["order_id"]
        if provider == "phonepe":
            p = payload.get("payload") or payload
            return p.get("merchantOrderId") or p.get("originalMerchantOrderId")
    except (KeyError, TypeError, AttributeError):
        return None
    return None


def _handle(db: Session, provider: str, public_id: str, raw: bytes) -> None:
    try:
        ref = _extract_ref(provider, json.loads(raw or b"{}"))
    except ValueError:
        return
    if not ref:
        return
    merchant = db.scalar(select(Merchant).where(Merchant.public_id == public_id))
    order = db.get(Order, ref) if merchant else None
    if order and order.merchant_id == merchant.id and order.gateway_provider == provider:
        # The webhook is only a hint. We never trust its content: the order is re-checked with the gateway's own API.
        svc.refresh_from_gateway(db, order)


@router.post("/webhooks/{provider}/{public_id}")
async def gateway_hint(provider: str, public_id: str, request: Request, db: Session = Depends(get_db)):
    if provider in ("razorpay", "cashfree", "phonepe") and public_limiter.allow(f"wh:{public_id}"):
        raw = await request.body()
        await run_in_threadpool(_handle, db, provider, public_id, raw)
    return {"ok": True}
