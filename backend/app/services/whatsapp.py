"""WhatsApp message parsing and response formatting.

Parses free-form WhatsApp messages into one of four intents — GST rate
lookup, GSTIN verification, HSN/SAC code lookup, or GST calculation —
and formats the result for WhatsApp's plain-text-with-emoji style.

The intent detection is keyword-based and deliberately generous: a user
typing "laptop gst" should get the same answer as "GST rate for laptop",
because autocorrect on a phone makes precise syntax unrealistic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from app.core.config import settings
from app.services import gstin as gstin_service

# Shown without a scheme, the way a person would type it into a phone.
SITE = settings.public_site_host


class Intent(str, Enum):
    GST_RATE = "gst_rate"
    VERIFY_GSTIN = "verify_gstin"
    HSN_LOOKUP = "hsn_lookup"
    CALCULATE = "calculate"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class ParsedMessage:
    intent: Intent
    query: str
    params: dict[str, Any]


# Patterns that identify each intent, tried in priority order.
_VERIFY_PATTERN = re.compile(
    r"(?:verify|validate|check\s+gstin|gstin)\s*[:.]?\s*"
    r"([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])",
    re.IGNORECASE,
)
_GSTIN_BARE = re.compile(
    r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b"
)

_CALC_PATTERN = re.compile(
    r"(?:calc(?:ulate)?|compute)\s+(?:gst\s+)?(?:on\s+)?"
    r"(?:rs\.?\s*|₹\s*|inr\s*)?"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"\s+(?:at|@)\s+"
    r"([0-9]+(?:\.[0-9]+)?)\s*%?",
    re.IGNORECASE,
)
_CALC_SIMPLE = re.compile(
    r"(?:rs\.?\s*|₹\s*|inr\s*)?"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"\s+(?:at|@)\s+"
    r"([0-9]+(?:\.[0-9]+)?)\s*%"
    r"(?:\s+gst)?",
    re.IGNORECASE,
)

_HSN_PATTERN = re.compile(
    r"(?:hsn|sac)\s*(?:code|number)?\s*(?:for|of)?\s*[:.]?\s*(.+)",
    re.IGNORECASE,
)

_RATE_PATTERN = re.compile(
    r"(?:gst\s+)?rate\s*(?:for|of|on)?\s*[:.]?\s*(.+)",
    re.IGNORECASE,
)
_RATE_SUFFIX = re.compile(
    r"(.+?)\s+(?:gst|rate|gst\s+rate)\s*$",
    re.IGNORECASE,
)

_HELP_WORDS = {"hi", "hello", "help", "hey", "start", "menu", "commands"}


def parse_message(text: str) -> ParsedMessage:
    """Turn a WhatsApp message into a structured intent."""
    raw = (text or "").strip()
    if not raw:
        return ParsedMessage(Intent.HELP, "", {})

    lowered = raw.lower().strip()

    if lowered in _HELP_WORDS:
        return ParsedMessage(Intent.HELP, raw, {})

    # GSTIN verification — a 15-char GSTIN in the message.
    m = _VERIFY_PATTERN.search(raw.upper())
    if m:
        return ParsedMessage(Intent.VERIFY_GSTIN, m.group(1), {})
    m = _GSTIN_BARE.search(raw.upper())
    if m:
        return ParsedMessage(Intent.VERIFY_GSTIN, m.group(1), {})

    # GST calculation — "calculate GST on 50000 at 18%"
    m = _CALC_PATTERN.search(raw)
    if m:
        amount = m.group(1).replace(",", "")
        rate = m.group(2)
        return ParsedMessage(Intent.CALCULATE, raw, {"amount": amount, "rate": rate})
    m = _CALC_SIMPLE.search(raw)
    if m:
        amount = m.group(1).replace(",", "")
        rate = m.group(2)
        return ParsedMessage(Intent.CALCULATE, raw, {"amount": amount, "rate": rate})

    # HSN/SAC code lookup — "HSN code for cotton fabric"
    m = _HSN_PATTERN.search(raw)
    if m:
        return ParsedMessage(Intent.HSN_LOOKUP, m.group(1).strip(), {})

    # GST rate lookup — "GST rate for laptop"
    m = _RATE_PATTERN.search(raw)
    if m:
        return ParsedMessage(Intent.GST_RATE, m.group(1).strip(), {})
    m = _RATE_SUFFIX.search(raw)
    if m:
        return ParsedMessage(Intent.GST_RATE, m.group(1).strip(), {})

    # Fallback: if the message is short and doesn't match, treat as a rate query.
    words = lowered.split()
    if 1 <= len(words) <= 4 and not any(c.isdigit() for c in lowered):
        return ParsedMessage(Intent.GST_RATE, raw.strip(), {})

    return ParsedMessage(Intent.UNKNOWN, raw, {})


# ---- Product GST rate database (mirrors frontend/src/lib/hsnData.js) ----

_PRODUCT_RATES: list[dict[str, Any]] = [
    {"product": "rice", "hsn": "1006", "rate": 5},
    {"product": "wheat", "hsn": "1001", "rate": 0},
    {"product": "wheat flour", "hsn": "1101", "rate": 0},
    {"product": "atta", "hsn": "1101", "rate": 0},
    {"product": "sugar", "hsn": "1701", "rate": 5},
    {"product": "milk", "hsn": "0401", "rate": 0},
    {"product": "tea", "hsn": "0902", "rate": 5},
    {"product": "coffee", "hsn": "0901", "rate": 5},
    {"product": "dal", "hsn": "0713", "rate": 0},
    {"product": "laptop", "hsn": "8471", "rate": 18},
    {"product": "computer", "hsn": "8471", "rate": 18},
    {"product": "desktop", "hsn": "8471", "rate": 18},
    {"product": "mobile phone", "hsn": "8517", "rate": 18},
    {"product": "smartphone", "hsn": "8517", "rate": 18},
    {"product": "phone", "hsn": "8517", "rate": 18},
    {"product": "television", "hsn": "8528", "rate": 18},
    {"product": "tv", "hsn": "8528", "rate": 18},
    {"product": "refrigerator", "hsn": "8418", "rate": 18},
    {"product": "fridge", "hsn": "8418", "rate": 18},
    {"product": "washing machine", "hsn": "8450", "rate": 18},
    {"product": "air conditioner", "hsn": "8415", "rate": 28},
    {"product": "ac", "hsn": "8415", "rate": 28},
    {"product": "car", "hsn": "8703", "rate": 28},
    {"product": "motorcycle", "hsn": "8711", "rate": 28},
    {"product": "bike", "hsn": "8711", "rate": 28},
    {"product": "scooter", "hsn": "8711", "rate": 28},
    {"product": "cement", "hsn": "2523", "rate": 28},
    {"product": "steel", "hsn": "7206", "rate": 18},
    {"product": "iron", "hsn": "7206", "rate": 18},
    {"product": "paint", "hsn": "3208", "rate": 28},
    {"product": "soap", "hsn": "3401", "rate": 18},
    {"product": "shampoo", "hsn": "3305", "rate": 18},
    {"product": "toothpaste", "hsn": "3306", "rate": 18},
    {"product": "detergent", "hsn": "3402", "rate": 18},
    {"product": "shoes", "hsn": "6403", "rate": 18},
    {"product": "footwear", "hsn": "6403", "rate": 18},
    {"product": "slippers", "hsn": "6402", "rate": 5},
    {"product": "clothes", "hsn": "6109", "rate": 5},
    {"product": "clothing", "hsn": "6109", "rate": 5},
    {"product": "garments", "hsn": "6109", "rate": 5},
    {"product": "shirt", "hsn": "6105", "rate": 5},
    {"product": "t-shirt", "hsn": "6109", "rate": 5},
    {"product": "jeans", "hsn": "6203", "rate": 5},
    {"product": "saree", "hsn": "5407", "rate": 5},
    {"product": "cotton fabric", "hsn": "5208", "rate": 5},
    {"product": "silk", "hsn": "5007", "rate": 5},
    {"product": "furniture", "hsn": "9403", "rate": 18},
    {"product": "chair", "hsn": "9401", "rate": 18},
    {"product": "table", "hsn": "9403", "rate": 18},
    {"product": "bed", "hsn": "9403", "rate": 18},
    {"product": "mattress", "hsn": "9404", "rate": 18},
    {"product": "paper", "hsn": "4802", "rate": 12},
    {"product": "notebook", "hsn": "4820", "rate": 12},
    {"product": "pen", "hsn": "9608", "rate": 18},
    {"product": "printer", "hsn": "8443", "rate": 18},
    {"product": "ink", "hsn": "3215", "rate": 18},
    {"product": "gold", "hsn": "7108", "rate": 3},
    {"product": "silver", "hsn": "7106", "rate": 3},
    {"product": "diamond", "hsn": "7102", "rate": 0.25},
    {"product": "jewellery", "hsn": "7113", "rate": 3},
    {"product": "jewelry", "hsn": "7113", "rate": 3},
    {"product": "watch", "hsn": "9101", "rate": 18},
    {"product": "perfume", "hsn": "3303", "rate": 28},
    {"product": "sunglasses", "hsn": "9004", "rate": 18},
    {"product": "medicine", "hsn": "3004", "rate": 12},
    {"product": "medicines", "hsn": "3004", "rate": 12},
    {"product": "tablet", "hsn": "3004", "rate": 12},
    {"product": "medical equipment", "hsn": "9018", "rate": 12},
    {"product": "surgical instrument", "hsn": "9018", "rate": 12},
    {"product": "restaurant", "sac": "9963", "rate": 5},
    {"product": "hotel", "sac": "9963", "rate": 12},
    {"product": "cab", "sac": "9964", "rate": 5},
    {"product": "taxi", "sac": "9964", "rate": 5},
    {"product": "courier", "sac": "9968", "rate": 18},
    {"product": "insurance", "sac": "9971", "rate": 18},
    {"product": "banking", "sac": "9971", "rate": 18},
    {"product": "gym", "sac": "9996", "rate": 18},
    {"product": "spa", "sac": "9996", "rate": 18},
    {"product": "movie ticket", "sac": "9996", "rate": 18},
    {"product": "software", "sac": "9983", "rate": 18},
    {"product": "saas", "sac": "9983", "rate": 18},
    {"product": "consulting", "sac": "9983", "rate": 18},
    {"product": "legal services", "sac": "9982", "rate": 18},
    {"product": "accounting", "sac": "9982", "rate": 18},
    {"product": "ca services", "sac": "9982", "rate": 18},
    {"product": "advertising", "sac": "9983", "rate": 18},
    {"product": "coaching", "sac": "9992", "rate": 18},
    {"product": "training", "sac": "9992", "rate": 18},
    {"product": "education", "sac": "9992", "rate": 18},
    {"product": "tuition", "sac": "9992", "rate": 18},
    {"product": "construction", "sac": "9954", "rate": 18},
    {"product": "real estate", "sac": "9972", "rate": 5},
    {"product": "rent", "sac": "9972", "rate": 18},
    {"product": "electricity", "hsn": "2716", "rate": 18},
    {"product": "petrol", "hsn": "2710", "rate": 0},
    {"product": "diesel", "hsn": "2710", "rate": 0},
    {"product": "biscuit", "hsn": "1905", "rate": 18},
    {"product": "chocolate", "hsn": "1806", "rate": 18},
    {"product": "chips", "hsn": "2005", "rate": 12},
    {"product": "namkeen", "hsn": "2106", "rate": 12},
    {"product": "butter", "hsn": "0405", "rate": 5},
    {"product": "ghee", "hsn": "0405", "rate": 5},
    {"product": "cheese", "hsn": "0406", "rate": 5},
    {"product": "paneer", "hsn": "0406", "rate": 5},
    {"product": "bread", "hsn": "1905", "rate": 0},
    {"product": "water bottle", "hsn": "2201", "rate": 18},
    {"product": "soft drink", "hsn": "2202", "rate": 28},
    {"product": "cold drink", "hsn": "2202", "rate": 28},
    {"product": "juice", "hsn": "2009", "rate": 12},
    {"product": "cigarette", "hsn": "2402", "rate": 28},
    {"product": "tobacco", "hsn": "2401", "rate": 28},
    {"product": "pan masala", "hsn": "2106", "rate": 28},
    {"product": "tyre", "hsn": "4011", "rate": 28},
    {"product": "tire", "hsn": "4011", "rate": 28},
    {"product": "battery", "hsn": "8507", "rate": 28},
    {"product": "bulb", "hsn": "8539", "rate": 18},
    {"product": "led light", "hsn": "9405", "rate": 18},
    {"product": "fan", "hsn": "8414", "rate": 18},
    {"product": "mixer", "hsn": "8509", "rate": 18},
    {"product": "microwave", "hsn": "8516", "rate": 18},
    {"product": "oven", "hsn": "8516", "rate": 18},
    {"product": "camera", "hsn": "8525", "rate": 18},
    {"product": "headphone", "hsn": "8518", "rate": 18},
    {"product": "speaker", "hsn": "8518", "rate": 18},
    {"product": "charger", "hsn": "8504", "rate": 18},
    {"product": "cable", "hsn": "8544", "rate": 18},
    {"product": "plastic bag", "hsn": "3923", "rate": 18},
    {"product": "stationery", "hsn": "4820", "rate": 12},
    {"product": "book", "hsn": "4901", "rate": 0},
    {"product": "books", "hsn": "4901", "rate": 0},
    {"product": "newspaper", "hsn": "4902", "rate": 0},
    {"product": "fertilizer", "hsn": "3105", "rate": 5},
    {"product": "pesticide", "hsn": "3808", "rate": 18},
    {"product": "seeds", "hsn": "1209", "rate": 0},
    {"product": "tractor", "hsn": "8701", "rate": 12},
]

# HSN code → description and rate (a subset covering common codes).
_HSN_CODES: list[dict[str, Any]] = [
    {"code": "0101", "desc": "Live horses, asses, mules", "rate": 0, "category": "Live Animals"},
    {"code": "0401", "desc": "Milk and cream, not concentrated", "rate": 0, "category": "Dairy"},
    {"code": "0713", "desc": "Dried leguminous vegetables (dal)", "rate": 0, "category": "Food"},
    {"code": "0901", "desc": "Coffee", "rate": 5, "category": "Food"},
    {"code": "0902", "desc": "Tea", "rate": 5, "category": "Food"},
    {"code": "1001", "desc": "Wheat and meslin", "rate": 0, "category": "Food"},
    {"code": "1006", "desc": "Rice", "rate": 5, "category": "Food"},
    {"code": "1101", "desc": "Wheat flour (atta)", "rate": 0, "category": "Food"},
    {"code": "1701", "desc": "Sugar", "rate": 5, "category": "Food"},
    {"code": "1905", "desc": "Bread, pastry, biscuits, cakes", "rate": 18, "category": "Food"},
    {"code": "2201", "desc": "Water including mineral water", "rate": 18, "category": "Beverages"},
    {"code": "2202", "desc": "Aerated/flavoured beverages", "rate": 28, "category": "Beverages"},
    {"code": "2402", "desc": "Cigars, cigarettes", "rate": 28, "category": "Tobacco"},
    {"code": "2523", "desc": "Portland cement", "rate": 28, "category": "Construction"},
    {"code": "3004", "desc": "Medicaments (medicines)", "rate": 12, "category": "Pharma"},
    {"code": "3305", "desc": "Hair preparations, shampoo", "rate": 18, "category": "Cosmetics"},
    {"code": "3401", "desc": "Soap", "rate": 18, "category": "Cosmetics"},
    {"code": "3402", "desc": "Washing/cleaning preparations", "rate": 18, "category": "Cosmetics"},
    {"code": "4011", "desc": "New pneumatic tyres, of rubber", "rate": 28, "category": "Rubber"},
    {"code": "4802", "desc": "Paper and paperboard", "rate": 12, "category": "Paper"},
    {"code": "4820", "desc": "Registers, notebooks, stationery", "rate": 12, "category": "Paper"},
    {"code": "4901", "desc": "Printed books, newspapers", "rate": 0, "category": "Paper"},
    {"code": "5007", "desc": "Woven fabrics of silk", "rate": 5, "category": "Textiles"},
    {"code": "5208", "desc": "Woven fabrics of cotton", "rate": 5, "category": "Textiles"},
    {"code": "5407", "desc": "Woven fabrics of synthetic yarn", "rate": 5, "category": "Textiles"},
    {"code": "6109", "desc": "T-shirts, singlets, vests", "rate": 5, "category": "Apparel"},
    {"code": "6203", "desc": "Men's suits, trousers, shorts", "rate": 5, "category": "Apparel"},
    {"code": "6402", "desc": "Rubber/plastic sole footwear", "rate": 5, "category": "Footwear"},
    {"code": "6403", "desc": "Leather sole footwear", "rate": 18, "category": "Footwear"},
    {"code": "7106", "desc": "Silver (unwrought)", "rate": 3, "category": "Precious Metals"},
    {"code": "7108", "desc": "Gold (unwrought)", "rate": 3, "category": "Precious Metals"},
    {"code": "7113", "desc": "Jewellery articles", "rate": 3, "category": "Precious Metals"},
    {"code": "7206", "desc": "Iron and steel", "rate": 18, "category": "Metals"},
    {"code": "8415", "desc": "Air conditioning machines", "rate": 28, "category": "Electronics"},
    {"code": "8418", "desc": "Refrigerators, freezers", "rate": 18, "category": "Electronics"},
    {"code": "8443", "desc": "Printing machinery, printers", "rate": 18, "category": "Electronics"},
    {"code": "8450", "desc": "Washing machines", "rate": 18, "category": "Electronics"},
    {"code": "8471", "desc": "Computers, laptops, desktops", "rate": 18, "category": "Electronics"},
    {"code": "8507", "desc": "Batteries, accumulators", "rate": 28, "category": "Electronics"},
    {"code": "8517", "desc": "Telephones, smartphones", "rate": 18, "category": "Electronics"},
    {"code": "8528", "desc": "Television receivers", "rate": 18, "category": "Electronics"},
    {"code": "8703", "desc": "Motor cars and vehicles", "rate": 28, "category": "Vehicles"},
    {"code": "8711", "desc": "Motorcycles, scooters, mopeds", "rate": 28, "category": "Vehicles"},
    {"code": "9018", "desc": "Medical or surgical instruments", "rate": 12, "category": "Medical"},
    {"code": "9101", "desc": "Wrist/pocket watches", "rate": 18, "category": "Accessories"},
    {"code": "9401", "desc": "Seats and chairs", "rate": 18, "category": "Furniture"},
    {"code": "9403", "desc": "Furniture (beds, tables)", "rate": 18, "category": "Furniture"},
    {"code": "9608", "desc": "Pens, pencils, markers", "rate": 18, "category": "Stationery"},
]

# SAC codes for services.
_SAC_CODES: list[dict[str, Any]] = [
    {"code": "9954", "desc": "Construction services", "rate": 18},
    {"code": "9963", "desc": "Accommodation, food and beverage services", "rate": 5},
    {"code": "9964", "desc": "Passenger transport services", "rate": 5},
    {"code": "9968", "desc": "Postal and courier services", "rate": 18},
    {"code": "9971", "desc": "Financial and insurance services", "rate": 18},
    {"code": "9972", "desc": "Real estate services", "rate": 18},
    {"code": "9982", "desc": "Legal and accounting services", "rate": 18},
    {"code": "9983", "desc": "IT and consulting services", "rate": 18},
    {"code": "9992", "desc": "Education services", "rate": 18},
    {"code": "9996", "desc": "Recreational, cultural and sporting services", "rate": 18},
]



def _find_product(query: str) -> dict[str, Any] | None:
    q = query.strip().lower().replace("-", " ")
    if not q:
        return None
    for p in _PRODUCT_RATES:
        if p["product"] == q:
            return p
    for p in _PRODUCT_RATES:
        if q in p["product"] or p["product"] in q:
            return p
    return None


def _search_hsn(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []

    if q.isdigit():
        return [h for h in _HSN_CODES if h["code"].startswith(q)][:limit]

    terms = q.split()
    results = []
    for item in _HSN_CODES:
        desc_lower = item["desc"].lower()
        cat_lower = item["category"].lower()
        if all(t in desc_lower or t in cat_lower or t in item["code"] for t in terms):
            results.append(item)
    for item in _SAC_CODES:
        desc_lower = item["desc"].lower()
        if all(t in desc_lower or t in item["code"] for t in terms):
            results.append(item)
    return results[:limit]


def _calculate_gst(amount_str: str, rate_str: str) -> dict[str, Any] | None:
    try:
        amount = Decimal(amount_str)
        rate = Decimal(rate_str)
    except (InvalidOperation, ValueError):
        return None

    if amount < 0 or rate < 0 or rate > 100:
        return None

    tax = (amount * rate / 100).quantize(Decimal("0.01"))
    half = (tax / 2).quantize(Decimal("0.01"))
    other_half = tax - half
    total = amount + tax

    return {
        "amount": str(amount),
        "rate": str(rate),
        "tax": str(tax),
        "cgst": str(half),
        "sgst": str(other_half),
        "igst": str(tax),
        "total": str(total),
    }


def format_response(parsed: ParsedMessage) -> str:
    """Produce a WhatsApp-friendly text reply for the parsed message."""
    if parsed.intent == Intent.HELP:
        return _help_text()

    if parsed.intent == Intent.VERIFY_GSTIN:
        return _verify_gstin(parsed.query)

    if parsed.intent == Intent.GST_RATE:
        return _gst_rate(parsed.query)

    if parsed.intent == Intent.HSN_LOOKUP:
        return _hsn_lookup(parsed.query)

    if parsed.intent == Intent.CALCULATE:
        return _gst_calculate(parsed.params)

    return _unknown_text()


def _help_text() -> str:
    return (
        "\U0001f916 *GSTIndia by DoAide*\n"
        "\n"
        "I can help you with GST queries! Try:\n"
        "\n"
        "\U0001f4b0 *GST Rate* — Send a product name\n"
        "   _Example: laptop_\n"
        "\n"
        "\U0001f50d *Verify GSTIN* — Send a 15-digit GSTIN\n"
        "   _Example: 27AAPFU0939F1ZV_\n"
        "\n"
        "\U0001f4cb *HSN/SAC Code* — hsn code for [product]\n"
        "   _Example: hsn code for cotton fabric_\n"
        "\n"
        "\U0001f4b1 *Calculate GST* — calculate [amount] at [rate]%\n"
        "   _Example: calculate 50000 at 18%_\n"
        "\n"
        f"\U0001f310 Visit {SITE} for more tools!"
    )


def _verify_gstin(gstin_str: str) -> str:
    try:
        parts = gstin_service.parse(gstin_str)
    except gstin_service.InvalidGSTIN as exc:
        normalized = gstin_service.normalize(gstin_str)
        return (
            f"❌ *Invalid GSTIN*\n"
            f"\n"
            f"GSTIN: `{normalized}`\n"
            f"Error: {exc}\n"
            f"\n"
            f"_A valid GSTIN has 15 characters with a check digit._"
        )

    return (
        f"✅ *GSTIN Verified*\n"
        f"\n"
        f"\U0001f4c4 GSTIN: `{parts.gstin}`\n"
        f"\U0001f3e2 State: {parts.state_name} ({parts.state_code})\n"
        f"\U0001f194 PAN: `{parts.pan}`\n"
        f"\U0001f522 Entity No: {parts.entity_number}\n"
        f"✅ Check Digit: {parts.check_digit}\n"
        f"\n"
        f"\U0001f310 Full details: {SITE}/gstin/{parts.gstin}"
    )


def _gst_rate(query: str) -> str:
    product = _find_product(query)
    if not product:
        return (
            f"\U0001f50d *GST Rate Lookup*\n"
            f"\n"
            f"Could not find GST rate for *{query}*.\n"
            f"\n"
            f"Try a different spelling or visit:\n"
            f"\U0001f310 {SITE}/gst-rate/{query.lower().replace(' ', '-')}"
        )

    code_key = "hsn" if "hsn" in product else "sac"
    code_label = "HSN" if "hsn" in product else "SAC"
    code = product[code_key]

    return (
        f"\U0001f4b0 *GST Rate for {query.title()}*\n"
        f"\n"
        f"\U0001f4ca Rate: *{product['rate']}%*\n"
        f"\U0001f4cb {code_label} Code: `{code}`\n"
        f"\n"
        f"• CGST: {product['rate'] / 2}%\n"
        f"• SGST: {product['rate'] / 2}%\n"
        f"• IGST: {product['rate']}% _(inter-state)_\n"
        f"\n"
        f"\U0001f310 More details: {SITE}/gst-rate/{query.lower().replace(' ', '-')}"
    )


def _hsn_lookup(query: str) -> str:
    results = _search_hsn(query)
    if not results:
        return (
            f"\U0001f4cb *HSN/SAC Lookup*\n"
            f"\n"
            f"No codes found for *{query}*.\n"
            f"\n"
            f"Try a different search or visit:\n"
            f"\U0001f310 {SITE}/hsn-sac-finder"
        )

    lines = ["\U0001f4cb *HSN/SAC Code Results*\n"]
    for item in results[:5]:
        rate = item.get("rate", "N/A")
        lines.append(f"• `{item['code']}` — {item['desc']} @ *{rate}%*")

    lines.append(f"\n\U0001f310 Search more: {SITE}/hsn-sac-finder")
    return "\n".join(lines)


def _gst_calculate(params: dict[str, Any]) -> str:
    amount_str = params.get("amount", "0")
    rate_str = params.get("rate", "18")

    result = _calculate_gst(amount_str, rate_str)
    if not result:
        return (
            "❌ *Calculation Error*\n"
            "\n"
            "Could not parse the amount or rate.\n"
            "_Example: calculate 50000 at 18%_"
        )

    return (
        f"\U0001f4b1 *GST Calculation*\n"
        f"\n"
        f"\U0001f4b5 Taxable Amount: ₹{result['amount']}\n"
        f"\U0001f4ca GST Rate: {result['rate']}%\n"
        f"\n"
        f"*Intra-state (CGST + SGST):*\n"
        f"• CGST: ₹{result['cgst']}\n"
        f"• SGST: ₹{result['sgst']}\n"
        f"\n"
        f"*Inter-state (IGST):*\n"
        f"• IGST: ₹{result['igst']}\n"
        f"\n"
        f"\U0001f4b0 *Total: ₹{result['total']}*\n"
        f"\n"
        f"\U0001f310 Calculator: {SITE}/calculator"
        f"?amount={result['amount']}&rate={result['rate']}"
    )


def _unknown_text() -> str:
    return (
        "\U0001f914 I didn't understand that.\n"
        "\n"
        "Send *hi* to see what I can do, or try:\n"
        "• A product name for GST rates\n"
        "• A 15-digit GSTIN to verify\n"
        "• _hsn code for [product]_\n"
        "• _calculate [amount] at [rate]%_"
    )
