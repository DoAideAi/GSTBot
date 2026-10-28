"""M19 — input validation: what each endpoint refuses before it does any work.

Every test sends a value a client can actually produce and pins the refusal
it gets — a 4xx naming the field — rather than whatever the value would
otherwise have done further in.
"""
from __future__ import annotations

import pytest

from app.core.params import MAX_ID
from tests.conftest import make_paid

# -----------------------------------------------------------------------
# Row ids in a JSON body are bounded like row ids in a path
# -----------------------------------------------------------------------

_VERIFY = {
    "razorpay_order_id": "order_ABC",
    "razorpay_payment_id": "pay_ABC",
    "razorpay_signature": "sig",
}


class TestReportRunIdsAreBounded:
    """``run_id`` was ``ge=1`` and nothing above it. A value wider than the
    column raised ``OverflowError`` out of the database driver, which no
    handler turns into a response: a 500 from a field in a JSON body.
    """

    @pytest.fixture()
    def client(self, raw_client, auth_client, db_session, business):
        make_paid(db_session, business.id)
        raw_client.headers.update(auth_client.headers)
        return raw_client

    @pytest.mark.parametrize("run_id", [10**20, MAX_ID + 1])
    def test_a_purchase_for_a_run_id_wider_than_the_column_is_a_422(self, client, run_id):
        response = client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run_id})
        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["loc"] == ["body", "run_id"]

    @pytest.mark.parametrize("run_id", [10**20, MAX_ID + 1])
    def test_a_verification_for_a_run_id_wider_than_the_column_is_a_422(self, client, run_id):
        response = client.post(
            "/api/v1/reconciliation/report/verify", json={"run_id": run_id, **_VERIFY}
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["loc"] == ["body", "run_id"]

    def test_the_largest_id_the_column_holds_is_still_looked_up(self, client):
        # The ceiling is the column's, not a guess below it: this id is one a
        # row could carry, so it gets the ordinary not-found answer.
        response = client.post("/api/v1/reconciliation/report/purchase", json={"run_id": MAX_ID})
        assert response.status_code == 404, response.text

    @pytest.mark.parametrize("run_id", [0, -1])
    def test_an_id_below_the_sequence_is_still_refused(self, client, run_id):
        response = client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run_id})
        assert response.status_code == 422
