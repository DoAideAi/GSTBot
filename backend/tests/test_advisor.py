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


class TestAdvisorLatency:
    """The two things that made each reply slower than it had to be."""

    def _ok(self):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    def test_one_pooled_client_serves_every_question(self, client):
        """A client per request was a fresh TCP + TLS handshake to Google each time."""
        from app.routers import advisor

        seen = []

        ok = self._ok()

        async def fake_post(self, *args, **kwargs):
            seen.append(id(self))
            return ok

        with (
            patch("app.routers.advisor._get_api_key", return_value="k"),
            patch("httpx.AsyncClient.post", new=fake_post),
        ):
            for _ in range(3):
                assert client.post("/api/v1/advisor/ask", json={"message": "Hi"}).status_code == 200
        assert len(seen) == 3
        assert len(set(seen)) == 1
        assert advisor._clients

    def test_only_the_recent_turns_are_forwarded(self, client):
        from app.routers.advisor import HISTORY_TURNS_SENT

        history = [
            {"role": "user" if i % 2 == 0 else "model", "text": f"turn {i}"} for i in range(50)
        ]
        with (
            patch("app.routers.advisor._get_api_key", return_value="k"),
            patch(
                "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=self._ok()
            ) as post,
        ):
            response = client.post(
                "/api/v1/advisor/ask", json={"message": "latest", "history": history}
            )
        assert response.status_code == 200
        contents = post.call_args.kwargs["json"]["contents"]
        texts = [c["parts"][0]["text"] for c in contents]
        # System prompt + its acknowledgement, the recent turns, then the question.
        assert len(contents) == 2 + HISTORY_TURNS_SENT + 1
        assert texts[2] == f"turn {50 - HISTORY_TURNS_SENT}"
        assert texts[-2] == "turn 49"
        assert texts[-1] == "latest"
        assert "turn 0" not in texts

    def test_shutdown_closes_the_pooled_clients(self):
        import asyncio

        from app.routers import advisor

        async def run():
            created = advisor._client()
            assert advisor._client() is created
            await advisor.close_clients()
            assert created.is_closed
            assert advisor._clients == {}

        asyncio.run(run())

    def test_a_client_that_fails_to_close_does_not_fail_shutdown(self):
        import asyncio

        from app.routers import advisor

        class Broken:
            async def aclose(self):
                raise RuntimeError("socket already gone")

        async def run():
            advisor._clients[asyncio.get_running_loop()] = Broken()
            await advisor.close_clients()
            assert advisor._clients == {}

        asyncio.run(run())


class TestAdvisorLeavesARecord:
    """Every outcome of a question is a log line: the user only ever sees a
    polite sentence, so the log is the only place the cause is written down."""

    def _ok(self):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    def test_an_answer_records_the_model_and_how_long_it_took(self, client, caplog):
        import logging

        with (
            patch("app.routers.advisor._get_api_key", return_value="k"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=self._ok()),
            caplog.at_level(logging.INFO, logger="app.routers.advisor"),
        ):
            client.post("/api/v1/advisor/ask", json={"message": "Hi"})
        [line] = [r for r in caplog.records if r.getMessage() == "Advisor answered"]
        assert line.model == "gemini-3.8-flash"
        assert line.attempt == 1
        assert line.duration_ms >= 0

    def test_a_timeout_is_logged_with_the_model(self, client, caplog):
        with (
            patch("app.routers.advisor._get_api_key", return_value="k"),
            patch(
                "httpx.AsyncClient.post",
                new_callable=AsyncMock,
                side_effect=httpx.ReadTimeout("slow"),
            ),
        ):
            reply = client.post("/api/v1/advisor/ask", json={"message": "Hi"}).json()["reply"]
        assert "timed out" in reply
        [line] = [r for r in caplog.records if "timed out" in r.getMessage()]
        assert line.levelname == "WARNING"
        assert line.model == "gemini-3.8-flash"

    def test_running_out_of_models_is_an_error(self, client, caplog):
        overloaded = httpx.Response(503, text="overloaded")
        with (
            patch("app.routers.advisor._get_api_key", return_value="k"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=overloaded),
        ):
            client.post("/api/v1/advisor/ask", json={"message": "Hi"})
        [line] = [r for r in caplog.records if "no Gemini model accepted" in r.getMessage()]
        assert line.levelname == "ERROR"
        assert line.last_status == 503

    def test_a_missing_key_is_reported_once_not_per_question(self, client, caplog):
        from app.routers import advisor

        advisor._reported_missing_key = False
        with patch("app.routers.advisor._get_api_key", return_value=None):
            for _ in range(3):
                client.post("/api/v1/advisor/ask", json={"message": "Hi"})
        lines = [r for r in caplog.records if "no Gemini API key" in r.getMessage()]
        assert len(lines) == 1
        assert lines[0].levelname == "ERROR"

    def test_an_unreadable_key_file_is_an_error_and_an_absent_one_is_not(self, caplog, tmp_path):
        from app.routers import advisor

        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with patch.object(advisor, "_KEY_FILE", tmp_path / "absent"):
                assert advisor._get_api_key() is None
            assert not [r for r in caplog.records if "could not be read" in r.getMessage()]

            # A directory where the file should be: exists, cannot be read as text.
            with patch.object(advisor, "_KEY_FILE", tmp_path):
                assert advisor._get_api_key() is None
        [line] = [r for r in caplog.records if "could not be read" in r.getMessage()]
        assert line.levelname == "ERROR"
