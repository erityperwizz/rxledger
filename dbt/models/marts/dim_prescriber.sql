-- INTERNAL ONLY. Contains names and NPIs. Never exported to Power BI, outputs_public, or
-- any committed file. Public outputs aggregate to specialty, state, drug, or manufacturer.

select
    row_number() over (order by p.npi)          as prescriber_key,
    p.npi,
    p.last_org_name,
    p.first_name,
    p.city,
    st.state_key,
    sp.specialty_key,
    p.op_specialty,
    p.in_partd,
    p.received_general_payment,
    p.total_claims,
    p.total_fills_30day,
    p.total_drug_cost,
    p.brand_claims,
    p.drugs_prescribed,
    p.drug_beneficiary_sum,
    p.general_payment_records,
    p.general_payment_usd,
    p.paying_manufacturers
from {{ ref('int_prescribers') }} p
left join {{ ref('dim_state') }} st using (state_code)
left join {{ ref('dim_specialty') }} sp
  on sp.specialty = coalesce(p.specialty, 'Not in Part D')
