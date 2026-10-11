-- CMS excludes prescriber x drug rows with fewer than 11 claims; any such row means a parsing problem.
select * from {{ ref('stg_partd__prescriber_drug') }} where claims < 11
