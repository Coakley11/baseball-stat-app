-- Baseball Monetization M2: forward-only trusted billing schema.
create table if not exists public.billing_customers (
  app_user_id uuid primary key references auth.users(id) on delete cascade,
  stripe_customer_id text not null unique,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.billing_subscriptions (
  stripe_subscription_id text primary key,
  app_user_id uuid not null references auth.users(id) on delete cascade,
  stripe_customer_id text not null references public.billing_customers(stripe_customer_id),
  stripe_price_id text, provider_status text not null,
  current_period_end bigint, cancel_at_period_end boolean not null default false,
  latest_event_id text not null, latest_event_created bigint not null,
  updated_at timestamptz not null default now()
);
create index if not exists billing_subscriptions_user_idx on public.billing_subscriptions(app_user_id);
create table if not exists public.billing_entitlements (
  app_user_id uuid primary key references auth.users(id) on delete cascade,
  plan text not null check (plan in ('free','pro')),
  status text not null,
  current_period_end text,
  source_subscription_id text,
  source_event_id text not null,
  source_event_created bigint not null,
  updated_at timestamptz not null default now()
);
create table if not exists public.billing_webhook_events (
  stripe_event_id text primary key, event_type text not null, event_created bigint not null,
  payload_fingerprint text not null, livemode boolean not null,
  processing_state text not null check (processing_state in ('processing','processed','failed')),
  attempt_count integer not null default 1, last_error text,
  processing_started_at timestamptz not null default now(), processed_at timestamptz,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists billing_events_retry_idx on public.billing_webhook_events(processing_state,updated_at);

alter table public.billing_customers enable row level security;
alter table public.billing_subscriptions enable row level security;
alter table public.billing_entitlements enable row level security;
alter table public.billing_webhook_events enable row level security;
revoke all on public.billing_customers,public.billing_subscriptions,public.billing_webhook_events from anon,authenticated;
revoke insert,update,delete on public.billing_entitlements from anon,authenticated;
grant select on public.billing_entitlements to authenticated;
drop policy if exists billing_entitlements_read_own on public.billing_entitlements;
create policy billing_entitlements_read_own on public.billing_entitlements for select to authenticated using (app_user_id=auth.uid());

create or replace function public.billing_claim_webhook_event(p_event_id text,p_event_type text,p_event_created bigint,p_fingerprint text,p_livemode boolean)
returns text language plpgsql security definer set search_path=public as $$
declare r public.billing_webhook_events; begin
  select * into r from public.billing_webhook_events where stripe_event_id=p_event_id for update;
  if found then
    if r.event_type<>p_event_type or r.event_created<>p_event_created or r.payload_fingerprint<>p_fingerprint or r.livemode<>p_livemode then raise exception 'event id collision'; end if;
    if r.processing_state='processed' then return 'duplicate'; end if;
    if r.processing_state='processing' and r.updated_at>now()-interval '5 minutes' then return 'in_progress'; end if;
    update public.billing_webhook_events set processing_state='processing',attempt_count=attempt_count+1,last_error=null,processing_started_at=now(),updated_at=now() where stripe_event_id=p_event_id;
    return 'retry';
  end if;
  insert into public.billing_webhook_events(stripe_event_id,event_type,event_created,payload_fingerprint,livemode,processing_state) values(p_event_id,p_event_type,p_event_created,p_fingerprint,p_livemode,'processing');
  return 'new';
end $$;

create or replace function public.billing_apply_subscription(p_app_user_id uuid,p_customer_id text,p_subscription_id text,p_price_id text,p_status text,p_period_end bigint,p_cancel_at_period_end boolean,p_event_id text,p_event_created bigint)
returns boolean language plpgsql security definer set search_path=public as $$
declare old_created bigint; old_id text; begin
  if not exists(select 1 from public.billing_customers where app_user_id=p_app_user_id and stripe_customer_id=p_customer_id) then raise exception 'customer ownership mismatch'; end if;
  select latest_event_created,latest_event_id into old_created,old_id from public.billing_subscriptions where stripe_subscription_id=p_subscription_id for update;
  if found and (old_created>p_event_created or (old_created=p_event_created and old_id>=p_event_id)) then return false; end if;
  insert into public.billing_subscriptions values(p_subscription_id,p_app_user_id,p_customer_id,p_price_id,p_status,p_period_end,p_cancel_at_period_end,p_event_id,p_event_created,now())
  on conflict(stripe_subscription_id) do update set stripe_price_id=excluded.stripe_price_id,provider_status=excluded.provider_status,current_period_end=excluded.current_period_end,cancel_at_period_end=excluded.cancel_at_period_end,latest_event_id=excluded.latest_event_id,latest_event_created=excluded.latest_event_created,updated_at=now();
  return true;
end $$;

create or replace function public.billing_save_entitlement(p_app_user_id uuid,p_plan text,p_status text,p_period_end text,p_subscription_id text,p_event_id text,p_event_created bigint)
returns void language plpgsql security definer set search_path=public as $$ begin
  insert into public.billing_entitlements values(p_app_user_id,p_plan,p_status,p_period_end,p_subscription_id,p_event_id,p_event_created,now())
  on conflict(app_user_id) do update set plan=excluded.plan,status=excluded.status,current_period_end=excluded.current_period_end,source_subscription_id=excluded.source_subscription_id,source_event_id=excluded.source_event_id,source_event_created=excluded.source_event_created,updated_at=now()
  where (billing_entitlements.source_event_created,billing_entitlements.source_event_id)<=(excluded.source_event_created,excluded.source_event_id);
end $$;
revoke all on function public.billing_claim_webhook_event(text,text,bigint,text,boolean) from public,anon,authenticated;
revoke all on function public.billing_apply_subscription(uuid,text,text,text,text,bigint,boolean,text,bigint) from public,anon,authenticated;
revoke all on function public.billing_save_entitlement(uuid,text,text,text,text,text,bigint) from public,anon,authenticated;
