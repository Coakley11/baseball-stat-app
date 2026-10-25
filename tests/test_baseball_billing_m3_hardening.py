import time
from dataclasses import replace
from unittest.mock import Mock,patch
import pytest

from baseball_billing import *
from baseball_billing_config import BillingConfig,RolloutMode,trusted_url

def cfg(**kw):
    base=BillingConfig(RolloutMode.TEST,"test","sk_test_RECOGNIZABLE_SECRET","whsec_RECOGNIZABLE_SECRET","price_pro","https://app.test","https://billing.test","https://db.test","SERVICE_ROLE_RECOGNIZABLE_SECRET","ANON_RECOGNIZABLE_VALUE")
    return replace(base,**kw)
def sub(customer="cus_1",metadata=None,status="active"):
    return {"id":"sub_1","customer":customer,"status":status,"metadata":metadata or {},"items":{"data":[{"price":{"id":"price_pro"}}]}}
def evt(eid="evt_1",created=100,obj=None): return {"id":eid,"type":"customer.subscription.updated","created":created,"livemode":False,"data":{"object":obj or sub()}}

def test_metadata_never_establishes_unknown_customer_ownership():
    store=InMemoryStore(); p=WebhookProcessor(cfg(),store,Mock())
    with pytest.raises(BillingError): p.process(evt(obj=sub("cus_unknown",{"app_user_id":"victim"})))
    assert not store.entitlements
def test_empty_customer_fails_without_projection():
    store=InMemoryStore(); p=WebhookProcessor(cfg(),store,Mock())
    with pytest.raises(BillingError): p.process(evt(obj=sub("",{"app_user_id":"user-1"})))
    assert not store.entitlements
def test_conflicting_metadata_fails_closed_against_trusted_mapping():
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("user-1","cus_1"))
    with pytest.raises(BillingError): WebhookProcessor(cfg(),store,Mock()).process(evt(obj=sub(metadata={"app_user_id":"attacker"})))
    assert not store.entitlements
def test_customer_one_to_one_races_fail_closed():
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("user-1","cus_1"))
    with pytest.raises(BillingError): store.upsert_customer(CustomerRecord("user-1","cus_2"))
    with pytest.raises(BillingError): store.upsert_customer(CustomerRecord("user-2","cus_1"))

def test_active_lease_blocks_second_worker_and_owner_token_controls_finish():
    store=InMemoryStore(); first=store.claim_event("evt","type",1,"fp",False); second=store.claim_event("evt","type",1,"fp",False)
    assert first.claim is EventClaim.NEW and first.token
    assert second.claim is EventClaim.IN_PROGRESS and not second.token
    with pytest.raises(BillingError): store.mark_event_processed("evt","wrong-token")
    store.mark_event_processed("evt",first.token)
    assert store.claim_event("evt","type",1,"fp",False).claim is EventClaim.DUPLICATE
def test_expired_lease_recovery_invalidates_abandoned_worker():
    store=InMemoryStore(); old=store.claim_event("evt","type",1,"fp",False); store.events["evt"]["updated"]-=LEASE_SECONDS+1
    new=store.claim_event("evt","type",1,"fp",False)
    assert new.claim is EventClaim.RETRY and new.token!=old.token
    with pytest.raises(BillingError): store.mark_event_failed("evt",old.token,"late")
    store.mark_event_failed("evt",new.token,"retryable")
    assert store.events["evt"]["state"]=="failed" and store.events["evt"]["attempts"]==2
def test_collision_is_audited_without_overwriting_original():
    store=InMemoryStore(); original=store.claim_event("evt","type",1,"fp-one",False)
    collision=store.claim_event("evt","other",2,"fp-two",False)
    assert collision.claim is EventClaim.COLLISION and store.events["evt"]["fingerprint"]=="fp-one" and store.events["evt"]["collision_count"]==1
    store.mark_event_processed("evt",original.token)

def test_checkout_idempotency_is_stable_server_derived_and_client_cannot_supply_it():
    store=InMemoryStore(); gateway=Mock(); gateway.create_customer.return_value="cus_1"; gateway.create_checkout.return_value={"url":"https://checkout.stripe.com/test"}
    service=CheckoutService(cfg(),store,gateway)
    with patch("baseball_billing.time.time",return_value=1_800_000_000):
        service.create(VerifiedUser("user-1")); service.create(VerifiedUser("user-1"))
    calls=gateway.create_checkout.call_args_list
    assert calls[0].kwargs["idempotency_key"]==calls[1].kwargs["idempotency_key"]
    assert "user-1" not in calls[0].kwargs["idempotency_key"]
    assert gateway.create_customer.call_count==1

def test_equal_timestamp_event_id_tie_break_prevents_resurrection():
    store=InMemoryStore()
    newer=SubscriptionRecord("u","c","s","p","canceled",0,False,"evt_z",100)
    older=SubscriptionRecord("u","c","s","p","active",0,False,"evt_a",100)
    assert store.apply_subscription_if_newer(newer)
    assert not store.apply_subscription_if_newer(older)
def test_wrong_provider_mode_never_claims_event():
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("u","c")); live=evt(); live["livemode"]=True
    with pytest.raises(BillingError): WebhookProcessor(cfg(),store,Mock()).process(live)
    assert not store.events

@pytest.mark.parametrize("url,allow,expected",[("https://billing.example.com",False,True),("http://localhost:8000",True,True),("http://localhost:8000",False,False),("http://evil.example",True,False),("https://user:pass@example.com",False,False),("https://example.com?q=secret",False,False)])
def test_trusted_url_policy(url,allow,expected): assert trusted_url(url,allow_loopback=allow) is expected
def test_live_requires_explicit_mode_https_and_distinct_supabase_roles():
    live=replace(cfg(),rollout=RolloutMode.LIVE,stripe_mode="live",stripe_secret_key="sk_live_secret")
    assert live.checkout_enabled
    assert not replace(live,public_base_url="http://localhost:8501").checkout_enabled
    assert not replace(live,supabase_anon_key=live.supabase_service_role_key).checkout_enabled
def test_public_status_and_errors_do_not_leak_recognizable_secrets():
    text=repr(cfg().public_status())
    for secret in ("RECOGNIZABLE_SECRET","SERVICE_ROLE_RECOGNIZABLE_SECRET","ANON_RECOGNIZABLE_VALUE"): assert secret not in text

def test_rollout_ui_matrix_off_preview_and_public_test_client():
    import baseball_billing_client as client
    with patch.object(client,"authenticated_subject",return_value=("user-1",True,"bearer")):
        assert client.billing_ui_state({}, {"BASEBALL_BILLING_ROLLOUT":"off"})["action"]=="disabled"
        assert client.billing_ui_state({}, {"BASEBALL_BILLING_ROLLOUT":"preview"})["action"]=="disabled"
        public_test={"BASEBALL_BILLING_ROLLOUT":"test","BASEBALL_STRIPE_MODE":"test","BASEBALL_BILLING_SERVICE_URL":"http://localhost:8000","BASEBALL_BILLING_SUPABASE_URL":"https://db.test","BASEBALL_BILLING_SUPABASE_ANON_KEY":"anon"}
        assert client.billing_ui_state({},public_test)["action"]=="checkout"
        assert not BillingConfig.from_environ(public_test).checkout_enabled  # server secrets remain absent

def test_forward_migration_reasserts_rls_and_privileged_function_revokes():
    from pathlib import Path
    sql=(Path(__file__).parents[1]/"supabase/migrations/20261007_baseball_billing_m3_hardening.sql").read_text()
    assert "lease_token uuid" in sql and "collision_count" in sql
    assert "from public,anon,authenticated" in sql
    assert "revoke all on public.billing_customers,public.billing_subscriptions,public.billing_webhook_events" in sql
    assert "revoke insert,update,delete on public.billing_entitlements" in sql
def test_m2_migration_remains_unmodified_in_m3_commit():
    from pathlib import Path
    assert (Path(__file__).parents[1]/"supabase/migrations/20261006_baseball_billing_m2.sql").exists()

def test_oversized_declared_body_rejected_before_read():
    import asyncio
    from baseball_billing_service import webhook
    class Request:
        headers={"content-length":"1000001"}
        async def body(self): raise AssertionError("body must not be read")
    response=asyncio.run(webhook(Request()))
    assert response.status_code==413 and b"secret" not in response.body.lower()

def test_normal_signed_raw_body_reaches_processor_unchanged():
    import asyncio,hashlib,hmac,json
    import baseball_billing_service as service
    raw=json.dumps(evt(),separators=(",",":")).encode(); stamp=int(time.time())
    digest=hmac.new(cfg().stripe_webhook_secret.encode(),str(stamp).encode()+b"."+raw,hashlib.sha256).hexdigest()
    class Request:
        headers={"content-length":str(len(raw)),"stripe-signature":f"t={stamp},v1={digest}"}
        async def body(self): return raw
    store=InMemoryStore(); store.upsert_customer(CustomerRecord("user-1","cus_1"))
    with patch.object(service,"deps",return_value=(cfg(),store,Mock())):
        response=asyncio.run(service.webhook(Request()))
    assert response.status_code==200 and store.entitlements["user-1"][0].plan.value=="pro"

def test_oversized_actual_body_rejected_when_length_is_absent():
    import asyncio
    from baseball_billing_service import webhook
    class Request:
        headers={}
        async def body(self): return b"x"*1_000_001
    assert asyncio.run(webhook(Request())).status_code==413

def test_delayed_hydration_then_pro_updates_central_interface_without_false_free():
    from baseball_monetization import EntitlementSnapshot,Plan,SubscriptionStatus,resolve_trusted_entitlement
    session={"_suite_auth_user_id":"user-1","_suite_auth_tokens":{"access_token":"token"}}
    provider=Mock(); provider.entitlement_for_user.side_effect=[RuntimeError("loading"),EntitlementSnapshot(Plan.PRO,True,"billing_database",SubscriptionStatus.ACTIVE,"user-1")]
    env={"BASEBALL_BILLING_ROLLOUT":"test"}
    with patch("suite_auth.is_auth_enabled",return_value=True),patch("suite_auth.is_authenticated",return_value=True):
        loading=resolve_trusted_entitlement(session,provider=provider,environ=env)
        ready=resolve_trusted_entitlement(session,provider=provider,environ=env)
    assert not loading.ready and loading.status is SubscriptionStatus.UNKNOWN
    assert ready.ready and ready.plan is Plan.PRO

@pytest.mark.parametrize("runtime",["preview","production","live",""])
def test_development_override_never_grants_outside_local_or_test(runtime):
    from baseball_monetization_ui import current_entitlement
    value=current_entitlement({"_dev_monetization_plan":"pro"},developer_mode=True,environ={"BASEBALL_ENTITLEMENT_DEV_CONTROLS":"1","BASEBALL_ENTITLEMENT_RUNTIME":runtime})
    assert value.plan.value=="free"
