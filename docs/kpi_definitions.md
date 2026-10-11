# KPI Definitions

Author: Erica Mathias

Every metric used in the findings, public outputs, and the Power BI report, with its
exact formula. Table and column names refer to the dbt marts (`marts.*`) or the Power BI
export (`fact_rx`, `fact_pay`, `prescriber_counts`). All figures are for calendar year
2024.

## Prescribing (Question 1)

| KPI | Formula | Grain and notes |
|---|---|---|
| **Total Drug Cost** | `SUM(fact_prescriptions.drug_cost)` | Tot_Drug_Cst: paid by plan, beneficiary, subsidies, and third parties, including dispensing fees and tax. Gross of manufacturer rebates. |
| **Total Claims** | `SUM(fact_prescriptions.claims)` | Tot_Clms, original fills and refills. Rows with fewer than 11 claims are not published by CMS. |
| **Total 30 Day Fills** | `SUM(fact_prescriptions.fills_30day)` | Standardized fills: days supplied / 30, bottom coded at 1 and top coded at 12 per claim by CMS. |
| **Cost per Claim** | `Total Drug Cost / Total Claims` | Ratio of sums, never an average of row ratios. |
| **Cost per 30 Day Fill** | `drug_cost / fills_30day` | Used for generic substitution pricing. |
| **Brand Share % (claims)** | `SUM(claims where brand_generic = 'Brand') / SUM(claims)` | Brand vs generic rule in data_dictionary.md. |
| **Brand Share of Cost %** | `SUM(drug_cost where brand_generic = 'Brand') / SUM(drug_cost)` | |
| **Generic Share %** | `SUM(claims where brand_generic = 'Generic') / SUM(claims)` | Brand Share % + Generic Share % = 100% except for merged small cells in the Power BI export. |
| **Share of total cost** | `drug cost of the group / Total Drug Cost` | Used for top drugs, specialties, states. |
| **Cost per prescriber** | `Total Drug Cost / COUNT(DISTINCT prescriber)` | Specialty and state tables. |
| **Opioid Share %** | `SUM(claims where is_opioid) / SUM(claims)` | `dim_drug.is_opioid`: whole word ingredient match from the opioid_ingredients seed; buprenorphine excluded. |

## Generic substitution (Question 1)

For each Brand drug b whose normalized generic name g also has Generic products:

```
brand_cost_per_fill(b)   = drug_cost(b) / fills_30day(b)
generic_cost_per_fill(g) = SUM(drug_cost of Generic rows of g) / SUM(fills_30day of Generic rows of g)
savings_upper_bound(b)   = fills_30day(b) x MAX(brand_cost_per_fill(b) - generic_cost_per_fill(g), 0)
savings_reviewed(b)      = 0 if b is in dbt/seeds/generic_substitution_exclusions.csv
                           else savings_upper_bound(b)
```

| KPI | Formula | Notes |
|---|---|---|
| **Generic Savings Opportunity** | `SUM(savings_reviewed)` | Headline estimate. In Power BI: `SUM(fact_rx[generic_savings_usd])`, where each row carries `fills_30day x savings_per_fill(drug)`, so the total slices by specialty and state and still sums to the national figure. |
| Savings upper bound | `SUM(savings_upper_bound)` | Formula applied to every pair, including pairs that are not interchangeable. |
| Savings, reliable generic prices | `SUM(savings_reviewed where generic fills >= 10,000)` | Sensitivity check. |

## Payments (Question 2)

| KPI | Formula | Notes |
|---|---|---|
| **Total Payments** | `SUM(fact_payments.amount_usd)` | Open Payments general payments. Payments naming several products are split evenly across them, so totals equal published amounts. |
| **Payment Records** | `COUNT(DISTINCT record_id)` | |
| **Part D Prescribers** | `COUNT(prescribers in Part D)` | One count per NPI. In Power BI: `SUM(prescriber_counts[partd_prescribers])`. Never sum the drug level prescriber column across drugs. |
| **Paid Prescribers** | `COUNT(Part D prescribers with at least one 2024 general payment)` | |
| **Paid Prescriber %** | `Paid Prescribers / Part D Prescribers` | |
| **Avg Payment per Paid Prescriber** | `SUM(general payments to Part D prescribers) / Paid Prescribers` | |
| Drug name match rate | `payment product rows matched to a Part D drug / all Drug or Biological product rows` | Reported in data_quality_report.md. |

## Payments vs prescribing estimates (Question 2)

Unit: Part D prescriber x brand family, among eligible prescribers (specialties writing
95% of the family's claims where at least 1% of the specialty prescribes it).

| KPI | Definition |
|---|---|
| **Prescribes (any_rx)** | 1 if the prescriber has a Part D row for the family (11 or more claims), else 0. |
| **Treated (paid)** | 1 if the prescriber received at least one 2024 general payment from a manufacturer making at least 5% of the payments that name the family. |
| **Raw difference** | `mean(any_rx | paid) - mean(any_rx | unpaid)`, percentage points. |
| **Adjusted difference** | OLS coefficient on Treated in `any_rx ~ treated + log(1 + other drug claims) + log(1 + beneficiary proxy) + specialty FE + state FE`, HC1 robust standard errors; 95% CI = estimate +/- 1.96 x SE. |
| **Matched difference** | Exact matching on specialty x state x volume decile; paid weighted mean of within cell (paid minus unpaid) prescribing rates; 95% CI from 500 stratified Poisson bootstrap replicates (seed 2024). |
| **Claims difference** | `exp(b) - 1` from the same regression on `log(claims)` among prescribers of the drug. |
| **Pooled estimate** | DerSimonian Laird random effects mean across drugs; I² = share of variation across drugs beyond chance. |
| **Dose response** | Same regression with payment amount bins ($1 to $100, $100 to $500, $500 to $5,000, over $5,000; reference unpaid), pooled per bin. |

## Outliers (Question 3)

Population: prescribers with at least 100 claims, in specialties with at least 100 such
prescribers.

| KPI | Formula |
|---|---|
| Cost per claim | `total drug cost / total claims` (scored on log scale) |
| Brand share | `brand claims / total claims` (scored on arcsine square root scale) |
| Cost per beneficiary (proxy) | `drug cost of rows with unsuppressed beneficiaries / SUM(those beneficiaries)` (log scale). A proxy: the same patient counts once per drug. |
| Opioid share | `opioid claims / total claims` (arcsine square root scale) |
| **Robust z** | `0.6745 x (x - specialty median) / specialty MAD`, on the scoring scale; not computed when MAD = 0 |
| **Flagged** | robust z > 3.5 (high side) |
| **Outlier flag rate** | `flagged prescribers / prescribers analyzed`, by specialty or state |
| **Multi metric flag rate** | share flagged on two or more metrics |
| Isolation Forest flag | top 1% most isolated within specialty (200 trees, seed 2024) |

## Privacy rules applied to every KPI

- A published group must contain at least 11 prescribers.
- Published counts from 1 to 10 are suppressed.
- Power BI cells under 11 prescribers are merged into "Small cells (combined)".
