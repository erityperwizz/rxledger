# Power BI Build Guide

Author: Erica Mathias

Step by step instructions for building `powerbi/RxLedger.pbix` in Power BI Desktop (no
sign in needed) from the aggregated star schema that `powerbi/export_powerbi.py` writes.
Plan on about two hours the first time.

## What you are building

A four page report on 2024 Medicare Part D spending and manufacturer payments:

1. Executive overview
2. Drugs and specialties
3. Payments vs prescribing
4. Data quality and methodology

Optional page 5: Outliers by specialty.

### Why the data is aggregated

The .pbix file goes on GitHub, and the project never publishes individual prescribers.
The export therefore has **no prescriber table and no NPIs or names**. Every row
describes at least 11 prescribers. Any smaller cell is merged into a member called
**"Small cells (combined)"** (in the drug, specialty, state, and manufacturer lists).
National totals are exact. About 15% of drug cost and 20% of payment dollars sit in
combined cells. The payment share is mostly large acquisition, consulting, and royalty
payments to a few recipients, which is exactly what the rule should protect.

## Step 0. Refresh the export

From the repo folder:

```
.venv\Scripts\python.exe powerbi\export_powerbi.py
```

This writes 15 CSV files to `data\powerbi\` and prints a reconciliation table (also saved
as `data\powerbi\export_checks.csv`). Every row with a warehouse value should say `True`.

## Step 1. Open Power BI Desktop and apply the theme

1. Open Power BI Desktop. If it asks you to sign in, close the dialog. Nothing in this
   guide needs an account.
2. **View > Themes > Browse for themes**, then pick `powerbi\rxledger_theme.json`.
   This applies the same validated colors used in the README charts.
3. **File > Save as** `powerbi\RxLedger.pbix` now, and save often.

## Step 2. Load the tables with Power Query

Loading through one parameter means the report still works if the repo moves.

### 2a. Create the folder parameter

1. **Home > Transform data** opens Power Query.
2. **Home > Manage parameters > New parameter**:
   - Name: `DataFolder`
   - Type: Text
   - Current value: `C:\Users\Erica\Downloads\rxledger\data\powerbi\` (keep the
     trailing backslash)
3. Click OK.

### 2b. Create the loader function

1. **Home > New source > Blank query**.
2. **Advanced editor**, replace everything with:

```
(name as text) as table =>
let
    Source = Csv.Document(
        File.Contents(DataFolder & name & ".csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])
in
    Promoted
```

3. Rename the query to `LoadCsv`. Right click it and **untick Enable load**.

### 2c. Create one query per table

For each table below: **New source > Blank query > Advanced editor**, paste the code,
then rename the query to the name in the heading exactly. All types use the `en-US`
culture, so decimals parse correctly whatever your Windows region is.

**fact_rx**

```
let
    Source = LoadCsv("fact_rx"),
    Typed = Table.TransformColumnTypes(Source, {
        {"drug_key", Int64.Type}, {"specialty_key", Int64.Type}, {"state_key", Int64.Type},
        {"prescribers", Int64.Type}, {"claims", Int64.Type}, {"fills_30day", type number},
        {"day_supply", Int64.Type}, {"drug_cost", type number},
        {"generic_savings_usd", type number}}, "en-US")
in
    Typed
```

**fact_pay**

```
let
    Source = LoadCsv("fact_pay"),
    Typed = Table.TransformColumnTypes(Source, {
        {"manufacturer_key", Int64.Type}, {"drug_key", Int64.Type}, {"date_key", Int64.Type},
        {"nature_of_payment", type text}, {"recipient_type", type text},
        {"payment_records", Int64.Type}, {"recipients", Int64.Type},
        {"amount_usd", type number}}, "en-US")
in
    Typed
```

**prescriber_counts**

```
let
    Source = LoadCsv("prescriber_counts"),
    Typed = Table.TransformColumnTypes(Source, {
        {"specialty_key", Int64.Type}, {"state_key", Int64.Type},
        {"partd_prescribers", Int64.Type}, {"paid_prescribers", Int64.Type},
        {"general_payment_usd", type number}}, "en-US")
in
    Typed
```

**dim_drug**

```
let
    Source = LoadCsv("dim_drug"),
    Typed = Table.TransformColumnTypes(Source, {
        {"drug_key", Int64.Type}, {"brand_name", type text}, {"generic_name", type text},
        {"brand_generic", type text}, {"generic_available", type logical},
        {"brand_with_generic_equivalent", type logical}, {"is_opioid", type logical},
        {"therapeutic_area", type text}, {"savings_per_fill", type number},
        {"substitution_review", type text}, {"drug_label", type text}}, "en-US")
in
    Typed
```

**dim_specialty**

```
let
    Source = LoadCsv("dim_specialty"),
    Typed = Table.TransformColumnTypes(Source, {
        {"specialty_key", Int64.Type}, {"specialty", type text}}, "en-US")
in
    Typed
```

**dim_state**

```
let
    Source = LoadCsv("dim_state"),
    Typed = Table.TransformColumnTypes(Source, {
        {"state_key", Int64.Type}, {"state_code", type text}, {"state_name", type text},
        {"census_region", type text}, {"is_us_state_or_dc", type logical}}, "en-US")
in
    Typed
```

**dim_manufacturer**

```
let
    Source = LoadCsv("dim_manufacturer"),
    Typed = Table.TransformColumnTypes(Source, {
        {"manufacturer_key", Int64.Type}, {"manufacturer_name", type text},
        {"manufacturer_state", type text}, {"manufacturer_country", type text}}, "en-US")
in
    Typed
```

**dim_date**

```
let
    Source = LoadCsv("dim_date"),
    Typed = Table.TransformColumnTypes(Source, {
        {"date_key", Int64.Type}, {"date", type date}, {"year", Int64.Type},
        {"quarter", Int64.Type}, {"month", Int64.Type}, {"month_name", type text},
        {"month_label", type text}, {"day_of_week", Int64.Type}, {"day_name", type text},
        {"is_weekend", type logical}}, "en-US")
in
    Typed
```

**Result and data quality tables.** These are small and stand alone (no relationships).
For each, use the same pattern with only `Source = LoadCsv("<name>")` and let Power BI
detect types (**Transform > Detect data type**), then check that numbers are Decimal or
Whole number:

- `q2_results`, `q2_pooled`, `q3_specialty`
- `dq_ingest`, `dq_tests`, `dq_matching`, `export_checks`

Click **Home > Close & apply**.

## Step 3. Model view: relationships

Open **Model view**. Delete any relationships Power BI auto detected, then create these
(drag the fact column onto the dimension column). Every one is **Many to one (*:1)**
with **Single** cross filter direction, and every one should be active.

| From (many side) | To (one side) |
|---|---|
| fact_rx[drug_key] | dim_drug[drug_key] |
| fact_rx[specialty_key] | dim_specialty[specialty_key] |
| fact_rx[state_key] | dim_state[state_key] |
| fact_pay[drug_key] | dim_drug[drug_key] |
| fact_pay[manufacturer_key] | dim_manufacturer[manufacturer_key] |
| fact_pay[date_key] | dim_date[date_key] |
| prescriber_counts[specialty_key] | dim_specialty[specialty_key] |
| prescriber_counts[state_key] | dim_state[state_key] |

This is a star schema with three fact tables sharing conformed dimensions. Note what does
**not** connect:

- `fact_pay` is national (no state or specialty). Geography of payments comes from
  `prescriber_counts`.
- `prescriber_counts` has no drug or date; it answers "how many prescribers, and how
  many were paid" by specialty and state.

Tidy the model:

1. Hide every `*_key` column in the fact tables (right click > Hide in report view).
2. Select `dim_date[month_label]` > **Column tools > Sort by column > month**. Do the same
   for `month_name` (by `month`) and `day_name` (by `day_of_week`).
3. Set **Data category** of `dim_state[state_name]` to **State or Province**.
4. Set format: `drug_cost`, `amount_usd`, `generic_savings_usd`, `general_payment_usd`
   as Currency, 0 decimals.

## Step 4. Mark the date table

Select `dim_date` > **Table tools > Mark as date table** > date column `date`. Power BI
validates that dates are unique and continuous (2024-01-01 to 2024-12-31). Payment rows
use the first day of each month as their date, so monthly visuals line up with the
calendar.

## Step 5. Measures (DAX)

Create a home for measures: **Home > Enter data**, name the table `_Measures`, load it,
then right click > **New measure** for each line below. Afterwards hide the placeholder
column in `_Measures`.

Core measures from the requirements:

```
Total Drug Cost = SUM ( fact_rx[drug_cost] )

Total Claims = SUM ( fact_rx[claims] )

Cost per Claim = DIVIDE ( [Total Drug Cost], [Total Claims] )

Brand Share % =
DIVIDE (
    CALCULATE ( [Total Claims], dim_drug[brand_generic] = "Brand" ),
    [Total Claims]
)

Generic Savings Opportunity = SUM ( fact_rx[generic_savings_usd] )

Total Payments = SUM ( fact_pay[amount_usd] )

Paid Prescriber % =
DIVIDE (
    SUM ( prescriber_counts[paid_prescribers] ),
    SUM ( prescriber_counts[partd_prescribers] )
)
```

Supporting measures:

```
Total 30 Day Fills = SUM ( fact_rx[fills_30day] )

Brand Share of Cost % =
DIVIDE (
    CALCULATE ( [Total Drug Cost], dim_drug[brand_generic] = "Brand" ),
    [Total Drug Cost]
)

Generic Share % =
DIVIDE (
    CALCULATE ( [Total Claims], dim_drug[brand_generic] = "Generic" ),
    [Total Claims]
)

Share of Claims =
DIVIDE ( [Total Claims], CALCULATE ( [Total Claims], ALL ( dim_drug ) ) )

Share of Cost =
DIVIDE ( [Total Drug Cost], CALCULATE ( [Total Drug Cost], ALL ( dim_drug ) ) )

Opioid Share % =
DIVIDE (
    CALCULATE ( [Total Claims], dim_drug[is_opioid] = TRUE () ),
    [Total Claims]
)

Payment Records = SUM ( fact_pay[payment_records] )

Part D Prescribers = SUM ( prescriber_counts[partd_prescribers] )

Paid Prescribers = SUM ( prescriber_counts[paid_prescribers] )

Payments to Part D Prescribers = SUM ( prescriber_counts[general_payment_usd] )

Avg Payment per Paid Prescriber =
DIVIDE ( [Payments to Part D Prescribers], [Paid Prescribers] )
```

Formats (select the measure > Measure tools):

| Measure | Format |
|---|---|
| Total Drug Cost, Generic Savings Opportunity, Total Payments, Payments to Part D Prescribers | Currency, 0 decimals (cards will show $226.74bn style when display units = Auto) |
| Cost per Claim, Avg Payment per Paid Prescriber | Currency, 2 decimals |
| Brand Share %, Brand Share of Cost %, Generic Share %, Opioid Share %, Paid Prescriber %, Share of Claims, Share of Cost | Percentage, 1 decimal |
| Total Claims, Total 30 Day Fills, Payment Records, Part D Prescribers, Paid Prescribers | Whole number, thousands separator |

Two rules to keep the numbers honest:

- **Do not sum `fact_rx[prescribers]` across drugs.** A prescriber who writes five drugs
  is counted in five rows. For prescriber counts use `[Part D Prescribers]`.
- `Brand Share %` counts "Small cells (combined)" claims in the denominator only, which
  lowers it by a negligible amount (merged drugs are under 0.1% of claims).

## Step 6. Check the numbers

Put each core measure in a Card on a blank page with no filters. You should see:

| Measure | Expected |
|---|---|
| Total Drug Cost | $226.74bn (226,740,902,131) |
| Total Claims | 1,479,628,807 |
| Cost per Claim | $153.24 |
| Brand Share % | 11.5% |
| Generic Savings Opportunity | $6.75bn (6,745,095,581) |
| Total Payments | $3.42bn (3,424,344,413) |
| Paid Prescriber % | 56.4% |

If any card differs, recheck the relationships (Step 3) and that the measure has no page
filter. Delete the test page afterwards.

## Step 7. Build the pages

Canvas: **View > Page view > Fit to page**; page size 16:9. Leave a 16 px margin and
align visuals with **Format > Align**. Give every visual a short title in sentence case.
Turn off visual borders and shadows (the theme already does).

### Page 1: Executive overview

1. **Title** text box: "RxLedger: Medicare Part D spending and manufacturer payments,
   2024". Subtitle text box: "Source: CMS Part D Prescribers by Provider and Drug, CMS Open
   Payments. Gross drug cost before rebates."
2. **Seven cards** in one row: Total Drug Cost, Total Claims, Cost per Claim, Brand
   Share %, Generic Savings Opportunity, Total Payments, Paid Prescriber %.
3. **Clustered bar chart** "Top 10 drugs by cost": Y axis `dim_drug[drug_label]`, X axis
   `Total Drug Cost`. Filters pane: `drug_label` > Top N > Top 10 by `Total Drug Cost`;
   and `brand_generic` is not "Small cells". Data labels on.
4. **Clustered column chart** "Generics fill most prescriptions; brands take most of the
   money": X axis `dim_drug[brand_generic]`, Y axis `Share of Claims` and `Share of
   Cost`. Filter `brand_generic` to Brand and Generic only. Data labels on.
5. **Clustered bar chart** "Drug cost by state (top 15)": Y axis `dim_state[state_name]`,
   X axis `Total Drug Cost`, Top N 15; filter `is_us_state_or_dc` = True.

### Page 2: Drugs and specialties

1. **Slicers** across the top (Dropdown style, search on): `dim_specialty[specialty]`,
   `dim_state[state_name]`, `dim_drug[brand_generic]`, `dim_drug[is_opioid]`.
2. **Matrix** "Specialties": rows `dim_specialty[specialty]`; values Part D Prescribers,
   Total Drug Cost, Total Claims, Cost per Claim, Brand Share %, Opioid Share %, Generic
   Savings Opportunity. Sort by Total Drug Cost descending. Add conditional formatting
   (data bars) on Total Drug Cost.
3. **Table** "Drugs": `dim_drug[drug_label]`, `dim_drug[brand_generic]`, Total Drug Cost,
   Total Claims, Cost per Claim, Generic Savings Opportunity. Top N 25 by Total Drug Cost.
4. **Clustered bar chart** "Largest generic substitution opportunities": Y axis
   `drug_label`, X axis `Generic Savings Opportunity`, Top N 10; filter
   `substitution_review` = Included.
5. **Text box** under the savings chart: "Brand 30 day fills x (brand minus generic cost
   per fill). Pairs that are not interchangeable (different form, route, device, or
   strength) were excluded after review. Gross of rebates; an opportunity size, not a
   forecast."

### Page 3: Payments vs prescribing

1. **Cards**: Total Payments, Payment Records, Paid Prescriber %, Avg Payment per Paid
   Prescriber.
2. **Line chart** "General payments by month": X axis `dim_date[month_label]`, Y axis
   Total Payments.
3. **Clustered bar chart** "Top 10 paying manufacturers": Y axis
   `dim_manufacturer[manufacturer_name]`, X axis Total Payments, Top N 10; exclude "Small
   cells (combined)".
4. **Clustered bar chart** "Payments by nature": Y axis `fact_pay[nature_of_payment]`,
   X axis Total Payments.
5. **Clustered bar chart** "Share of prescribers paid, by specialty": Y axis
   `dim_specialty[specialty]`, X axis Paid Prescriber %; visual filter Part D
   Prescribers is greater than or equal to 5000.
6. **Table** "Payments and prescribing, 30 drugs (Question 2)": from `q2_results`:
   `drug`, `paid_share`, `prescribing_rate_unpaid`, `prescribing_rate_paid`, `lpm_coef`,
   `lpm_lo`, `lpm_hi`. Rename the columns in the visual to: Drug, Paid share, Prescribes
   (unpaid), Prescribes (paid), Adjusted difference, CI low, CI high. Format all as
   percentage, 1 decimal. Sort by Adjusted difference.
7. **Text box** (required, keep it visible): "Association, not causation. Manufacturers
   target prescribers who already treat these conditions, so the gap can run in either
   direction. Industry payments are legal and disclosed; this is not evidence that any
   prescriber acted improperly. Adjusted for specialty, state, and prescribing volume."

### Page 4: Data quality and methodology

1. **Table** "Ingest row counts": `dq_ingest` all columns.
2. **Matrix** "dbt tests": rows `dq_tests[test_type]`, columns `dq_tests[status]`,
   values Count of `test`.
3. **Table** "Drug name matching": `dq_matching` all columns.
4. **Table** "Export reconciliation": `export_checks` all columns.
5. **Text boxes** with the rules, one short paragraph each:
   - Suppression: CMS hides prescriber and drug rows under 11 claims and beneficiary
     counts under 11; suppressed values are stored as blank, never zero.
   - Brand vs generic: derived from names; generic when the brand name equals the generic
     name or starts with the same word.
   - Privacy: no prescriber level data in this report; cells under 11 prescribers are
     merged into "Small cells (combined)".
   - Sources: data.cms.gov (Part D Prescribers by Provider and Drug, 2024) and
     openpaymentsdata.cms.gov (Program Year 2024).
   - Author: Erica Mathias.

### Optional page 5: Outliers by specialty

1. **Clustered bar chart** "Share of prescribers flagged, by specialty": from
   `q3_specialty`, Y axis `specialty`, X axis `any_flag_rate`; Top N 15 by `prescribers`.
2. **Text box**: "Flagged = robust z above 3.5 within specialty on cost per claim, brand
   share, cost per beneficiary, or opioid share. An outlier is unusual for its specialty
   label, not a finding of fraud, waste, or poor care. No individual is shown."

## Step 8. Finish and export

1. **Page names**: rename the tabs "Executive overview", "Drugs and specialties",
   "Payments vs prescribing", "Data quality".
2. **Save** `powerbi\RxLedger.pbix`. Check the file size in File Explorer; it should be
   well under GitHub's 100 MB limit (roughly 10 to 30 MB).
3. **PDF**: **File > Export > Export to PDF** > save as `powerbi\RxLedger.pdf`.
4. **Screenshots**: for each page, maximize the window, press **Win + Shift + S**,
   capture the canvas only, and save as PNG:
   - `powerbi\screenshots\01_executive_overview.png`
   - `powerbi\screenshots\02_drugs_and_specialties.png`
   - `powerbi\screenshots\03_payments_vs_prescribing.png`
   - `powerbi\screenshots\04_data_quality.png`
5. Tell Claude Code the files are saved; the README links to these exact names.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "DataFolder" not found | The parameter name must match exactly, including case. |
| Numbers load as text or decimals look 100x too big | Make sure each Typed step ends with `"en-US"`. |
| Mark as date table fails | `dim_date[date]` must be type Date, not Date/Time or Text. |
| Card totals differ from Step 6 | A relationship is missing or inactive, or a filter is on the page. |
| Paid Prescriber % shows blank by drug | Expected: `prescriber_counts` has no drug; use specialty or state. |
| A visual shows "Small cells (combined)" | Expected; filter it out for rankings, keep it for totals. |
