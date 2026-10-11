-- One row per NPI seen in Part D or as an Open Payments general payment recipient.
-- Part D attributes (specialty, state) take priority; NPIs that only appear in Open
-- Payments keep their Open Payments state and have no Part D specialty.

select
    coalesce(p.npi, o.npi)                          as npi,
    coalesce(p.last_org_name, o.last_name)          as last_org_name,
    coalesce(p.first_name, o.first_name)            as first_name,
    p.city,
    coalesce(p.state_code, o.state_code)            as state_code,
    p.specialty,
    p.specialty_source,
    o.op_specialty,
    (p.npi is not null)                             as in_partd,
    (o.npi is not null)                             as received_general_payment,
    coalesce(p.total_claims, 0)                     as total_claims,
    coalesce(p.total_fills_30day, 0)                as total_fills_30day,
    coalesce(p.total_drug_cost, 0)                  as total_drug_cost,
    coalesce(p.brand_claims, 0)                     as brand_claims,
    coalesce(p.drugs_prescribed, 0)                 as drugs_prescribed,
    p.drug_beneficiary_sum,
    p.drug_rows_bene_suppressed,
    coalesce(o.general_payment_records, 0)          as general_payment_records,
    coalesce(o.general_payment_usd, 0)              as general_payment_usd,
    coalesce(o.paying_manufacturers, 0)             as paying_manufacturers
from {{ ref('int_prescriber_partd') }} p
full outer join {{ ref('int_prescriber_payments') }} o on p.npi = o.npi
