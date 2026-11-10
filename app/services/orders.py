"""Order lifecycle: create, mark paid, expire, cancel, and re-check with the gateway."""
import json
import logging
import random
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..errors import ApiError
from ..models import GatewayCredential, Merchant, Order, Wallet
from ..security import decrypt_json
from ..utils import CURRENCIES, DECIMALS, NETWORKS, iso, new_id, plain_amount, to_units, utcnow
from . import gateways, telegram, webhooks

log = logging.getLogger("paygate.orders")

LIMITS = {"INR": (Decimal("1"), Decimal("1000000")), "USDT": (Decimal("1"), Decimal("100000"))}
TEST_ADDRESS = "TEST-MODE-DO-NOT-SEND-REAL-FUNDS"


def checkout_url(order: Order) -> str:
    return f"{settings.BASE_URL}/pay/{order.id}"


def merchant_return_url(order: Order) -> str | None:
    if not order.return_url:
        return None
    p = urlparse(order.return_url)
    q = dict(parse_qsl(p.query))
    q.update({"order_id": order.id, "status": order.status})
    if order.reference:
        q["reference"] = order.reference
    return urlunparse(p._replace(query=urlencode(q)))


def order_to_dict(o: Order) -> dict:
    try:
        meta = json.loads(o.metadata_json or "{}")
    except ValueError:
        meta = {}
    d = {
        "id": o.id,
        "object": "order",
        "mode": o.mode,
        "status": o.status,
        "amount": plain_amount(o.amount_units, o.currency),
        "currency": o.currency,
        "description": o.description,
        "reference": o.reference,
        "customer_email": o.customer_email,
        "customer_phone": o.customer_phone,
        "metadata": meta,
        "checkout_url": checkout_url(o),
        "method": o.method,
        "created_at": iso(o.created_at),
        "expires_at": iso(o.expires_at),
        "paid_at": iso(o.paid_at),
    }
    if o.currency == "INR":
        d["gateway"] = None if o.gateway_provider in (None, "demo") else o.gateway_provider
    else:
        d["crypto"] = {
            "network": o.crypto_network,
            "address": o.crypto_address,
            "amount": plain_amount(o.crypto_amount_units or 0, "USDT"),
            "tx_hash": o.crypto_tx_hash,
        }
    return d


def _clean(v, n: int) -> str | None:
    return (str(v).strip()[:n] or None) if v is not None else None


def _require_live(merchant: Merchant) -> None:
    if settings.REQUIRE_KYC and merchant.kyc_status != "approved":
        raise ApiError(403, "kyc_required", "Complete KYC in Dashboard → Settings to accept live payments. Test mode works without it.")


def allocate_crypto_units(db: Session, network: str, address: str, base_units: int) -> int:
    """Adds a tiny unique amount (max 0.009999 USDT) so each open order can be matched on-chain."""
    cutoff = utcnow() - timedelta(hours=2)
    used = set(
        db.scalars(
            select(Order.crypto_amount_units).where(
                Order.mode == "live",
                Order.crypto_network == network,
                Order.crypto_address == address,
                Order.created_at > cutoff,
            )
        ).all()
    )
    for _ in range(300):
        cand = base_units + random.randint(1, 9999)
        if cand not in used:
            return cand
    raise ApiError(503, "busy", "Too many open crypto payments for this wallet. Try again in a moment.")


def _attach_gateway(db: Session, merchant: Merchant, order: Order, wanted: str | None) -> None:
    rows = db.scalars(
        select(GatewayCredential).where(GatewayCredential.merchant_id == merchant.id).order_by(GatewayCredential.created_at)
    ).all()
    wanted = (wanted or "").strip().lower() or None
    if wanted:
        row = next((r for r in rows if r.provider == wanted), None)
        if not row:
            raise ApiError(400, "gateway_not_connected", f"'{wanted}' is not connected. Add its API keys in Dashboard → Integrations.")
    else:
        if not rows:
            raise ApiError(400, "no_gateway", "No payment gateway connected. Add Razorpay, Cashfree or PhonePe keys in Dashboard → Integrations.")
        row = rows[0]
    if row.provider == "phonepe":
        order.expires_at = min(order.expires_at, utcnow() + timedelta(minutes=60))
    ctx = {
        "return_url": f"{settings.BASE_URL}/pay/{order.id}/return",
        "notify_url": f"{settings.BASE_URL}/webhooks/{row.provider}/{merchant.public_id}",
    }
    try:
        res = gateways.create_payment(row.provider, order, decrypt_json(row.data_enc), row.env, ctx)
    except gateways.GatewayError as e:
        raise ApiError(502, "gateway_error", f"{gateways.PROVIDERS[row.provider]['name']} said: {e}")
    order.gateway_provider = row.provider
    order.gateway_ref = res["ref"]
    order.gateway_checkout_url = res.get("checkout_url")
    order.gateway_extra = json.dumps(res.get("extra") or {})


def _attach_wallet(db: Session, merchant: Merchant, order: Order, wanted: str | None, base_units: int) -> None:
    wallets = db.scalars(select(Wallet).where(Wallet.merchant_id == merchant.id).order_by(Wallet.created_at)).all()
    wanted = (wanted or "").strip().upper() or None
    if wanted:
        w = next((x for x in wallets if x.network == wanted), None)
        if not w:
            raise ApiError(400, "wallet_not_connected", f"No {wanted} wallet saved. Add one in Dashboard → Integrations.")
    else:
        if not wallets:
            raise ApiError(400, "no_wallet", "No crypto wallet saved. Add your USDT address in Dashboard → Integrations.")
        w = wallets[0]
    order.crypto_network = w.network
    order.crypto_address = w.address
    order.crypto_amount_units = allocate_crypto_units(db, w.network, w.address, base_units)


def create_order(db: Session, merchant: Merchant, mode: str, data: dict) -> tuple[Order, bool]:
    """Returns (order, created). created=False means an idempotent replay of an earlier request."""
    idem = _clean(data.get("idempotency_key"), 80)
    if idem:
        existing = db.scalar(select(Order).where(Order.merchant_id == merchant.id, Order.idempotency_key == idem))
        if existing:
            return existing, False

    currency = str(data.get("currency") or "INR").upper()
    if currency not in CURRENCIES:
        raise ApiError(400, "invalid_currency", "currency must be INR or USDT")
    try:
        amount = Decimal(str(data.get("amount")))
    except (InvalidOperation, ValueError):
        raise ApiError(400, "invalid_amount", "amount must be a number, for example 499.00")
    if not amount.is_finite() or amount.as_tuple().exponent < -DECIMALS[currency]:
        raise ApiError(400, "invalid_amount", f"{currency} amounts can have at most {DECIMALS[currency]} decimal places")
    lo, hi = LIMITS[currency]
    if amount < lo or amount > hi:
        raise ApiError(400, "invalid_amount", f"amount must be between {lo} and {hi} {currency}")

    return_url = _clean(data.get("return_url"), 500)
    if return_url and urlparse(return_url).scheme not in ("http", "https"):
        raise ApiError(400, "invalid_return_url", "return_url must start with http:// or https://")

    meta = data.get("metadata") or {}
    if not isinstance(meta, dict) or len(meta) > 20:
        raise ApiError(400, "invalid_metadata", "metadata must be an object with at most 20 keys")
    meta = {str(k)[:40]: str(v)[:200] for k, v in meta.items()}

    email = _clean(data.get("customer_email"), 160)
    if email and "@" not in email:
        raise ApiError(400, "invalid_email", "customer_email is not a valid email address")
    phone = _clean(data.get("customer_phone"), 20)

    try:
        minutes = int(data.get("expires_in_minutes") or 30)
    except (TypeError, ValueError):
        minutes = 30
    minutes = max(20, min(10080, minutes))

    now = utcnow()
    base_units = to_units(amount, currency)
    order = Order(
        id=new_id("ord_"),
        merchant_id=merchant.id,
        mode=mode,
        amount_units=base_units,
        currency=currency,
        description=_clean(data.get("description"), 250),
        reference=_clean(data.get("reference"), 80),
        customer_email=email,
        customer_phone=phone,
        return_url=return_url,
        metadata_json=json.dumps(meta),
        idempotency_key=idem,
        status="created",
        created_at=now,
        expires_at=now + timedelta(minutes=minutes),
    )

    if mode == "test":
        order.gateway_provider = "demo"
        if currency == "USDT":
            network = (_clean(data.get("network"), 8) or "TRC20").upper()
            if network not in NETWORKS:
                raise ApiError(400, "invalid_network", "network must be TRC20 or BEP20")
            order.crypto_network = network
            order.crypto_address = TEST_ADDRESS
            order.crypto_amount_units = base_units + random.randint(1, 9999)
    else:
        _require_live(merchant)
        if currency == "INR":
            _attach_gateway(db, merchant, order, data.get("gateway"))
        else:
            _attach_wallet(db, merchant, order, data.get("network"), base_units)

    db.add(order)
    db.commit()
    return order, True


def enqueue_event(db: Session, order: Order, event: str) -> None:
    merchant = db.get(Merchant, order.merchant_id)
    webhooks.enqueue(db, merchant, event, {"order": order_to_dict(order)}, order.id, livemode=order.mode == "live")


def mark_paid(db: Session, order: Order, method: str | None = None, tx_hash: str | None = None) -> bool:
    """Idempotent. Returns True only the first time the order flips to paid."""
    if order.status == "paid" or order.status == "cancelled":
        return False
    order.status = "paid"
    order.paid_at = utcnow()
    if method:
        order.method = method
    if tx_hash:
        order.crypto_tx_hash = tx_hash
    db.flush()
    enqueue_event(db, order, "order.paid")
    db.commit()
    try:
        telegram.notify_paid(db.get(Merchant, order.merchant_id), order)
    except Exception:
        log.exception("telegram notification failed")
    return True


def _close(db: Session, order: Order, status: str) -> None:
    order.status = status
    db.flush()
    enqueue_event(db, order, f"order.{status}")
    db.commit()
    if status == "failed":
        try:
            telegram.notify_failed(db.get(Merchant, order.merchant_id), order)
        except Exception:
            log.exception("telegram notification failed")


def cancel_order(db: Session, order: Order) -> None:
    if order.status != "created":
        raise ApiError(409, "not_cancellable", f"Only unpaid orders can be cancelled (this one is {order.status})")
    _close(db, order, "cancelled")


def refresh_from_gateway(db: Session, order: Order) -> None:
    """Asks the merchant's gateway for the truth. This is how INR payments get confirmed."""
    if order.mode != "live" or order.status != "created" or order.gateway_provider in (None, "demo"):
        return
    row = db.scalar(
        select(GatewayCredential).where(
            GatewayCredential.merchant_id == order.merchant_id, GatewayCredential.provider == order.gateway_provider
        )
    )
    if not row:
        return
    try:
        res = gateways.fetch_status(row.provider, order, decrypt_json(row.data_enc), row.env)
    except gateways.GatewayError as e:
        log.warning("status check failed for %s (%s): %s", order.id, row.provider, e)
        return
    st = res["status"]
    if st == "paid":
        mark_paid(db, order, method=res.get("method") or row.provider)
    elif st in ("expired", "cancelled", "failed"):
        _close(db, order, st)


def expire_due(db: Session) -> None:
    rows = db.scalars(select(Order).where(Order.status == "created", Order.expires_at < utcnow()).limit(200)).all()
    for o in rows:
        if o.mode == "live" and o.gateway_provider not in (None, "demo"):
            refresh_from_gateway(db, o)  # it may have been paid right before expiry
            if o.status != "created":
                continue
        _close(db, o, "expired")


def poll_gateway_orders(db: Session) -> None:
    rows = db.scalars(
        select(Order)
        .where(
            Order.mode == "live",
            Order.status == "created",
            Order.gateway_provider.in_(list(gateways.PROVIDERS)),
            Order.created_at > utcnow() - timedelta(hours=24),
        )
        .order_by(Order.created_at)
        .limit(50)
    ).all()
    for o in rows:
        refresh_from_gateway(db, o)
