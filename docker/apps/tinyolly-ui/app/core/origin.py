"""Browser-origin checks.

TinyOlly has no login, so any web page the developer visits could otherwise POST to the local API
(reset the service map, create alert rules with a webhook URL, apply a collector config) or open the
update WebSocket: browsers send those cross-site "simple" requests without a CORS preflight.
Browsers always attach an `Origin` header to cross-origin POSTs and WebSocket handshakes, so a request that
carries an Origin we do not trust is rejected. Requests without an Origin (curl, the OTel collector,
server-to-server) are unaffected.
"""
import re
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def _glob_to_regex(pattern: str) -> str:
    return "^" + re.escape(pattern).replace(r"\*", r"[^/]*") + "$"


def cors_origin_regex(patterns: Iterable[str]) -> str:
    """Single regex for Starlette's allow_origin_regex. Starlette matches allow_origins literally, so the
    default 'http://localhost:*' never matched anything."""
    parts = [_glob_to_regex(p) for p in patterns if p]
    return "|".join(parts) if parts else r"^$"


def origin_allowed(origin: Optional[str], host_header: Optional[str], patterns: List[str]) -> bool:
    """True if there is no Origin, or it is same-origin, a localhost origin, or matches a configured pattern."""
    if not origin:
        return True
    if origin == "null":
        return False
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    if host_header and parts.netloc.lower() == host_header.lower():
        return True            # same-origin page (also covers access via a LAN IP / docker host name)
    if (parts.hostname or "").lower() in LOCAL_HOSTS or f"[{parts.hostname}]" in LOCAL_HOSTS:
        return True
    return any(re.match(_glob_to_regex(p), origin) for p in patterns if p)
