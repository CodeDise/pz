"""PhonePe Payment Gateway, Standard Checkout (OAuth client credentials). Official API."""
import time

from ...utils import utcnow
from .base import GatewayError, ensure_ok, http

_TOKENS: dict[tuple[str, str], tuple[str, float]] = {}


def _urls(env: str) -> tuple[str, str]:
    if env == "sandbox":
        base = "https://api-preprod.phonepe.com/apis/pg-sandbox"
        return base + "/v1/oauth/token", base
    return "https://api.phonepe.com/apis/identity-manager/v1/oauth/token", "https://api.phonepe.com/apis/pg"


def _token(creds: dict, env: str) -> str:
    key = (creds["client_id"], env)
    cached = _TOKENS.get(key)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    token_url, _ = _urls(env)
    data = ensure_ok(
        http(
            "POST",
            token_url,
            data={
                "client_id": creds["client_id"],
                "client_version": creds.get("client_version") or "1",
                "client_secret": creds["client_secret"],
                "grant_type": "client_credentials",
            },
        )
    )
    token = data.get("access_token")
    if not token:
        raise GatewayError("PhonePe did not return an access token")
    expires = float(data.get("expires_at") or time.time() + 600)
    if expires > 1e11:  # milliseconds
        expires /= 1000
    _TOKENS[key] = (token, expires)
    return token


def _auth(creds: dict, env: str) -> dict:
    return {"Authorization": f"O-Bearer {_token(creds, env)}", "Content-Type": "application/json"}


def create(order, creds: dict, env: str, ctx: dict) -> dict:
    _, api = _urls(env)
    seconds = int((order.expires_at - utcnow()).total_seconds())
    body = {
        "merchantOrderId": order.id,
        "amount": order.amount_units,
        "expireAfter": max(300, min(3600, seconds)),
        "metaInfo": {"udf1": order.id},
        "paymentFlow": {
            "type": "PG_CHECKOUT",
            "message": (order.description or "Payment")[:100],
            "merchantUrls": {"redirectUrl": ctx["return_url"]},
        },
    }
    data = ensure_ok(http("POST", f"{api}/checkout/v2/pay", headers=_auth(creds, env), json=body))
    if not data.get("redirectUrl"):
        raise GatewayError("PhonePe did not return a checkout URL")
    return {"ref": order.id, "checkout_url": data["redirectUrl"], "extra": {"phonepe_order_id": data.get("orderId")}}


def fetch_status(order, creds: dict, env: str) -> dict:
    _, api = _urls(env)
    resp = http(
        "GET",
        f"{api}/checkout/v2/order/{order.gateway_ref}/status",
        params={"details": "false"},
        headers=_auth(creds, env),
    )
    if resp.status_code == 404:
        return {"status": "pending", "method": None}
    data = ensure_ok(resp)
    status = {"COMPLETED": "paid", "FAILED": "failed"}.get(data.get("state"), "pending")
    return {"status": status, "method": "phonepe"}


def validate(creds: dict, env: str) -> str:
    _TOKENS.pop((creds["client_id"], env), None)
    _token(creds, env)
    return f"Connected to PhonePe ({'sandbox' if env == 'sandbox' else 'production'})"
