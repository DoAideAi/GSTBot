"""Configuration: what refuses to boot, and what only warns.

The split is the point. A setting that would silently make the deployment
insecure raises out of ``Settings`` and the process never starts; a setting that
is merely questionable comes back from ``validate_startup_config`` as a warning
and is logged. Getting an item on the wrong side of that line is the bug these
tests exist to catch — a production deployment must not start with a sample JWT
secret, and it must not refuse to start because nobody set an OpenRouter key.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, redact_url, validate_startup_config

PROD = {
    "environment": "production",
    "debug": False,
    "jwt_secret": "a-genuinely-long-random-production-secret-value-here",
    "backend_cors_origins": "https://app.example.com",
    # The site the origins above belong to; a clean config names its own.
    "public_site_url": "https://app.example.com",
    "database_url": "postgresql+psycopg://u:p@db:5432/gstbot",
    # Stated rather than left to the default, because conftest exports
    # BCRYPT_ROUNDS=4 for the whole suite and Settings reads the environment
    # for anything not passed here. Without this line every one of these
    # production configs trips the bcrypt floor first, and the tests below
    # would pass or fail on that instead of on the setting each one names.
    "bcrypt_rounds": 12,
}


def prod(**overrides) -> dict:
    return {**PROD, **overrides}


class TestProductionRefusesToStart:
    """Every one of these would be a real incident if it booted."""

    def test_debug_true_in_production_is_fatal(self):
        # Debug mode renders the traceback into the HTTP response, ahead of the
        # error handler that exists to prevent exactly that.
        with pytest.raises(ValidationError, match="DEBUG must be false"):
            Settings(**prod(debug=True))

    def test_the_sample_jwt_secret_is_fatal(self):
        # Anyone with the repository could otherwise mint a token for any user.
        with pytest.raises(ValidationError):
            Settings(**prod(jwt_secret="change-me-to-a-long-random-string"))

    def test_a_short_jwt_secret_is_fatal(self):
        with pytest.raises(ValidationError):
            Settings(**prod(jwt_secret="short"))

    def test_a_wildcard_cors_origin_is_fatal(self):
        # With credentials allowed, "*" would let any site call the API using a
        # signed-in user's token.
        with pytest.raises(ValidationError, match="explicit origins"):
            Settings(**prod(backend_cors_origins="*"))

    def test_no_cors_origin_at_all_is_fatal(self):
        with pytest.raises(ValidationError, match="at least one origin"):
            Settings(**prod(backend_cors_origins=""))

    def test_the_bcrypt_factor_the_tests_run_at_is_fatal_in_production(self):
        """The suite runs at 4. This is what stops 4 reaching a real deployment.

        The route it would take is not a typo — it is a .env or a container
        image built for tests being promoted, the same way the sample JWT
        secret above would ship. A stolen table hashed at 4 is a wordlist away
        from plaintext, and nothing else in the system would look wrong.
        """
        with pytest.raises(ValidationError, match="BCRYPT_ROUNDS must be at least"):
            Settings(**prod(bcrypt_rounds=4))

    def test_a_bcrypt_factor_one_step_under_the_floor_is_still_fatal(self):
        # The boundary, so the floor is a decision rather than whichever
        # comparison operator was typed.
        with pytest.raises(ValidationError, match="BCRYPT_ROUNDS must be at least"):
            Settings(**prod(bcrypt_rounds=9))

    def test_the_floor_itself_is_allowed_in_production(self):
        # Slow hardware may take the bounded step down; that is why the floor
        # sits below the default rather than on it.
        assert Settings(**prod(bcrypt_rounds=10)).bcrypt_rounds == 10

    def test_a_low_bcrypt_factor_outside_production_is_fine(self):
        # Development and the suite are the whole reason the setting exists.
        assert Settings(environment="development", bcrypt_rounds=4).bcrypt_rounds == 4

    def test_an_oauth_provider_with_the_localhost_redirect_base_is_fatal(self):
        # M15: the default callback base is a laptop; every sign-in would land there.
        with pytest.raises(ValidationError, match="OAUTH_REDIRECT_BASE"):
            Settings(**prod(google_client_id="gid", google_client_secret="gs"))

    def test_an_oauth_provider_with_an_https_redirect_base_builds(self):
        s = Settings(
            **prod(
                github_client_id="gid",
                github_client_secret="gs",
                oauth_redirect_base="https://gst.example.com",
            )
        )
        assert s.oauth_providers_configured == ["github"]

    def test_no_oauth_provider_leaves_the_redirect_base_unchecked(self):
        # Production today: no client ids, OAUTH_REDIRECT_BASE unset.
        assert Settings(**prod()).oauth_providers_configured == []

    def test_a_localhost_redirect_base_outside_production_is_fine(self):
        assert Settings(environment="development", google_client_id="gid").is_production is False

    def test_a_valid_production_config_builds(self):
        # The negative tests above are only meaningful if this one passes.
        assert Settings(**prod()).is_production

    def test_the_shipped_default_bcrypt_factor_is_the_strong_one(self):
        """A deployment that sets nothing must land on the strong value.

        Asserted against the field's declared default rather than by building
        a Settings, because conftest exports BCRYPT_ROUNDS=4 for the suite and
        a constructed instance would report the environment's value — this
        test would then be asserting the test harness, and would keep passing
        if the shipped default were lowered to 4 tomorrow.
        """
        assert Settings.model_fields["bcrypt_rounds"].default == 12


class TestValidation:
    def test_a_non_database_url_is_refused(self):
        with pytest.raises(ValidationError, match="postgresql|sqlite"):
            Settings(**prod(database_url="mysql://u:p@db/gstbot"))

    def test_an_empty_database_url_is_refused(self):
        with pytest.raises(ValidationError):
            Settings(**prod(database_url=""))

    def test_a_non_redis_url_is_refused(self):
        with pytest.raises(ValidationError, match="redis"):
            Settings(**prod(redis_url="http://localhost:6379"))

    def test_a_malformed_rate_limit_is_refused_at_startup(self):
        # Better here than on the first request that would have been limited.
        with pytest.raises(ValidationError):
            Settings(**prod(rate_limit_default="30/fortnight"))

    def test_cors_origins_are_split_and_trimmed(self):
        settings = Settings(
            **prod(backend_cors_origins="https://a.example.com, https://b.example.com")
        )
        assert settings.cors_origins == ["https://a.example.com", "https://b.example.com"]


class TestFieldsThatMustBeSane:
    """Single-field guards, each protecting something a long way from here.

    Cheap to write and easy to leave untested, which is exactly the problem: a
    validator nobody has ever watched fire is indistinguishable from one that
    does not fire at all. The normalisation cases matter for the same reason —
    every caller downstream assumes the canonical form came back.
    """

    @pytest.mark.parametrize("field", ["access_token_expire_minutes", "max_upload_mb"])
    @pytest.mark.parametrize("value", [0, -1])
    def test_a_non_positive_value_is_refused(self, field, value):
        # Zero is the interesting one. A zero token lifetime signs credentials
        # that have already expired, and a zero upload cap rejects every file —
        # both look like a working deployment until someone tries to use it.
        with pytest.raises(ValidationError, match="must be positive"):
            Settings(**prod(**{field: value}))

    def test_an_unknown_log_level_is_refused(self):
        with pytest.raises(ValidationError, match="LOG_LEVEL must be one of"):
            Settings(**prod(log_level="CHATTY"))

    def test_a_log_level_is_normalised_to_upper_case(self):
        assert Settings(**prod(log_level=" debug ")).log_level == "DEBUG"

    def test_an_unknown_log_format_is_refused(self):
        # Typo'd to "text" and accepted, this would emit console output into an
        # aggregator that only parses JSON — logs that exist but are unsearchable.
        with pytest.raises(ValidationError, match="LOG_FORMAT must be"):
            Settings(**prod(log_format="text"))

    def test_an_asymmetric_jwt_algorithm_is_refused(self):
        # RS256 here would mean the verification key and the signing key are the
        # same string, which is the classic JWT confusion. The product signs and
        # verifies with one secret, so the asymmetric family must not be offered.
        with pytest.raises(ValidationError, match="JWT_ALGORITHM must be"):
            Settings(**prod(jwt_algorithm="RS256"))

    def test_a_supported_algorithm_is_normalised(self):
        assert Settings(**prod(jwt_algorithm="hs512")).jwt_algorithm == "HS512"

    def test_a_blank_environment_falls_back_to_development(self):
        # Not to production: an empty ENVIRONMENT is an unset one, and the
        # stricter branch must be opted into rather than arrived at by accident.
        settings = Settings(environment="   ")
        assert settings.environment == "development"
        assert not settings.is_production

    def test_a_plaintext_cors_origin_is_fatal_in_production(self):
        # Allowing the origin is what makes the browser attach the token, so a
        # http:// entry here puts a live credential on the wire in clear text.
        with pytest.raises(ValidationError, match="must use https"):
            Settings(**prod(backend_cors_origins="https://app.example.com,http://staging.local"))

    def test_max_upload_bytes_matches_the_megabyte_setting(self):
        # The setting an operator writes is MB; every size check reads bytes.
        assert Settings(**prod(max_upload_mb=15)).max_upload_bytes == 15 * 1024 * 1024


class TestPlanLimits:
    """``plan_monthly_invoice_limits`` is enforced at upload, parsed here."""

    def test_the_shipped_default_parses(self):
        limits = Settings(**prod()).plan_limits
        assert limits["free"] == 50
        assert limits["starter"] == 500
        # 0 is "unlimited", not "nothing allowed" — the paid plans rely on it.
        assert limits["pro"] == 0

    def test_a_garbled_entry_is_dropped_and_its_neighbours_survive(self):
        # A typo in one plan must not take the other plans' ceilings with it,
        # and must not raise: this string is read on the upload path.
        limits = Settings(
            **prod(plan_monthly_invoice_limits="free=50,starter=lots,=9,pro=0")
        ).plan_limits
        assert limits == {"free": 50, "pro": 0}

    def test_names_are_lower_cased_and_trimmed(self):
        assert Settings(**prod(plan_monthly_invoice_limits=" Free = 50 ")).plan_limits == {
            "free": 50
        }


class TestRateLimitOverrides:
    """``RATE_LIMIT_OVERRIDES`` is the one config string that warns instead of raising."""

    def test_the_global_default_is_always_present(self):
        # Every caller passes through it, so its absence would mean no ceiling
        # at all rather than a missing override.
        assert Settings(**prod()).rate_limits["global"] == "300/minute"

    def test_an_override_applies_under_its_registered_name(self):
        limits = Settings(
            **prod(rate_limit_overrides="Login=5/minute, upload=20/hour")
        ).rate_limits
        assert limits["login"] == "5/minute"
        assert limits["upload"] == "20/hour"
        assert limits["global"] == "300/minute"

    def test_an_unparseable_override_warns_and_leaves_the_rest_alone(self):
        # Deliberately not fatal, and this is the asymmetry worth pinning down:
        # an operator tuning a limit at 2am should get the built-in default for
        # the entry they fat-fingered, not an API that refuses to start. The
        # entry beside it still has to apply.
        with pytest.warns(UserWarning, match="login=5/fortnight"):
            limits = Settings(
                **prod(rate_limit_overrides="login=5/fortnight,upload=20/hour")
            ).rate_limits
        assert "login" not in limits
        assert limits["upload"] == "20/hour"

    def test_a_valueless_entry_is_skipped_silently(self):
        # "login=" is a half-finished edit rather than a wrong value; there is
        # nothing to tell the operator that the built-in default does not say.
        assert "login" not in Settings(**prod(rate_limit_overrides="login=")).rate_limits


class TestStartupWarnings:
    """Questionable, not fatal — the deployment still comes up."""

    def test_a_missing_model_key_only_warns(self):
        # Extraction degrades to heuristics and OCR; that is a worse product,
        # not an insecure one, and refusing to boot would be wrong.
        warnings = validate_startup_config(Settings(**prod(openrouter_api_key="")))
        assert any("OPENROUTER_API_KEY" in w for w in warnings)

    def test_production_without_rate_limiting_warns(self):
        warnings = validate_startup_config(Settings(**prod(rate_limit_enabled=False)))
        assert any("RATE_LIMIT_ENABLED" in w for w in warnings)

    def test_cors_origins_left_from_an_earlier_domain_warn(self):
        """P23 M16: production allowed only the product's previous domain to
        call the API with credentials, and the site's own origin was absent;
        nothing broke, so nothing said so."""
        warnings = validate_startup_config(
            Settings(
                **prod(
                    backend_cors_origins="https://gstbot.aiknol.com",
                    public_site_url="https://gst.doaide.com",
                )
            )
        )
        (warning,) = [w for w in warnings if "BACKEND_CORS_ORIGINS" in w]
        assert "https://gstbot.aiknol.com" in warning and "https://gst.doaide.com" in warning

    def test_cors_origins_that_include_the_site_do_not_warn(self):
        warnings = validate_startup_config(
            Settings(
                **prod(
                    backend_cors_origins="https://gst.doaide.com,https://partner.example.com",
                    public_site_url="https://gst.doaide.com/",
                )
            )
        )
        assert not [w for w in warnings if "BACKEND_CORS_ORIGINS" in w]

    def test_production_with_public_docs_warns(self):
        warnings = validate_startup_config(Settings(**prod(docs_enabled=True)))
        assert any("DOCS_ENABLED" in w for w in warnings)

    def test_production_on_sqlite_warns(self):
        warnings = validate_startup_config(
            Settings(**prod(database_url="sqlite+pysqlite:///./gstbot.db"))
        )
        assert any("SQLite" in w for w in warnings)

    def test_email_alerts_turned_on_without_an_smtp_host_warns(self):
        """The switch is on and there is nowhere to send. Alerts stay in-app.

        A warning rather than a refusal because the product still works — the
        alerts are on the dashboard either way. What must not happen is the
        operator believing email is on because they set the flag.
        """
        warnings = validate_startup_config(
            Settings(**prod(alerts_email_enabled=True, smtp_host=""))
        )
        assert any("SMTP_HOST" in w for w in warnings)

    def test_email_alerts_with_a_host_configured_says_nothing(self):
        warnings = validate_startup_config(
            Settings(**prod(alerts_email_enabled=True, smtp_host="smtp.example.com"))
        )
        assert not any("SMTP_HOST" in w for w in warnings)

    def test_a_razorpay_key_id_without_its_secret_warns(self):
        warnings = validate_startup_config(Settings(**prod(razorpay_key_id="rzp_live_x")))
        assert any("RAZORPAY_KEY_SECRET" in w for w in warnings)

    def test_razorpay_without_a_webhook_secret_warns(self):
        warnings = validate_startup_config(
            Settings(**prod(razorpay_key_id="rzp_live_x", razorpay_key_secret="s"))
        )
        assert any("RAZORPAY_WEBHOOK_SECRET" in w for w in warnings)

    def test_fully_configured_razorpay_warns_about_nothing(self):
        warnings = validate_startup_config(
            Settings(
                **prod(
                    razorpay_key_id="rzp_live_x",
                    razorpay_key_secret="s",
                    razorpay_webhook_secret="w",
                )
            )
        )
        assert not any("RAZORPAY" in w for w in warnings)

    def test_an_oauth_client_id_without_its_secret_warns(self):
        warnings = validate_startup_config(
            Settings(
                **prod(microsoft_client_id="mid", oauth_redirect_base="https://gst.example.com")
            )
        )
        assert any("MICROSOFT_CLIENT_SECRET" in w for w in warnings)

    def test_production_with_console_logs_warns(self):
        warnings = validate_startup_config(Settings(**prod(log_format="console")))
        assert any("LOG_FORMAT" in w for w in warnings)

    def test_an_smtp_username_with_no_password_warns(self):
        warnings = validate_startup_config(
            Settings(**prod(smtp_username="alerts", smtp_password=""))
        )
        assert any("SMTP_PASSWORD" in w for w in warnings)

    def test_an_smtp_username_with_a_password_warns_about_nothing(self):
        warnings = validate_startup_config(
            Settings(**prod(smtp_username="alerts", smtp_password="hunter2"))
        )
        assert not any("SMTP" in w for w in warnings)

    def test_a_clean_production_config_warns_about_nothing_security_related(self):
        warnings = validate_startup_config(
            Settings(
                **prod(
                    openrouter_api_key="sk-test",
                    rate_limit_enabled=True,
                    trust_proxy_headers=True,
                    hsts_enabled=True,
                    log_format="json",
                    docs_enabled=False,
                )
            )
        )
        assert warnings == []

    def test_the_sample_secret_is_only_a_warning_in_development(self):
        # Fine locally; the production path above makes it fatal.
        warnings = validate_startup_config(
            Settings(environment="development", jwt_secret="change-me-to-a-long-random-string")
        )
        assert any("JWT_SECRET" in w for w in warnings)


class TestSecretsNeverLeak:
    def test_the_startup_report_redacts_the_database_password(self):
        report = Settings(
            **prod(database_url="postgresql+psycopg://user:hunter2@db:5432/gstbot")
        ).startup_report()
        assert "hunter2" not in str(report)

    def test_the_startup_report_does_not_contain_the_jwt_secret(self):
        secret = "a-genuinely-long-random-production-secret-value-here"
        assert secret not in str(Settings(**prod(jwt_secret=secret)).startup_report())

    def test_the_startup_report_does_not_contain_the_model_key(self):
        report = Settings(**prod(openrouter_api_key="sk-super-secret")).startup_report()
        assert "sk-super-secret" not in str(report)

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+psycopg://user:hunter2@db:5432/gstbot",
            "redis://:hunter2@cache:6379/0",
            "rediss://user:hunter2@cache:6379/0",
        ],
    )
    def test_redact_url_removes_the_password_but_keeps_the_host(self, url):
        redacted = redact_url(url)
        assert "hunter2" not in redacted
        # Still has to be useful — "which database am I pointed at" is the
        # question the startup line exists to answer.
        assert "db:5432" in redacted or "cache:6379" in redacted

    def test_redact_url_leaves_a_passwordless_url_alone(self):
        url = "postgresql+psycopg://db:5432/gstbot"
        assert redact_url(url) == url

    def test_redact_url_survives_junk(self):
        # It runs inside the startup logger; raising there loses the line that
        # would have explained the misconfiguration.
        assert redact_url("not a url at all")


class TestThePublicSiteUrlIsOneSetting:
    """P17 M15: the origin was a literal in five modules, so a staging box
    advertised production in its sitemap, its GPT spec and its WhatsApp
    replies. It is one setting now, and it has to be an origin."""

    def test_a_trailing_slash_is_dropped(self):
        assert Settings(public_site_url="https://staging.example.com/").public_site_url == (
            "https://staging.example.com"
        )

    @pytest.mark.parametrize("bad", ["staging.example.com", "https://x.com/app", "ftp://x.com"])
    def test_anything_but_an_origin_is_refused(self, bad):
        with pytest.raises(ValidationError, match="PUBLIC_SITE_URL"):
            Settings(public_site_url=bad)

    def test_the_host_is_the_origin_without_its_scheme(self):
        assert Settings(public_site_url="https://staging.example.com").public_site_host == (
            "staging.example.com"
        )

    def test_no_module_hardcodes_the_production_origin_any_more(self):
        from pathlib import Path

        app = Path(__file__).resolve().parents[1] / "app"
        offenders = [
            f"{path.relative_to(app)}: {line.strip()}"
            for path in app.rglob("*.py")
            if path.name != "config.py"
            for line in path.read_text().splitlines()
            # The GPT spec file names production; its server substitutes that.
            if "gst.doaide.com" in line and '.replace("https://gst.doaide.com"' not in line
        ]
        assert offenders == []


class TestTheOpenRouterSiteFollowsThePublicOne:
    """P19 M15: OPENROUTER_APP_URL had its own literal production default, so a
    staging box that set PUBLIC_SITE_URL still told OpenRouter it was
    production."""

    def test_unset_it_is_the_public_site(self):
        settings = Settings(public_site_url="https://staging.example.com", openrouter_app_url="")
        assert settings.openrouter_app_url == "https://staging.example.com"

    def test_set_it_wins(self):
        settings = Settings(
            public_site_url="https://staging.example.com",
            openrouter_app_url="https://ranking.example.com",
        )
        assert settings.openrouter_app_url == "https://ranking.example.com"

    def test_the_default_deployment_is_unchanged(self):
        assert Settings(openrouter_app_url="").openrouter_app_url == "https://gst.doaide.com"
