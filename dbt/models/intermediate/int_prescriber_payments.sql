-- One row per NPI that received at least one 2024 general payment.
-- State and specialty are the most frequent values across that NPI's payment records.

with attr as (
    select
        npi,
        arg_max(recipient_state, n)         as state_code,
        arg_max(recipient_specialty, n)     as op_specialty
    from (
        select npi, recipient_state, recipient_specialty, count(*) as n
        from {{ ref('stg_op__general_payments') }}
        where npi is not null
        group by 1, 2, 3
    )
    group by 1
),

totals as (
    select
        npi,
        any_value(recipient_last_name)      as last_name,
        any_value(recipient_first_name)     as first_name,
        count(*)                            as general_payment_records,
        sum(amount_usd)                     as general_payment_usd,
        count(distinct manufacturer_id)     as paying_manufacturers
    from {{ ref('stg_op__general_payments') }}
    where npi is not null
    group by 1
)

select t.*, a.state_code, a.op_specialty
from totals t
join attr a using (npi)
