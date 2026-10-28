"""Every setting an operator can set is in the production env template.

deploy/gstbot.env.example is what a new server's /etc/gstbot/gstbot.env is
copied from. It had drifted: payments, sign-in providers, the advisor's key,
the WhatsApp bot and ADMIN_EMAILS were all read by Settings and named
nowhere an operator would look, so a fresh deployment came up with each of
them silently off.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "gstbot.env.example"

# Constants of the codebase rather than of a deployment: changing one is a code
# change, not configuration, so the template does not offer them.
NOT_FOR_OPERATORS = {
    "APP_NAME",
    "APP_VERSION",
    "API_V1_PREFIX",
    "JWT_ALGORITHM",
    "DB_ECHO",
}


def _named_in_template() -> set[str]:
    # Set (`NAME=`) or offered commented out at its default (`# NAME=`).
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", TEMPLATE.read_text(), re.MULTILINE))


def test_every_setting_is_in_the_template():
    settings_names = {name.upper() for name in Settings.model_fields}
    missing = sorted(settings_names - NOT_FOR_OPERATORS - _named_in_template())
    assert not missing, f"add these to deploy/gstbot.env.example: {missing}"


def test_the_exemptions_are_still_settings():
    # A renamed setting would otherwise leave a stale exemption hiding nothing.
    settings_names = {name.upper() for name in Settings.model_fields}
    assert not NOT_FOR_OPERATORS - settings_names


def test_the_template_names_nothing_the_app_does_not_read():
    # Read by the unit files and deploy/monitor.sh rather than by Settings.
    outside_the_app = {
        "WEB_CONCURRENCY",
        "CELERY_CONCURRENCY",
        "CELERY_LOG_LEVEL",
        "GSTBOT_ALERT_WEBHOOK",
    }
    settings_names = {name.upper() for name in Settings.model_fields}
    unknown = sorted(_named_in_template() - settings_names - outside_the_app)
    assert not unknown, f"the template sets variables nothing reads: {unknown}"
