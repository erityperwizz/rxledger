-- The star schema fact must keep every Part D row and every dollar.
with s as (select count(*) as n, sum(drug_cost) as cost, sum(claims) as claims
           from {{ ref('stg_partd__prescriber_drug') }}),
     f as (select count(*) as n, sum(drug_cost) as cost, sum(claims) as claims
           from {{ ref('fact_prescriptions') }})
select * from s, f
where s.n <> f.n or s.cost <> f.cost or s.claims <> f.claims
