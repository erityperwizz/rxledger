-- Splitting payments across product slots must preserve the published total
-- (to within one dollar of rounding) and every payment record.
with s as (select count(*) as n, sum(amount_usd) as amt from {{ ref('stg_op__general_payments') }}),
     f as (select count(distinct record_id) as n, sum(amount_usd) as amt from {{ ref('fact_payments') }})
select * from s, f
where s.n <> f.n or abs(s.amt - f.amt) > 1
