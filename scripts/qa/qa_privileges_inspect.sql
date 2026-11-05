-- READ-ONLY (SELECT only). Run in the baseball-qa-staging SQL editor. Nothing is changed.
-- Effective table privileges of the API roles on the tables the app uses, with each table's RLS state.
-- "open" means the role could read or change every row through the public REST API (privilege granted
-- and RLS off). With RLS on and no policy for the role, the privilege alone returns no rows.
with t(name) as (
  values ('suite_users'), ('suite_app_current_state'), ('suite_user_settings'), ('suite_activity_events'),
         ('suite_resume_items'), ('suite_saved_items'), ('baseball_shared_draft_rooms'),
         ('baseball_shared_leagues'), ('subscriptions')
), r(role) as (values ('anon'), ('authenticated'), ('service_role'))
select r.role, t.name as table_name,
       concat_ws(' ',
         case when has_table_privilege(r.role, 'public.' || t.name, 'SELECT') then 'SELECT' end,
         case when has_table_privilege(r.role, 'public.' || t.name, 'INSERT') then 'INSERT' end,
         case when has_table_privilege(r.role, 'public.' || t.name, 'UPDATE') then 'UPDATE' end,
         case when has_table_privilege(r.role, 'public.' || t.name, 'DELETE') then 'DELETE' end) as privileges,
       case when c.relrowsecurity then 'ON' else 'off' end as rls,
       (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = t.name
          and (r.role = any(p.roles) or 'public' = any(p.roles)))::int as policies_for_role,
       case
         when r.role = 'service_role' then 'server key (bypasses RLS by design)'
         when not (has_table_privilege(r.role, 'public.' || t.name, 'SELECT')
                   or has_table_privilege(r.role, 'public.' || t.name, 'INSERT')
                   or has_table_privilege(r.role, 'public.' || t.name, 'UPDATE')
                   or has_table_privilege(r.role, 'public.' || t.name, 'DELETE')) then 'no access'
         when not c.relrowsecurity then 'OPEN: privilege with RLS off'
         else 'RLS-limited (rows only through a policy)'
       end as verdict
from t cross join r
join pg_class c on c.relname = t.name and c.relnamespace = 'public'::regnamespace
order by case r.role when 'anon' then 1 when 'authenticated' then 2 else 3 end, t.name;
