-- READ-ONLY (2026-11-24): which Auth account is which, and which Auth account each protected profile is bound to.
-- Prints account numbers (by creation date, as in the owner mapping), the owner's two known account names,
-- and protected profile names only. No email address, id or token.
with au as (
  select id::text as id, row_number() over (order by created_at, id) as acct_no, created_at::date as created,
         case when split_part(lower(email), '@', 1) = 'daniel.cohen11' then 'daniel.cohen11 (owner)'
              when split_part(lower(email), '@', 1) like 'coakley11%' then 'coakley11 (owner)'
              else 'third account (not the owner)' end as who
  from auth.users
)
select * from (
  select '1 accounts' as section, 'account #' || acct_no as item, who || ', created ' || created as detail from au
  union all
  select '2 bindings',
         case when u.external_id in ('daniel', 'coakley11', 'ariel', 'guest', 'test_user') then 'profile ' || u.external_id
              else 'other profile' end,
         case when s.user_id is null then 'UNBOUND'
              else coalesce('bound to account #' || au.acct_no || ' (' || au.who || ')', 'bound to an unknown Auth id') end
  from public.suite_users u
  left join public.suite_user_settings s on s.user_id = u.id and s.app = '_auth_binding'
  left join au on au.id = s.settings ->> 'auth_user_id'
  where u.external_id in ('daniel', 'coakley11', 'ariel', 'guest', 'test_user') or s.user_id is not null
) x
order by 1, 2, 3;
