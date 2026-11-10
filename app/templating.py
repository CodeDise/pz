from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import settings
from .services.gateways.meta import PROVIDERS
from .utils import NETWORKS, exact_usdt, fmt_units, ist

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    settings=settings, fmt_units=fmt_units, exact_usdt=exact_usdt, PROVIDERS=PROVIDERS, NETWORKS=NETWORKS
)
templates.env.filters["ist"] = ist
