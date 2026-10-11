-- Costs, fills, day supply, and payment amounts must never be negative.
select 'partd' as source, cast(npi as varchar) as id from {{ ref('stg_partd__prescriber_drug') }}
where drug_cost < 0 or fills_30day < 0 or day_supply < 0 or claims < 0
union all
select 'general_payments', cast(record_id as varchar) from {{ ref('stg_op__general_payments') }}
where amount_usd < 0
union all
select 'fact_payments', cast(record_id as varchar) from {{ ref('fact_payments') }}
where amount_usd < 0
