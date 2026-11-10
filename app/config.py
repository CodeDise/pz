"""Settings. Order of priority for every value:
   1. an environment variable (e.g. set on Render), if present and not empty
   2. my_config.py in the project root folder (the file you fill in)
   3. the built-in default
"""
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

_FILE_PATH = Path(__file__).resolve().parent.parent / "my_config.py"


def _load_file_values() -> dict:
    if not _FILE_PATH.exists():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("paygate_my_config", _FILE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:  # a typo in the file should stop the app with a clear message
        raise RuntimeError(
            f"my_config.py has a mistake: {e.__class__.__name__}: {e}. "
            "Check that every value is inside quotes and no line is broken."
        ) from e
    return {k: v for k, v in vars(module).items() if k.isupper()}


_FILE = _load_file_values()


def _get(name: str, default: str = "") -> str:
    env = os.environ.get(name, "").strip()
    if env:
        return env
    value = _FILE.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).strip() or default


class Settings:
    def __init__(self) -> None:
        self.APP_NAME = _get("APP_NAME", "PayGate")

        # Telegram
        self.BOT_TOKEN = _get("BOT_TOKEN")
        self.BOT_USERNAME = _get("BOT_USERNAME").lstrip("@")

        # Security key: use the one you set, otherwise derive a stable one from the bot token.
        secret = _get("SECRET_KEY")
        self.secret_derived = False
        if not secret and self.BOT_TOKEN:
            secret = hashlib.sha256(("paygate-derived-key|" + self.BOT_TOKEN).encode()).hexdigest()
            self.secret_derived = True
        self.SECRET_KEY = secret or "dev-only-insecure-key-change-me"

        base = _get("BASE_URL") or _get("RENDER_EXTERNAL_URL") or "http://localhost:8000"
        self.BASE_URL = base.rstrip("/")
        self.https = self.BASE_URL.startswith("https://")

        db = _get("DATABASE_URL", "sqlite:///./paygate.db")
        if db.startswith("postgres://"):
            db = "postgresql+psycopg2://" + db[len("postgres://"):]
        elif db.startswith("postgresql://"):
            db = "postgresql+psycopg2://" + db[len("postgresql://"):]
        self.DATABASE_URL = db
        if db.startswith("sqlite") and os.environ.get("RENDER"):
            print(
                "[config] WARNING: no DATABASE_URL set. Data is stored in a temporary file and will be "
                "DELETED on every restart. Add your Render PostgreSQL 'Internal Database URL' in my_config.py.",
                file=sys.stderr,
            )

        self.telegram_webhook_secret = hashlib.sha256(("tg|" + self.SECRET_KEY).encode()).hexdigest()[:48]

        # Force-subscribe: users must join this channel before using the bot, e.g. @payzuupdates.
        # The bot must be an ADMIN of that channel. Leave empty to turn the feature off.
        fsub = _get("FSUB_CHANNEL")
        if fsub and not fsub.startswith("@") and not fsub.lstrip("-").isdigit():
            fsub = "@" + fsub
        self.FSUB_CHANNEL = fsub

        # Admin panel (/admin): needs a real password, at least 16 characters.
        admin = _get("ADMIN_TOKEN")
        if admin and len(admin) < 16:
            print("[config] ADMIN_TOKEN is shorter than 16 characters, so the /admin page is switched off.", file=sys.stderr)
            admin = ""
        self.ADMIN_TOKEN = admin

        # Crypto watchers
        self.TRONGRID_API_KEY = _get("TRONGRID_API_KEY")
        self.BSC_RPC_URL = _get("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
        self.BSC_CONFIRMATIONS = int(_get("BSC_CONFIRMATIONS", "12"))
        self.BSC_BLOCK_TIME = float(_get("BSC_BLOCK_TIME", "0.75"))

        # Worker
        self.POLL_INTERVAL = max(5, int(_get("POLL_INTERVAL", "15")))

        # Live payments need an approved merchant (approve in /admin). REQUIRE_KYC=False skips this.
        self.REQUIRE_KYC = _get("REQUIRE_KYC", "1").lower() not in ("0", "false", "no")

        # Dev helpers
        self.DEV_LOGIN = _get("DEV_LOGIN", "0").lower() in ("1", "true", "yes")
        self.ALLOW_PRIVATE_WEBHOOKS = _get("ALLOW_PRIVATE_WEBHOOKS", "0").lower() in ("1", "true", "yes")

    @property
    def insecure_secret(self) -> bool:
        return self.SECRET_KEY.startswith("dev-only")


settings = Settings()
