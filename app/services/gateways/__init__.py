from . import cashfree, phonepe, razorpay
from .base import GatewayError
from .meta import CRYPTO_LINKS, PROVIDERS

_MODULES = {"razorpay": razorpay, "cashfree": cashfree, "phonepe": phonepe}

__all__ = ["GatewayError", "PROVIDERS", "CRYPTO_LINKS", "create_payment", "fetch_status", "validate"]


def create_payment(provider: str, order, creds: dict, env: str, ctx: dict) -> dict:
    return _MODULES[provider].create(order, creds, env, ctx)


def fetch_status(provider: str, order, creds: dict, env: str) -> dict:
    return _MODULES[provider].fetch_status(order, creds, env)


def validate(provider: str, creds: dict, env: str) -> str:
    return _MODULES[provider].validate(creds, env)
