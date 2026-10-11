"""Generate docs/data_dictionary.md from dbt metadata.

Author: Erica Mathias

Column types come from dbt/target/catalog.json (run `dbt docs generate` first) and
descriptions from dbt/target/manifest.json (the schema .yml files). The rules section at
the top is maintained here by hand.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

TARGET = config.ROOT / "dbt" / "target"
OUT = config.DOCS_DIR / "data_dictionary.md"

LAYERS = [
    ("Gold: star schema (marts)", "marts",
     ["fact_prescriptions", "fact_payments", "dim_prescriber", "dim_drug", "dim_specialty",
      "dim_state", "dim_manufacturer", "dim_date"]),
    ("Silver: staging", "staging",
     ["stg_partd__prescriber_drug", "stg_op__general_payments", "stg_op__payment_products",
      "stg_op__research_payments"]),
    ("Silver: intermediate", "intermediate",
     ["int_drugs", "int_op_product_drug_map", "int_prescriber_partd", "int_prescriber_payments",
      "int_prescribers", "int_manufacturers"]),
]

HEADER = """# Data Dictionary

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
"""


def main():
    manifest = json.loads((TARGET / "manifest.json").read_text())
    catalog = json.loads((TARGET / "catalog.json").read_text())
    lines = [HEADER]
    for title, schema, models in LAYERS:
        lines.append(f"\n### {title}\n")
        for model in models:
            node = manifest["nodes"][f"model.rxledger.{model}"]
            cat = catalog["nodes"][f"model.rxledger.{model}"]
            stats = cat.get("stats", {})
            lines.append(f"\n#### {schema}.{model}\n")
            if node.get("description"):
                lines.append(node["description"].strip() + "\n")
            row_count = stats.get("row_count", {}).get("value")
            if row_count:
                lines.append(f"Approximate rows: {int(row_count):,}\n")
            lines.append("| Column | Type | Description |")
            lines.append("|---|---|---|")
            described = node.get("columns", {})
            for col in sorted(cat["columns"].values(), key=lambda c: c["index"]):
                desc = described.get(col["name"], {}).get("description", "")
                lines.append(f"| {col['name']} | {col['type']} | {desc} |")
            lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
