"""
Request ids for traceability (BRD §9: "include request_id/correlation_id").

Every HTTP request gets an id: the caller's X-Request-ID header if it sent
one, otherwise a new UUID. The id is:
  * available to route code as `request.state.request_id`,
  * stored in audit_events.request_id for admin actions,
  * returned in the X-Request-ID response header,
so one id links a user's complaint, the server logs and the audit trail.
"""

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HEADER = "X-Request-ID"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(HEADER, "")
        request_id = incoming if _SAFE.match(incoming) else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)
