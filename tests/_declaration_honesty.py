"""ASGI plumbing for suite-wide declaration honesty. The contract knowledge
lives in `error_contract.assert_declared_mode`; this shim only intercepts
responses and hands complete bodies to it.

See `docs/architecture.md` ("How errors become HTTP status codes").
"""

from typing import Any

from a11y_health.core.error_contract import FRAMEWORK_STATUSES, assert_declared_mode


class DeclarationHonestyShim:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        pending_status: int | None = None
        body = b""

        async def send_wrapper(message: Any) -> None:
            nonlocal pending_status, body
            route = scope.get("route")
            if message["type"] == "http.response.start":
                status = message["status"]
                if 400 <= status < 500 and status not in FRAMEWORK_STATUSES and route is not None:
                    pending_status = status
            elif message["type"] == "http.response.body" and pending_status is not None:
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    assert_declared_mode(scope["method"], scope["path"], route, pending_status, body)
                    pending_status = None
                    body = b""
            await send(message)

        await self.inner(scope, receive, send_wrapper)
