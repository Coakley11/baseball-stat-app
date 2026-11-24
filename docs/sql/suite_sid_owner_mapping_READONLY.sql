-- READ-ONLY: why do browser-session rows have 6 owners but only 2 linked Auth accounts? (2026-11-24)
-- One row per row-owner (suite workspace profile). Prints numbers and categories only: no id, email,
-- external id or token. "token account #n" = which Auth user (numbered by creation date) issued the token
-- stored in that profile's rows, read from the token's own "sub" claim.

with b as (
  select i.user_id, i.valid, i.updated_at,
         nullif(split_part(i.payload ->> 'access_token', '.', 2), '') as jwt_body
  from public.suite_saved_items i
  where i.app = '_auth_browser' and i.item_type = 'browser_session'
),
d as (
  select b.*,
         case when b.jwt_body ~ '^[A-Za-z0-9_-]+$' and length(b.jwt_body) % 4 <> 1 then
           convert_from(decode(rpad(translate(b.jwt_body, '-_', '+/'), ((length(b.jwt_body) + 3) / 4) * 4, '='), 'base64'), 'UTF8')::jsonb ->> 'sub'
         end as token_sub
  from b
),
au as (select id, row_number() over (order by created_at, id) as acct_no from auth.users),
own as (select user_id, row_number() over (order by count(*) desc, min(updated_at)) as owner_no from b group by user_id)
select own.owner_no                                   as profile_no,
       count(*)                                       as rows,
       count(*) filter (where d.valid)                as valid_rows,
       min(d.updated_at)::date                        as first_written,
       max(d.updated_at)::date                        as last_written,
       case when coalesce(u.email, '') = '' then 'profile has no email'
            when exists (select 1 from auth.users a where lower(a.email) = lower(u.email)) then 'profile email = an Auth account'
            else 'profile email not in Auth' end      as profile_email,
       case when u.external_id ~* '^guest' then 'guest workspace'
            when u.external_id like '%@%' then 'email-style id'
            else 'named profile' end                  as profile_kind,
       string_agg(distinct coalesce('token account #' || au.acct_no,
                  case when d.token_sub is null then 'token unreadable' else 'token from unknown Auth id' end), ', ') as tokens_belong_to
from d
join own using (user_id)
join public.suite_users u on u.id = d.user_id
left join au on au.id::text = d.token_sub
group by own.owner_no, u.email, u.external_id
order by 1;
