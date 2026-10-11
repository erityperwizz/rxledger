-- Drug catalog: one row per distinct Part D (normalized brand name, normalized generic name).
-- Display names use the most common original spelling.

with base as (
    select
        brand_name_norm,
        generic_name_norm,
        mode(brand_name)                   as brand_name,
        mode(generic_name)                 as generic_name,
        mode(brand_generic)                as brand_generic,
        bool_or(is_generic_strict_rule)    as is_generic_strict_rule,
        sum(claims)                        as claims,
        sum(fills_30day)                   as fills_30day,
        sum(drug_cost)                     as drug_cost,
        count(distinct npi)                as prescribers
    from {{ ref('stg_partd__prescriber_drug') }}
    group by 1, 2
),

generic_availability as (
    select generic_name_norm, bool_or(brand_generic = 'Generic') as generic_available
    from base
    group by 1
)

select
    row_number() over (order by b.generic_name_norm, b.brand_name_norm) as drug_key,
    b.*,
    g.generic_available
from base b
join generic_availability g using (generic_name_norm)
