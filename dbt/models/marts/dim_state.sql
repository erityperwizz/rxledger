-- States and other areas seen in either dataset, labeled from the states seed.

with observed as (
    select distinct state_code from {{ ref('int_prescribers') }} where state_code is not null
    union
    select state_code from {{ ref('states') }}
)

select
    row_number() over (order by o.state_code)          as state_key,
    o.state_code,
    coalesce(s.state_name, 'Unrecognized')             as state_name,
    coalesce(s.census_region, 'Territory or other')    as census_region,
    coalesce(s.is_us_state_or_dc, false)               as is_us_state_or_dc
from observed o
left join {{ ref('states') }} s using (state_code)
