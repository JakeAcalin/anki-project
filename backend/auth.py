import base64
import binascii
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from . import config


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gates every request behind HTTP Basic Auth when APP_USERNAME and
    APP_PASSWORD are both set. No-op (open access) otherwise, which is fine
    for local-only use but should always be set for a public deployment."""

    async def dispatch(self, request: Request, call_next):
        if not (config.APP_USERNAME and config.APP_PASSWORD):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                username, _, password = decoded.partition(":")
            except (binascii.Error, UnicodeDecodeError):
                username, password = "", ""

            if secrets.compare_digest(username, config.APP_USERNAME) and secrets.compare_digest(
                password, config.APP_PASSWORD
            ):
                return await call_next(request)

        return Response(
            status_code=401,
            content="Authentication required.",
            headers={"WWW-Authenticate": 'Basic realm="Anki Card Media Generator"'},
        )
