"""Razorpay Payment Links API (official). Money settles in the merchant's own Razorpay account."""
import re
import time

from ...utils import to_epoch
from .base import GatewayError, ensure_ok, http

BASE = "https://api.razorpay.com/v1"


def _auth(creds: dict) -> tuple[str, str]:
    return (creds["key_id"], creds["key_secret"])


def create(order, creds: dict, env: str, ctx: dict) -> dict:
    # Razorpay needs expire_by to be at least ~15 minutes in the future.
    expire_by = int(max(to_epoch(order.expires_at), time.time() + 16 * 60))
    body = {
        "amount": order.amount_units,
        "currency": "INR",
        "accept_partial": False,
        "expire_by": expire_by,
        "reference_id": order.id,
        "description": (order.description or f"Payment {order.id}")[:240],
        "callback_url": ctx["return_url"],
        "callback_method": "get",
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "notes": {"paygate_order": order.id},
    }
    customer = {}
    if order.customer_email:
        customer["email"] = order.customer_email
    if order.customer_phone and re.fullmatch(r"\+?\d{8,15}", order.customer_phone):
        customer["contact"] = order.customer_phone
    if customer:
        body["customer"] = customer

    data = ensure_ok(http("POST", f"{BASE}/payment_links", auth=_auth(creds), json=body))
    if not data.get("id") or not data.get("short_url"):
        raise GatewayError("Razorpay did not return a payment link")
    return {"ref": data["id"], "checkout_url": data["short_url"], "extra": {}}


def fetch_status(order, creds: dict, env: str) -> dict:
    data = ensure_ok(http("GET", f"{BASE}/payment_links/{order.gateway_ref}", auth=_auth(creds)))
    status = {"paid": "paid", "expired": "expired", "cancelled": "cancelled"}.get(data.get("status"), "pending")
    method = None
    payments = data.get("payments")
    if isinstance(payments, list) and payments and isinstance(payments[0], dict):
        method = payments[0].get("method")
    return {"status": status, "method": method}


def validate(creds: dict, env: str) -> str:
    ensure_ok(http("GET", f"{BASE}/payment_links", params={"count": 1}, auth=_auth(creds)))
    mode = "test" if creds["key_id"].startswith("rzp_test_") else "live"
    return f"Connected to Razorpay ({mode} keys)"
