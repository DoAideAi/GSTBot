"""Starting an OAuth sign-in while the provider cannot be reached.

Google and Microsoft are registered by discovery URL, so the first step of a
sign-in fetches the provider's metadata. With the provider unreachable that
used to surface as a JSON 500 in the browser tab; it now sends the user back
to the login page with an error code, as the callbacks already do.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.core.config import settings
from app.routers import oauth as oauth_router


class _Unreachable:
    async def authorize_redirect(self, request, redirect_uri):
        raise httpx.ConnectError("accounts.google.com: Temporary failure in name resolution")


@pytest.mark.parametrize("provider", ["google", "github", "microsoft"])
def test_an_unreachable_provider_sends_the_user_back_to_login(client, provider):
    with (
        patch.object(settings, f"{provider}_client_id", "test-id"),
        patch.object(oauth_router.oauth, "create_client", return_value=_Unreachable()),
    ):
        response = client.get(f"/api/v1/auth/{provider}", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith(f"/login?error={provider}_auth_failed")


def test_an_unconfigured_provider_is_still_a_501(client):
    with patch.object(settings, "google_client_id", ""):
        assert client.get("/api/v1/auth/google").status_code == 501
