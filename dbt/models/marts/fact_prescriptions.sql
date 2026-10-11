-- Grain: prescriber x drug, Medicare Part D 2024. beneficiaries is NULL when suppressed.

select
    pr.prescriber_key,
    d.drug_key,
    pr.state_key,
    pr.specialty_key,
    s.claims,
    s.fills_30day,
    s.day_supply,
    s.drug_cost,
    s.beneficiaries,
    s.beneficiaries_suppressed
from {{ ref('stg_partd__prescriber_drug') }} s
join {{ ref('dim_prescriber') }} pr using (npi)
join {{ ref('int_drugs') }} d using (brand_name_norm, generic_name_norm)
