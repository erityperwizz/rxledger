-- Maps each Open Payments drug or biological product name to Part D drugs.
-- Matching runs in stages; a product takes the first stage that finds any match:
--   1 exact_brand    normalized product name = normalized Part D brand name
--   2 exact_generic  normalized product name = normalized Part D generic name (brand rows only)
--   3 brand_prefix   Part D brand starts with the product name plus a space
--                    ("DUPIXENT" -> "DUPIXENT PEN", "REPATHA" -> "REPATHA SURECLICK")
--   4 product_prefix product name starts with the Part D brand plus a space
--                    ("PROLASTIN C LIQUID" -> "PROLASTIN C"); Part D brand must be 4+ characters
-- Prefix stages (3, 4) only match Part D Brand rows: matching generic rows produced false
-- matches such as "BUPRENORPHINE AND NALOXONE" -> "BUPRENORPHINE" (reviewed by hand).
-- One product can map to several Part D drugs (pen and syringe forms). is_primary marks
-- the highest cost match, used as the single drug_key in fact_payments.

with products as (
    select product_name_norm, count(*) as payment_product_rows
    from {{ ref('stg_op__payment_products') }}
    where product_type in ('Drug', 'Biological')
      and product_name_norm is not null
    group by 1
),

drugs as (
    select drug_key, brand_name_norm, generic_name_norm, brand_generic, drug_cost
    from {{ ref('int_drugs') }}
),

candidates as (
    select p.product_name_norm, d.drug_key, d.drug_cost, 1 as match_stage
    from products p join drugs d on d.brand_name_norm = p.product_name_norm
    union all
    select p.product_name_norm, d.drug_key, d.drug_cost, 2
    from products p join drugs d
      on d.generic_name_norm = p.product_name_norm and d.brand_generic = 'Brand'
    union all
    select p.product_name_norm, d.drug_key, d.drug_cost, 3
    from products p join drugs d
      on starts_with(d.brand_name_norm, p.product_name_norm || ' ')
     and d.brand_generic = 'Brand'
    union all
    select p.product_name_norm, d.drug_key, d.drug_cost, 4
    from products p join drugs d
      on starts_with(p.product_name_norm, d.brand_name_norm || ' ')
     and length(d.brand_name_norm) >= 4
     and d.brand_generic = 'Brand'
),

best_stage as (
    select product_name_norm, min(match_stage) as match_stage
    from candidates
    group by 1
),

matched as (
    select distinct c.product_name_norm, c.drug_key, c.drug_cost, c.match_stage
    from candidates c
    join best_stage b using (product_name_norm, match_stage)
)

select
    p.product_name_norm,
    p.payment_product_rows,
    m.drug_key,
    coalesce(
        case m.match_stage
            when 1 then 'exact_brand' when 2 then 'exact_generic'
            when 3 then 'brand_prefix' when 4 then 'product_prefix'
        end, 'unmatched')                                                   as match_method,
    coalesce(row_number() over (
        partition by p.product_name_norm order by m.drug_cost desc, m.drug_key) = 1
        and m.drug_key is not null, false)                                  as is_primary
from products p
left join matched m using (product_name_norm)
