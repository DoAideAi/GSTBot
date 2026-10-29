"""The AI advisor proxy returns a model reply without exposing the API key."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest


class TestAdvisorAsk:

    def test_a_missing_api_key_is_a_503_that_says_it_is_not_set_up(self, client):
        """Not a 200 with an apology dressed as an answer: the chat could not
        tell it from a reply, and "temporarily" was untrue — it is a setup
        fault that waiting does not fix."""
        with patch("app.routers.advisor._get_api_key", return_value=None):
            response = client.post(
                "/api/v1/advisor/ask",
                json={"message": "What is GST?"},
            )
        assert response.status_code == 503
        assert "not set up" in response.json()["detail"]
        assert "reply" not in response.json()

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
        assert response.status_code == 502
        assert "having problems" in response.json()["detail"]

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
        assert response.status_code == 504
        assert "took too long" in response.json()["detail"]

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
        # Reached without a token: the answer is about the advisor, not auth.
        assert response.status_code not in (401, 403)

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
        assert response.status_code == 502
        assert "refused this question" in response.json()["detail"]

    def test_every_model_overloaded_returns_the_graceful_fallback(self, client):
        post = AsyncMock(return_value=httpx.Response(503, text="high demand"))

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", post),
        ):
            response = client.post("/api/v1/advisor/ask", json={"message": "Hello"})

        assert post.await_count > 1
        assert response.status_code == 503
        assert "overloaded" in response.json()["detail"]

    def test_a_reply_with_no_parts_is_not_returned_as_blank(self, client):
        blocked = httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=blocked),
        ):
            response = client.post("/api/v1/advisor/ask", json={"message": "Hello"})

        assert response.status_code == 502
        assert "no answer" in response.json()["detail"]

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
        payload = post.call_args.kwargs["json"]
        # System prompt moved to systemInstruction, no longer a conversation turn.
        assert "systemInstruction" in payload
        contents = payload["contents"]
        texts = [c["parts"][0]["text"] for c in contents]
        assert len(contents) == HISTORY_TURNS_SENT + 1
        assert texts[0] == f"turn {50 - HISTORY_TURNS_SENT}"
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
            response = client.post("/api/v1/advisor/ask", json={"message": "Hi"})
        assert response.status_code == 504
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

        with patch.object(advisor.settings, "gemini_api_key", ""):
            with patch.object(advisor.settings, "gemini_api_key_file", str(tmp_path / "absent")):
                assert advisor._get_api_key() is None
            assert not [r for r in caplog.records if "could not be read" in r.getMessage()]

            # A directory where the file should be: exists, cannot be read as text.
            with patch.object(advisor.settings, "gemini_api_key_file", str(tmp_path)):
                assert advisor._get_api_key() is None
        [line] = [r for r in caplog.records if "could not be read" in r.getMessage()]
        assert line.levelname == "ERROR"


def test_clients_for_closed_loops_are_not_kept():
    """GB082: the per-loop client map dropped nothing, so it grew by a client and
    a dead loop for every event loop the process ever ran."""
    import asyncio

    from app.routers import advisor

    advisor._clients.clear()

    async def touch():
        return advisor._client()

    for _ in range(5):
        asyncio.run(touch())
    # The last loop is closed too, but entries are pruned on the next call,
    # so at most one stale entry can be waiting.
    assert len(advisor._clients) <= 1

    async def touch_and_count():
        advisor._client()
        return len(advisor._clients)

    assert asyncio.run(touch_and_count()) == 1
    advisor._clients.clear()


# ---------------------------------------------------------------------------
# Streaming endpoint
# ---------------------------------------------------------------------------

def _sse_body(text_chunks: list[str]) -> bytes:
    """Fake SSE bytes like Gemini's ``streamGenerateContent?alt=sse``."""
    parts = []
    for chunk in text_chunks:
        data = json.dumps({"candidates": [{"content": {"parts": [{"text": chunk}]}}]})
        parts.append(f"data: {data}\n\n")
    return "".join(parts).encode()


class _FakeStreamResponse:
    """Stands in for ``httpx.Response`` from ``client.send(stream=True)``."""

    def __init__(self, status_code: int, body: bytes = b""):
        self.status_code = status_code
        self._body = body
        self._pos = 0

    async def aiter_lines(self):
        for line in self._body.decode().splitlines():
            yield line

    async def aread(self) -> bytes:
        return self._body

    async def aclose(self) -> None:
        pass


class TestAdvisorStream:

    def test_a_streamed_answer_arrives_as_sse_chunks(self, client):
        body = _sse_body(["GST ", "is ", "18%."])
        response_obj = _FakeStreamResponse(200, body)

        async def fake_send(self, req, *, stream=False):
            return response_obj

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            response = client.post(
                "/api/v1/advisor/ask/stream",
                json={"message": "What is the GST rate?"},
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [
            ln for ln in response.text.strip().split("\n") if ln.startswith("data: ")
        ]
        texts = [json.loads(ln[6:]).get("t") for ln in lines if "\"t\"" in ln]
        # Chunks keep their spacing: the model splits mid-sentence, and the
        # browser joins them as they come.
        assert texts == ["GST ", "is ", "18%."]
        assert "".join(texts) == "GST is 18%."
        assert any('"done": true' in ln or '"done":true' in ln for ln in lines)

    def test_a_missing_key_on_stream_is_a_503(self, client):
        with patch("app.routers.advisor._get_api_key", return_value=None):
            response = client.post(
                "/api/v1/advisor/ask/stream",
                json={"message": "Hello"},
            )
        assert response.status_code == 503

    def test_stream_falls_through_on_retryable_error(self, client):
        overloaded = _FakeStreamResponse(503, b"overloaded")
        ok_body = _sse_body(["ok"])
        ok_resp = _FakeStreamResponse(200, ok_body)
        responses = iter([overloaded, ok_resp])

        async def fake_send(self, req, *, stream=False):
            return next(responses)

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            response = client.post(
                "/api/v1/advisor/ask/stream",
                json={"message": "Hello"},
            )
        assert response.status_code == 200
        assert '"t": "ok"' in response.text or '"t":"ok"' in response.text

    def test_stream_all_models_fail_sends_error_event(self, client):
        fail = _FakeStreamResponse(503, b"overloaded")

        async def fake_send(self, req, *, stream=False):
            return fail

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            response = client.post(
                "/api/v1/advisor/ask/stream",
                json={"message": "Hello"},
            )
        assert response.status_code == 200
        assert '"error"' in response.text
        assert "overloaded" in response.text


class _CutOffStream(_FakeStreamResponse):
    """Sends its first chunk, then the connection to Gemini times out."""

    async def aiter_lines(self):
        for line in self._body.decode().splitlines():
            yield line
        raise httpx.ReadTimeout("read timed out")


def _events(response) -> list[dict]:
    return [
        json.loads(ln[6:]) for ln in response.text.split("\n") if ln.startswith("data: ")
    ]


class TestAdvisorStreamFailures:
    def test_a_stream_cut_off_midway_is_not_restarted_by_the_next_model(self, client):
        # Falling through would append a second answer, from its first word,
        # to the half of the first one the visitor is already reading.
        calls = []
        cut = _CutOffStream(200, _sse_body(["GST on laptops "]))

        async def fake_send(self, req, *, stream=False):
            calls.append(str(req.url))
            return cut

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            response = client.post("/api/v1/advisor/ask/stream", json={"message": "Laptops?"})

        events = _events(response)
        assert [e.get("t") for e in events if "t" in e] == ["GST on laptops "]
        assert events[-1] == {"error": "The answer was cut off. Ask again for the rest."}
        assert len(calls) == 1

    def test_an_empty_answer_tries_the_next_model_and_never_reports_done(self, client):
        empty = _FakeStreamResponse(200, b'data: {"candidates": [{"finishReason": "SAFETY"}]}\n\n')

        async def fake_send(self, req, *, stream=False):
            return empty

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            response = client.post("/api/v1/advisor/ask/stream", json={"message": "Hi"})

        events = _events(response)
        assert not any(e.get("done") for e in events)
        assert "error" in events[-1]

    def test_the_system_prompt_is_an_instruction_not_a_fake_turn(self, client):
        sent = {}

        async def fake_send(self, req, *, stream=False):
            sent.update(json.loads(req.content))
            return _FakeStreamResponse(200, _sse_body(["ok"]))

        history = [
            {"role": "assistant", "text": "Hello! Ask me about GST."},
            {"role": "user", "text": "Rate on gold?"},
            {"role": "assistant", "text": "3%."},
        ]
        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            client.post(
                "/api/v1/advisor/ask/stream", json={"message": "And silver?", "history": history}
            )

        assert sent["systemInstruction"]["parts"][0]["text"]
        roles = [c["role"] for c in sent["contents"]]
        # Gemini needs the first turn to be the user's: a leading model greeting is dropped.
        assert roles == ["user", "model", "user"]


class TestTheAdvisorBill:
    """Every question is a paid Gemini call. Without a key the endpoint answers
    503 once every limit has passed, so a 429 is a limit and a 503 is not."""

    @pytest.fixture()
    def tight(self, monkeypatch, rate_limited):
        from app.core.config import settings
        from app.core.ratespec import parse_rate
        from app.routers import advisor

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        monkeypatch.setattr(advisor._advisor_daily, "_rate", parse_rate("2/day"))
        monkeypatch.setattr(advisor._advisor_site_daily, "_rate", parse_rate("3/day"))
        monkeypatch.setattr(advisor, "_get_api_key", lambda: None)

    def _ask(self, client, ip, path="/api/v1/advisor/ask"):
        return client.post(path, json={"message": "GST on gold?"}, headers={"X-Real-IP": ip})

    def test_one_address_has_a_daily_allowance(self, client, tight):
        assert self._ask(client, "198.51.100.1").status_code == 503
        assert self._ask(client, "198.51.100.1", "/api/v1/advisor/ask/stream").status_code == 503
        refused = self._ask(client, "198.51.100.1")
        assert refused.status_code == 429
        assert "daily limit" in refused.json()["detail"]
        assert "Retry-After" in refused.headers

    def test_many_addresses_cannot_do_what_one_cannot(self, client, tight):
        for ip in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
            assert self._ask(client, ip).status_code == 503
        refused = self._ask(client, "198.51.100.4")
        assert refused.status_code == 429
        assert "as many questions as it can today" in refused.json()["detail"]

    def test_a_caller_refused_for_their_own_day_is_not_charged_to_everyone(self, client, tight):
        for _ in range(4):  # two answered, two refused for the address's own day
            self._ask(client, "198.51.100.1")
        assert self._ask(client, "198.51.100.2").status_code == 503


class TestKeyComesFromSettings:
    """M15: the key is read through Settings, so ``.env`` and the file path count."""

    def test_a_key_in_settings_is_used_without_any_environment_variable(self, tmp_path):
        from app.routers import advisor

        # Settings is what reads .env; a direct os.environ lookup never saw it.
        with (
            patch.dict("os.environ", {}, clear=False) as env,
            patch.object(advisor.settings, "gemini_api_key", " from-dotenv "),
        ):
            env.pop("GEMINI_API_KEY", None)
            assert advisor._get_api_key() == "from-dotenv"

    def test_the_key_file_path_is_configurable(self, tmp_path):
        from app.routers import advisor

        key_file = tmp_path / "gemini"
        key_file.write_text("from-file\n")
        with (
            patch.object(advisor.settings, "gemini_api_key", ""),
            patch.object(advisor.settings, "gemini_api_key_file", str(key_file)),
        ):
            assert advisor._get_api_key() == "from-file"

    def test_an_empty_key_file_setting_disables_the_fallback(self):
        from app.routers import advisor

        with (
            patch.object(advisor.settings, "gemini_api_key", ""),
            patch.object(advisor.settings, "gemini_api_key_file", ""),
        ):
            assert advisor._get_api_key() is None


class TestAnUnusualReplyStillSerialises:
    """P18 M5: ``json.loads`` accepts a lone ``\\ud800`` escape in Gemini's
    reply and returns an unpaired surrogate, which cannot be encoded to UTF-8 —
    the response failed to serialise and the user got a 500 for one bad
    character. A misbehaving upstream's 3 MB body was relayed whole."""

    def _ask(self, client, body: bytes):
        response = httpx.Response(200, content=body, headers={"content-type": "application/json"})
        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response),
        ):
            return client.post("/api/v1/advisor/ask", json={"message": "hi"})

    def test_a_lone_surrogate_becomes_a_replacement_character(self, raw_client):
        body = json.dumps(
            {"candidates": [{"content": {"parts": [{"text": "GST \ud800 is 18%"}]}}]}
        ).encode()
        response = self._ask(raw_client, body)
        assert response.status_code == 200
        assert response.json()["reply"] == "GST � is 18%"

    def test_an_oversized_reply_is_cut_to_the_ceiling(self, client):
        from app.routers.advisor import MAX_REPLY_CHARS

        body = json.dumps(
            {"candidates": [{"content": {"parts": [{"text": "A" * (MAX_REPLY_CHARS * 3)}]}}]}
        ).encode()
        response = self._ask(client, body)
        assert response.status_code == 200
        assert len(response.json()["reply"]) == MAX_REPLY_CHARS


class TestAStreamThatWillNotStop:
    """P22 M5: the per-chunk read timeout never trips for an upstream that keeps
    sending, and the stream had no other bound — a whole reply was capped at
    MAX_REPLY_CHARS, a streamed one relayed every chunk for as long as they
    came."""

    def _stream(self, client, response_obj):
        async def fake_send(self, req, *, stream=False):
            return response_obj

        with (
            patch("app.routers.advisor._get_api_key", return_value="test-key"),
            patch("httpx.AsyncClient.send", new=fake_send),
        ):
            return client.post("/api/v1/advisor/ask/stream", json={"message": "Hi"})

    def test_the_text_sent_is_capped_like_a_whole_reply(self, client):
        from app.routers import advisor

        chunk = "x" * 1000
        count = advisor.MAX_REPLY_CHARS // 1000 + 20
        events = _events(self._stream(client, _FakeStreamResponse(200, _sse_body([chunk] * count))))
        sent = "".join(e.get("t", "") for e in events)
        assert len(sent) == advisor.MAX_REPLY_CHARS
        assert events[-1] == {"done": True}

    def test_lines_carrying_no_text_are_bounded_too(self, client, monkeypatch):
        from app.routers import advisor

        monkeypatch.setattr(advisor, "_MAX_STREAM_RAW_CHARS", 5_000)
        body = _sse_body(["first "]) + b": keepalive " + b"y" * 200 + b"\n" * 1
        body += (b": " + b"z" * 200 + b"\n") * 100  # comments, no data, forever
        events = _events(self._stream(client, _FakeStreamResponse(200, body)))
        assert events[0] == {"t": "first "}
        assert "error" in events[-1] and "cut off" in events[-1]["error"]

    def test_a_stream_past_its_deadline_is_ended(self, client, monkeypatch):
        from app.routers import advisor

        monkeypatch.setattr(advisor, "_STREAM_DEADLINE_S", -1.0)
        events = _events(self._stream(client, _FakeStreamResponse(200, _sse_body(["late"]))))
        assert events == [
            {"error": "The AI advisor could not answer just now. Try again in a minute."}
        ]


class TestAConversationTheBrowserKeptBadly:
    """P22 M2/M3: the history is whatever the browser kept. A question whose
    answer failed stays with no reply, a cut-off answer leaves a partial bubble
    and an empty one can be left behind. Gemini refuses a turn with no text,
    so one blank bubble made every later question in the conversation fail."""

    def _contents(self, history, message="Next question?"):
        from app.routers.advisor import HistoryMessage, _build_contents

        return _build_contents([HistoryMessage(**m) for m in history], message)

    def test_blank_turns_are_dropped(self):
        contents = self._contents(
            [
                {"role": "user", "text": "What is ITC?"},
                {"role": "assistant", "text": ""},
                {"role": "assistant", "text": "   "},
            ]
        )
        assert all(c["parts"][0]["text"].strip() for c in contents)

    def test_the_turns_always_alternate_and_start_with_the_user(self):
        contents = self._contents(
            [
                {"role": "assistant", "text": "Hello!"},
                {"role": "user", "text": "First, unanswered"},
                {"role": "user", "text": "Second"},
                {"role": "assistant", "text": "Partial answer"},
                {"role": "assistant", "text": "It was cut off"},
            ]
        )
        roles = [c["role"] for c in contents]
        assert roles == ["user", "model", "user"]
        assert contents[0]["parts"][0]["text"] == "First, unanswered\n\nSecond"
        assert contents[1]["parts"][0]["text"] == "Partial answer\n\nIt was cut off"

    def test_a_question_after_an_unanswered_one_is_one_user_turn(self):
        contents = self._contents([{"role": "user", "text": "Unanswered?"}], "Again?")
        assert contents == [{"role": "user", "parts": [{"text": "Unanswered?\n\nAgain?"}]}]
