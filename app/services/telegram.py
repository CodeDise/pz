"""Telegram bot: welcome/force-subscribe images, login links, mobile verification, payment notifications.

Webhook-based (no polling). Images live in app/static/bot/ and are uploaded once, then re-used by file_id.
"""
import html
import json
import logging
import re
import secrets
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import LoginToken, Merchant, Order
from ..security import sha256_hex
from ..utils import fmt_units, ist, utcnow
from .merchants import get_or_create_merchant

log = logging.getLogger("paygate.telegram")

IMG_DIR = Path(__file__).resolve().parent.parent / "static" / "bot"
_file_ids: dict[str, str] = {}


def call(method: str, payload: dict | None = None) -> dict | None:
    if not settings.BOT_TOKEN:
        return None
    try:
        r = httpx.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}", json=payload or {}, timeout=15)
        data = r.json()
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, data.get("description"))
        return data
    except Exception as e:  # never log the exception text: it contains the bot token URL
        log.warning("telegram %s error: %s", method, e.__class__.__name__)
        return None


def send(chat_id: int, text: str, markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = markup
    call("sendMessage", payload)


def send_photo(chat_id: int, image: str, caption: str, markup: dict | None = None) -> bool:
    """Sends one of the bot images (app/static/bot/<image>.png) with a caption.
    If the image cannot be sent for any reason, the caption goes out as a normal text message instead."""
    if not settings.BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendPhoto"
    fields = {"chat_id": str(chat_id), "caption": caption[:1000], "parse_mode": "HTML"}
    if markup:
        fields["reply_markup"] = json.dumps(markup)
    path = IMG_DIR / f"{image}.png"
    for _attempt in range(2):
        cached = _file_ids.get(image)
        try:
            if cached:
                r = httpx.post(url, data={**fields, "photo": cached}, timeout=30)
            elif path.exists():
                r = httpx.post(url, data=fields, files={"photo": (path.name, path.read_bytes(), "image/png")}, timeout=60)
            else:
                break
            data = r.json()
            if data.get("ok"):
                photos = (data.get("result") or {}).get("photo") or []
                if photos:
                    _file_ids[image] = photos[-1]["file_id"]
                return True
            log.warning("sendPhoto %s failed: %s", image, data.get("description"))
        except Exception as e:
            log.warning("sendPhoto %s error: %s", image, e.__class__.__name__)
        if cached:
            _file_ids.pop(image, None)  # stale file_id: retry once with a fresh upload
            continue
        break
    send(chat_id, caption, markup)
    return False


def setup() -> None:
    """Registers the webhook, menu button and commands. Runs at startup."""
    if not settings.BOT_TOKEN:
        log.info("BOT_TOKEN not set: Telegram bot disabled")
        return
    me = call("getMe")
    if me and me.get("ok") and not settings.BOT_USERNAME:
        settings.BOT_USERNAME = me["result"].get("username", "")
    if settings.https:
        call(
            "setWebhook",
            {
                "url": f"{settings.BASE_URL}/telegram/webhook/{settings.telegram_webhook_secret}",
                "secret_token": settings.telegram_webhook_secret,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        call(
            "setChatMenuButton",
            {"menu_button": {"type": "web_app", "text": "Dashboard", "web_app": {"url": f"{settings.BASE_URL}/app/tg"}}},
        )
    else:
        log.warning("BASE_URL is not https: Telegram webhook and Mini App button were not registered")
    call(
        "setMyCommands",
        {
            "commands": [
                {"command": "dashboard", "description": "Open your merchant dashboard"},
                {"command": "orders", "description": "Latest payments"},
                {"command": "verify", "description": "Verify your mobile number"},
                {"command": "help", "description": "How it works"},
            ]
        },
    )
    if settings.FSUB_CHANNEL:
        log.info("Force-subscribe is ON for %s (the bot must be an admin of that channel)", settings.FSUB_CHANNEL)


# ---------------------------------------------------------------- force subscribe
def is_member(user_id: int) -> bool | None:
    """True/False if we can tell, None if the check itself failed (e.g. bot is not a channel admin)."""
    res = call("getChatMember", {"chat_id": settings.FSUB_CHANNEL, "user_id": user_id})
    if not res or not res.get("ok"):
        return None
    info = res["result"]
    status = info.get("status")
    if status in ("creator", "administrator", "member"):
        return True
    if status == "restricted":
        return bool(info.get("is_member"))
    return False


def _fsub_allows(chat_id: int, tg_id: int) -> bool:
    """False means the user was shown the 'join our channel' image and must not continue yet."""
    if not settings.FSUB_CHANNEL:
        return True
    if is_member(tg_id) is not False:  # member, or check failed: never lock everyone out because of a setup mistake
        return True
    rows = []
    if settings.FSUB_CHANNEL.startswith("@"):
        rows.append([{"text": "Join channel", "url": f"https://t.me/{settings.FSUB_CHANNEL[1:]}"}])
    rows.append([{"text": "I've joined", "callback_data": "fsub_check"}])
    send_photo(
        chat_id,
        "fsub",
        "<b>Join our channel first</b>\nYou need to join our channel to use this bot. Join, then come back and tap “I've joined”.",
        {"inline_keyboard": rows},
    )
    return False


# ---------------------------------------------------------------- flows
def make_login_link(db, tg_id: int, name: str | None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(LoginToken(token_hash=sha256_hex(token), tg_id=tg_id, tg_name=name, expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    return f"{settings.BASE_URL}/auth/link?t={token}"


def _contact_keyboard() -> dict:
    return {
        "keyboard": [[{"text": "Verify my mobile", "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def _welcome(db, chat_id: int, tg_id: int, name: str | None, first: bool) -> None:
    merchant = get_or_create_merchant(db, tg_id, name)
    link = make_login_link(db, tg_id, name)
    esc = html.escape
    markup = None
    if settings.https:
        markup = {
            "inline_keyboard": [
                [{"text": "Open dashboard", "web_app": {"url": f"{settings.BASE_URL}/app/tg"}}],
                [{"text": "Open in browser", "url": link}],
            ]
        }
    if first:
        text = (
            f"<b>Welcome to {esc(settings.APP_NAME)}</b>\n"
            "Accept UPI, card and USDT payments through your own gateway accounts and wallets. "
            "We never hold your money: it goes straight to you.\n\n"
            "Open your dashboard to connect Razorpay, Cashfree, PhonePe or a crypto wallet and create your API keys."
        )
        if not markup:
            text += f"\n\nYour login link (valid 10 minutes):\n{esc(link)}"
        send_photo(chat_id, "welcome", text, markup)
    elif markup:
        send(chat_id, "Your dashboard is ready.", markup)
    else:
        send(chat_id, f"Your login link (valid 10 minutes):\n{esc(link)}")
    if first and not merchant.mobile_verified:
        send(chat_id, "Verify your mobile number with one tap. Telegram shares it securely.", _contact_keyboard())


def _contact(db, chat_id: int, msg: dict, tg_id: int, name: str | None) -> None:
    contact = msg["contact"]
    if contact.get("user_id") != tg_id:
        send(chat_id, "Please share your own contact using the button, not someone else's.")
        return
    digits = re.sub(r"\D", "", contact.get("phone_number", ""))
    merchant = get_or_create_merchant(db, tg_id, name)
    merchant.mobile = "+" + digits
    merchant.mobile_verified = True
    db.commit()
    send(chat_id, f"Mobile verified: <code>{html.escape(merchant.mobile)}</code>", {"remove_keyboard": True})


def _orders(db, chat_id: int, tg_id: int) -> None:
    merchant = db.scalar(select(Merchant).where(Merchant.tg_id == tg_id))
    if not merchant:
        send(chat_id, "Send /start first to create your account.")
        return
    rows = db.scalars(select(Order).where(Order.merchant_id == merchant.id).order_by(Order.created_at.desc()).limit(5)).all()
    if not rows:
        send(chat_id, "No payments yet. Create your first one from the dashboard.")
        return
    icon = {"paid": "✅", "created": "🕓", "expired": "⌛", "cancelled": "✖️", "failed": "⚠️"}
    lines = [
        f"{icon.get(o.status, '•')} <b>{fmt_units(o.amount_units, o.currency)}</b>  {o.status}"
        f"{' (test)' if o.mode == 'test' else ''}  <i>{ist(o.created_at)}</i>"
        for o in rows
    ]
    send(chat_id, "<b>Latest payments</b>\n" + "\n".join(lines))


def _display_name(frm: dict) -> str | None:
    return " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or frm.get("username")


def _callback(cb: dict) -> None:
    """Handles the 'I've joined' button."""
    frm = cb.get("from") or {}
    tg_id = frm.get("id")
    answer = {"callback_query_id": cb.get("id")}
    if cb.get("data") != "fsub_check" or not tg_id:
        call("answerCallbackQuery", answer)
        return
    if settings.FSUB_CHANNEL and is_member(tg_id) is False:
        call("answerCallbackQuery", {**answer, "text": "You have not joined yet. Join the channel first.", "show_alert": True})
        return
    call("answerCallbackQuery", {**answer, "text": "Thanks for joining!"})
    chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id") or tg_id
    with SessionLocal() as db:
        _welcome(db, chat_id, tg_id, _display_name(frm), first=True)


def handle_update(update: dict) -> None:
    if update.get("callback_query"):
        _callback(update["callback_query"])
        return
    msg = update.get("message")
    if not msg or (msg.get("chat") or {}).get("type") != "private":
        return
    frm = msg.get("from") or {}
    tg_id = frm.get("id")
    if not tg_id:
        return
    chat_id = msg["chat"]["id"]
    if not _fsub_allows(chat_id, tg_id):
        return
    name = _display_name(frm)
    with SessionLocal() as db:
        if "contact" in msg:
            _contact(db, chat_id, msg, tg_id, name)
            return
        text = (msg.get("text") or "").strip()
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd == "/start":
            _welcome(db, chat_id, tg_id, name, first=True)
        elif cmd in ("/dashboard", "/login"):
            _welcome(db, chat_id, tg_id, name, first=False)
        elif cmd == "/orders":
            _orders(db, chat_id, tg_id)
        elif cmd == "/verify":
            send(chat_id, "Tap the button to share your mobile number.", _contact_keyboard())
        else:
            send_photo(
                chat_id,
                "how_it_works",
                "<b>How it works</b>\n/dashboard  open your merchant dashboard\n/orders  latest payments\n/verify  verify your mobile number",
            )


# ---------------------------------------------------------------- notifications to the merchant
def notify_paid(merchant: Merchant, order: Order) -> None:
    if not settings.BOT_TOKEN:
        return
    esc = html.escape
    lines = [
        "<b>Payment received</b>" + (" (test)" if order.mode == "test" else ""),
        f"<b>{esc(fmt_units(order.amount_units, order.currency))}</b>",
        f"Order <code>{esc(order.id)}</code>",
    ]
    if order.reference:
        lines.append(f"Reference: {esc(order.reference)}")
    if order.description:
        lines.append(esc(order.description))
    if order.method:
        lines.append(f"Via {esc(order.method)}")
    send_photo(merchant.tg_id, "payment_success", "\n".join(lines))


def notify_failed(merchant: Merchant, order: Order) -> None:
    if not settings.BOT_TOKEN:
        return
    esc = html.escape
    lines = [
        "<b>Payment failed</b>" + (" (test)" if order.mode == "test" else ""),
        f"<b>{esc(fmt_units(order.amount_units, order.currency))}</b>",
        f"Order <code>{esc(order.id)}</code>",
    ]
    if order.reference:
        lines.append(f"Reference: {esc(order.reference)}")
    send_photo(merchant.tg_id, "payment_failed", "\n".join(lines))


def notify_kyc(merchant: Merchant, status: str) -> None:
    if not settings.BOT_TOKEN:
        return
    if status == "pending":
        send_photo(
            merchant.tg_id,
            "kyc_in_review",
            "<b>Your details are in review</b>\nLive payments switch on as soon as you are approved. Until then, try everything in test mode.",
        )
    elif status == "approved":
        send(merchant.tg_id, "<b>You are approved.</b> Live payments are now switched on.")
    elif status == "rejected":
        send(merchant.tg_id, "<b>We could not approve your details.</b> Update them in Settings and save to ask for another review.")


def notify_new_key(merchant: Merchant, mode: str) -> None:
    if not settings.BOT_TOKEN:
        return
    send_photo(
        merchant.tg_id,
        "api_key_ready",
        f"<b>New {html.escape(mode)} API key created</b>\nCopy it from your dashboard now, it is shown only once. "
        "If this was not you, revoke it right away in Developers.",
    )
