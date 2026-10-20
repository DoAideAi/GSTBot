"""GSTIN parsing, validation and the tax split that follows from it.

A GSTIN is 15 characters: ``27AAPFU0939F1ZV``.

===========  ==========================================================
Position     Meaning
===========  ==========================================================
1-2          State code (01-38, plus 97 "other territory" and 99 "centre")
3-12         PAN of the registered entity
13           Entity/registration number for that PAN in that state (1-9, A-Z)
14           Always ``Z`` (reserved by the GST design)
15           Check digit, base-36 weighted mod-36
===========  ==========================================================

The check digit matters more than it looks: a transposed character in a
supplier GSTIN is the single most common cause of a purchase invoice failing to
match anything in GSTR-2B, and it is silent — the invoice just shows up as
"missing at the supplier's end" and the ITC on it goes unclaimed. Validating at
ingest turns that into an error the user can fix while the paper is still in
their hand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The check-digit alphabet, in value order: '0'-'9' are 0-9, 'A'-'Z' are 10-35.
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# Loose pattern for pulling candidate GSTINs out of free-form invoice text,
# where they may be surrounded by punctuation or a "GSTIN:" label.
GSTIN_SCAN_PATTERN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")

# State code -> state/UT name. Codes are assigned by the GST Council; 97 and 99
# are the two non-state codes.
STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (before division)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}


class InvalidGSTIN(ValueError):
    """Raised when a string is not a well-formed, checksum-valid GSTIN."""


@dataclass(frozen=True)
class GSTINParts:
    """The fields a GSTIN encodes, once it has been validated."""

    gstin: str
    state_code: str
    state_name: str
    pan: str
    entity_number: str
    check_digit: str


def normalize(gstin: str) -> str:
    """Upper-case and strip separators, without judging the result.

    Users paste GSTINs out of PDFs and spreadsheets, where they routinely
    arrive as ``27 AAPFU0939F 1ZV`` or ``27-aapfu0939f1zv``.
    """
    return re.sub(r"[\s\-]", "", (gstin or "")).upper()


def compute_check_digit(first14: str) -> str:
    """Return the check digit for the first 14 characters of a GSTIN.

    Base-36 weighted mod-36: each character's value is multiplied by an
    alternating 1/2 factor, the quotient and remainder of that product over 36
    are both added to a running total, and the check digit is whatever brings
    the total to a multiple of 36.
    """
    if len(first14) != 14:
        raise InvalidGSTIN("GSTIN body must be exactly 14 characters")
    total = 0
    for index, char in enumerate(first14):
        value = _ALPHABET.find(char)
        if value < 0:
            raise InvalidGSTIN(f"Invalid character {char!r} in GSTIN")
        product = value * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def is_valid(gstin: str) -> bool:
    """True when *gstin* is well-formed, in a known state, and checksums."""
    try:
        parse(gstin)
    except InvalidGSTIN:
        return False
    return True


def parse(gstin: str) -> GSTINParts:
    """Validate *gstin* and return its parts, or raise :class:`InvalidGSTIN`."""
    candidate = normalize(gstin)
    if len(candidate) != 15:
        raise InvalidGSTIN("GSTIN must be 15 characters")
    if not GSTIN_PATTERN.match(candidate):
        raise InvalidGSTIN("GSTIN format is invalid")
    state_code = candidate[:2]
    if state_code not in STATE_CODES:
        raise InvalidGSTIN(f"Unknown state code {state_code!r}")
    if compute_check_digit(candidate[:14]) != candidate[14]:
        raise InvalidGSTIN("GSTIN check digit does not match")
    return GSTINParts(
        gstin=candidate,
        state_code=state_code,
        state_name=STATE_CODES[state_code],
        pan=candidate[2:12],
        entity_number=candidate[12],
        check_digit=candidate[14],
    )


def state_code_of(gstin: str) -> str | None:
    """The state code of a valid GSTIN, or ``None`` if it does not validate."""
    try:
        return parse(gstin).state_code
    except InvalidGSTIN:
        return None


# The fourth character of a PAN says what kind of person holds it. A GSTIN
# embeds the PAN, so a valid GSTIN answers "is my supplier a company or a
# proprietor?" without a portal lookup — which is the question a buyer asking
# about TDS, reverse charge or composition eligibility usually has.
PAN_ENTITY_TYPES: dict[str, str] = {
    "P": "Individual / Proprietor",
    "C": "Company",
    "H": "Hindu Undivided Family (HUF)",
    "F": "Firm / LLP",
    "A": "Association of Persons (AOP)",
    "T": "Trust",
    "B": "Body of Individuals (BOI)",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "G": "Government",
}


def entity_type(pan: str) -> str | None:
    """What kind of holder *pan* belongs to, or ``None`` for an unassigned letter."""
    return PAN_ENTITY_TYPES.get(pan[3:4])


def find_gstins(text: str) -> list[str]:
    """Every checksum-valid GSTIN in *text*, in order, de-duplicated.

    Used by the heuristic invoice parser and as a sanity check on what the
    model extracted. Candidates that match the shape but fail the check digit
    are dropped — on an invoice, a near-miss is OCR noise far more often than
    it is a real GSTIN.
    """
    # Upper-cased but *not* run through :func:`normalize`: that strips spaces,
    # which is right for one field and wrong for a document — it welds
    # neighbouring words onto the GSTIN and destroys the word boundaries the
    # scan pattern anchors on.
    seen: list[str] = []
    for match in GSTIN_SCAN_PATTERN.finditer((text or "").upper()):
        candidate = match.group(0)
        if is_valid(candidate) and candidate not in seen:
            seen.append(candidate)
    return seen


def is_interstate(supplier_gstin: str | None, buyer_gstin: str | None) -> bool | None:
    """Whether a supply between these two parties crosses a state border.

    Returns ``None`` when either side is unknown or invalid, because "we cannot
    tell" and "same state" must not collapse into one answer: the first should
    leave the tax split alone, and the second actively sets it to CGST+SGST.
    """
    supplier_state = state_code_of(supplier_gstin or "")
    buyer_state = state_code_of(buyer_gstin or "")
    if supplier_state is None or buyer_state is None:
        return None
    return supplier_state != buyer_state
