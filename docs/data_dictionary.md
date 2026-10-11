# Data Dictionary

Author: Erica Mathias

RxLedger models two CMS public datasets for calendar year 2024 in DuckDB with dbt:
Medicare Part D Prescribers by Provider and Drug, and Open Payments (general, research,
ownership, and recipient profile files). Raw CSVs become text only Parquet (bronze),
typed staging and intermediate tables (silver), and a star schema (gold).

## Rules applied to the data

### Suppression (Part D)

CMS suppresses small counts to protect beneficiaries. RxLedger stores every suppressed
value as NULL (missing), never as zero, and a dbt test enforces this.

| Field | Suppression | Stored as |
|---|---|---|
| Whole row | Prescriber x drug rows with fewer than 11 claims are not published | absent |
| Tot_Benes | Blank when fewer than 11 beneficiaries | NULL, `beneficiaries_suppressed` = true |
| GE65_Tot_Clms, GE65_Tot_30day_Fills, GE65_Tot_Drug_Cst, GE65_Tot_Day_Suply | GE65_Sprsn_Flag `*` (1 to 10 claims) or `#` (counter suppressed to prevent back calculation) | NULL |
| GE65_Tot_Benes | GE65_Bene_Sprsn_Flag `*` or `#` | NULL |

An unflagged GE65 value of 0 is a real zero (no patients aged 65 or older for that drug)
and is kept. Beneficiary counts are not additive across drugs (a patient on three drugs
is counted three times), so prescriber level totals use claims and cost, and
`drug_beneficiary_sum` is labeled as a proxy.

### Brand vs generic

The CMS data dictionary defines Brnd_Name (trademarked name) and Gnrc_Name (USAN generic
name) but publishes no brand or generic flag. A strict rule (generic when the brand name
equals the generic name) misclassifies many generic products whose Brnd_Name is a
reformatted generic name, for example "Clopidogrel" vs "Clopidogrel Bisulfate",
"Hydrocodone-Acetaminophen" vs "Hydrocodone/Acetaminophen", or "Metformin Hcl Er" vs
"Metformin Hcl". RxLedger classifies a row as **Generic** when, after normalization:

1. the brand name equals the generic name, or
2. the brand name and the generic name start with the same first word.

Everything else is **Brand**. Known limits: branded generics sold under their own
trademark (for example Jantoven for warfarin, Klor-Con for potassium chloride) stay Brand;
unbranded biologics and authorized generics named after the molecule (for example Insulin
Lispro, Dapagliflozin) count as Generic. The strict rule is kept as
`is_generic_strict_rule` for comparison; the effect of the choice is reported in
docs/data_quality_report.md.

### Name normalization

Drug and product names are upper cased, every run of characters other than A to Z and
0 to 9 is replaced by one space, and the result is trimmed (dbt macro `normalize_name`,
mirrored in Python and unit tested).

### Open Payments to Part D drug matching

Open Payments product slots of type Drug or Biological are matched to Part D drugs in
stages, taking the first stage with any match: exact brand name, exact generic name
(brand rows only), Part D brand starting with the product name ("DUPIXENT" to "DUPIXENT
PEN"), product name starting with the Part D brand. Match rates are in
docs/data_quality_report.md.

### Opioid flag

`dim_drug.is_opioid` is true when the normalized generic name contains an opioid
ingredient from `dbt/seeds/opioid_ingredients.csv` as a whole word (so ipratropium,
tiotropium, and apomorphine do not match). Buprenorphine products are excluded because in
Part D they are mostly prescribed to treat opioid use disorder. A dbt test pins these
edge cases.

### Payment allocation

A general payment can name up to five products. fact_payments has one row per payment x
product, with the amount split evenly across named products, so sums over any slice
reproduce the published total (tested).

### Exclusions

- Teaching hospital payments have no NPI and are excluded from every prescriber level join.
- 75 general payments dated 11/30/0002 (a source entry error) keep their amount but have
  a NULL date.
- Records listed in the removed or deleted file are confirmed absent (tested).

### Privacy

`dim_prescriber` holds names and NPIs for internal joins only. It is never exported to
Power BI, `outputs_public/`, or any committed file. Public outputs are aggregated to
specialty, state, drug, or manufacturer.

## Tables and columns


### Gold: star schema (marts)


#### marts.fact_prescriptions

Grain prescriber x drug, Medicare Part D 2024. One row per Part D source row.

| Column | Type | Description |
|---|---|---|
| prescriber_key | BIGINT | Foreign key to dim_prescriber. |
| drug_key | BIGINT | Foreign key to dim_drug. |
| state_key | BIGINT | Foreign key to dim_state (prescriber state per NPPES). |
| specialty_key | BIGINT | Foreign key to dim_specialty (Part D prescriber type). |
| claims | INTEGER | Number of Part D claims including refills (Tot_Clms). Always 11 or more. |
| fills_30day | DECIMAL(18,1) | Standardized 30 day fills (Tot_30day_Fills); each claim bottom coded at 1 and top coded at 12 by CMS. |
| day_supply | BIGINT | Total days supplied (Tot_Day_Suply). |
| drug_cost | DECIMAL(18,2) | Total drug cost paid in USD (Tot_Drug_Cst), all payers, including dispensing fees and taxes. |
| beneficiaries | INTEGER | Unique beneficiaries for this prescriber and drug (Tot_Benes). NULL when suppressed (fewer than 11). Not additive across drugs. |
| beneficiaries_suppressed | BOOLEAN | True when Tot_Benes was suppressed by CMS. |


#### marts.fact_payments

Grain general payment record x product slot. amount_usd is the payment split evenly across the products it names, so sums reproduce published totals.

| Column | Type | Description |
|---|---|---|
| record_id | BIGINT | Open Payments Record_ID. |
| product_slot | INTEGER | Product slot 1 to 5; 0 when the payment names no product. |
| prescriber_key | BIGINT | Foreign key to dim_prescriber. NULL for teaching hospital recipients (no NPI). |
| manufacturer_key | BIGINT | Foreign key to dim_manufacturer (the paying manufacturer or GPO). |
| drug_key | BIGINT | Foreign key to dim_drug. Set only for Drug or Biological products that map to a Part D drug (primary match). |
| date_key | INTEGER | Payment date as yyyymmdd, foreign key to dim_date. NULL for the 75 records with an invalid source date. |
| amount_usd | DOUBLE | Allocated payment amount in USD (payment amount divided by products named). |
| payment_amount_usd | DECIMAL(18,2) | Full amount of the payment record, repeated on each product line. Do not sum. |
| products_named | BIGINT | Number of product slots the payment names (0 to 5). |
| nature_of_payment | VARCHAR | Nature_of_Payment_or_Transfer_of_Value (16 CMS categories). |
| form_of_payment | VARCHAR | Form_of_Payment_or_Transfer_of_Value. |
| recipient_type | VARCHAR | Covered_Recipient_Type (physician, non physician practitioner, teaching hospital). |
| is_teaching_hospital | BOOLEAN | True for teaching hospital recipients. |
| product_type | VARCHAR | Drug, Biological, Device, or Medical Supply, as reported. |
| product_name | VARCHAR | Product name as reported by the manufacturer. |
| product_category | VARCHAR | Product category or therapeutic area as reported. |
| number_of_payments | INTEGER | Number of payments included in the record total. |
| payment_date_invalid | BOOLEAN | True when the source date was missing or outside 2024. |


#### marts.dim_prescriber

INTERNAL ONLY. Contains names and NPIs; never exported publicly. One row per NPI in Part D or Open Payments.

| Column | Type | Description |
|---|---|---|
| prescriber_key | BIGINT | Surrogate key. |
| npi | VARCHAR | National Provider Identifier. |
| last_org_name | VARCHAR | Last name or organization name (Part D first, else Open Payments). |
| first_name | VARCHAR | First name. |
| city | VARCHAR | City from Part D (NULL for NPIs only in Open Payments). |
| state_key | BIGINT | Foreign key to dim_state. |
| specialty_key | BIGINT | Foreign key to dim_specialty; 'Not in Part D' for NPIs only in Open Payments. |
| op_specialty | VARCHAR | Most frequent Open Payments specialty (different taxonomy from Part D). |
| in_partd | BOOLEAN | True when the NPI appears in Part D 2024. |
| received_general_payment | BOOLEAN | True when the NPI received at least one 2024 general payment. |
| total_claims | HUGEINT | Sum of Part D claims across drugs. |
| total_fills_30day | DECIMAL(38,1) | Sum of standardized 30 day fills across drugs. |
| total_drug_cost | DECIMAL(38,2) | Sum of Part D drug cost across drugs. |
| brand_claims | HUGEINT | Part D claims for drugs classified Brand. |
| drugs_prescribed | BIGINT | Number of distinct drugs with 11 or more claims. |
| drug_beneficiary_sum | HUGEINT | Sum of non suppressed drug level beneficiary counts. A volume proxy only, it double counts patients on several drugs. |
| general_payment_records | BIGINT | Number of 2024 general payment records received. |
| general_payment_usd | DECIMAL(38,2) | Total 2024 general payments received, USD. |
| paying_manufacturers | BIGINT | Distinct manufacturers that made a general payment to this NPI. |


#### marts.dim_drug

One row per Part D drug (brand name x generic name).

| Column | Type | Description |
|---|---|---|
| drug_key | BIGINT | Surrogate key. |
| brand_name | VARCHAR | Brand name (Brnd_Name), most common spelling. |
| generic_name | VARCHAR | Generic name (Gnrc_Name), most common spelling. |
| brand_name_norm | VARCHAR | Normalized brand name used for matching. |
| generic_name_norm | VARCHAR | Normalized generic name used for matching. |
| brand_generic | VARCHAR | Brand or Generic (rule in docs/data_dictionary.md). |
| is_generic_strict_rule | BOOLEAN | True when the brand name exactly equals the generic name after normalization (strict rule, kept for comparison). |
| generic_available | BOOLEAN | True when any Part D row with the same generic name is classified Generic. |
| brand_with_generic_equivalent | BOOLEAN | True for Brand drugs whose generic name also has a Generic product in Part D (substitution candidates). |
| therapeutic_area | VARCHAR | Most common Open Payments product category for payments naming this drug; NULL when none. |
| is_opioid | BOOLEAN | True when the generic name contains an included opioid ingredient (seed opioid_ingredients, whole word match). Buprenorphine products are excluded. |


#### marts.dim_specialty

Part D prescriber specialty (Prscrbr_Type) plus 'Not in Part D'.

| Column | Type | Description |
|---|---|---|
| specialty_key | BIGINT | Surrogate key. |
| specialty | VARCHAR | Specialty name. |
| prescribers | BIGINT | Number of prescribers (NPIs) with this specialty. |


#### marts.dim_state

States, DC, territories, and CMS special codes seen in either dataset.

| Column | Type | Description |
|---|---|---|
| state_key | BIGINT | Surrogate key. |
| state_code | VARCHAR | Two letter postal code (XX unknown, ZZ foreign, AA AE AP armed forces). |
| state_name | VARCHAR | State or area name. |
| census_region | VARCHAR | Census region; 'Territory or other' outside the 50 states and DC. |
| is_us_state_or_dc | BOOLEAN | True for the 50 states and DC. |


#### marts.dim_manufacturer

Applicable manufacturers and GPOs that made 2024 general payments.

| Column | Type | Description |
|---|---|---|
| manufacturer_key | BIGINT | Surrogate key. |
| manufacturer_id | BIGINT | Open Payments Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID. |
| manufacturer_name | VARCHAR | Most common reported name for the ID. |
| manufacturer_state | VARCHAR | Manufacturer state. |
| manufacturer_country | VARCHAR | Manufacturer country. |
| name_variants | BIGINT | Number of name spellings reported under this ID in 2024. |


#### marts.dim_date

2024 calendar.

| Column | Type | Description |
|---|---|---|
| date_key | INTEGER | yyyymmdd integer key. |
| date | DATE | Calendar date (mark as date table in Power BI). |
| year | BIGINT | Year. |
| quarter | BIGINT | Quarter 1 to 4. |
| month | BIGINT | Month number. |
| month_name | VARCHAR | Month name. |
| month_label | VARCHAR | Short month and year, for example Jan 2024. |
| day_of_week | BIGINT | 0 Sunday to 6 Saturday. |
| day_name | VARCHAR | Day name. |
| is_weekend | BOOLEAN | True on Saturday and Sunday. |


### Silver: staging


#### staging.stg_partd__prescriber_drug

Medicare Part D Prescribers by Provider and Drug, 2024. One row per prescriber x drug. Typed and trimmed; suppressed values are NULL, never zero.

| Column | Type | Description |
|---|---|---|
| npi | VARCHAR | Prescriber National Provider Identifier (Prscrbr_NPI). |
| prescriber_last_org_name | VARCHAR |  |
| prescriber_first_name | VARCHAR |  |
| prescriber_city | VARCHAR |  |
| state_code | VARCHAR | Prescriber state postal abbreviation (Prscrbr_State_Abrvtn); includes territories and XX, ZZ. |
| state_fips | VARCHAR |  |
| specialty | VARCHAR | Prescriber specialty (Prscrbr_Type), derived by CMS from Part B claims or NPPES taxonomy. |
| specialty_source | VARCHAR |  |
| brand_name | VARCHAR |  |
| generic_name | VARCHAR |  |
| brand_name_norm | VARCHAR | Brand name upper cased, punctuation collapsed to single spaces, trimmed. |
| generic_name_norm | VARCHAR |  |
| brand_generic | VARCHAR | Brand or Generic, from the name rule documented in docs/data_dictionary.md. |
| is_generic_strict_rule | BOOLEAN |  |
| claims | INTEGER | Tot_Clms. CMS excludes rows with fewer than 11 claims. |
| fills_30day | DECIMAL(18,1) |  |
| day_supply | BIGINT |  |
| drug_cost | DECIMAL(18,2) | Tot_Drug_Cst, total paid by plan, beneficiary, subsidies, and third parties. |
| beneficiaries | INTEGER | Tot_Benes. NULL when CMS suppressed it (fewer than 11 beneficiaries). |
| beneficiaries_suppressed | BOOLEAN |  |
| ge65_suppression_flag | VARCHAR |  |
| ge65_bene_suppression_flag | VARCHAR |  |
| ge65_claims | INTEGER |  |
| ge65_fills_30day | DECIMAL(18,1) |  |
| ge65_drug_cost | DECIMAL(18,2) |  |
| ge65_day_supply | BIGINT |  |
| ge65_beneficiaries | INTEGER |  |


#### staging.stg_op__general_payments

Open Payments 2024 general payments, one row per record.

| Column | Type | Description |
|---|---|---|
| record_id | BIGINT |  |
| change_type | VARCHAR |  |
| recipient_type | VARCHAR |  |
| is_teaching_hospital | BOOLEAN |  |
| recipient_profile_id | VARCHAR |  |
| npi | VARCHAR |  |
| recipient_first_name | VARCHAR |  |
| recipient_last_name | VARCHAR |  |
| recipient_state | VARCHAR |  |
| recipient_primary_type | VARCHAR |  |
| recipient_specialty | VARCHAR |  |
| manufacturer_id | BIGINT |  |
| manufacturer_name | VARCHAR |  |
| manufacturer_state | VARCHAR |  |
| manufacturer_country | VARCHAR |  |
| amount_usd | DECIMAL(18,2) |  |
| number_of_payments | INTEGER |  |
| form_of_payment | VARCHAR |  |
| nature_of_payment | VARCHAR |  |
| dispute_status | VARCHAR |  |
| related_product_indicator | VARCHAR |  |
| program_year | INTEGER |  |
| payment_date | DATE |  |
| payment_date_invalid | BOOLEAN |  |


#### staging.stg_op__payment_products

General payment product slots 1 to 5 unpivoted to one row per payment x product.

| Column | Type | Description |
|---|---|---|
| record_id | BIGINT |  |
| product_slot | INTEGER |  |
| covered_indicator | VARCHAR |  |
| product_type | VARCHAR |  |
| product_category | VARCHAR |  |
| product_name | VARCHAR |  |
| product_name_norm | VARCHAR |  |
| ndc | VARCHAR |  |


#### staging.stg_op__research_payments

Open Payments 2024 research payments (narrow), for manufacturer and therapeutic area context.

| Column | Type | Description |
|---|---|---|
| record_id | BIGINT |  |
| recipient_type | VARCHAR |  |
| npi | VARCHAR |  |
| manufacturer_id | BIGINT |  |
| manufacturer_name | VARCHAR |  |
| amount_usd | DECIMAL(18,2) |  |
| payment_date | DATE |  |
| product_type_1 | VARCHAR |  |
| product_category_1 | VARCHAR |  |
| product_name_1 | VARCHAR |  |
| preclinical_research_indicator | VARCHAR |  |


### Silver: intermediate


#### intermediate.int_drugs

Part D drug catalog, one row per normalized brand name x normalized generic name.

| Column | Type | Description |
|---|---|---|
| drug_key | BIGINT |  |
| brand_name_norm | VARCHAR |  |
| generic_name_norm | VARCHAR |  |
| brand_name | VARCHAR |  |
| generic_name | VARCHAR |  |
| brand_generic | VARCHAR |  |
| is_generic_strict_rule | BOOLEAN |  |
| claims | HUGEINT |  |
| fills_30day | DECIMAL(38,1) |  |
| drug_cost | DECIMAL(38,2) |  |
| prescribers | BIGINT |  |
| generic_available | BOOLEAN |  |


#### intermediate.int_op_product_drug_map

Open Payments drug and biological product names mapped to Part D drugs, with match method.

| Column | Type | Description |
|---|---|---|
| product_name_norm | VARCHAR |  |
| payment_product_rows | BIGINT |  |
| drug_key | BIGINT |  |
| match_method | VARCHAR |  |
| is_primary | BOOLEAN |  |


#### intermediate.int_prescriber_partd

| Column | Type | Description |
|---|---|---|
| npi | VARCHAR |  |
| last_org_name | VARCHAR |  |
| first_name | VARCHAR |  |
| city | VARCHAR |  |
| state_code | VARCHAR |  |
| specialty | VARCHAR |  |
| specialty_source | VARCHAR |  |
| total_claims | HUGEINT |  |
| total_fills_30day | DECIMAL(38,1) |  |
| total_drug_cost | DECIMAL(38,2) |  |
| drugs_prescribed | BIGINT |  |
| drug_beneficiary_sum | HUGEINT |  |
| drug_rows_bene_suppressed | BIGINT |  |
| brand_claims | HUGEINT |  |


#### intermediate.int_prescriber_payments

| Column | Type | Description |
|---|---|---|
| npi | VARCHAR |  |
| last_name | VARCHAR |  |
| first_name | VARCHAR |  |
| general_payment_records | BIGINT |  |
| general_payment_usd | DECIMAL(38,2) |  |
| paying_manufacturers | BIGINT |  |
| state_code | VARCHAR |  |
| op_specialty | VARCHAR |  |


#### intermediate.int_prescribers

| Column | Type | Description |
|---|---|---|
| npi | VARCHAR |  |
| last_org_name | VARCHAR |  |
| first_name | VARCHAR |  |
| city | VARCHAR |  |
| state_code | VARCHAR |  |
| specialty | VARCHAR |  |
| specialty_source | VARCHAR |  |
| op_specialty | VARCHAR |  |
| in_partd | BOOLEAN |  |
| received_general_payment | BOOLEAN |  |
| total_claims | HUGEINT |  |
| total_fills_30day | DECIMAL(38,1) |  |
| total_drug_cost | DECIMAL(38,2) |  |
| brand_claims | HUGEINT |  |
| drugs_prescribed | BIGINT |  |
| drug_beneficiary_sum | HUGEINT |  |
| drug_rows_bene_suppressed | BIGINT |  |
| general_payment_records | BIGINT |  |
| general_payment_usd | DECIMAL(38,2) |  |
| paying_manufacturers | BIGINT |  |


#### intermediate.int_manufacturers

| Column | Type | Description |
|---|---|---|
| manufacturer_id | BIGINT |  |
| manufacturer_name | VARCHAR |  |
| manufacturer_state | VARCHAR |  |
| manufacturer_country | VARCHAR |  |
| name_variants | BIGINT |  |
| general_payment_records | BIGINT |  |
| general_payment_usd | DECIMAL(38,2) |  |
