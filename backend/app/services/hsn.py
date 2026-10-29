"""HSN code search over the same table the ``/hsn`` tool page ships.

The table lives in ``hsn_data.json`` beside this module, exported from
``frontend/src/lib/hsnData.js``. Two copies of one table is a drift risk, so
``tests/test_gpt_actions.py`` reads the JavaScript and fails when the two
disagree — the JSON is regenerated from the page, never edited by hand. From
the repository root::

    node --input-type=module -e '
      import {HSN_DATA, allProducts} from "./frontend/src/lib/hsnData.js";
      import fs from "fs";
      fs.writeFileSync("backend/app/services/hsn_data.json", JSON.stringify({
        hsn: HSN_DATA.map(h => ({code: h.code, description: h.desc, rate: h.rate,
                                 category: h.category, sac: Boolean(h.sac)})),
        products: allProducts().map(p => ({product: p.product, hsn: p.hsn, rate: p.rate})),
      }, null, 1) + "\n");'

Search mirrors ``searchHSN`` on the page: a numeric query is a code prefix, a
text query must match every word somewhere in the description, category or
code. Common product names ("atta", "cold drinks") resolve through a second,
hand-curated alias table first, because the tariff wording for wheat flour is
"Wheat or meslin flour" and nobody types that.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).with_name("hsn_data.json")

# A leading label the code is printed after: "HSN: 8471", "SAC Code 998314".
_HSN_LABEL = re.compile(r"^\s*(?:HSN|SAC)(?:\s*/\s*SAC)?(?:\s*CODE)?\s*[:#.\-]?\s*", re.IGNORECASE)


def normalize_hsn_code(value: object, *, cut_long: bool = False) -> str | None:
    """*value* as the 4-8 digit code the portal takes, or ``None`` if it is not one.

    One rule for every way a code enters: typed in an edit, or read off a
    document by the model. The two had drifted — the edit form accepted the
    dotted tariff form (``8471.30.10``) as its digits, while the parser kept
    whatever it was handed cut to eight characters, so the same invoice stored
    ``8471.30.`` from an upload and ``84713010`` from an edit, and an upload
    could carry ``HSN: 847`` or ``abcd`` into the GSTR-1 HSN summary.

    *cut_long* keeps the first eight digits of a longer run of digits — the
    chapter, heading and tariff item, which is all the portal takes — for text a
    model read, where a code runs into the digits printed after it. A person
    typing more than eight digits is told instead.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        # A code a model emitted as a JSON number: 8471.30 arrives as 8471.3,
        # its trailing zero already gone, and its digits read as the wrong code
        # (84713). Only a whole number is a code that survived the trip.
        if not value.is_integer():
            return None
        value = int(value)
    digits = re.sub(r"[.\s]", "", _HSN_LABEL.sub("", str(value)))
    if cut_long and len(digits) > 8 and digits.isascii() and digits.isdigit():
        digits = digits[:8]
    # Chapter 00 does not exist: HSN chapters run 01-98 and SAC codes are 99.
    if digits.isascii() and digits.isdigit() and 4 <= len(digits) <= 8 and digits[:2] != "00":
        return digits
    return None


@dataclass(frozen=True)
class HsnEntry:
    code: str
    description: str
    rate: Decimal
    category: str
    # Services are classified by SAC (chapter 99) rather than HSN; the page
    # keeps both in one table and flags which is which.
    sac: bool = False


@dataclass(frozen=True)
class ProductAlias:
    product: str
    hsn: str
    rate: Decimal


@lru_cache(maxsize=1)
def _table() -> tuple[tuple[HsnEntry, ...], tuple[ProductAlias, ...]]:
    raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    # Rates go through ``str`` so 0.25 arrives as Decimal("0.25") rather than
    # the binary float's 0.2500000000000000138...
    entries = tuple(
        HsnEntry(e["code"], e["description"], Decimal(str(e["rate"])), e["category"], e["sac"])
        for e in raw["hsn"]
    )
    aliases = tuple(
        ProductAlias(p["product"], p["hsn"], Decimal(str(p["rate"])))
        for p in raw["products"]
    )
    return entries, aliases


def entries() -> tuple[HsnEntry, ...]:
    return _table()[0]


def aliases() -> tuple[ProductAlias, ...]:
    return _table()[1]


def by_code(code: str) -> HsnEntry | None:
    return next((e for e in entries() if e.code == code), None)


def find_product(query: str) -> ProductAlias | None:
    """The alias a product name resolves to: exact first, then containment."""
    q = " ".join(query.strip().lower().replace("-", " ").split())
    if not q:
        return None
    for alias in aliases():
        if alias.product == q:
            return alias
    for alias in aliases():
        if alias.product in q or q in alias.product:
            return alias
    return None


def search(query: str, *, limit: int = 10) -> list[HsnEntry]:
    q = query.strip().lower()
    if not q:
        return []
    if q.isdigit():
        return [e for e in entries() if e.code.startswith(q)][:limit]

    terms = q.split()
    found: list[HsnEntry] = []
    for entry in entries():
        haystacks = (entry.description.lower(), entry.category.lower(), entry.code)
        if all(any(term in h for h in haystacks) for term in terms):
            found.append(entry)
            if len(found) == limit:
                break
    return found
