"""The AI advisor proxy returns a model reply without exposing the API key."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx


class TestAdvisorAsk:

    def test_a_missing_api_key_returns_a_graceful_fallback(self, client):
        with patch("app.routers.advisor._get_api_key", return_value=None):
            response = client.post(
                "/api/v1/advisor/ask",
                json={"message": "What is GST?"},
            )
        assert response.status_code == 200
        assert "unavailable" in response.json()["reply"].lower()

    def test_a_successful_gemini_call_returns_the_reply(self, client):
        gemini_body = {
            "candidates": [
                {"content": {"parts": [{"text": "GST is 18% for IT services."}]}}
            ]
        }
        mock_response = httpx.Response(200, json=gemini_body)

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        ):
            response = client.post(
                "/api/v1/advisor/ask",
                json={"message": "What is the GST rate for IT?"},
            )
        assert response.status_code == 200
        assert response.json()["reply"] == "GST is 18% for IT services."

    def test_conversation_history_is_accepted(self, client):
        gemini_body = {
            "candidates": [
                {"content": {"parts": [{"text": "Yes, 18%."}]}}
            ]
        }
        mock_response = httpx.Response(200, json=gemini_body)

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        ):
            response = client.post(
                "/api/v1/advisor/ask",
                json={
                    "message": "Are you sure?",
                    "history": [
                        {"role": "user", "text": "What is the GST rate for IT?"},
                        {"role": "assistant", "text": "It is 18%."},
                    ],
                },
            )
        assert response.status_code == 200
        assert response.json()["reply"] == "Yes, 18%."

    def test_a_gemini_error_returns_a_graceful_fallback(self, client):
        mock_response = httpx.Response(500, text="Internal Server Error")

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response),
        ):
            response = client.post(
                "/api/v1/advisor/ask",
                json={"message": "Hello"},
            )
        assert response.status_code == 200
        assert "could not generate" in response.json()["reply"].lower()

    def test_a_timeout_returns_a_graceful_fallback(self, client):
        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch(
                "httpx.AsyncClient.post",
                new_callable=AsyncMock,
                side_effect=httpx.TimeoutException("timed out"),
            ),
        ):
            response = client.post(
                "/api/v1/advisor/ask",
                json={"message": "Hello"},
            )
        assert response.status_code == 200
        assert "timed out" in response.json()["reply"].lower()

    def test_an_empty_message_is_refused(self, client):
        response = client.post(
            "/api/v1/advisor/ask",
            json={"message": ""},
        )
        assert response.status_code == 422

    def test_a_missing_message_is_refused(self, client):
        response = client.post(
            "/api/v1/advisor/ask",
            json={},
        )
        assert response.status_code == 422

    def test_the_endpoint_does_not_require_authentication(self, raw_client):
        with patch("app.routers.advisor._get_api_key", return_value=None):
            response = raw_client.post(
                "/api/v1/advisor/ask",
                json={"message": "What is GST?"},
            )
        assert response.status_code == 200

    def test_an_overloaded_model_falls_through_to_the_next_one(self, client):
        overloaded = httpx.Response(503, text="high demand")
        answered = httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "18%."}]}}]}
        )
        post = AsyncMock(side_effect=[overloaded, answered])

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", post),
        ):
            response = client.post("/api/v1/advisor/ask", json={"message": "Phones?"})

        assert response.json()["reply"] == "18%."
        first, second = (call.args[0] for call in post.call_args_list)
        assert first != second

    def test_a_bad_request_is_not_retried_on_another_model(self, client):
        post = AsyncMock(return_value=httpx.Response(400, text="bad"))

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", post),
        ):
            response = client.post("/api/v1/advisor/ask", json={"message": "Hello"})

        assert post.await_count == 1
        assert "could not generate" in response.json()["reply"].lower()

    def test_every_model_overloaded_returns_the_graceful_fallback(self, client):
        post = AsyncMock(return_value=httpx.Response(503, text="high demand"))

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", post),
        ):
            response = client.post("/api/v1/advisor/ask", json={"message": "Hello"})

        assert post.await_count > 1
        assert "could not generate" in response.json()["reply"].lower()

    def test_a_reply_with_no_parts_is_not_returned_as_blank(self, client):
        blocked = httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=blocked),
        ):
            response = client.post("/api/v1/advisor/ask", json={"message": "Hello"})

        assert "could not generate" in response.json()["reply"].lower()

    def test_the_api_key_is_sent_in_a_header_not_the_url(self, client):
        post = AsyncMock(
            return_value=httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            )
        )

        with (
            patch("app.routers.advisor._get_api_key", return_value="secret-key"),
            patch("httpx.AsyncClient.post", post),
        ):
            client.post("/api/v1/advisor/ask", json={"message": "Hello"})

        call = post.call_args
        assert "secret-key" not in call.args[0]
        assert "params" not in call.kwargs
        assert call.kwargs["headers"]["x-goog-api-key"] == "secret-key"
