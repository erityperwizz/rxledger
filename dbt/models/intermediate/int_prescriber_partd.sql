-- One row per Part D prescriber NPI with prescribing totals.
-- Beneficiary totals cannot be summed across drugs (the same patient is counted once per
-- drug, and small counts are suppressed), so drug_beneficiary_sum is a documented proxy
-- for patient volume, counting only non suppressed drug rows.

select
    npi,
    any_value(prescriber_last_org_name)                 as last_org_name,
    any_value(prescriber_first_name)                    as first_name,
    any_value(prescriber_city)                          as city,
    any_value(state_code)                               as state_code,
    any_value(specialty)                                as specialty,
    any_value(specialty_source)                         as specialty_source,
    sum(claims)                                         as total_claims,
    sum(fills_30day)                                    as total_fills_30day,
    sum(drug_cost)                                      as total_drug_cost,
    count(*)                                            as drugs_prescribed,
    sum(beneficiaries)                                  as drug_beneficiary_sum,
    count(*) filter (where beneficiaries_suppressed)    as drug_rows_bene_suppressed,
    coalesce(sum(claims) filter (where brand_generic = 'Brand'), 0) as brand_claims
from {{ ref('stg_partd__prescriber_drug') }}
group by 1
