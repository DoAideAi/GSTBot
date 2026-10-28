"""C103 Pass 14, M6: inputs written to break an assumption, at each surface that takes them."""
from __future__ import annotations

import xml.dom.minidom

import pytest

WHATSAPP = "/api/v1/whatsapp/webhook"


def _twiml_message(response) -> str:
    """The reply text, after proving the body is a well-formed TwiML document
    with exactly one message — what Twilio needs to deliver anything at all."""
    document = xml.dom.minidom.parseString(response.content)
    messages = document.getElementsByTagName("Message")
    assert len(messages) == 1
    return "".join(node.data for node in messages[0].childNodes)


def _send(client, body: str):
    return client.post(WHATSAPP, data={"From": "whatsapp:+919800000000", "Body": body})


class TestWhatsappRepliesStayDeliverable:
    @pytest.mark.parametrize(
        "body",
        ["\x00\x01\x02\x7f", "hsn \x0b\x0c\x1b[31mred", "gst \x08 18% on 1000", "￾￿"],
        ids=["c0 controls", "escape sequence", "backspace", "non-characters"],
    )
    def test_control_characters_do_not_break_the_xml(self, client, body):
        """They were echoed into the TwiML, which then was not XML."""
        response = _send(client, body)
        assert response.status_code == 200
        _twiml_message(response)

    def test_a_huge_message_gets_a_reply_twilio_will_send(self, client):
        """A 100 KB message was echoed into a 100 KB reply; Twilio refuses any
        body over 1,600 characters, so the user got nothing."""
        reply = _twiml_message(_send(client, "hsn " + "A" * 100_000))
        assert len(reply) <= 1600

    @pytest.mark.parametrize(
        "body",
        [
            "</Message><Message>pwned</Message>",
            "]]><x>",
            "&amp; &lt;script&gt;",
            "<script>alert(1)</script>",
        ],
    )
    def test_markup_in_the_message_stays_text(self, client, body):
        """One Message element, whatever the text tried to close or open."""
        _twiml_message(_send(client, body))

    def test_emoji_sequences_survive(self, client):
        assert _send(client, "👨‍👩‍👧‍👦" * 200).status_code == 200

    def test_a_query_with_newlines_is_still_understood(self, client):
        reply = _twiml_message(_send(client, "gstin\n27AAPFU0939F1ZV"))
        assert "27AAPFU0939F1ZV" in reply
