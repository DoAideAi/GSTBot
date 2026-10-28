"""The README's map of the API is the API.

It said 79 routes across twelve areas when there were 90 across nineteen —
subscriptions, referrals, feedback, the advisor, OAuth sign-in, the WhatsApp
webhook and SEO were all missing from the table a newcomer reads first.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.core.routes import collect_api_routes
from app.main import app

README = Path(__file__).resolve().parents[2] / "README.md"


def _actual() -> Counter:
    counts: Counter = Counter()
    for route in collect_api_routes(app):
        if not hasattr(route, "methods") or not route.path.startswith("/api/v1/"):
            continue
        area = route.path.split("/")[3]
        counts[area] += len(route.methods - {"HEAD", "OPTIONS"})
    return counts


def test_every_area_is_in_the_table_with_its_route_count():
    text = README.read_text()
    documented = {area: int(n) for area, n in re.findall(r"^\| `([a-z]+)` \| (\d+) \|", text, re.M)}
    assert documented == dict(_actual()), "update the API table in README.md"


def test_the_total_is_the_total():
    total = int(re.search(r"(\d+) routes under `/api/v1`", README.read_text()).group(1))
    assert total == sum(_actual().values())
