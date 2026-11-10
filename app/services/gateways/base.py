import httpx


class GatewayError(Exception):
    """A payment gateway rejected a call or could not be reached."""


def http(method: str, url: str, **kw) -> httpx.Response:
    kw.setdefault("timeout", 20)
    try:
        return httpx.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise GatewayError(f"Could not reach the gateway ({e.__class__.__name__})") from e


def error_message(resp: httpx.Response) -> str:
    try:
        j = resp.json()
    except Exception:
        return (resp.text or "")[:200] or f"HTTP {resp.status_code}"
    if isinstance(j, dict):
        err = j.get("error")
        if isinstance(err, dict) and err.get("description"):
            return str(err["description"])[:250]
        for k in ("message", "description", "error_description", "code"):
            if j.get(k):
                return str(j[k])[:250]
    return f"HTTP {resp.status_code}"


def ensure_ok(resp: httpx.Response) -> dict:
    if resp.status_code >= 400:
        raise GatewayError(error_message(resp))
    try:
        return resp.json()
    except ValueError:
        raise GatewayError("Gateway returned an invalid response")
