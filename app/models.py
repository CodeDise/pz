from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .utils import utcnow


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    tg_name: Mapped[str | None] = mapped_column(String(120))
    business_name: Mapped[str | None] = mapped_column(String(120))
    full_name: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str | None] = mapped_column(String(20))
    mobile_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str | None] = mapped_column(String(160))
    # none -> pending -> approved | rejected
    kyc_status: Mapped[str] = mapped_column(String(16), default="none")
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    webhook_secret_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8))  # test | live
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last4: Mapped[str] = mapped_column(String(4))
    label: Mapped[str | None] = mapped_column(String(60))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class GatewayCredential(Base):
    """A merchant's OWN payment-gateway credentials (Razorpay / Cashfree / PhonePe). Encrypted."""

    __tablename__ = "gateway_credentials"
    __table_args__ = (UniqueConstraint("merchant_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    env: Mapped[str] = mapped_column(String(12), default="production")  # sandbox | production
    data_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Wallet(Base):
    """A merchant's OWN receiving wallet. We never hold keys or funds."""

    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("merchant_id", "network"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    network: Mapped[str] = mapped_column(String(8))  # TRC20 | BEP20
    address: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("merchant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8), default="live")
    amount_units: Mapped[int] = mapped_column(BigInteger)  # INR paise / USDT micro-units
    currency: Mapped[str] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(String(250))
    reference: Mapped[str | None] = mapped_column(String(80))
    customer_email: Mapped[str | None] = mapped_column(String(160))
    customer_phone: Mapped[str | None] = mapped_column(String(20))
    return_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(80))

    status: Mapped[str] = mapped_column(String(12), default="created", index=True)
    method: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)

    gateway_provider: Mapped[str | None] = mapped_column(String(16))
    gateway_ref: Mapped[str | None] = mapped_column(String(80))
    gateway_checkout_url: Mapped[str | None] = mapped_column(Text)
    gateway_extra: Mapped[str | None] = mapped_column(Text)

    crypto_network: Mapped[str | None] = mapped_column(String(8))
    crypto_address: Mapped[str | None] = mapped_column(String(80))
    crypto_amount_units: Mapped[int | None] = mapped_column(BigInteger)
    crypto_tx_hash: Mapped[str | None] = mapped_column(String(100), unique=True)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(String(32))
    event: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(500))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending|delivered|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChainCursor(Base):
    """Last scanned block per EVM network (BEP20 watcher)."""

    __tablename__ = "chain_cursors"

    network: Mapped[str] = mapped_column(String(8), primary_key=True)
    last_block: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoginToken(Base):
    """One-time login links sent by the Telegram bot."""

    __tablename__ = "login_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger)
    tg_name: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
