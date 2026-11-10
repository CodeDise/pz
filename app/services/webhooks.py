"""Signed, retried webhook delivery to merchant servers."""
import ipaddress
import json
import logging
import socket
import time
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Merchant, WebhookDelivery
from ..security import decrypt_text, hmac_sha256_hex
from ..utils import iso, new_id, utcnow

log = logging.getLogger("paygate.webhooks")

BACKOFF_SECONDS = [0, 60, 300, 1800, 7200, 21600, 43200, 86400]  # 8 attempts over ~1.5 days


def is_safe_url(url: str) -> tuple[bool, str]:
    """Blocks non-http(s) URLs and anything resolving to a private/internal address (SSRF guard)."""
    try:
        p = urlparse(url)
    except ValueError:
        return False, "Invalid URL"
    if p.scheme not in ("http", "https") or not p.hostname:
        return False, "URL must start with https://"
    if p.scheme == "http" and settings.https and not settings.ALLOW_PRIVATE_WEBHOOKS:
        return False, "Use an https:// URL"
    if settings.ALLOW_PRIVATE_WEBHOOKS:
        return True, ""
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, "Could not resolve that hostname"
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            return False, "URL points to a private or internal address"
    return True, ""


def sign(secret: str, ts: int, body: str) -> str:
    return hmac_sha256_hex(secret, f"{ts}.{body}")


def enqueue(db: Session, merchant: Merchant, event: str, data: dict, order_id: str | None, livemode: bool) -> WebhookDelivery | None:
    if not merchant.webhook_url:
        return None
    payload = {
        "id": new_id("evt_"),
        "type": event,
        "livemode": livemode,
        "created": iso(utcnow()),
        "data": data,
    }
    d = WebhookDelivery(
        id=new_id("whd_"),
        merchant_id=merchant.id,
        order_id=order_id,
        event=event,
        url=merchant.webhook_url,
        payload=json.dumps(payload, separators=(",", ":")),
    )
    db.add(d)
    return d


def _attempt(db: Session, d: WebhookDelivery) -> bool:
    merchant = db.get(Merchant, d.merchant_id)
    ok_url, why = is_safe_url(d.url)
    d.attempts += 1
    if not ok_url:
        d.status, d.last_error = "failed", why
        db.commit()
        return False
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"{settings.APP_NAME}-Webhooks/1.0",
        "X-PayGate-Event": d.event,
        "X-PayGate-Delivery": d.id,
        "X-PayGate-Signature": f"t={ts},v1={sign(decrypt_text(merchant.webhook_secret_enc), ts, d.payload)}",
    }
    try:
        r = httpx.post(d.url, content=d.payload, headers=headers, timeout=10, follow_redirects=False)
        d.last_status_code = r.status_code
        success = 200 <= r.status_code < 300
        d.last_error = None if success else f"HTTP {r.status_code}"
    except Exception as e:
        success = False
        d.last_status_code = None
        d.last_error = e.__class__.__name__
    if success:
        d.status = "delivered"
    elif d.attempts >= len(BACKOFF_SECONDS):
        d.status = "failed"
    else:
        d.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[d.attempts])
    db.commit()
    return success


def deliver_due(db: Session, limit: int = 25) -> None:
    due = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= utcnow())
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(limit)
    ).all()
    for d in due:
        try:
            _attempt(db, d)
        except Exception:
            db.rollback()
            log.exception("webhook delivery crashed")


def send_test(db: Session, merchant: Merchant) -> tuple[bool, str]:
    """Sends a 'ping' event right away so merchants can check their endpoint and signature code."""
    if not merchant.webhook_url:
        return False, "Save a webhook URL first."
    d = enqueue(db, merchant, "ping", {"message": "Hello from PayGate"}, None, livemode=False)
    db.commit()
    ok = _attempt(db, d)
    return ok, "Your server answered with a success code." if ok else f"Delivery failed ({d.last_error or 'no response'})."
