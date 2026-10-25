import hashlib,hmac,json,time
from dataclasses import replace
from unittest.mock import Mock,patch
import pytest

from baseball_billing import *
from baseball_billing_config import BillingConfig,RolloutMode
from baseball_monetization import Plan,SubscriptionStatus,resolve_trusted_entitlement

def config(**kw):
    base=BillingConfig(RolloutMode.TEST,"test","sk_test_secret","whsec_secret","price_pro","https://baseball.test","https://billing.test","https://supabase.test","service-secret","anon-public")
    return replace(base,**kw)
def subscription(status="active",cancel=False,price="price_pro",customer="cus_1"):
    return {"id":"sub_1","customer":customer,"status":status,"current_period_end":2000,"cancel_at_period_end":cancel,"metadata":{"app_user_id":"user-1"},"items":{"data":[{"price":{"id":price}}]}}
def event(eid="evt_1",created=100,live=False,status="active",cancel=False):
    return {"id":eid,"type":"customer.subscription.updated","created":created,"livemode":live,"data":{"object":subscription(status,cancel)}}
def gateway(sub=None):
    g=Mock(); g.create_customer.return_value="cus_1"; g.create_checkout.return_value={"url":"https://checkout.stripe.com/test"}; g.create_portal.return_value={"url":"https://billing.stripe.com/test"}; g.retrieve_subscription.return_value=sub or subscription(); return g

def test_rollout_disabled_by_default_and_public_status_has_no_secrets():
    c=BillingConfig.from_environ({})
    assert c.rollout is RolloutMode.OFF and not c.checkout_enabled
    rendered=repr(config().public_status())
    assert "sk_test_secret" not in rendered and "service-secret" not in rendered and "whsec_secret" not in rendered
def test_live_requires_explicit_live_mode_and_matching_credentials():
    assert not replace(config(),rollout=RolloutMode.LIVE).checkout_enabled
    assert replace(config(),rollout=RolloutMode.LIVE,stripe_mode="live",stripe_secret_key="sk_live_x").checkout_enabled

def test_checkout_requires_identity_and_uses_only_trusted_price_customer():
    store=InMemoryStore(); g=gateway(); service=CheckoutService(config(),store,g)
    with pytest.raises(AuthenticationRequired): service.create(VerifiedUser(""))
    with pytest.raises(BillingError): service.create(VerifiedUser("user-1"),intent="client-price-id")
    service.create(VerifiedUser("user-1","u@example.test")); service.create(VerifiedUser("user-1"))
    assert g.create_customer.call_count==1
    assert g.create_checkout.call_args.kwargs["price_id"]=="price_pro"
    assert g.create_checkout.call_args.kwargs["customer_id"]=="cus_1"
def test_success_redirect_does_not_grant_entitlement():
    store=InMemoryStore(); CheckoutService(config(),store,gateway()).create(VerifiedUser("user-1"))
    assert store.entitlements=={}

def signature(raw,secret="whsec_secret",stamp=1000):
    digest=hmac.new(secret.encode(),str(stamp).encode()+b"."+raw,hashlib.sha256).hexdigest(); return f"t={stamp},v1={digest}"
def test_raw_body_signature_valid_invalid_and_malformed_payload():
    raw=b'{"id":"evt"}'
    assert parse_verified_event(raw,signature(raw),"whsec_secret",now=1000)["id"]=="evt"
    with pytest.raises(InvalidWebhookSignature): parse_verified_event(raw+b" ",signature(raw),"whsec_secret",now=1000)
    bad=b"not-json"
    with pytest.raises(BillingError): parse_verified_event(bad,signature(bad),"whsec_secret",now=1000)

def test_webhook_idempotency_retry_and_event_collision():
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("user-1","cus_1")); p=WebhookProcessor(config(),store,gateway())
    assert p.process(event())=="processed" and p.process(event())=="duplicate"
    failed=event("evt_fail",110); store.claim_event("evt_fail",failed["type"],110,"wrong",False); store.events["evt_fail"]["state"]="failed"
    with pytest.raises(BillingError): p.process(failed)
    retry=event("evt_retry",120); fp=hashlib.sha256(json.dumps(retry,sort_keys=True,separators=(",",":")).encode()).hexdigest(); store.claim_event("evt_retry",retry["type"],120,fp,False); store.events["evt_retry"]["state"]="failed"
    assert p.process(retry)=="processed" and store.events["evt_retry"]["attempts"]==2
def test_failed_processing_is_retryable():
    store=InMemoryStore(); p=WebhookProcessor(config(),store,gateway())
    with pytest.raises(BillingError): p.process(event("evt_retryable"))
    assert store.events["evt_retryable"]["state"]=="failed"
    store.upsert_customer(CustomerRecord("user-1","cus_1")); assert p.process(event("evt_retryable"))=="processed"
def test_out_of_order_event_cannot_overwrite_newer_projection():
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("user-1","cus_1")); p=WebhookProcessor(config(),store,gateway())
    p.process(event("evt_new",200,status="active")); p.process(event("evt_old",100,status="canceled"))
    assert store.entitlements["user-1"][0].plan is Plan.PRO
def test_mode_mismatch_rejected_before_claim():
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("user-1","cus_1"))
    with pytest.raises(BillingError): WebhookProcessor(config(),store,gateway()).process(event(live=True))
    assert not store.events

@pytest.mark.parametrize("status,cancel,plan,mapped",[("active",False,Plan.PRO,SubscriptionStatus.ACTIVE),("trialing",False,Plan.PRO,SubscriptionStatus.TRIALING),("active",True,Plan.PRO,SubscriptionStatus.CANCELED_PERIOD_END),("past_due",False,Plan.FREE,SubscriptionStatus.PAST_DUE),("canceled",False,Plan.FREE,SubscriptionStatus.EXPIRED)])
def test_projection_semantics(status,cancel,plan,mapped):
    row=SubscriptionRecord("user-1","cus_1","sub_1","price_pro",status,2000,cancel,"evt",1); value=project(row,"price_pro")
    assert value.plan is plan and value.status is mapped

def test_delayed_hydration_is_unready_not_free(monkeypatch):
    session={"_suite_auth_user_id":"user-1","_suite_auth_tokens":{"access_token":"token"}}
    provider=Mock(); provider.entitlement_for_user.side_effect=RuntimeError("loading")
    with patch("suite_auth.is_auth_enabled",return_value=True),patch("suite_auth.is_authenticated",return_value=True):
        value=resolve_trusted_entitlement(session,provider=provider,environ={"BASEBALL_BILLING_ROLLOUT":"test"})
    assert not value.ready and value.status is SubscriptionStatus.UNKNOWN
def test_production_ignores_session_dev_plan():
    from baseball_monetization_ui import current_entitlement
    value=current_entitlement({"_dev_monetization_plan":"pro"},developer_mode=True,environ={"BASEBALL_ENTITLEMENT_DEV_CONTROLS":"1","BASEBALL_ENTITLEMENT_RUNTIME":"production"})
    assert value.plan is Plan.FREE

def test_migration_enforces_rls_and_no_client_writes():
    sql=(__import__("pathlib").Path(__file__).parents[1]/"supabase/migrations/20261006_baseball_billing_m2.sql").read_text()
    assert "app_user_id=auth.uid()" in sql
    assert "revoke insert,update,delete on public.billing_entitlements" in sql
    assert "revoke all on public.billing_customers,public.billing_subscriptions,public.billing_webhook_events" in sql
