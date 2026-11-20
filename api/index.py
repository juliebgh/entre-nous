"""Point d’entrée Vercel. Le site statique est publié depuis public/ uniquement."""
import ipaddress
import os
from urllib.parse import parse_qs, urlsplit

from server import app as game_app

ROUTES = {"state", "act", "create", "join"}


async def app(scope, receive, send):
    if scope["type"] != "http":
        await game_app(scope, receive, send)
        return
    origin = urlsplit(os.environ.get("PUBLIC_ORIGIN", ""))
    configured = (origin.scheme == "https" and origin.netloc and not origin.path.rstrip("/")
                  and not origin.query and not origin.fragment and os.getenv("DATABASE_URL")
                  and len(os.getenv("RATE_LIMIT_SECRET", "")) >= 32)
    if not configured:
        await send({"type": "http.response.start", "status": 503, "headers": [(b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b"Configuration serveur incomplete."})
        return
    path = scope["path"].strip("/").split("/")
    route = path[-1] if len(path) == 2 and path[0] == "api" and path[1] in ROUTES else None
    if not route:
        values = parse_qs(scope.get("query_string", b"")).get(b"route", [])
        route = values[0].decode("ascii", "ignore") if len(values) == 1 else ""
    headers = dict(scope["headers"])
    ip = (scope.get("client") or ("unknown", 0))[0]
    if os.environ.get("VERCEL") == "1":
        try:
            ip = str(ipaddress.ip_address(headers[b"x-vercel-forwarded-for"].decode().split(",")[0].strip()))
        except (KeyError, ValueError, UnicodeError):
            ip = "unknown"
    adapted = dict(scope, path="/api/" + (route if route in ROUTES else "unknown"), client=(ip, 0))
    await game_app(adapted, receive, send)
