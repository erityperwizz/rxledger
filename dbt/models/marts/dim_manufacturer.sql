select
    row_number() over (order by manufacturer_id)   as manufacturer_key,
    manufacturer_id,
    manufacturer_name,
    manufacturer_state,
    manufacturer_country,
    name_variants
from {{ ref('int_manufacturers') }}
