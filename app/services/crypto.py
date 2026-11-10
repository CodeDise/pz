"""On-chain USDT payment detection (read-only). We never hold keys: payments go straight to the merchant's wallet.

Matching works by exact amount: every open order for a wallet gets a unique amount (see orders.allocate_crypto_units).
"""
import logging
import math
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChainCursor, Order
from ..utils import to_epoch, utcnow
from . import orders as order_service

log = logging.getLogger("paygate.crypto")

TRON_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
BSC_USDT = "0x55d398326f99059fF775485246999027B3197955"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
GRACE = timedelta(minutes=30)  # a payment that lands shortly after expiry still counts


def _watchable(db: Session, network: str) -> list[Order]:
    return db.scalars(
        select(Order).where(
            Order.mode == "live",
            Order.crypto_network == network,
            Order.paid_at.is_(None),
            Order.status.in_(("created", "expired")),
            Order.expires_at > utcnow() - GRACE,
        )
    ).all()


def _tx_seen(db: Session, tx_hash: str) -> bool:
    return db.scalar(select(Order.id).where(Order.crypto_tx_hash == tx_hash)) is not None


def _match(group: list[Order], units: int, ts: float | None) -> Order | None:
    for o in sorted(group, key=lambda x: x.created_at):
        if o.crypto_amount_units != units:
            continue
        if ts is not None and ts < to_epoch(o.created_at) - 60:
            continue
        return o
    return None


# ---------------- TRON (TRC20) ----------------
def poll_trc20(db: Session) -> None:
    by_addr: dict[str, list[Order]] = {}
    for o in _watchable(db, "TRC20"):
        by_addr.setdefault(o.crypto_address, []).append(o)
    headers = {"TRON-PRO-API-KEY": settings.TRONGRID_API_KEY} if settings.TRONGRID_API_KEY else {}
    for addr, group in by_addr.items():
        min_ts = int(min(to_epoch(o.created_at) for o in group) * 1000) - 60_000
        try:
            r = httpx.get(
                f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20",
                params={
                    "only_to": "true",
                    "only_confirmed": "true",
                    "limit": 200,
                    "contract_address": TRON_USDT,
                    "min_timestamp": min_ts,
                    "order_by": "block_timestamp,asc",
                },
                headers=headers,
                timeout=20,
            )
            r.raise_for_status()
            txs = r.json().get("data", [])
        except Exception as e:
            log.warning("trongrid error for %s: %s", addr[:6], e.__class__.__name__)
            continue
        for tx in txs:
            try:
                if tx.get("type") != "Transfer" or tx.get("to") != addr:
                    continue
                if (tx.get("token_info") or {}).get("address") != TRON_USDT:
                    continue
                txid = tx["transaction_id"]
                if _tx_seen(db, txid):
                    continue
                order = _match(group, int(tx["value"]), tx["block_timestamp"] / 1000)
                if order and order_service.mark_paid(db, order, method="usdt_trc20", tx_hash=txid):
                    group.remove(order)
            except (KeyError, ValueError, TypeError):
                continue


# ---------------- BNB Smart Chain (BEP20) ----------------
def _rpc(method: str, params: list):
    r = httpx.post(
        settings.BSC_RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=25,
    )
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(str(j["error"])[:200])
    return j["result"]


def poll_bep20(db: Session) -> None:
    orders = _watchable(db, "BEP20")
    if not orders:
        return
    group = {o.crypto_address.lower(): [] for o in orders}
    for o in orders:
        group[o.crypto_address.lower()].append(o)
    try:
        latest = int(_rpc("eth_blockNumber", []), 16)
    except Exception as e:
        log.warning("bsc rpc error: %s", e.__class__.__name__)
        return
    safe = latest - settings.BSC_CONFIRMATIONS
    oldest = min(to_epoch(o.created_at) for o in orders)
    blocks_back = math.ceil((utcnow().timestamp() - oldest) / settings.BSC_BLOCK_TIME) + 100
    start = max(0, safe - blocks_back)

    cursor = db.get(ChainCursor, "BEP20")
    frm = max(start, (cursor.last_block + 1) if cursor else start)
    topics_to = ["0x" + "0" * 24 + a[2:] for a in group]

    for _ in range(20):  # max 20 chunks per run
        if frm > safe:
            break
        to = min(frm + 999, safe)
        try:
            logs = _rpc(
                "eth_getLogs",
                [{"fromBlock": hex(frm), "toBlock": hex(to), "address": BSC_USDT, "topics": [TRANSFER_TOPIC, None, topics_to]}],
            )
        except Exception as e:
            log.warning("bsc getLogs error: %s", e.__class__.__name__)
            return
        for lg in logs:
            try:
                to_addr = "0x" + lg["topics"][2][-40:]
                raw = int(lg["data"], 16)
                if raw % 10**12:
                    continue
                txh = lg["transactionHash"]
                if _tx_seen(db, txh):
                    continue
                order = _match(group.get(to_addr.lower(), []), raw // 10**12, None)
                if order and order_service.mark_paid(db, order, method="usdt_bep20", tx_hash=txh):
                    group[to_addr.lower()].remove(order)
            except (KeyError, ValueError, IndexError, TypeError):
                continue
        if cursor:
            cursor.last_block, cursor.updated_at = to, utcnow()
        else:
            cursor = ChainCursor(network="BEP20", last_block=to)
            db.add(cursor)
        db.commit()
        frm = to + 1
