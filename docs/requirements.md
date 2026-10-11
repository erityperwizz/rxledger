# Business Requirements: RxLedger

Author: Erica Mathias
Status: Delivered (calendar year 2024 data)

## 1. Purpose

Medicare Part D is one of the largest drug benefit programs in the United States, and
drug manufacturers make billions of dollars of disclosed payments to prescribers every
year. RxLedger turns two large public CMS datasets into a governed analytics product that
answers where Part D money goes, whether manufacturer payments are associated with
prescribing, and which prescribing patterns are unusual within a specialty, without ever
publishing an individual prescriber.

## 2. Stakeholders

| Stakeholder | Interest | What they need from RxLedger |
|---|---|---|
| Medicare Part D plan sponsor (pharmacy benefit and formulary team) | Control drug spend | Spend by drug, specialty, and state; generic substitution opportunity |
| CMS or state program integrity analyst | Prioritize review work | Specialty level outlier rates and the methods behind them |
| Health policy researcher or journalist | Understand industry influence | Payments vs prescribing estimates with confidence intervals and caveats |
| Pharmaceutical market access analyst | Benchmark brand uptake | Brand vs generic share and payments by manufacturer and drug |
| Data governance and privacy reviewer | Protect individuals | Documented suppression, small cell, and privacy rules |
| Hiring manager reviewing this portfolio | Assess skills | Reproducible code, tested models, clear findings |

The stakeholders are representative personas for a portfolio project; no external
client commissioned this work.

## 3. Business questions

1. **Where does Medicare Part D drug money go?** Spend by drug, specialty, and state;
   brand vs generic share; estimated savings if brand drugs with an interchangeable
   generic were dispensed as the generic.
2. **Is receiving manufacturer payments associated with prescribing more of that
   manufacturer's drugs?** Compare paid and unpaid prescribers in the same specialty with
   regression and a matched comparison, controlling for prescribing volume and state.
3. **Which prescribers are statistical outliers within their specialty?** Robust outlier
   detection on cost per claim, brand share, cost per beneficiary, and opioid share,
   reported only in aggregate.

## 4. Key performance indicators

Exact formulas are in [kpi_definitions.md](kpi_definitions.md).

| KPI | Answers |
|---|---|
| Total Drug Cost, Total Claims, Cost per Claim | Q1: size and unit cost of Part D spend |
| Brand Share % (claims and cost) | Q1: brand vs generic mix |
| Generic Savings Opportunity | Q1: savings from substitution |
| Total Payments, Paid Prescriber % | Q2: scale and reach of manufacturer payments |
| Adjusted difference in prescribing probability (pp) | Q2: association between payments and prescribing |
| Outlier flag rate by specialty | Q3: share of prescribers with unusual patterns |

## 5. Scope

In scope:

- Medicare Part D Prescribers by Provider and Drug, calendar year 2024 (about 28 million
  prescriber x drug rows).
- CMS Open Payments, Program Year 2024: general payments (about 15.5 million records),
  plus research, ownership, and recipient profile files for context and validation.
- Joining the two datasets on the prescriber NPI and on normalized drug names.
- A dbt modeled star schema with data quality tests, three analyses, a Power BI report,
  and documentation.

Out of scope:

- Medicare Part B (physician administered) drugs, Medicaid, and commercial claims.
- Manufacturer rebates and net prices (not published at drug level).
- Clinical appropriateness of any prescription, and any causal claim about payments.
- Identifying, ranking, or naming individual prescribers in any public output.
- Years other than 2024 (2024 is the newest year present in both datasets).

## 6. Functional requirements

| ID | Requirement | Delivered by |
|---|---|---|
| F1 | Ingest raw CSVs to Parquet without type guessing, and prove row counts match | `ingest/to_parquet.py`, data_quality_report.md |
| F2 | Type, clean, and model the data in dbt with suppressed values stored as NULL | `dbt/models/staging` |
| F3 | Classify brand vs generic and normalize drug names, with the rule documented | `stg_partd__prescriber_drug`, data_dictionary.md |
| F4 | Unpivot the five payment product slots and match products to Part D drugs, reporting the match rate | `stg_op__payment_products`, `int_op_product_drug_map` |
| F5 | Provide a star schema for BI (facts for prescriptions and payments, conformed dimensions) | `dbt/models/marts` |
| F6 | Test keys, relationships, accepted values, and business rules on every build | `dbt build` (94 tests) |
| F7 | Answer Q1 to Q3 with numbers, confidence intervals, and caveats | `analysis/`, findings.md |
| F8 | Deliver a four page Power BI report on the star schema with DAX measures | `powerbi/`, powerbi_build_steps.md |
| F9 | Rebuild everything from a clean clone with one command | `run_pipeline.py` |

## 7. Non functional requirements

- **Privacy.** No prescriber names or NPIs in any committed file, chart, or the Power BI
  file. Every public number describes at least 11 prescribers; counts from 1 to 10 are
  suppressed. Individual level analysis stays in git-ignored `outputs_private/`.
- **Honesty.** Associations are reported as associations, with 95% confidence intervals
  and a caveats section. The README states that payments correlating with prescribing
  is not evidence of wrongdoing.
- **Reproducibility.** Fixed random seeds, pinned processing order, documented commands.
- **Performance.** The full pipeline runs on a 16 GB Windows laptop. DuckDB is limited to
  about 60% of RAM and spills to disk.
- **Data handling.** Raw data, Parquet, and database files are never committed.

## 8. Assumptions and constraints

- CMS excludes prescriber x drug rows with fewer than 11 claims, so low volume
  prescribing is invisible. Analyses treat "no row" as "0 to 10 claims".
- Part D drug cost is gross of manufacturer rebates.
- Part D has no dosage form or strength field; generic substitution pairs that are not
  interchangeable were excluded after a documented review.
- Teaching hospital payments have no NPI and cannot be linked to prescribing.
- Power BI is shared as a .pbix, PDF, and screenshots, not "Publish to web" (an
  organizational policy blocks the Fabric sign up).

## 9. Acceptance criteria

| Criterion | Status |
|---|---|
| Bronze row counts match the raw CSVs exactly for all six sources | Met |
| `dbt build` passes with zero failing tests | Met |
| Fact tables reconcile to source totals (rows, cost, claims, payment dollars) | Met (dbt tests) |
| Q1 to Q3 findings include numbers, confidence intervals where relevant, and caveats | Met |
| No public output contains prescriber level data or groups under 11 prescribers | Met (checked in code and tests) |
| Power BI report rebuilt from the aggregated export with the documented measures | Built by the author from the guide |
| README numbers match pipeline outputs | Met (`tests/test_readme_numbers.py`) |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Readers infer misconduct from Q2 | Caveats in findings, README, and on the Power BI page; no individuals shown |
| Name matching links the wrong product | Staged matching, hand review of prefix matches, match rate reported |
| Brand vs generic misclassification | Rule tested against examples; strict rule kept for comparison |
| Small cells reveal individuals | Small cell merging in exports; 1 to 10 counts suppressed |
| Results drift from the README | Headline numbers generated by the pipeline and tested |
