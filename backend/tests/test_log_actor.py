"""Every line a request logs says who it acted as (P24 M16).

The access line named the login, the business acted for and the role, and it is
the only audit trail the product keeps; the lines saying what happened, such as
"Filing withdrawn" and "Invoice deleted", named the business alone, so who
withdrew a return took a join by correlation id inside the journal's few days.
"""
from __future__ import annotations

import logging

from tests.conftest import SAMPLE_INVOICE_TEXT


def _upload(client):
    return client.post(
        "/api/v1/invoices/upload",
        files={"file": ("a.txt", SAMPLE_INVOICE_TEXT.encode(), "text/plain")},
        data={"invoice_type": "purchase"},
    ).json()["invoice"]


def test_a_service_line_names_the_login_the_business_and_the_role(
    auth_client, business, caplog
):
    invoice = _upload(auth_client)
    with caplog.at_level(logging.INFO):
        assert auth_client.delete(f"/api/v1/invoices/{invoice['id']}").status_code == 204
    (deleted,) = [r for r in caplog.records if r.getMessage().startswith("Invoice deleted")]
    assert deleted.business_id == business.id
    assert deleted.user_id == business.users[0].id
    assert deleted.role == "owner"


def test_a_line_that_names_its_own_business_keeps_it(auth_client, caplog):
    from app.core.logging import note_actor

    logger = logging.getLogger("app.test")
    with caplog.at_level(logging.INFO):
        note_actor(business_id=999)  # outside a request: nothing to record into
        logger.info("explicit", extra={"business_id": 7})
    (record,) = [r for r in caplog.records if r.getMessage() == "explicit"]
    assert record.business_id == 7


def test_nothing_leaks_from_one_request_into_the_next(auth_client, client, caplog):
    _upload(auth_client)
    auth_client.headers.pop("Authorization")
    caplog.clear()  # the upload's own lines rightly carry its user
    with caplog.at_level(logging.INFO):
        client.get("/api/v1/no-such-route")  # logs a rejection and an access line
    lines = [r for r in caplog.records if r.name.startswith("app")]
    assert lines and not [r for r in lines if hasattr(r, "user_id")]
