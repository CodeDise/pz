"""Background loop (runs inside the web process): expiry, crypto watchers, gateway re-checks, webhook delivery."""
import logging
import threading
import time

from .config import settings
from .db import SessionLocal
from .services import crypto, orders, webhooks

log = logging.getLogger("paygate.worker")


def _run(step) -> None:
    db = SessionLocal()
    try:
        step(db)
    except Exception:
        db.rollback()
        log.exception("worker step %s failed", getattr(step, "__name__", step))
    finally:
        db.close()


def loop(stop: threading.Event) -> None:
    last_slow = 0.0
    log.info("worker started (poll every %ss)", settings.POLL_INTERVAL)
    while not stop.is_set():
        _run(webhooks.deliver_due)  # every 5 seconds
        if time.time() - last_slow >= settings.POLL_INTERVAL:
            last_slow = time.time()
            _run(crypto.poll_trc20)
            _run(crypto.poll_bep20)
            _run(orders.poll_gateway_orders)
            _run(orders.expire_due)
        stop.wait(5)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop,), name="paygate-worker", daemon=True).start()
    return stop
