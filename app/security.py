"""Encryption, signed tokens, API key helpers, Telegram initData verification."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl

from cryptography.fernet import Fernet

from .config import settings

_fernet = Fernet(
    base64.urlsafe_b64encode(hashlib.sha256(("enc|" + settings.SECRET_KEY).encode()).digest())
)


# ---------- encryption at rest (merchant gateway credentials, webhook secrets) ----------
def encrypt_text(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


def encrypt_json(data: dict) -> str:
    return encrypt_text(json.dumps(data))


def decrypt_json(value: str) -> dict:
    return json.loads(decrypt_text(value))


# ---------- signed, expiring tokens (session cookie etc.) ----------
def _sig(message: str) -> str:
    return hmac.new(("sign|" + settings.SECRET_KEY).encode(), message.encode(), hashlib.sha256).hexdigest()


def make_token(kind: str, subject: str, ttl_seconds: int) -> str:
    body = f"{kind}|{subject}|{int(time.time()) + ttl_seconds}"
    raw = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    return f"{raw}.{_sig(body)}"


def read_token(token: str | None, kind: str) -> str | None:
    if not token:
        return None
    try:
        raw, sig = token.rsplit(".", 1)
        body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        if not hmac.compare_digest(sig, _sig(body)):
            return None
        k, subject, exp = body.split("|", 2)
        if k != kind or int(exp) < time.time():
            return None
        return subject
    except Exception:
        return None


def csrf_token(session_cookie: str) -> str:
    return _sig("csrf|" + (session_cookie or ""))[:32]


# ---------- API keys ----------
def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_api_key(mode: str) -> str:
    return f"sk_{mode}_" + secrets.token_urlsafe(24)


def hmac_sha256_hex(secret: str, message: str | bytes) -> str:
    if isinstance(message, str):
        message = message.encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


# ---------- Telegram Mini App ----------
def verify_telegram_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    """Validates Telegram WebApp initData and returns the user dict, or None."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received_hash):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except Exception:
        return None
