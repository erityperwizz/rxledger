-- Suppressed values must be NULL (missing), never 0, and flagged GE65 values must be NULL.
-- Note: an unflagged GE65 value of 0 is legitimate (no patients aged 65+ for that drug, for
-- example all patients qualify through disability), so it is not tested as an error.
-- Tot_Benes can never truly be 0 because every row has at least 11 claims.
select 'beneficiaries_zero' as issue, npi from {{ ref('stg_partd__prescriber_drug') }}
where beneficiaries = 0
union all
select 'beneficiaries_null_but_not_flagged', npi from {{ ref('stg_partd__prescriber_drug') }}
where beneficiaries is null and not beneficiaries_suppressed
union all
select 'ge65_flagged_but_present', npi from {{ ref('stg_partd__prescriber_drug') }}
where ge65_suppression_flag is not null
  and (ge65_claims is not null or ge65_drug_cost is not null
       or ge65_fills_30day is not null or ge65_day_supply is not null)
union all
select 'ge65_bene_flagged_but_present', npi from {{ ref('stg_partd__prescriber_drug') }}
where ge65_bene_suppression_flag is not null and ge65_beneficiaries is not null
union all
select 'ge65_unflagged_but_missing', npi from {{ ref('stg_partd__prescriber_drug') }}
where ge65_suppression_flag is null and ge65_claims is null
