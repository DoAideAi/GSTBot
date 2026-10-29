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
        # Read by deploy.sh into the frontend build (vite inlines VITE_*).
        "VITE_WHATSAPP_NUMBER",
    }
    settings_names = {name.upper() for name in Settings.model_fields}
    unknown = sorted(_named_in_template() - settings_names - outside_the_app)
    assert not unknown, f"the template sets variables nothing reads: {unknown}"


# ---------------------------------------------------------------------------
# P35 M19: what each setting is documented to do is what it does
# ---------------------------------------------------------------------------

APP = Path(__file__).resolve().parents[1] / "app"

# Every module that reads the email switch, and the words the template's email
# section must use for what that module sends. A new reader of the switch
# fails test_every_reader_of_the_email_switch_is_named until it is added here
# and described there.
EMAIL_SWITCH_READERS = {
    "services/alert_delivery.py": "alert digest",
    "services/subscriber_reminders.py": "deadline reminder",
    "routers/auth.py": "password-reset",
}


def _section(heading: str) -> str:
    text = TEMPLATE.read_text()
    start = text.index(heading)
    end = text.find("\n# ----", start + len(heading))
    return text[start : end if end != -1 else None]


def test_every_reader_of_the_email_switch_is_named():
    readers = {
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if "alerts_email_enabled" in path.read_text()
        # Defined there, and only reported on /health there; neither sends.
        and str(path.relative_to(APP)) not in {"core/config.py", "routers/misc.py"}
    }
    assert readers == set(EMAIL_SWITCH_READERS), (
        "a module reads ALERTS_EMAIL_ENABLED that the env template does not describe"
    )


def test_the_email_section_says_what_switching_it_off_stops():
    """It was headed "alert digests" and said alerts stay visible in-app either
    way — while the same switch decides whether subscribers get their deadline
    reminders and whether a forgotten password can be reset at all. An
    operator reading it had every reason to think "off" cost nothing."""
    section = _section("# ---- Email").lower()
    for module, words in EMAIL_SWITCH_READERS.items():
        assert words in section, f"{module} sends {words}s; the email section does not say so"


def test_the_oauth_section_states_the_rule_the_api_enforces():
    # P35 M15 made the redirect base the site's own origin, not just https.
    assert "PUBLIC_SITE_URL" in _section("# ---- Sign-in providers")
