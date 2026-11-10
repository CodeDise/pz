import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApiKey, Merchant
from ..security import encrypt_text, new_api_key, sha256_hex
from ..utils import new_id


def get_or_create_merchant(db: Session, tg_id: int, tg_name: str | None) -> Merchant:
    m = db.scalar(select(Merchant).where(Merchant.tg_id == tg_id))
    if m:
        if tg_name and m.tg_name != tg_name:
            m.tg_name = tg_name
            db.commit()
        return m
    m = Merchant(
        public_id=new_id("mer_"),
        tg_id=tg_id,
        tg_name=tg_name,
        webhook_secret_enc=encrypt_text("whsec_" + secrets.token_urlsafe(24)),
    )
    db.add(m)
    db.commit()
    return m


def create_api_key(db: Session, merchant: Merchant, mode: str, label: str | None) -> str:
    key = new_api_key(mode)
    db.add(
        ApiKey(
            merchant_id=merchant.id,
            mode=mode,
            key_hash=sha256_hex(key),
            last4=key[-4:],
            label=(label or "").strip()[:60] or None,
        )
    )
    db.commit()
    return key
