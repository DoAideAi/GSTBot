"""The security headers every API response carries, defined once.

Two places put them on a response, and they cannot share a code path:

* ``SecurityHeadersMiddleware`` (``app.core.middleware``) adds them on the way
  out of every request the user middleware sees.
* The bare-``Exception`` handler in ``app.core.errors`` builds its 500 inside
  Starlette's outermost ``ServerErrorMiddleware``, which no user middleware
  runs after — so it has to set them itself.

They used to be a private class attribute on the middleware, which the error
handler reached into (``SecurityHeadersMiddleware._BASE``) with an import
deferred into the function, because ``middleware`` imports ``errors`` for
``error_body`` and a top-level import the other way was a cycle. That handler
also built its own CSP and left out HSTS, so the one response that most needs
hardening was the one served without it when HSTS is on.

Depends on nothing but settings, so either module can import it at the top.
"""
from __future__ import annotations

from app.core.config import settings

BASE_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": (
        "geolocation=(), microphone=(), camera=(), payment=(), "
        "interest-cohort=(), browsing-topics=()"
    ),
    "Cache-Control": "no-store",
}

# Strict because this is an API: nothing it serves should ever be rendered, and
# ``default-src 'none'`` means a stored value reflected into an error page
# cannot execute.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

HSTS = "max-age=31536000; includeSubDomains"


def security_headers(*, csp: bool = True) -> dict[str, str]:
    """The headers for one response.

    ``csp=False`` is for the docs pages, which load Swagger UI's own bundle.
    HSTS only where TLS is actually terminated in front of us; sending it from
    a plain-HTTP dev server would pin a developer's browser.
    """
    headers = dict(BASE_SECURITY_HEADERS)
    if csp:
        headers["Content-Security-Policy"] = API_CSP
    if settings.hsts_enabled:
        headers["Strict-Transport-Security"] = HSTS
    return headers


__all__ = ["API_CSP", "BASE_SECURITY_HEADERS", "HSTS", "security_headers"]
