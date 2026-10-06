"""Supabase billing adapters: service-role writes and user-JWT RLS reads."""
from __future__ import annotations
from typing import Mapping
import requests
from baseball_billing import BillingError,CustomerRecord,EventClaim,EventLease,SubscriptionRecord
from baseball_monetization import EntitlementSnapshot,Plan,SubscriptionStatus

class Rest:
    def __init__(self,url,key,bearer=None): self.url=url.rstrip("/"); self.key=key; self.bearer=bearer or key
    def request(self,method,path,*,params=None,body=None,prefer="return=representation"):
        r=requests.request(method,f"{self.url}/rest/v1/{path}",params=params,json=body,headers={"apikey":self.key,"Authorization":f"Bearer {self.bearer}","Prefer":prefer},timeout=12)
        if not r.ok: raise BillingError(f"Billing database request failed ({r.status_code})")
        return r.json() if r.content else None
def _first(v): return v[0] if isinstance(v,list) and v else (v if isinstance(v,Mapping) else None)

class SupabaseBillingStore:
    def __init__(self,config):
        if not config.supabase_url or not config.supabase_service_role_key: raise BillingError("Server billing storage is not configured")
        self.db=Rest(config.supabase_url,config.supabase_service_role_key)
    def customer_for_user(self,u): return self._customer(_first(self.db.request("GET","billing_customers",params={"app_user_id":f"eq.{u}","select":"*"})))
    def customer_by_stripe_id(self,c): return self._customer(_first(self.db.request("GET","billing_customers",params={"stripe_customer_id":f"eq.{c}","select":"*"})))
    def _customer(self,r): return CustomerRecord(str(r["app_user_id"]),str(r["stripe_customer_id"])) if r else None
    def upsert_customer(self,row):
        self.db.request("POST","billing_customers",body={"app_user_id":row.app_user_id,"stripe_customer_id":row.stripe_customer_id},prefer="resolution=ignore-duplicates,return=minimal")
        if self.customer_for_user(row.app_user_id)!=row or self.customer_by_stripe_id(row.stripe_customer_id)!=row: raise BillingError("Customer ownership conflict")
    def _rpc(self,name,body):
        v=self.db.request("POST",f"rpc/{name}",body=body); return v[0] if isinstance(v,list) and v else v
    def claim_event(self,e,t,c,f,l):
        value=self._rpc("billing_claim_webhook_event_v2",{"p_event_id":e,"p_event_type":t,"p_event_created":c,"p_fingerprint":f,"p_livemode":l})
        return EventLease(EventClaim(str(value.get("claim") if isinstance(value,Mapping) else value).strip('"')),str(value.get("lease_token") or "") if isinstance(value,Mapping) else "")
    def apply_subscription_if_newer(self,r): return bool(self._rpc("billing_apply_subscription",{"p_app_user_id":r.app_user_id,"p_customer_id":r.customer_id,"p_subscription_id":r.subscription_id,"p_price_id":r.price_id,"p_status":r.provider_status,"p_period_end":r.period_end,"p_cancel_at_period_end":r.cancel_at_period_end,"p_event_id":r.event_id,"p_event_created":r.event_created}))
    def save_entitlement(self,u,s,e,c,sub): self._rpc("billing_save_entitlement",{"p_app_user_id":u,"p_plan":s.plan.value,"p_status":s.status.value,"p_period_end":s.current_period_end or None,"p_subscription_id":sub,"p_event_id":e,"p_event_created":c})
    def mark_event_processed(self,e,token):
        if not self._rpc("billing_finish_webhook_event_v2",{"p_event_id":e,"p_lease_token":token,"p_state":"processed","p_error":None}): raise BillingError("Webhook lease ownership lost")
    def mark_event_failed(self,e,token,error):
        if not self._rpc("billing_finish_webhook_event_v2",{"p_event_id":e,"p_lease_token":token,"p_state":"failed","p_error":str(error)[:1000]}): raise BillingError("Webhook lease ownership lost")

class SupabaseEntitlementProvider:
    def __init__(self,config,token):
        if not config.supabase_url or not config.supabase_anon_key or not token: raise BillingError("Entitlement read is not configured")
        self.db=Rest(config.supabase_url,config.supabase_anon_key,token)
    def entitlement_for_user(self,u):
        r=_first(self.db.request("GET","billing_entitlements",params={"app_user_id":f"eq.{u}","select":"*"}))
        if not r: return None
        if str(r.get("app_user_id"))!=u: raise BillingError("Entitlement ownership mismatch")
        try: return EntitlementSnapshot(Plan(str(r["plan"])),True,"billing_database",SubscriptionStatus(str(r["status"])),u,str(r.get("current_period_end") or ""))
        except ValueError: return EntitlementSnapshot(ready=False,source="billing_database",status=SubscriptionStatus.UNKNOWN,user_id=u)
