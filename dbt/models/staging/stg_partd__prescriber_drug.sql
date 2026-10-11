-- One row per prescriber x drug (brand name + generic name), Medicare Part D 2024.
-- Suppressed values stay NULL (never zero):
--   Tot_Benes blank            = fewer than 11 beneficiaries
--   GE65_Sprsn_Flag '*' or '#' = GE65 claim, fill, cost, day supply suppressed
--   GE65_Bene_Sprsn_Flag '*' or '#' = GE65 beneficiaries suppressed
-- Brand vs generic (see docs/data_dictionary.md): the CMS dictionary has no flag, so a
-- row is Generic when the normalized brand name equals the normalized generic name, or
-- when both start with the same first word (for example "Clopidogrel" vs
-- "Clopidogrel Bisulfate", "Metformin Hcl Er" vs "Metformin Hcl"). Otherwise Brand.

with src as (
    select * from read_parquet('{{ var("bronze_dir") }}/partd_prescriber_drug.parquet')
),

typed as (
    select
        trim(Prscrbr_NPI)                               as npi,
        trim(Prscrbr_Last_Org_Name)                     as prescriber_last_org_name,
        trim(Prscrbr_First_Name)                        as prescriber_first_name,
        trim(Prscrbr_City)                              as prescriber_city,
        upper(trim(Prscrbr_State_Abrvtn))               as state_code,
        trim(Prscrbr_State_FIPS)                        as state_fips,
        coalesce(trim(Prscrbr_Type), 'Unknown')         as specialty,
        trim(Prscrbr_Type_Src)                          as specialty_source,
        trim(Brnd_Name)                                 as brand_name,
        trim(Gnrc_Name)                                 as generic_name,
        {{ normalize_name('Brnd_Name') }}               as brand_name_norm,
        {{ normalize_name('Gnrc_Name') }}               as generic_name_norm,
        cast(Tot_Clms as integer)                       as claims,
        cast(Tot_30day_Fills as double)                 as fills_30day,
        cast(Tot_Day_Suply as bigint)                   as day_supply,
        cast(Tot_Drug_Cst as decimal(18, 2))            as drug_cost,
        cast(nullif(trim(Tot_Benes), '') as integer)    as beneficiaries,
        nullif(trim(GE65_Sprsn_Flag), '')               as ge65_suppression_flag,
        nullif(trim(GE65_Bene_Sprsn_Flag), '')          as ge65_bene_suppression_flag,
        GE65_Tot_Clms, GE65_Tot_30day_Fills, GE65_Tot_Drug_Cst, GE65_Tot_Day_Suply, GE65_Tot_Benes
    from src
)

select
    npi,
    prescriber_last_org_name,
    prescriber_first_name,
    prescriber_city,
    state_code,
    state_fips,
    specialty,
    specialty_source,
    brand_name,
    generic_name,
    brand_name_norm,
    generic_name_norm,
    case
        when brand_name_norm = generic_name_norm then 'Generic'
        when split_part(brand_name_norm, ' ', 1) = split_part(generic_name_norm, ' ', 1) then 'Generic'
        else 'Brand'
    end                                                  as brand_generic,
    (brand_name_norm = generic_name_norm)               as is_generic_strict_rule,
    claims,
    fills_30day,
    day_supply,
    drug_cost,
    beneficiaries,
    (beneficiaries is null)                              as beneficiaries_suppressed,
    ge65_suppression_flag,
    ge65_bene_suppression_flag,
    case when ge65_suppression_flag is null then cast(GE65_Tot_Clms as integer) end          as ge65_claims,
    case when ge65_suppression_flag is null then cast(GE65_Tot_30day_Fills as double) end    as ge65_fills_30day,
    case when ge65_suppression_flag is null then cast(GE65_Tot_Drug_Cst as decimal(18, 2)) end as ge65_drug_cost,
    case when ge65_suppression_flag is null then cast(GE65_Tot_Day_Suply as bigint) end      as ge65_day_supply,
    case when ge65_bene_suppression_flag is null
         then cast(nullif(trim(GE65_Tot_Benes), '') as integer) end                          as ge65_beneficiaries
from typed
