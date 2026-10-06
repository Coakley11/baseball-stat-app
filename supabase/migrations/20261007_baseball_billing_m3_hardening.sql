-- M3 forward-only hardening: tokenized webhook leases and explicit collision audit.
alter table public.billing_webhook_events add column if not exists lease_token uuid;
alter table public.billing_webhook_events add column if not exists lease_expires_at timestamptz;
alter table public.billing_webhook_events add column if not exists collision_count integer not null default 0;
alter table public.billing_webhook_events add column if not exists last_collision_at timestamptz;

create or replace function public.billing_claim_webhook_event_v2(p_event_id text,p_event_type text,p_event_created bigint,p_fingerprint text,p_livemode boolean)
returns jsonb language plpgsql security definer set search_path=public as $$
declare r public.billing_webhook_events; token uuid; begin
  if coalesce(p_event_id,'')='' or coalesce(p_event_type,'')='' or coalesce(p_fingerprint,'')='' then raise exception 'invalid event claim'; end if;
  select * into r from public.billing_webhook_events where stripe_event_id=p_event_id for update;
  if found then
    if r.event_type<>p_event_type or r.event_created<>p_event_created or r.payload_fingerprint<>p_fingerprint or r.livemode<>p_livemode then
      update public.billing_webhook_events set collision_count=least(collision_count+1,1000000),last_collision_at=now(),updated_at=now() where stripe_event_id=p_event_id;
      return jsonb_build_object('claim','collision','lease_token','');
    end if;
    if r.processing_state='processed' then return jsonb_build_object('claim','duplicate','lease_token',''); end if;
    if r.processing_state='processing' and r.lease_expires_at>now() then return jsonb_build_object('claim','in_progress','lease_token',''); end if;
    token=gen_random_uuid();
    update public.billing_webhook_events set processing_state='processing',attempt_count=least(attempt_count+1,100),last_error=null,lease_token=token,lease_expires_at=now()+interval '5 minutes',processing_started_at=now(),updated_at=now() where stripe_event_id=p_event_id;
    return jsonb_build_object('claim','retry','lease_token',token::text);
  end if;
  token=gen_random_uuid();
  insert into public.billing_webhook_events(stripe_event_id,event_type,event_created,payload_fingerprint,livemode,processing_state,lease_token,lease_expires_at) values(p_event_id,p_event_type,p_event_created,p_fingerprint,p_livemode,'processing',token,now()+interval '5 minutes');
  return jsonb_build_object('claim','new','lease_token',token::text);
end $$;

create or replace function public.billing_finish_webhook_event_v2(p_event_id text,p_lease_token uuid,p_state text,p_error text)
returns boolean language plpgsql security definer set search_path=public as $$
declare changed integer; begin
  if p_state not in ('processed','failed') then raise exception 'invalid terminal state'; end if;
  update public.billing_webhook_events set processing_state=p_state,last_error=case when p_state='failed' then left(coalesce(p_error,''),1000) else null end,processed_at=case when p_state='processed' then now() else null end,lease_token=null,lease_expires_at=null,updated_at=now()
  where stripe_event_id=p_event_id and processing_state='processing' and lease_token=p_lease_token;
  get diagnostics changed=row_count; return changed=1;
end $$;

revoke all on function public.billing_claim_webhook_event_v2(text,text,bigint,text,boolean) from public,anon,authenticated;
revoke all on function public.billing_finish_webhook_event_v2(text,uuid,text,text) from public,anon,authenticated;
revoke all on public.billing_customers,public.billing_subscriptions,public.billing_webhook_events from anon,authenticated;
revoke insert,update,delete on public.billing_entitlements from anon,authenticated;
grant select on public.billing_entitlements to authenticated;
