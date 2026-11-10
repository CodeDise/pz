import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

CURRENCIES = ("INR", "USDT")
# INR is stored in paise (2 decimals). USDT is stored in 6 decimals (same as on-chain TRC20).
DECIMALS = {"INR": 2, "USDT": 6}


NETWORKS = {
    "TRC20": {"label": "USDT on TRON (TRC20)", "hint": "Low fees. Address starts with T."},
    "BEP20": {"label": "USDT on BNB Smart Chain (BEP20)", "hint": "Address starts with 0x."},
}


def utcnow() -> datetime:
    """Naive UTC datetime (all DB timestamps are naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_epoch(dt: datetime) -> float:
    """Epoch seconds for a naive-UTC datetime."""
    return dt.replace(tzinfo=timezone.utc).timestamp()


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def ist(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return (dt + timedelta(hours=5, minutes=30)).strftime("%d %b, %I:%M %p")


def new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(8)


def to_units(amount: Decimal, currency: str) -> int:
    return int((amount * (Decimal(10) ** DECIMALS[currency])).to_integral_value())


def from_units(units: int, currency: str) -> Decimal:
    return Decimal(int(units)) / (Decimal(10) ** DECIMALS[currency])


def plain_amount(units: int, currency: str) -> str:
    """Machine-friendly amount string, e.g. '499.00' or '10.037000'."""
    v = from_units(units, currency)
    if currency == "INR" or units % 10_000 == 0:
        return format(v, ".2f")
    return format(v, ".6f")


def exact_usdt(units: int) -> str:
    s = format(from_units(units, "USDT"), ".6f")
    head, tail = s.split(".")
    return f"{head}.{tail.rstrip('0').ljust(2, '0')}"


def fmt_units(units: int | None, currency: str) -> str:
    """Human-friendly amount for UI."""
    if units is None:
        return "—"
    v = from_units(units, currency)
    if currency == "INR":
        return f"₹{v:,.2f}"
    if units % 10_000 == 0:
        return f"{v:,.2f} USDT"
    return f"{exact_usdt(units)} USDT"
