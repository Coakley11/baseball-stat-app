-- Baseball billing runtime additions for an EXISTING public.subscriptions table.
--
-- This migration intentionally does not create, alter, truncate, or backfill
-- public.subscriptions. It does not change the existing signup trigger, grants,
-- constraints, policies, or rows. The first block fails closed if the live table
-- does not match the security contract established before this migration.

begin;

do $$
declare
  missing_columns text;
begin
  if to_regclass('public.subscriptions') is null then
    raise exception 'public.subscriptions must exist before applying Baseball billing runtime';
  end if;

  select string_agg(required.column_name, ', ' order by required.column_name)
  into missing_columns
  from (
    values
      ('user_id'),
      ('plan'),
      ('status'),
      ('stripe_customer_id'),
      ('stripe_subscription_id'),
      ('current_period_end'),
      ('created_at'),
      ('updated_at')
  ) as required(column_name)
  where not exists (
    select 1
    from information_schema.columns existing
    where existing.table_schema = 'public'
      and existing.table_name = 'subscriptions'
      and existing.column_name = required.column_name
  );

  if missing_columns is not null then
    raise exception 'public.subscriptions is missing required columns: %', missing_columns;
  end if;

  if not exists (
    select 1
    from pg_class relation
    join pg_namespace namespace on namespace.oid = relation.relnamespace
    where namespace.nspname = 'public'
      and relation.relname = 'subscriptions'
      and relation.relrowsecurity
  ) then
    raise exception 'RLS must already be enabled on public.subscriptions';
  end if;

  if not has_table_privilege('authenticated', 'public.subscriptions', 'SELECT') then
    raise exception 'authenticated must already have SELECT on public.subscriptions';
  end if;

  if not exists (
    select 1
    from pg_policies policy
    where policy.schemaname = 'public'
      and policy.tablename = 'subscriptions'
      and policy.cmd = 'SELECT'
      and ('authenticated' = any(policy.roles) or 'public' = any(policy.roles))
      and policy.qual ilike '%auth.uid%'
      and policy.qual ilike '%user_id%'
  ) then
    raise exception 'an authenticated auth.uid() ownership SELECT policy must already protect public.subscriptions';
  end if;

  if exists (
    select 1
    from pg_policies policy
    where policy.schemaname = 'public'
      and policy.tablename = 'subscriptions'
      and policy.cmd in ('INSERT', 'UPDATE', 'DELETE', 'ALL')
      and ('authenticated' = any(policy.roles) or 'public' = any(policy.roles))
  ) then
    raise exception 'client write policies must not exist on public.subscriptions';
  end if;
end
$$;

create schema if not exists private;

create table if not exists private.baseball_billing_webhook_events (
  stripe_event_id text primary key,
  event_type text not null,
  event_created bigint not null,
  payload_fingerprint text not null,
  livemode boolean not null,
  processing_state text not null check (processing_state in ('processing','processed','failed')),
  attempt_count integer not null default 1,
  last_error text,
  lease_token uuid,
  lease_expires_at timestamptz,
  collision_count integer not null default 0,
  last_collision_at timestamptz,
  processing_started_at timestamptz not null default now(),
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists baseball_billing_events_retry_idx
on private.baseball_billing_webhook_events(processing_state, updated_at);

create table if not exists private.baseball_billing_subscription_versions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  stripe_subscription_id text not null,
  latest_event_id text not null,
  latest_event_created bigint not null,
  updated_at timestamptz not null default now()
);

alter table private.baseball_billing_webhook_events enable row level security;
alter table private.baseball_billing_subscription_versions enable row level security;
revoke all on schema private from anon, authenticated;
revoke all on table private.baseball_billing_webhook_events from anon, authenticated;
revoke all on table private.baseball_billing_subscription_versions from anon, authenticated;
grant usage on schema private to service_role;
grant select, insert, update, delete on table private.baseball_billing_webhook_events to service_role;
grant select, insert, update, delete on table private.baseball_billing_subscription_versions to service_role;

create or replace function public.baseball_attach_stripe_customer(
  p_user_id uuid,
  p_customer_id text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  changed integer;
begin
  if p_user_id is null or coalesce(p_customer_id, '') = '' then
    return false;
  end if;
  update public.subscriptions
  set stripe_customer_id = p_customer_id, updated_at = now()
  where user_id = p_user_id
    and (stripe_customer_id is null or stripe_customer_id = p_customer_id);
  get diagnostics changed = row_count;
  return changed = 1;
end
$$;

create or replace function public.baseball_claim_webhook_event(
  p_event_id text,
  p_event_type text,
  p_event_created bigint,
  p_fingerprint text,
  p_livemode boolean
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  existing private.baseball_billing_webhook_events%rowtype;
  token uuid;
begin
  if coalesce(p_event_id, '') = ''
     or coalesce(p_event_type, '') = ''
     or coalesce(p_fingerprint, '') = ''
     or p_event_created <= 0 then
    raise exception 'invalid event claim';
  end if;
  select * into existing
  from private.baseball_billing_webhook_events
  where stripe_event_id = p_event_id
  for update;
  if found then
    if existing.event_type <> p_event_type
       or existing.event_created <> p_event_created
       or existing.payload_fingerprint <> p_fingerprint
       or existing.livemode <> p_livemode then
      update private.baseball_billing_webhook_events
      set collision_count = least(collision_count + 1, 1000000),
          last_collision_at = now(),
          updated_at = now()
      where stripe_event_id = p_event_id;
      return jsonb_build_object('claim', 'collision', 'lease_token', '');
    end if;
    if existing.processing_state = 'processed' then
      return jsonb_build_object('claim', 'duplicate', 'lease_token', '');
    end if;
    if existing.processing_state = 'processing'
       and existing.lease_expires_at > now() then
      return jsonb_build_object('claim', 'in_progress', 'lease_token', '');
    end if;
    token = gen_random_uuid();
    update private.baseball_billing_webhook_events
    set processing_state = 'processing',
        attempt_count = least(attempt_count + 1, 100),
        last_error = null,
        lease_token = token,
        lease_expires_at = now() + interval '5 minutes',
        processing_started_at = now(),
        updated_at = now()
    where stripe_event_id = p_event_id;
    return jsonb_build_object('claim', 'retry', 'lease_token', token::text);
  end if;
  token = gen_random_uuid();
  insert into private.baseball_billing_webhook_events(
    stripe_event_id, event_type, event_created, payload_fingerprint,
    livemode, processing_state, lease_token, lease_expires_at
  ) values (
    p_event_id, p_event_type, p_event_created, p_fingerprint,
    p_livemode, 'processing', token, now() + interval '5 minutes'
  );
  return jsonb_build_object('claim', 'new', 'lease_token', token::text);
end
$$;

create or replace function public.baseball_apply_subscription_event(
  p_user_id uuid,
  p_customer_id text,
  p_subscription_id text,
  p_plan text,
  p_status text,
  p_period_end timestamptz,
  p_event_id text,
  p_event_created bigint,
  p_lease_token uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  previous private.baseball_billing_subscription_versions%rowtype;
begin
  if p_plan not in ('free', 'pro')
     or p_status not in ('inactive', 'active', 'trialing', 'past_due', 'canceled') then
    raise exception 'invalid subscription projection';
  end if;
  if not exists (
    select 1 from private.baseball_billing_webhook_events
    where stripe_event_id = p_event_id
      and processing_state = 'processing'
      and lease_token = p_lease_token
      and lease_expires_at > now()
  ) then
    raise exception 'webhook lease ownership lost';
  end if;
  if not exists (
    select 1 from public.subscriptions
    where user_id = p_user_id and stripe_customer_id = p_customer_id
    for update
  ) then
    raise exception 'customer ownership mismatch';
  end if;
  select * into previous
  from private.baseball_billing_subscription_versions
  where user_id = p_user_id
  for update;
  if found and (
    previous.latest_event_created > p_event_created
    or (
      previous.latest_event_created = p_event_created
      and previous.latest_event_id >= p_event_id
    )
  ) then
    return false;
  end if;
  update public.subscriptions
  set plan = p_plan,
      status = p_status,
      stripe_customer_id = p_customer_id,
      stripe_subscription_id = p_subscription_id,
      current_period_end = p_period_end,
      updated_at = now()
  where user_id = p_user_id and stripe_customer_id = p_customer_id;
  insert into private.baseball_billing_subscription_versions(
    user_id, stripe_subscription_id, latest_event_id, latest_event_created, updated_at
  ) values (
    p_user_id, p_subscription_id, p_event_id, p_event_created, now()
  )
  on conflict (user_id) do update
  set stripe_subscription_id = excluded.stripe_subscription_id,
      latest_event_id = excluded.latest_event_id,
      latest_event_created = excluded.latest_event_created,
      updated_at = now();
  return true;
end
$$;

create or replace function public.baseball_finish_webhook_event(
  p_event_id text,
  p_lease_token uuid,
  p_state text,
  p_error text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  changed integer;
begin
  if p_state not in ('processed', 'failed') then
    raise exception 'invalid terminal state';
  end if;
  update private.baseball_billing_webhook_events
  set processing_state = p_state,
      last_error = case when p_state = 'failed' then left(coalesce(p_error, ''), 1000) else null end,
      processed_at = case when p_state = 'processed' then now() else null end,
      lease_token = null,
      lease_expires_at = null,
      updated_at = now()
  where stripe_event_id = p_event_id
    and processing_state = 'processing'
    and lease_token = p_lease_token;
  get diagnostics changed = row_count;
  return changed = 1;
end
$$;

revoke all on function public.baseball_attach_stripe_customer(uuid, text) from public, anon, authenticated;
revoke all on function public.baseball_claim_webhook_event(text, text, bigint, text, boolean) from public, anon, authenticated;
revoke all on function public.baseball_apply_subscription_event(uuid, text, text, text, text, timestamptz, text, bigint, uuid) from public, anon, authenticated;
revoke all on function public.baseball_finish_webhook_event(text, uuid, text, text) from public, anon, authenticated;
grant execute on function public.baseball_attach_stripe_customer(uuid, text) to service_role;
grant execute on function public.baseball_claim_webhook_event(text, text, bigint, text, boolean) to service_role;
grant execute on function public.baseball_apply_subscription_event(uuid, text, text, text, text, timestamptz, text, bigint, uuid) to service_role;
grant execute on function public.baseball_finish_webhook_event(text, uuid, text, text) to service_role;

commit;
