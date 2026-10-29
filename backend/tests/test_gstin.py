"""GSTIN validation — the check every other correctness claim rests on."""
from __future__ import annotations

import pytest

from app.services import gstin as gstin_service
from tests.conftest import (
    BUSINESS_GSTIN,
    SUPPLIER_GSTIN_OTHER_STATE,
    SUPPLIER_GSTIN_SAME_STATE,
)

VALID = [BUSINESS_GSTIN, SUPPLIER_GSTIN_SAME_STATE, SUPPLIER_GSTIN_OTHER_STATE]


@pytest.mark.parametrize("gstin", VALID)
def test_valid_gstins_parse(gstin):
    parts = gstin_service.parse(gstin)
    assert parts.gstin == gstin
    assert parts.state_code == gstin[:2]
    assert parts.pan == gstin[2:12]
    assert parts.check_digit == gstin[14]


def test_state_name_is_resolved():
    assert gstin_service.parse(BUSINESS_GSTIN).state_name == "Maharashtra"
    assert gstin_service.parse(SUPPLIER_GSTIN_OTHER_STATE).state_name == "Karnataka"


def test_normalize_strips_separators_and_upcases():
    assert gstin_service.normalize(" 27aapfu0939f 1zv ") == BUSINESS_GSTIN
    assert gstin_service.normalize("27-AAPFU0939F-1ZV") == BUSINESS_GSTIN


def test_normalized_input_still_validates():
    assert gstin_service.is_valid("27 aapfu0939f 1zv")


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ("", "empty"),
        ("27AAPFU0939F1Z", "too short"),
        ("27AAPFU0939F1ZVX", "too long"),
        ("27AAPFU0939F1ZW", "wrong check digit"),
        ("00AAPFU0939F1ZV", "state code 00 does not exist"),
        ("40AAPFU0939F1ZV", "state code 40 is unassigned"),
        ("27AAPFU0939F1AV", "14th character must be Z"),
        ("2AAPFU0939F1ZVV", "state code must be two digits"),
        ("27AAPFU0939F0ZV", "entity number cannot be 0"),
    ],
)
def test_invalid_gstins_are_rejected(bad, reason):
    assert not gstin_service.is_valid(bad), reason
    with pytest.raises(gstin_service.InvalidGSTIN):
        gstin_service.parse(bad)


# ---------------------------------------------------------------------------
# What a refusal says. Each one is read by someone holding the invoice or the
# certificate — on the registration form, the lookup page, a bulk result row,
# WhatsApp and the GPT — so it has to name the character to look at again.
# "GSTIN format is invalid" named nothing.
# ---------------------------------------------------------------------------


def _refusal(gstin: str) -> str:
    with pytest.raises(gstin_service.InvalidGSTIN) as caught:
        gstin_service.parse(gstin)
    return str(caught.value)


@pytest.mark.parametrize(("bad", "length"), [("27AAPFU0939F1Z", 14), ("27AAPFU0939F1ZVX", 16)])
def test_a_gstin_of_the_wrong_length_says_how_long_it_is(bad, length):
    assert _refusal(bad) == f"A GSTIN is 15 characters; this one has {length}."


@pytest.mark.parametrize(
    ("bad", "position", "expected"),
    [
        ("2AAPFU0939F1ZVV", 2, "a digit (the state code)"),
        ("2712345678901ZV", 3, "a letter (part of the PAN)"),
        ("27AAPFUA939F1ZV", 8, "a digit (part of the PAN)"),
        ("27AAPFU093951ZV", 12, "a letter (the last character of the PAN)"),
        ("27AAPFU0939F0ZV", 13, "1-9 or a letter (the registration number)"),
        ("27AAPFU0939F1AV", 14, "the letter Z"),
        ("27AAPFU0939F1Z.", 15, "a digit or a letter (the check digit)"),
    ],
)
def test_a_misplaced_character_is_named_by_its_position(bad, position, expected):
    message = _refusal(bad)
    assert message.startswith(
        f"Character {position} of a GSTIN should be {expected}, but it is {bad[position - 1]!r}."
    )


@pytest.mark.parametrize(
    ("bad", "suggested"),
    [
        ("27AAPFUO939F1ZV", "0"),  # the letter O typed in the PAN's digits
        ("27AAPFU0939F0ZV", "O"),  # a zero where the registration number allows a letter
        ("27AAPF50939F1ZV", "S"),
        ("27AAPFU09I9F1ZV", "1"),
        ("27AAPFU0939F1Z.", None),  # nothing a full stop is mistaken for
        ("27AAPFUA939F1ZV", None),  # A is no digit's lookalike
    ],
)
def test_a_lookalike_character_suggests_the_one_it_was_mistaken_for(bad, suggested):
    message = _refusal(bad)
    if suggested is None:
        assert "Check whether" not in message
    else:
        assert message.endswith(f"Check whether it should be {suggested!r}.")


def test_the_position_rules_are_the_format_rule():
    """Every character, at every position, is refused by one iff by the other.

    The positions table exists to explain ``GSTIN_PATTERN``, so a disagreement
    between them is a refusal that names the wrong character — or, the other
    way round, a pattern failure that explains nothing.
    """
    for index in range(15):
        for char in gstin_service._ALPHABET + ".":
            candidate = BUSINESS_GSTIN[:index] + char + BUSINESS_GSTIN[index + 1 :]
            matches = bool(gstin_service.GSTIN_PATTERN.match(candidate))
            allowed = char in gstin_service._POSITIONS[index][0]
            assert matches == allowed, (index + 1, char)


def test_an_unknown_state_code_says_what_the_first_two_digits_are():
    message = _refusal("40AAPFU0939F1ZV")
    assert message.startswith("40 is not a GST state code.")
    assert "27 for Maharashtra" in message


def test_a_wrong_check_digit_says_one_character_is_mistyped():
    message = _refusal("27AAPFU0939F1ZW")
    assert "check digit (its last character)" in message
    assert "mistyped" in message


def test_no_adjacent_transposition_survives_validation():
    """The failure mode validation exists for.

    Swapping two adjacent characters is the commonest typing and OCR error,
    and it is what silently misattributes an invoice to another taxpayer. Every
    such swap is asserted rather than one sample: a single example passing
    would say nothing about the rest, and "usually caught" is not a property
    worth having here.
    """
    swaps = [
        BUSINESS_GSTIN[:i] + BUSINESS_GSTIN[i + 1] + BUSINESS_GSTIN[i] + BUSINESS_GSTIN[i + 2 :]
        for i in range(len(BUSINESS_GSTIN) - 1)
    ]
    # A swap of two identical characters is not a corruption; it is the same
    # string, and there is nothing for validation to catch.
    distinct = [s for s in swaps if s != BUSINESS_GSTIN]
    assert len(distinct) == 13, "fixture should exercise all but one position"

    survivors = [s for s in distinct if gstin_service.is_valid(s)]
    assert survivors == []


def test_compute_check_digit_matches_known_gstins():
    for gstin in VALID:
        assert gstin_service.compute_check_digit(gstin[:14]) == gstin[14]


def test_compute_check_digit_rejects_wrong_length():
    with pytest.raises(gstin_service.InvalidGSTIN):
        gstin_service.compute_check_digit("27AAPFU0939F1")


@pytest.mark.parametrize("body", ["27AAPFU0939F1-", "27aapfu0939f1z", "27AAPFU0939F1 "])
def test_compute_check_digit_rejects_a_character_outside_the_alphabet(body):
    """Right length, wrong alphabet.

    ``str.find`` answers -1 for a character that is not there, and -1 is a
    number the weighting arithmetic accepts without complaint. Left unchecked
    it produces a check digit rather than an error, so a lowercase or
    punctuated GSTIN would validate against a checksum computed from nonsense.
    """
    assert len(body) == 14
    with pytest.raises(gstin_service.InvalidGSTIN):
        gstin_service.compute_check_digit(body)


# ---------------------------------------------------------------------------
# The check digit, pinned to the specification rather than to three examples
# ---------------------------------------------------------------------------
#
# Three known-good GSTINs are enough to catch a check digit that is wrong for
# everything, and not enough to catch one that is wrong for a few inputs.
# Mutating each `36` in `compute_check_digit` individually showed which: two of
# them survived the whole suite, because the constants only diverge on inputs
# no fixture happened to contain.
#
# `_reference_check_digit` is written straight from the module docstring's
# description of the algorithm, independently of the implementation. Two
# implementations of the same spec agreeing on a corpus that spans every
# character in every position is a much stronger claim than three fixtures.


def _reference_check_digit(first14: str) -> str:
    """The base-36 weighted mod-36 algorithm, transcribed from the spec."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    total = 0
    for index, char in enumerate(first14):
        weight = 2 if index % 2 else 1
        product = alphabet.index(char) * weight
        total += (product // 36) + (product % 36)
    return alphabet[(36 - (total % 36)) % 36]


def _bodies():
    """14-character bodies that put every alphabet value at every position.

    Not restricted to the GSTIN shape on purpose: `compute_check_digit` is
    defined over the base-36 alphabet, and the point here is to cover the
    arithmetic rather than the format `parse` separately enforces.

    The third family is what guarantees every check digit appears. The last
    position carries weight 2, so sweeping it alone walks the running total
    through all 36 residues: below 'I' the contribution is 2v, and from 'I' up
    the carry out of `product // 36` makes it 2v-35 — the odd residues the
    doubling skips.
    """
    alphabet = gstin_service._ALPHABET
    for offset in range(len(alphabet)):
        yield "".join(alphabet[(offset + position) % 36] for position in range(14))
        yield "".join(alphabet[(offset * position) % 36] for position in range(14))
    for base in ("27AAPFU0939F1Z", "0000000000000A", "ZZZZZZZZZZZZZZ"):
        for last in alphabet:
            yield base[:13] + last


def test_the_check_digit_agrees_with_an_independent_implementation():
    for body in _bodies():
        assert gstin_service.compute_check_digit(body) == _reference_check_digit(body), body


def test_the_corpus_produces_every_possible_check_digit():
    """Otherwise the previous test's agreement could be over a narrow range.

    The wrap in `(36 - total % 36) % 36` only does anything when the total is
    already a multiple of 36 — the case that yields '0' — so a corpus that
    never lands there leaves that expression unasserted.
    """
    produced = {gstin_service.compute_check_digit(body) for body in _bodies()}
    assert produced == set(gstin_service._ALPHABET)


# 'I' is worth a case of its own: its value is 18, so at an odd index its
# weighted product is exactly 36 — the one input where `product // 36` and the
# quotient of any nearby divisor disagree.
GSTIN_WITH_I_AT_AN_ODD_INDEX = "27AAAIA0939F1ZN"

# A GSTIN whose own check digit is '0', i.e. one whose weighted total is a
# multiple of 36. Nothing in the rest of the suite has one.
GSTIN_WITH_A_ZERO_CHECK_DIGIT = "27AAAAU6094J2Z0"


@pytest.mark.parametrize(
    "gstin", [GSTIN_WITH_I_AT_AN_ODD_INDEX, GSTIN_WITH_A_ZERO_CHECK_DIGIT]
)
def test_the_arithmetic_edges_are_real_gstins_that_validate(gstin):
    assert gstin_service.compute_check_digit(gstin[:14]) == gstin[14]
    assert gstin_service.is_valid(gstin)


def test_a_zero_check_digit_is_not_confused_with_a_missing_one():
    assert gstin_service.parse(GSTIN_WITH_A_ZERO_CHECK_DIGIT).check_digit == "0"


def test_every_field_a_parsed_gstin_exposes_is_the_one_it_encodes():
    """`entity_number` had no assertion anywhere, and position 13 is always 'Z'.

    A field read off the wrong offset returns a plausible-looking constant, so
    it takes an assertion naming the expected value to notice.
    """
    parts = gstin_service.parse(BUSINESS_GSTIN)
    assert parts.gstin == "27AAPFU0939F1ZV"
    assert parts.state_code == "27"
    assert parts.state_name == "Maharashtra"
    assert parts.pan == "AAPFU0939F"
    assert parts.entity_number == "1"
    assert parts.check_digit == "V"


def test_a_parsed_gstin_cannot_be_edited_after_validation():
    """It is passed around as a validated fact; a mutable one is not that."""
    parts = gstin_service.parse(BUSINESS_GSTIN)
    with pytest.raises(Exception, match="assign|immutable|frozen"):
        parts.state_code = "29"  # type: ignore[misc]


def test_find_gstins_extracts_from_invoice_text(sample_invoice_text):
    found = gstin_service.find_gstins(sample_invoice_text)
    # Supplier's letterhead GSTIN first, buyer's from the "Bill To" block second.
    assert found == [SUPPLIER_GSTIN_OTHER_STATE, BUSINESS_GSTIN]


def test_find_gstins_drops_shape_matches_that_fail_the_checksum():
    text = f"Supplier GSTIN: 27AAPFU0939F1ZW and {BUSINESS_GSTIN}"
    assert gstin_service.find_gstins(text) == [BUSINESS_GSTIN]


def test_find_gstins_deduplicates():
    text = f"{BUSINESS_GSTIN} ... {BUSINESS_GSTIN}"
    assert gstin_service.find_gstins(text) == [BUSINESS_GSTIN]


def test_interstate_detection():
    assert gstin_service.is_interstate(SUPPLIER_GSTIN_OTHER_STATE, BUSINESS_GSTIN) is True
    assert gstin_service.is_interstate(SUPPLIER_GSTIN_SAME_STATE, BUSINESS_GSTIN) is False


def test_interstate_is_none_when_either_side_is_unknown():
    """Unknown must not collapse into "same state".

    A ``False`` here would tell the validator to expect CGST/SGST on an
    invoice whose supplier we cannot identify, producing a warning on a
    perfectly correct IGST invoice.
    """
    assert gstin_service.is_interstate(None, BUSINESS_GSTIN) is None
    assert gstin_service.is_interstate("garbage", BUSINESS_GSTIN) is None
    assert gstin_service.is_interstate(BUSINESS_GSTIN, None) is None


def test_state_code_of():
    assert gstin_service.state_code_of(BUSINESS_GSTIN) == "27"
    assert gstin_service.state_code_of("not-a-gstin") is None
