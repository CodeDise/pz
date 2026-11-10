"""Public merchant API: /api/v1  (Authorization: Bearer sk_test_... or sk_live_...)"""
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..models import ApiKey, Merchant, Order
from ..ratelimit import api_limiter
from ..security import sha256_hex
from ..services import orders as svc
from ..utils import utcnow

router = APIRouter(prefix="/api/v1", tags=["Orders"])


class Auth:
    def __init__(self, merchant: Merchant, key: ApiKey):
        self.merchant, self.key = merchant, key


def authenticate(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Auth:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token.startswith("sk_"):
        raise ApiError(401, "unauthorized", "Send your API key as 'Authorization: Bearer sk_...'")
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256_hex(token), ApiKey.revoked.is_(False)))
    if not key:
        raise ApiError(401, "unauthorized", "Invalid or revoked API key")
    if not api_limiter.allow(f"key:{key.id}"):
        raise ApiError(429, "rate_limited", "Too many requests. Limit is 120 per minute per key.")
    if not key.last_used_at or (utcnow() - key.last_used_at).total_seconds() > 60:
        key.last_used_at = utcnow()
        db.commit()
    return Auth(db.get(Merchant, key.merchant_id), key)


class OrderIn(BaseModel):
    amount: Decimal = Field(..., description="Amount in major units, e.g. 499.00 (INR) or 10.5 (USDT)")
    currency: str = Field("INR", description="INR or USDT")
    description: str | None = Field(None, max_length=250)
    reference: str | None = Field(None, max_length=80, description="Your own order/invoice id")
    customer_email: str | None = None
    customer_phone: str | None = None
    return_url: str | None = Field(None, description="Customer is sent here after paying")
    metadata: dict[str, str] | None = None
    expires_in_minutes: int = Field(30, description="20 to 10080")
    gateway: str | None = Field(None, description="razorpay, cashfree or phonepe (INR only). Default: first connected")
    network: str | None = Field(None, description="TRC20 or BEP20 (USDT only). Default: first saved wallet")


@router.get("/ping", summary="Check your API key")
def ping(auth: Auth = Depends(authenticate)):
    m = auth.merchant
    return {"ok": True, "mode": auth.key.mode, "merchant": m.business_name or m.tg_name, "kyc_status": m.kyc_status}


@router.post("/orders", summary="Create an order", status_code=201)
def create_order(
    body: OrderIn,
    response: Response,
    idempotency_key: str | None = Header(None),
    auth: Auth = Depends(authenticate),
    db: Session = Depends(get_db),
):
    data = body.model_dump()
    data["idempotency_key"] = idempotency_key
    order, created = svc.create_order(db, auth.merchant, auth.key.mode, data)
    if not created:
        response.status_code = 200
    return svc.order_to_dict(order)


def _own(db: Session, auth: Auth, order_id: str) -> Order:
    o = db.get(Order, order_id)
    if not o or o.merchant_id != auth.merchant.id or o.mode != auth.key.mode:
        raise ApiError(404, "not_found", "No such order for this API key")
    return o


@router.get("/orders/{order_id}", summary="Retrieve an order")
def get_order(order_id: str, auth: Auth = Depends(authenticate), db: Session = Depends(get_db)):
    o = _own(db, auth, order_id)
    svc.refresh_from_gateway(db, o)
    return svc.order_to_dict(o)


@router.get("/orders", summary="List orders")
def list_orders(
    limit: int = 20,
    status: str | None = None,
    starting_after: str | None = None,
    auth: Auth = Depends(authenticate),
    db: Session = Depends(get_db),
):
    limit = max(1, min(100, limit))
    q = select(Order).where(Order.merchant_id == auth.merchant.id, Order.mode == auth.key.mode)
    if status:
        q = q.where(Order.status == status)
    if starting_after:
        anchor = _own(db, auth, starting_after)
        q = q.where(Order.created_at < anchor.created_at)
    rows = db.scalars(q.order_by(Order.created_at.desc()).limit(limit + 1)).all()
    return {"object": "list", "data": [svc.order_to_dict(o) for o in rows[:limit]], "has_more": len(rows) > limit}


@router.post("/orders/{order_id}/cancel", summary="Cancel an unpaid order")
def cancel(order_id: str, auth: Auth = Depends(authenticate), db: Session = Depends(get_db)):
    o = _own(db, auth, order_id)
    svc.cancel_order(db, o)
    return svc.order_to_dict(o)
