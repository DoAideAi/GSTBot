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
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).with_name("hsn_data.json")


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
