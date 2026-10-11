-- Open Payments 2024 research payments, kept narrow: used only for manufacturer and
-- therapeutic area context, never joined to individual prescribers in public outputs.

select
    cast(Record_ID as bigint)                                               as record_id,
    trim(Covered_Recipient_Type)                                            as recipient_type,
    nullif(trim(Covered_Recipient_NPI), '')                                 as npi,
    cast(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID as bigint) as manufacturer_id,
    trim(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name)     as manufacturer_name,
    cast(Total_Amount_of_Payment_USDollars as decimal(18, 2))               as amount_usd,
    try_strptime(Date_of_Payment, '%m/%d/%Y')::date                         as payment_date,
    trim(Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1)         as product_type_1,
    trim(Product_Category_or_Therapeutic_Area_1)                            as product_category_1,
    trim(Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1)          as product_name_1,
    trim(Preclinical_Research_Indicator)                                    as preclinical_research_indicator
from read_parquet('{{ var("bronze_dir") }}/op_research.parquet')
