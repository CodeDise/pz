"""Cashfree Payment Gateway Orders API (official). Checkout is opened with Cashfree's own JS SDK."""
import re
import uuid

from ...config import settings
from .base import GatewayError, ensure_ok, error_message, http

API_VERSION = "2023-08-01"


def _base(env: str) -> str:
    return "https://sandbox.cashfree.com/pg" if env == "sandbox" else "https://api.cashfree.com/pg"


def _headers(creds: dict) -> dict:
    return {
        "x-client-id": creds["client_id"],
        "x-client-secret": creds["client_secret"],
        "x-api-version": API_VERSION,
        "Content-Type": "application/json",
    }


def create(order, creds: dict, env: str, ctx: dict) -> dict:
    digits = re.sub(r"\D", "", order.customer_phone or "")[-10:]
    phone = digits if len(digits) == 10 else "9999999999"  # Cashfree requires a phone number
    body = {
        "order_id": order.id,
        "order_amount": float(order.amount_units) / 100,
        "order_currency": "INR",
        "customer_details": {
            "customer_id": "cust_" + order.id,
            "customer_phone": phone,
            **({"customer_email": order.customer_email} if order.customer_email else {}),
        },
        "order_meta": {"return_url": ctx["return_url"]},
        "order_note": (order.description or "")[:200],
    }
    if ctx.get("notify_url", "").startswith("https://"):
        body["order_meta"]["notify_url"] = ctx["notify_url"]
    data = ensure_ok(http("POST", f"{_base(env)}/orders", headers=_headers(creds), json=body))
    if not data.get("payment_session_id"):
        raise GatewayError("Cashfree did not return a payment session")
    return {
        "ref": order.id,
        "checkout_url": None,  # our checkout page opens Cashfree's JS checkout with this session id
        "extra": {"payment_session_id": data["payment_session_id"], "cf_order_id": data.get("cf_order_id")},
    }


def fetch_status(order, creds: dict, env: str) -> dict:
    data = ensure_ok(http("GET", f"{_base(env)}/orders/{order.gateway_ref}", headers=_headers(creds)))
    st = data.get("order_status")
    status = {
        "PAID": "paid",
        "EXPIRED": "expired",
        "TERMINATED": "cancelled",
        "TERMINATION_REQUESTED": "cancelled",
    }.get(st, "pending")
    method = None
    if status == "paid":
        try:
            pays = http("GET", f"{_base(env)}/orders/{order.gateway_ref}/payments", headers=_headers(creds)).json()
            for p in pays if isinstance(pays, list) else []:
                if p.get("payment_status") == "SUCCESS":
                    method = p.get("payment_group")
                    break
        except Exception:
            pass
    return {"status": status, "method": method}


def validate(creds: dict, env: str) -> str:
    # Look up an order that does not exist: valid keys answer 404, bad keys answer 401/403.
    resp = http("GET", f"{_base(env)}/orders/paygate_probe_{uuid.uuid4().hex[:10]}", headers=_headers(creds))
    if resp.status_code in (401, 403):
        raise GatewayError("Cashfree rejected these keys. Check the App ID, Secret and the Sandbox/Production choice.")
    if resp.status_code >= 500:
        raise GatewayError("Cashfree is not responding right now. Try again in a minute.")
    if resp.status_code not in (200, 404):
        raise GatewayError(error_message(resp))
    return f"Connected to Cashfree ({'sandbox' if env == 'sandbox' else 'production'})"
