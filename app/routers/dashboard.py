"""Merchant dashboard (web + Telegram Mini App): orders, integrations, developers, settings."""
import hmac
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..db import get_db
from ..errors import ApiError
from ..models import ApiKey, GatewayCredential, LoginToken, Merchant, Order, Wallet, WebhookDelivery
from ..security import (
    csrf_token,
    decrypt_json,
    decrypt_text,
    encrypt_json,
    encrypt_text,
    make_token,
    read_token,
    sha256_hex,
    verify_telegram_init_data,
)
from ..services import gateways, telegram, webhooks
from ..services import orders as svc
from ..services.addresses import valid_address
from ..services.gateways.meta import CRYPTO_LINKS
from ..services.merchants import create_api_key, get_or_create_merchant
from ..templating import templates
from ..utils import CURRENCIES, NETWORKS, utcnow
from .checkout import qr_svg

COOKIE = "pg_session"
SESSION_DAYS = 30
STATUSES = ("created", "paid", "expired", "cancelled", "failed")

router = APIRouter(include_in_schema=False)


class LoginRequired(Exception):
    pass


# ---------------------------------------------------------------- helpers
def go(path: str, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    qs = []
    if ok:
        qs.append("ok=" + quote(ok))
    if err:
        qs.append("err=" + quote(err))
    sep = "&" if "?" in path else "?"
    return RedirectResponse(path + (sep + "&".join(qs) if qs else ""), status_code=303)


def set_session(resp, merchant: Merchant) -> None:
    resp.set_cookie(
        COOKIE,
        make_token("session", str(merchant.id), SESSION_DAYS * 86400),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.https,
    )


def current_merchant(request: Request, db: Session = Depends(get_db)) -> Merchant:
    subject = read_token(request.cookies.get(COOKIE), "session")
    merchant = db.get(Merchant, int(subject)) if subject and subject.isdigit() else None
    if not merchant:
        raise LoginRequired()
    return merchant


def verify_csrf(request: Request, csrf: str = Form("")) -> None:
    sess = request.cookies.get(COOKIE, "")
    if not sess or not hmac.compare_digest(csrf, csrf_token(sess)):
        raise HTTPException(403, "Your session expired. Reload the page and try again.")


def page(request: Request, template: str, merchant: Merchant, nav: str, **ctx):
    ctx.update(
        merchant=merchant,
        nav=nav,
        csrf=csrf_token(request.cookies.get(COOKIE, "")),
        ok=request.query_params.get("ok"),
        err=request.query_params.get("err"),
    )
    return templates.TemplateResponse(request, template, ctx)


def _mode(value: str | None) -> str:
    return "test" if value == "test" else "live"


def _owned_order(db: Session, merchant: Merchant, order_id: str) -> Order:
    o = db.get(Order, order_id)
    if not o or o.merchant_id != merchant.id:
        raise HTTPException(404, "Order not found")
    return o


# ---------------------------------------------------------------- login / logout
@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"bot": settings.BOT_USERNAME, "dev": settings.DEV_LOGIN, "err": request.query_params.get("err")},
    )


@router.post("/login/dev")
def dev_login(tg_id: int = Form(...), name: str = Form("Developer"), db: Session = Depends(get_db)):
    if not settings.DEV_LOGIN:
        raise HTTPException(404)
    merchant = get_or_create_merchant(db, tg_id, name.strip()[:60] or "Developer")
    resp = go("/dashboard")
    set_session(resp, merchant)
    return resp


@router.get("/auth/link")
def auth_link(t: str, db: Session = Depends(get_db)):
    row = db.get(LoginToken, sha256_hex(t))
    if not row or row.used or row.expires_at < utcnow():
        return go("/login", err="That login link has expired. Send /dashboard to the bot to get a new one.")
    row.used = True
    db.commit()
    merchant = get_or_create_merchant(db, row.tg_id, row.tg_name)
    resp = go("/dashboard")
    set_session(resp, merchant)
    return resp


@router.get("/app/tg")
def telegram_app(request: Request):
    return templates.TemplateResponse(request, "tg_app.html", {})


@router.post("/auth/webapp")
def auth_webapp(payload: dict = Body(...), db: Session = Depends(get_db)):
    user = verify_telegram_init_data(str(payload.get("initData", "")), settings.BOT_TOKEN) if settings.BOT_TOKEN else None
    if not user or "id" not in user:
        raise HTTPException(401, "Telegram login failed")
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or user.get("username")
    merchant = get_or_create_merchant(db, int(user["id"]), name)
    resp = JSONResponse({"ok": True})
    set_session(resp, merchant)
    return resp


@router.post("/logout")
def logout(_: None = Depends(verify_csrf)):
    resp = go("/login")
    resp.delete_cookie(COOKIE)
    return resp


# ---------------------------------------------------------------- overview
@router.get("/dashboard")
def overview(request: Request, mode: str = "live", m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    mode = _mode(mode)
    offset = timedelta(hours=5, minutes=30)
    now = utcnow()
    day0 = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0) - offset
    mine = (Order.merchant_id == m.id, Order.mode == mode)

    paid = db.scalars(select(Order).where(*mine, Order.status == "paid", Order.paid_at >= day0 - timedelta(days=6))).all()
    days = []
    for i in range(6, -1, -1):
        start = day0 - timedelta(days=i)
        end = start + timedelta(days=1)
        per = {c: sum(o.amount_units for o in paid if o.currency == c and start <= o.paid_at < end) for c in CURRENCIES}
        days.append(((start + offset).strftime("%a"), per))
    charts = []
    for c in CURRENCIES:
        peak = max([d[1][c] for d in days] + [1])
        charts.append(
            {
                "currency": c,
                "week": sum(d[1][c] for d in days),
                "today": days[-1][1][c],
                "days": [{"label": l, "units": p[c], "pct": max(6, round(p[c] * 100 / peak)) if p[c] else 0} for l, p in days],
            }
        )
    month = {c: 0 for c in CURRENCIES}
    for cur, total in db.execute(
        select(Order.currency, func.sum(Order.amount_units))
        .where(*mine, Order.status == "paid", Order.paid_at >= now - timedelta(days=30))
        .group_by(Order.currency)
    ):
        month[cur] = int(total or 0)
    counts = {s: n for s, n in db.execute(select(Order.status, func.count()).where(*mine).group_by(Order.status))}
    recent = db.scalars(select(Order).where(*mine).order_by(Order.created_at.desc()).limit(8)).all()

    has_conn = bool(db.scalar(select(GatewayCredential.id).where(GatewayCredential.merchant_id == m.id).limit(1))) or bool(
        db.scalar(select(Wallet.id).where(Wallet.merchant_id == m.id).limit(1))
    )
    has_key = bool(db.scalar(select(ApiKey.id).where(ApiKey.merchant_id == m.id).limit(1)))
    has_order = bool(db.scalar(select(Order.id).where(Order.merchant_id == m.id).limit(1)))
    checklist = [
        {"done": m.kyc_status != "none", "title": "Add your business details", "text": "Name, email and verified mobile.", "href": "/dashboard/settings", "cta": "Open settings"},
        {"done": has_conn, "title": "Connect a gateway or wallet", "text": "Razorpay, Cashfree, PhonePe or a USDT address.", "href": "/dashboard/integrations", "cta": "Connect"},
        {"done": has_key, "title": "Create an API key", "text": "Start with a test key. No KYC needed.", "href": "/dashboard/developers", "cta": "Create key"},
        {"done": has_order, "title": "Create your first payment link", "text": "Try the full flow in test mode.", "href": "/dashboard/orders", "cta": "Create link"},
    ]
    return page(
        request, "dashboard/overview.html", m, "overview",
        mode=mode, charts=charts, month=month, counts=counts, recent=recent, checklist=checklist,
        onboarding=not all(c["done"] for c in checklist),
    )


# ---------------------------------------------------------------- orders
@router.get("/dashboard/orders")
def orders_page(request: Request, mode: str = "live", status: str = "", m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    mode = _mode(mode)
    q = select(Order).where(Order.merchant_id == m.id, Order.mode == mode)
    if status in STATUSES:
        q = q.where(Order.status == status)
    rows = db.scalars(q.order_by(Order.created_at.desc()).limit(100)).all()
    connected = [r.provider for r in db.scalars(select(GatewayCredential).where(GatewayCredential.merchant_id == m.id))]
    wallets = [w.network for w in db.scalars(select(Wallet).where(Wallet.merchant_id == m.id))]
    return page(
        request, "dashboard/orders.html", m, "orders",
        mode=mode, status=status, statuses=STATUSES, orders=rows, connected=connected, wallets=wallets,
        providers=gateways.PROVIDERS, networks=NETWORKS,
    )


@router.post("/dashboard/orders/new")
def orders_new(
    mode: str = Form("test"),
    amount: str = Form(...),
    currency: str = Form("INR"),
    description: str = Form(""),
    reference: str = Form(""),
    gateway: str = Form(""),
    network: str = Form(""),
    _: None = Depends(verify_csrf),
    m: Merchant = Depends(current_merchant),
    db: Session = Depends(get_db),
):
    mode = _mode(mode)
    try:
        order, _created = svc.create_order(
            db, m, mode,
            {"amount": amount, "currency": currency, "description": description, "reference": reference, "gateway": gateway, "network": network},
        )
    except ApiError as e:
        return go(f"/dashboard/orders?mode={mode}", err=e.message)
    return go(f"/dashboard/orders/{order.id}", ok="Payment link created. Share it with your customer.")


@router.get("/dashboard/orders/{order_id}")
def order_detail(order_id: str, request: Request, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    o = _owned_order(db, m, order_id)
    svc.refresh_from_gateway(db, o)
    deliveries = db.scalars(select(WebhookDelivery).where(WebhookDelivery.order_id == o.id).order_by(WebhookDelivery.created_at.desc())).all()
    link = svc.checkout_url(o)
    return page(request, "dashboard/order_detail.html", m, "orders", o=o, link=link, qr=qr_svg(link), deliveries=deliveries)


@router.post("/dashboard/orders/{order_id}/cancel")
def order_cancel(order_id: str, _: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    o = _owned_order(db, m, order_id)
    try:
        svc.cancel_order(db, o)
    except ApiError as e:
        return go(f"/dashboard/orders/{o.id}", err=e.message)
    return go(f"/dashboard/orders/{o.id}", ok="Payment link cancelled.")


# ---------------------------------------------------------------- integrations
def _mask(value: str) -> str:
    return value if len(value) <= 8 else value[:6] + "••••" + value[-4:]


@router.get("/dashboard/integrations")
def integrations(request: Request, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    rows = {r.provider: r for r in db.scalars(select(GatewayCredential).where(GatewayCredential.merchant_id == m.id))}
    providers = []
    for pid, meta in gateways.PROVIDERS.items():
        row = rows.get(pid)
        preview = None
        if row:
            preview = _mask(decrypt_json(row.data_enc).get(meta["fields"][0]["key"], ""))
        providers.append({"id": pid, **meta, "connected": bool(row), "preview": preview, "env": row.env if row else None})
    wallets = {w.network: w.address for w in db.scalars(select(Wallet).where(Wallet.merchant_id == m.id))}
    return page(
        request, "dashboard/integrations.html", m, "integrations",
        providers=providers, wallets=wallets, networks=NETWORKS, crypto_links=CRYPTO_LINKS,
    )


def _provider_or_404(provider: str) -> dict:
    meta = gateways.PROVIDERS.get(provider)
    if not meta:
        raise HTTPException(404)
    return meta


@router.post("/dashboard/integrations/gateway/{provider}")
async def gateway_save(
    provider: str,
    request: Request,
    _: None = Depends(verify_csrf),
    m: Merchant = Depends(current_merchant),
    db: Session = Depends(get_db),
):
    meta = _provider_or_404(provider)
    form = await request.form()
    creds = {}
    for f in meta["fields"]:
        value = str(form.get(f["key"], "") or f.get("default", "")).strip()
        if not value or len(value) > 300:
            return go("/dashboard/integrations#" + provider, err=f"{f['label']} is required.")
        creds[f["key"]] = value
    if provider == "razorpay":
        if not creds["key_id"].startswith("rzp_"):
            return go("/dashboard/integrations#razorpay", err="Razorpay Key ID starts with rzp_test_ or rzp_live_.")
        env = "sandbox" if creds["key_id"].startswith("rzp_test_") else "production"
    else:
        env = "sandbox" if form.get("env") == "sandbox" else "production"

    note = "Keys saved."
    if not form.get("skip_check"):
        try:
            note = await run_in_threadpool(gateways.validate, provider, creds, env)
        except gateways.GatewayError as e:
            return go(
                "/dashboard/integrations#" + provider,
                err=f"{meta['name']} could not verify these keys: {e}. Check them, or tick 'Save without checking'.",
            )

    row = db.scalar(select(GatewayCredential).where(GatewayCredential.merchant_id == m.id, GatewayCredential.provider == provider))
    if row:
        row.data_enc, row.env = encrypt_json(creds), env
    else:
        db.add(GatewayCredential(merchant_id=m.id, provider=provider, env=env, data_enc=encrypt_json(creds)))
    db.commit()
    return go("/dashboard/integrations#" + provider, ok=note)


@router.post("/dashboard/integrations/gateway/{provider}/test")
def gateway_test(provider: str, _: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    meta = _provider_or_404(provider)
    row = db.scalar(select(GatewayCredential).where(GatewayCredential.merchant_id == m.id, GatewayCredential.provider == provider))
    if not row:
        return go("/dashboard/integrations#" + provider, err="Add your keys first.")
    try:
        note = gateways.validate(provider, decrypt_json(row.data_enc), row.env)
    except gateways.GatewayError as e:
        return go("/dashboard/integrations#" + provider, err=f"{meta['name']}: {e}")
    return go("/dashboard/integrations#" + provider, ok=note)


@router.post("/dashboard/integrations/gateway/{provider}/delete")
def gateway_delete(provider: str, _: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    _provider_or_404(provider)
    row = db.scalar(select(GatewayCredential).where(GatewayCredential.merchant_id == m.id, GatewayCredential.provider == provider))
    if row:
        db.delete(row)
        db.commit()
    return go("/dashboard/integrations#" + provider, ok="Keys removed.")


@router.post("/dashboard/integrations/wallet")
def wallet_save(
    network: str = Form(...),
    address: str = Form(...),
    _: None = Depends(verify_csrf),
    m: Merchant = Depends(current_merchant),
    db: Session = Depends(get_db),
):
    network, address = network.strip().upper(), address.strip()
    if network not in NETWORKS:
        return go("/dashboard/integrations#crypto", err="Choose TRC20 or BEP20.")
    if not valid_address(network, address):
        return go("/dashboard/integrations#crypto", err=f"That is not a valid {network} address. Copy it again from your wallet or exchange.")
    row = db.scalar(select(Wallet).where(Wallet.merchant_id == m.id, Wallet.network == network))
    if row:
        row.address = address
    else:
        db.add(Wallet(merchant_id=m.id, network=network, address=address))
    db.commit()
    return go("/dashboard/integrations#crypto", ok=f"{network} wallet saved. Payments go straight to this address.")


@router.post("/dashboard/integrations/wallet/{network}/delete")
def wallet_delete(network: str, _: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    row = db.scalar(select(Wallet).where(Wallet.merchant_id == m.id, Wallet.network == network.upper()))
    if row:
        db.delete(row)
        db.commit()
    return go("/dashboard/integrations#crypto", ok="Wallet removed.")


# ---------------------------------------------------------------- developers
def _dev_ctx(db: Session, m: Merchant) -> dict:
    return {
        "keys": db.scalars(select(ApiKey).where(ApiKey.merchant_id == m.id).order_by(ApiKey.created_at.desc())).all(),
        "webhook_secret": decrypt_text(m.webhook_secret_enc),
        "deliveries": db.scalars(
            select(WebhookDelivery).where(WebhookDelivery.merchant_id == m.id).order_by(WebhookDelivery.created_at.desc()).limit(15)
        ).all(),
        "new_key": None,
    }


@router.get("/dashboard/developers")
def developers(request: Request, m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    return page(request, "dashboard/developers.html", m, "developers", **_dev_ctx(db, m))


@router.post("/dashboard/developers/keys/new")
def key_new(
    request: Request,
    mode: str = Form("test"),
    label: str = Form(""),
    _: None = Depends(verify_csrf),
    m: Merchant = Depends(current_merchant),
    db: Session = Depends(get_db),
):
    mode = _mode(mode)
    if mode == "live" and settings.REQUIRE_KYC and m.kyc_status != "approved":
        return go("/dashboard/developers", err="Live keys unlock after KYC approval. Test keys work right now.")
    ctx = _dev_ctx(db, m)
    ctx["new_key"] = create_api_key(db, m, mode, label)
    ctx["keys"] = _dev_ctx(db, m)["keys"]
    telegram.notify_new_key(m, mode)
    return page(request, "dashboard/developers.html", m, "developers", **ctx)


@router.post("/dashboard/developers/keys/{key_id}/revoke")
def key_revoke(key_id: int, _: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    k = db.get(ApiKey, key_id)
    if k and k.merchant_id == m.id:
        k.revoked = True
        db.commit()
    return go("/dashboard/developers", ok="API key revoked. It stops working immediately.")


@router.post("/dashboard/developers/webhook")
def webhook_save(url: str = Form(""), _: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    url = url.strip()
    if url:
        ok, why = webhooks.is_safe_url(url)
        if not ok:
            return go("/dashboard/developers#webhook", err=why + ".")
    m.webhook_url = url or None
    db.commit()
    return go("/dashboard/developers#webhook", ok="Webhook URL saved." if url else "Webhook URL removed.")


@router.post("/dashboard/developers/webhook/rotate")
def webhook_rotate(_: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    import secrets

    m.webhook_secret_enc = encrypt_text("whsec_" + secrets.token_urlsafe(24))
    db.commit()
    return go("/dashboard/developers#webhook", ok="New signing secret created. Update it on your server.")


@router.post("/dashboard/developers/webhook/test")
def webhook_test(_: None = Depends(verify_csrf), m: Merchant = Depends(current_merchant), db: Session = Depends(get_db)):
    ok, msg = webhooks.send_test(db, m)
    return go("/dashboard/developers#webhook", ok=msg if ok else None, err=None if ok else msg)


# ---------------------------------------------------------------- settings / KYC
@router.get("/dashboard/settings")
def settings_page(request: Request, m: Merchant = Depends(current_merchant)):
    return page(request, "dashboard/settings.html", m, "settings", dev=settings.DEV_LOGIN)


@router.post("/dashboard/settings")
def settings_save(
    full_name: str = Form(""),
    business_name: str = Form(""),
    email: str = Form(""),
    mobile: str = Form(""),
    _: None = Depends(verify_csrf),
    m: Merchant = Depends(current_merchant),
    db: Session = Depends(get_db),
):
    full_name, business_name, email = full_name.strip()[:120], business_name.strip()[:120], email.strip()[:160]
    if not full_name or not business_name or "@" not in email:
        return go("/dashboard/settings", err="Enter your name, business name and a valid email.")
    if not m.mobile_verified:
        if settings.DEV_LOGIN and mobile.strip():
            m.mobile, m.mobile_verified = mobile.strip()[:20], True
        else:
            return go("/dashboard/settings", err="Verify your mobile first: open the Telegram bot and send /verify.")
    m.full_name, m.business_name, m.email = full_name, business_name, email
    previous = m.kyc_status
    if m.kyc_status in ("none", "rejected"):
        m.kyc_status = "pending" if settings.REQUIRE_KYC else "approved"
    db.commit()
    if m.kyc_status != previous:
        telegram.notify_kyc(m, m.kyc_status)
    msg = "Saved. We will review your details shortly." if m.kyc_status == "pending" else "Saved."
    return go("/dashboard/settings", ok=msg)
