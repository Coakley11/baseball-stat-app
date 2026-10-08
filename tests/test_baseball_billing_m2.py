import asyncio
import hashlib
import hmac
import json
import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from baseball_billing import (
    AuthenticationRequired,
    BillingError,
    CheckoutService,
    CustomerRecord,
    InMemoryStore,
    InvalidWebhookSignature,
    SubscriptionRecord,
    VerifiedUser,
    WebhookProcessor,
    parse_verified_event,
    project,
)
from baseball_billing_config import (
    BASEBALL_PRO_TEST_PRICE_ID,
    BillingConfig,
    RolloutMode,
)
from baseball_monetization import (
    EntitlementLevel,
    EntitlementSnapshot,
    Plan,
    SubscriptionStatus,
    resolve_trusted_entitlement,
)


def config(**changes):
    base = BillingConfig(
        RolloutMode.TEST,
        "test",
        "sk_test_secret",
        "whsec_secret",
        BASEBALL_PRO_TEST_PRICE_ID,
        "https://baseball.test",
        "https://billing.test",
        "https://supabase.test",
        "service-secret",
        "anon-public",
    )
    return replace(base, **changes)


def subscription(status="active", price=BASEBALL_PRO_TEST_PRICE_ID, customer="cus_1"):
    return {
        "id": "sub_1",
        "customer": customer,
        "status": status,
        "current_period_end": 2_000,
        "metadata": {"app_user_id": "user-1"},
        "items": {"data": [{"price": {"id": price}}]},
    }


def event(event_id="evt_1", created=100, live=False, event_type="customer.subscription.updated"):
    obj = subscription()
    if event_type.startswith("invoice.") or event_type == "checkout.session.completed":
        obj = {
            "customer": "cus_1",
            "subscription": "sub_1",
            "client_reference_id": "user-1",
            "metadata": {"app_user_id": "user-1"},
        }
    return {
        "id": event_id,
        "type": event_type,
        "created": created,
        "livemode": live,
        "data": {"object": obj},
    }


def gateway(current=None):
    stripe = Mock()
    stripe.create_customer.return_value = "cus_1"
    stripe.create_checkout.return_value = {"url": "https://checkout.stripe.com/test"}
    stripe.create_portal.return_value = {"url": "https://billing.stripe.com/test"}
    stripe.retrieve_subscription.return_value = current or subscription()
    return stripe


def test_rollout_disabled_by_default_and_public_status_has_no_secrets():
    value = BillingConfig.from_environ({})
    assert value.rollout is RolloutMode.OFF
    assert not value.checkout_enabled
    rendered = repr(config().public_status())
    assert "sk_test_secret" not in rendered
    assert "service-secret" not in rendered
    assert "whsec_secret" not in rendered


def test_test_checkout_requires_exact_server_controlled_price_and_webhook():
    assert config().checkout_enabled
    assert not config(pro_price_id="price_client_supplied").checkout_enabled
    assert not config(stripe_webhook_secret="").checkout_enabled


def test_checkout_requires_identity_reuses_customer_and_uses_trusted_price():
    store = InMemoryStore()
    stripe = gateway()
    service = CheckoutService(config(), store, stripe)
    with pytest.raises(AuthenticationRequired):
        service.create(VerifiedUser(""))
    service.create(VerifiedUser("user-1", "u@example.test"))
    service.create(VerifiedUser("user-1"))
    assert stripe.create_customer.call_count == 1
    assert stripe.create_checkout.call_args.kwargs["price_id"] == BASEBALL_PRO_TEST_PRICE_ID
    assert stripe.create_checkout.call_args.kwargs["customer_id"] == "cus_1"
    assert stripe.create_checkout.call_args.kwargs["app_user_id"] == "user-1"


def test_checkout_return_does_not_grant_entitlement():
    store = InMemoryStore()
    CheckoutService(config(), store, gateway()).create(VerifiedUser("user-1"))
    assert store.entitlements == {}


def signature(raw, secret="whsec_secret", stamp=1000):
    digest = hmac.new(
        secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return f"t={stamp},v1={digest}"


def test_webhook_signature_rejection_happens_before_json_trust():
    raw = b'{"id":"evt"}'
    with pytest.raises(InvalidWebhookSignature):
        parse_verified_event(raw + b" ", signature(raw), "whsec_secret", now=1000)
    bad_json = b"not-json"
    with pytest.raises(BillingError):
        parse_verified_event(bad_json, signature(bad_json), "whsec_secret", now=1000)


def test_webhook_updates_only_customer_owner_and_duplicate_is_idempotent():
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    processor = WebhookProcessor(config(), store, gateway())
    assert processor.process(event()) == "processed"
    assert processor.process(event()) == "duplicate"
    snapshot = store.entitlements["user-1"][0]
    assert snapshot.entitlement is EntitlementLevel.PRO_ACTIVE
    assert "user-2" not in store.entitlements


def test_unknown_customer_and_conflicting_metadata_cannot_choose_user():
    unknown = InMemoryStore()
    with pytest.raises(BillingError):
        WebhookProcessor(config(), unknown, gateway()).process(event())
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    bad = subscription()
    bad["metadata"] = {"app_user_id": "user-2"}
    with pytest.raises(BillingError):
        WebhookProcessor(config(), store, gateway(bad)).process(event("evt_bad"))
    assert store.entitlements == {}


def test_out_of_order_event_cannot_resurrect_or_downgrade_access():
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    WebhookProcessor(config(), store, gateway(subscription("active"))).process(
        event("evt_new", 200)
    )
    WebhookProcessor(config(), store, gateway(subscription("canceled"))).process(
        event("evt_old", 100)
    )
    assert store.entitlements["user-1"][0].entitlement is EntitlementLevel.PRO_ACTIVE


def test_webhook_lifecycle_past_due_recovery_and_cancellation():
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    WebhookProcessor(config(), store, gateway(subscription("active"))).process(
        event("evt_active", 100)
    )
    assert store.entitlements["user-1"][0].entitlement is EntitlementLevel.PRO_ACTIVE

    WebhookProcessor(config(), store, gateway(subscription("past_due"))).process(
        event("evt_failed", 110, event_type="invoice.payment_failed")
    )
    assert store.entitlements["user-1"][0].status is SubscriptionStatus.PAST_DUE
    assert not store.entitlements["user-1"][0].grants_pro

    WebhookProcessor(config(), store, gateway(subscription("active"))).process(
        event("evt_paid", 120, event_type="invoice.paid")
    )
    assert store.entitlements["user-1"][0].grants_pro

    deleted = event("evt_deleted", 130, event_type="customer.subscription.deleted")
    deleted["data"]["object"] = subscription("canceled")
    WebhookProcessor(config(), store, gateway()).process(deleted)
    assert store.entitlements["user-1"][0].status is SubscriptionStatus.CANCELED
    assert not store.entitlements["user-1"][0].grants_pro


@pytest.mark.parametrize(
    "status,plan,mapped,level",
    [
        ("active", Plan.PRO, SubscriptionStatus.ACTIVE, EntitlementLevel.PRO_ACTIVE),
        ("trialing", Plan.PRO, SubscriptionStatus.TRIALING, EntitlementLevel.PRO_ACTIVE),
        ("past_due", Plan.PRO, SubscriptionStatus.PAST_DUE, EntitlementLevel.PRO_INACTIVE),
        ("canceled", Plan.PRO, SubscriptionStatus.CANCELED, EntitlementLevel.PRO_INACTIVE),
        ("unpaid", Plan.PRO, SubscriptionStatus.CANCELED, EntitlementLevel.PRO_INACTIVE),
    ],
)
def test_subscription_projection_semantics(status, plan, mapped, level):
    row = SubscriptionRecord(
        "user-1", "cus_1", "sub_1", BASEBALL_PRO_TEST_PRICE_ID, status, 2000, "evt", 1
    )
    value = project(row, BASEBALL_PRO_TEST_PRICE_ID)
    assert value.plan is plan
    assert value.status is mapped
    assert value.entitlement is level


def test_webhook_accepts_current_stripe_item_level_period_end():
    current = subscription("active")
    current.pop("current_period_end")
    current["items"]["data"][0]["current_period_end"] = 2_500
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    WebhookProcessor(config(), store, gateway(current)).process(event())
    assert store.subscriptions["sub_1"].period_end == 2_500


def test_webhook_accepts_current_stripe_invoice_parent_subscription_reference():
    invoice_event = event("evt_invoice", event_type="invoice.paid")
    invoice_event["data"]["object"].pop("subscription")
    invoice_event["data"]["object"]["parent"] = {
        "type": "subscription_details",
        "subscription_details": {"subscription": "sub_1"},
    }
    store = InMemoryStore()
    store.attach_customer(CustomerRecord("user-1", "cus_1"))
    processor = WebhookProcessor(config(), store, gateway())
    assert processor.process(invoice_event) == "processed"
    assert store.entitlements["user-1"][0].entitlement is EntitlementLevel.PRO_ACTIVE


def test_unauthenticated_and_authenticated_entitlement_states():
    with patch("suite_auth.is_auth_enabled", return_value=True), patch(
        "suite_auth.is_authenticated", return_value=False
    ):
        anonymous = resolve_trusted_entitlement({}, environ={"BASEBALL_BILLING_ROLLOUT": "test"})
    assert anonymous.status is SubscriptionStatus.ANONYMOUS
    assert anonymous.entitlement is EntitlementLevel.FREE

    session = {"_suite_auth_user_id": "user-1", "_suite_auth_tokens": {"access_token": "token"}}
    provider = Mock()
    provider.entitlement_for_user.return_value = EntitlementSnapshot(
        Plan.FREE,
        True,
        "subscriptions",
        SubscriptionStatus.INACTIVE,
        "user-1",
    )
    with patch("suite_auth.is_auth_enabled", return_value=True), patch(
        "suite_auth.is_authenticated", return_value=True
    ):
        free = resolve_trusted_entitlement(
            session,
            provider=provider,
            environ={"BASEBALL_BILLING_ROLLOUT": "test"},
        )
    assert free.entitlement is EntitlementLevel.FREE


@pytest.mark.parametrize(
    "plan,status,expected",
    [
        ("pro", "active", EntitlementLevel.PRO_ACTIVE),
        ("pro", "canceled", EntitlementLevel.PRO_INACTIVE),
        ("free", "inactive", EntitlementLevel.FREE),
    ],
)
def test_user_jwt_provider_reads_only_requested_subscription(plan, status, expected):
    from baseball_billing_supabase import SupabaseEntitlementProvider

    response = Mock()
    response.ok = True
    response.content = b"json"
    response.json.return_value = [
        {
            "user_id": "user-1",
            "plan": plan,
            "status": status,
            "stripe_customer_id": "cus_1" if plan == "pro" else None,
            "stripe_subscription_id": "sub_1" if plan == "pro" else None,
            "current_period_end": "2026-11-01T00:00:00+00:00" if plan == "pro" else None,
        }
    ]
    with patch("baseball_billing_supabase.requests.request", return_value=response) as request:
        value = SupabaseEntitlementProvider(config(), "user-jwt").entitlement_for_user(
            "user-1"
        )
    assert value.entitlement is expected
    call = request.call_args
    assert call.kwargs["params"]["user_id"] == "eq.user-1"
    assert call.kwargs["headers"]["apikey"] == "anon-public"
    assert call.kwargs["headers"]["Authorization"] == "Bearer user-jwt"


def test_portal_requires_an_authenticated_user_with_customer():
    service = CheckoutService(config(), InMemoryStore(), gateway())
    with pytest.raises(AuthenticationRequired):
        service.portal(VerifiedUser(""))
    with pytest.raises(BillingError):
        service.portal(VerifiedUser("user-1"))


def test_checkout_endpoint_ignores_client_price_and_plan_fields():
    import baseball_billing_service as service

    store = InMemoryStore()
    stripe = gateway()

    class Request:
        headers = {"authorization": "Bearer signed-user-token"}

        async def json(self):
            return {"price": "price_attacker", "plan": "pro", "user_id": "victim"}

    with patch.object(service, "deps", return_value=(config(), store, stripe)), patch.object(
        service, "verify_supabase_user", return_value=VerifiedUser("user-1")
    ):
        response = asyncio.run(service.checkout(Request()))
    assert response.status_code == 201
    assert stripe.create_checkout.call_args.kwargs["price_id"] == BASEBALL_PRO_TEST_PRICE_ID
    assert store.customer_for_user("user-1") is not None
    assert store.customer_for_user("victim") is None


def test_migration_preserves_existing_subscription_schema_and_adds_private_runtime():
    sql = (
        Path(__file__).parents[1]
        / "supabase/migrations/20261008_baseball_billing_runtime.sql"
    ).read_text(encoding="utf-8").lower()
    before_functions = sql.split(
        "create or replace function public.baseball_attach_stripe_customer", 1
    )[0]
    assert "alter table public.subscriptions" not in before_functions
    assert "drop policy" not in before_functions
    assert "create policy" not in before_functions
    assert "grant select on table public.subscriptions" not in before_functions
    assert "revoke all on table public.subscriptions" not in before_functions
    assert re.search(r"(?m)^\s*truncate\b", sql) is None
    assert "insert into public.subscriptions" not in before_functions
    assert "update public.subscriptions" not in before_functions
    assert "delete from public.subscriptions" not in before_functions
    assert "private.baseball_billing_webhook_events" in sql
    assert "private.baseball_billing_subscription_versions" in sql
    assert "create schema if not exists private" in sql
    assert "create table if not exists private.baseball_billing_webhook_events" in sql
    assert "create table if not exists private.baseball_billing_subscription_versions" in sql
    assert sql.count("create or replace function public.baseball_") == 4
    assert "public.subscriptions must exist" in sql
    assert "client write policies must not exist" in sql
    assert "auth.uid() ownership select policy" in sql
    assert "from public, anon, authenticated" in sql


def test_live_schema_preflight_is_read_only():
    sql = (
        Path(__file__).parents[1]
        / "supabase/preflight/baseball_billing_preflight.sql"
    ).read_text(encoding="utf-8").lower()
    statements = [
        line.strip()
        for line in sql.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    joined = "\n".join(statements)
    for forbidden in (
        "insert into ",
        "update public.",
        "delete from ",
        "alter table ",
        "create table ",
        "drop table ",
        "truncate ",
        "grant ",
        "revoke ",
    ):
        assert forbidden not in joined
