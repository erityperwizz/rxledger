-- Part D prescriber specialty (Prscrbr_Type). Prescribers seen only in Open Payments have
-- no Part D specialty and map to 'Not in Part D'.

with s as (
    select specialty, count(*) as prescribers
    from {{ ref('int_prescribers') }}
    where in_partd
    group by 1
    union all
    select 'Not in Part D', count(*) from {{ ref('int_prescribers') }} where not in_partd
)

select
    row_number() over (order by specialty)  as specialty_key,
    specialty,
    prescribers
from s
