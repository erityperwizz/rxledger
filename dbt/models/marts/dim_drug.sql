-- One row per Part D drug (brand name x generic name). therapeutic_area is the most common
-- Open Payments product category among payments whose product maps to this drug (NULL
-- when no payment names it).

with ta as (
    select m.drug_key, mode(pp.product_category) as therapeutic_area
    from {{ ref('int_op_product_drug_map') }} m
    join {{ ref('stg_op__payment_products') }} pp using (product_name_norm)
    where m.drug_key is not null
      and pp.product_type in ('Drug', 'Biological')
      and nullif(pp.product_category, '') is not null
    group by 1
),

opioid_pattern as (
    -- whole word match on included ingredients (seed: opioid_ingredients)
    select '\b(' || string_agg(ingredient, '|') || ')\b' as pattern
    from {{ ref('opioid_ingredients') }}
    where included
),

buprenorphine as (
    select '\bBUPRENORPHINE\b' as pattern
)

select
    d.drug_key,
    d.brand_name,
    d.generic_name,
    d.brand_name_norm,
    d.generic_name_norm,
    d.brand_generic,
    d.is_generic_strict_rule,
    d.generic_available,
    (d.brand_generic = 'Brand' and d.generic_available)   as brand_with_generic_equivalent,
    ta.therapeutic_area,
    regexp_matches(d.generic_name_norm, op.pattern)
        and not regexp_matches(d.generic_name_norm, bu.pattern)  as is_opioid
from {{ ref('int_drugs') }} d
left join ta using (drug_key)
cross join opioid_pattern op
cross join buprenorphine bu
