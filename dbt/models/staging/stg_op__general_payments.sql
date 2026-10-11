-- One row per Open Payments 2024 general payment record.
-- Teaching hospital recipients have no NPI and are kept here (flagged) but never join to
-- prescribers. Payment dates outside 2024 (75 rows dated 11/30/0002, a source entry
-- error) are set to NULL and flagged rather than guessed.

with src as (
    select * from read_parquet('{{ var("bronze_dir") }}/op_general.parquet')
),

typed as (
    select
        cast(Record_ID as bigint)                                           as record_id,
        trim(Change_Type)                                                   as change_type,
        trim(Covered_Recipient_Type)                                        as recipient_type,
        (Covered_Recipient_Type = 'Covered Recipient Teaching Hospital')     as is_teaching_hospital,
        trim(Covered_Recipient_Profile_ID)                                  as recipient_profile_id,
        nullif(trim(Covered_Recipient_NPI), '')                             as npi,
        trim(Covered_Recipient_First_Name)                                  as recipient_first_name,
        trim(Covered_Recipient_Last_Name)                                   as recipient_last_name,
        upper(trim(Recipient_State))                                        as recipient_state,
        trim(Covered_Recipient_Primary_Type_1)                              as recipient_primary_type,
        trim(Covered_Recipient_Specialty_1)                                 as recipient_specialty,
        cast(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID as bigint) as manufacturer_id,
        trim(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name) as manufacturer_name,
        upper(trim(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_State))   as manufacturer_state,
        trim(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Country)        as manufacturer_country,
        cast(Total_Amount_of_Payment_USDollars as decimal(18, 2))           as amount_usd,
        try_strptime(Date_of_Payment, '%m/%d/%Y')::date                     as raw_payment_date,
        cast(Number_of_Payments_Included_in_Total_Amount as integer)        as number_of_payments,
        trim(Form_of_Payment_or_Transfer_of_Value)                          as form_of_payment,
        trim(Nature_of_Payment_or_Transfer_of_Value)                        as nature_of_payment,
        trim(Dispute_Status_for_Publication)                                as dispute_status,
        trim(Related_Product_Indicator)                                     as related_product_indicator,
        cast(Program_Year as integer)                                       as program_year
    from src
)

select
    * exclude (raw_payment_date),
    case when year(raw_payment_date) = 2024 then raw_payment_date end      as payment_date,
    (raw_payment_date is null or year(raw_payment_date) <> 2024)           as payment_date_invalid
from typed
