-- One row per paying manufacturer or GPO. 63 IDs report more than one name spelling
-- during the year, so the most common spelling is used.

select
    manufacturer_id,
    mode(manufacturer_name)         as manufacturer_name,
    mode(manufacturer_state)        as manufacturer_state,
    mode(manufacturer_country)      as manufacturer_country,
    count(distinct manufacturer_name) as name_variants,
    count(*)                        as general_payment_records,
    sum(amount_usd)                 as general_payment_usd
from {{ ref('stg_op__general_payments') }}
group by 1
