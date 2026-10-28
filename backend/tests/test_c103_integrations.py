"""C103 Pass 14, M5: what each external service can send back, and what we do with it."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import settings
from app.services import razorpay_client

# A 2xx is not a promise about the body. Each of these is valid JSON that a
# proxy or a degraded upstream can answer with; none of them is an order.
NOT_AN_ORDER = [b"[]", b'"ok"', b"null", b"42", b'{"error": {"code": "SERVER_ERROR"}}', b"<html>"]


@pytest.fixture()
def razorpay_on(monkeypatch):
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_test_secret")


def _answers(body: bytes, status: int = 200):
    def send(*args, **kwargs):
        request = httpx.Request("GET", "https://api.razorpay.com")
        return httpx.Response(status, content=body, request=request)

    return send


class TestRazorpayAnsweringWithSomethingThatIsNotAnOrder:
    @pytest.mark.parametrize("body", NOT_AN_ORDER)
    def test_create_order_is_a_retryable_502_not_a_500(self, auth_client, razorpay_on, body):
        with patch.object(httpx, "post", _answers(body)):
            response = auth_client.post("/api/v1/subscriptions/create-order", json={"tier": "pro"})
        assert response.status_code == 502

    @pytest.mark.parametrize("body", NOT_AN_ORDER)
    def test_verify_payment_is_a_retryable_502_not_a_500(self, auth_client, razorpay_on, body):
        with patch.object(httpx, "get", _answers(body)), patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_1",
                    "razorpay_payment_id": "pay_1",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert response.status_code in (400, 502)
        # 400 only for the error object, which is an order-shaped refusal;
        # everything that is not an object at all is the provider's fault.
        if body != b'{"error": {"code": "SERVER_ERROR"}}':
            assert response.status_code == 502

    @pytest.mark.parametrize("body", NOT_AN_ORDER)
    def test_the_report_purchase_is_a_502_too(
        self, auth_client, db_session, business, razorpay_on, body
    ):
        from tests.test_reconciliation_report import _run

        run = _run(db_session, business)
        with patch.object(httpx, "post", _answers(body)):
            response = auth_client.post(
                "/api/v1/reconciliation/report/purchase", json={"run_id": run.id}
            )
        assert response.status_code == 502

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_a_5xx_from_razorpay_is_a_502(self, auth_client, razorpay_on, status):
        with patch.object(httpx, "post", _answers(b"{}", status)):
            response = auth_client.post("/api/v1/subscriptions/create-order", json={"tier": "pro"})
        assert response.status_code == 502

    def test_a_timeout_is_a_502(self, auth_client, razorpay_on):
        def times_out(*args, **kwargs):
            raise httpx.ReadTimeout("timed out")

        with patch.object(httpx, "post", times_out):
            response = auth_client.post("/api/v1/subscriptions/create-order", json={"tier": "pro"})
        assert response.status_code == 502


class TestAnOrderIdIsShapedLikeOne:
    """The order id goes into the path of a request made with this server's
    Razorpay credentials; a "/" or ".." in it could aim that request elsewhere."""

    @pytest.mark.parametrize(
        "order_id", ["../payments/pay_x", "order_1/../../customers", "order_1?expand=x", "pay_1"]
    )
    def test_anything_else_is_refused_before_razorpay_is_asked(
        self, auth_client, razorpay_on, order_id
    ):
        with patch.object(httpx, "get") as fetched, patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": "pay_1",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 422
        fetched.assert_not_called()


# ---------------------------------------------------------------------------
# Gemini, behind the advisor
# ---------------------------------------------------------------------------

UNUSABLE_REPLIES = [
    {"candidates": [None]},
    {"candidates": ["text"]},
    {"candidates": [{"content": "text"}]},
    {"candidates": [{"content": {"parts": [None, "x"]}}]},
    {"candidates": [{"content": {"parts": [{"text": 5}]}}]},
    [],
    "a string",
    None,
]


def _ask(client, gemini_response):
    with (
        patch("app.routers.advisor._get_api_key", return_value="test-key"),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=gemini_response),
    ):
        return client.post("/api/v1/advisor/ask", json={"message": "What is GST?"})


class TestGeminiAnsweringWithSomethingUnusable:
    """Each of these raised out of the reply parser into the catch-all, which
    told the user "a problem on our side" and logged a traceback."""

    @pytest.mark.parametrize("body", UNUSABLE_REPLIES, ids=repr)
    def test_it_is_the_no_answer_502(self, client, body):
        response = _ask(client, httpx.Response(200, json=body))
        assert response.status_code == 502
        assert "produced no answer" in response.json()["detail"]

    def test_a_200_that_is_not_json_is_the_no_answer_502_too(self, client):
        response = _ask(client, httpx.Response(200, content=b"<html>Bad gateway</html>"))
        assert response.status_code == 502
        assert "produced no answer" in response.json()["detail"]

    def test_text_beside_junk_parts_is_still_the_answer(self, client):
        body = {"candidates": [{"content": {"parts": [None, {"text": "18%."}, {"text": 3}]}}]}
        response = _ask(client, httpx.Response(200, json=body))
        assert response.status_code == 200
        assert response.json()["reply"] == "18%."
