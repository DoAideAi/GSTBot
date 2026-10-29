"""Uploading the statement already on file is not an import.

``store_gstr2b`` returns the record already on file when the same statement
comes in again, storing nothing. The route still answered 201 Created with
``replaced_previous: true`` and "Imported N invoices for … (replacing the
previous import)" — the message the reconcile page shows. A client was told a
replacement happened, which is the cue to re-run the reconciliation, for an
upload that changed nothing.
"""
from __future__ import annotations

import json

from tests.test_gstr2b import portal_json
from tests.test_reconciliation import upload_2b


def test_the_same_statement_again_is_200_and_says_nothing_changed(auth_client, paid_business):
    body = json.dumps(portal_json()).encode()
    first = upload_2b(auth_client, content=body)
    assert first.status_code == 201, first.text
    assert first.json()["replaced_previous"] is False
    assert first.json()["unchanged"] is False

    again = upload_2b(auth_client, content=body)

    assert again.status_code == 200, again.text
    payload = again.json()
    assert payload["id"] == first.json()["id"]
    assert payload["unchanged"] is True
    assert payload["replaced_previous"] is False
    assert "replacing" not in payload["message"]
    assert "already" in payload["message"].lower()


def test_a_different_statement_still_replaces_with_201(auth_client, paid_business):
    upload_2b(auth_client, content=json.dumps(portal_json()).encode())
    changed = portal_json()
    changed["data"]["docdata"]["b2b"][0]["inv"][0]["val"] = 999999
    response = upload_2b(auth_client, content=json.dumps(changed).encode())
    assert response.status_code == 201, response.text
    assert response.json()["replaced_previous"] is True
    assert response.json()["unchanged"] is False


def test_both_answers_are_in_the_spec(auth_client):
    op = auth_client.get("/openapi.json").json()["paths"][
        "/api/v1/reconciliation/gstr2b/import"
    ]["post"]
    assert {"200", "201"} <= set(op["responses"])
