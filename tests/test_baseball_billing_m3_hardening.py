import asyncio
import time
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from baseball_billing import (
    BillingError,
    CustomerRecord,
    EventClaim,
    InMemoryStore,
    LEASE_SECONDS,
    VerifiedUser,
)
from baseball_billing_config import (
    BASEBALL_PRO_TEST_PRICE_ID,
    BillingConfig,
    RolloutMode,
    load_client_billing_config,
    trusted_url,
)


def config(**changes):
    base = BillingConfig(
        RolloutMode.TEST,
        "test",
        "sk_test_RECOGNIZABLE_SECRET",
        "whsec_RECOGNIZABLE_SECRET",
        BASEBALL_PRO_TEST_PRICE_ID,
        "https://app.test",
        "https://billing.test",
        "https://db.test",
        "SERVICE_ROLE_RECOGNIZABLE_SECRET",
        "ANON_RECOGNIZABLE_VALUE",
    )
    return replace(base, **changes)


def test_customer_mapping_is_one_to_one():
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    with pytest.raises(BillingError):
        store.attach_customer(CustomerRecord("user-1", "cus_2"))
    with pytest.raises(BillingError):
        store.attach_customer(CustomerRecord("user-2", "cus_1"))


def test_event_lease_duplicate_retry_and_collision_behavior():
    store = InMemoryStore()
    first = store.claim_event("evt", "type", 1, "fp", False)
    assert first.claim is EventClaim.NEW and first.token
    assert store.claim_event("evt", "type", 1, "fp", False).claim is EventClaim.IN_PROGRESS
    assert store.claim_event("evt", "other", 1, "other", False).claim is EventClaim.COLLISION
    with pytest.raises(BillingError):
        store.mark_event_processed("evt", "wrong-token")
    store.events["evt"]["updated"] -= LEASE_SECONDS + 1
    retry = store.claim_event("evt", "type", 1, "fp", False)
    assert retry.claim is EventClaim.RETRY and retry.token != first.token
    store.mark_event_processed("evt", retry.token)
    assert store.claim_event("evt", "type", 1, "fp", False).claim is EventClaim.DUPLICATE


@pytest.mark.parametrize(
    "url,allow,expected",
    [
        ("https://billing.example.com", False, True),
        ("http://localhost:8000", True, True),
        ("http://localhost:8000", False, False),
        ("http://evil.example", True, False),
        ("https://user:pass@example.com", False, False),
        ("https://example.com?q=secret", False, False),
    ],
)
def test_trusted_url_policy(url, allow, expected):
    assert trusted_url(url, allow_loopback=allow) is expected


def test_live_mode_cannot_reuse_test_price_or_test_key():
    live = replace(
        config(),
        rollout=RolloutMode.LIVE,
        stripe_mode="live",
        stripe_secret_key="sk_live_secret",
    )
    assert not live.checkout_enabled
    live = replace(live, pro_price_id="price_live_reviewed")
    assert live.checkout_enabled
    assert not replace(live, public_base_url="http://localhost:8501").checkout_enabled


def test_client_loader_never_loads_server_secrets():
    value = load_client_billing_config(
        {
            "BASEBALL_BILLING_ROLLOUT": "test",
            "BASEBALL_STRIPE_MODE": "test",
            "STRIPE_SECRET_KEY": "sk_test_do_not_forward",
            "STRIPE_WEBHOOK_SECRET": "whsec_do_not_forward",
            "BASEBALL_BILLING_SUPABASE_SERVICE_ROLE_KEY": "service-do-not-forward",
        }
    )
    assert value.stripe_secret_key == ""
    assert value.stripe_webhook_secret == ""
    assert value.supabase_service_role_key == ""
    source = __import__("pathlib").Path(__file__).parents[1].joinpath(
        "baseball_billing_config.py"
    ).read_text(encoding="utf-8")
    client_block = source[source.index("def load_client_billing_config"):]
    assert 'stripe_secret_key=""' in client_block
    assert 'supabase_service_role_key=""' in client_block


def test_public_health_and_errors_do_not_leak_secrets():
    rendered = repr(config().public_status())
    for secret in (
        "RECOGNIZABLE_SECRET",
        "SERVICE_ROLE_RECOGNIZABLE_SECRET",
        "ANON_RECOGNIZABLE_VALUE",
    ):
        assert secret not in rendered


def test_oversized_webhook_body_rejected_before_read():
    import baseball_billing_service as service

    class Request:
        headers = {"content-length": "1000001"}

        async def body(self):
            raise AssertionError("body must not be read")

    response = asyncio.run(service.webhook(Request()))
    assert response.status_code == 413
    assert b"secret" not in response.body.lower()


def test_billing_portal_endpoint_requires_verified_customer():
    import baseball_billing_service as service

    class Request:
        headers = {"authorization": "Bearer token"}

    store = InMemoryStore()
    stripe = Mock()
    with patch.object(service, "deps", return_value=(config(), store, stripe)), patch.object(
        service, "verify_supabase_user", return_value=VerifiedUser("user-1")
    ):
        response = asyncio.run(service.portal(Request()))
    assert response.status_code == 503
    stripe.create_portal.assert_not_called()


def test_auth_api_key_never_falls_back_to_service_role(monkeypatch):
    import suite_storage_config as storage_config

    monkeypatch.delenv("SUITE_SUPABASE_ANON_KEY", raising=False)
    storage_config.reset_cloud_config_cache()
    with patch.object(storage_config, "_auth_key_from_streamlit_secrets", return_value=""), patch.object(
        storage_config, "get_cloud_config", return_value=Mock(key="service-role")
    ):
        assert storage_config.get_auth_api_key() is None
    storage_config.reset_cloud_config_cache()
