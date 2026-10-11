-- Long table: one row per general payment x product slot (up to 5 per payment).
-- Slots with no product name and no product type are dropped.

with src as (
    select * from read_parquet('{{ var("bronze_dir") }}/op_general.parquet')
),

{% set slots = [1, 2, 3, 4, 5] %}
unpivoted as (
    {% for i in slots %}
    select
        cast(Record_ID as bigint)                                               as record_id,
        {{ i }}                                                                 as product_slot,
        trim(Covered_or_Noncovered_Indicator_{{ i }})                           as covered_indicator,
        trim(Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_{{ i }})   as product_type,
        trim(Product_Category_or_Therapeutic_Area_{{ i }})                      as product_category,
        trim(Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_{{ i }})    as product_name,
        {{ normalize_name('Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_' ~ i) }} as product_name_norm,
        nullif(trim(Associated_Drug_or_Biological_NDC_{{ i }}), '')             as ndc
    from src
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)

select *
from unpivoted
where nullif(product_name, '') is not null
   or nullif(product_type, '') is not null
