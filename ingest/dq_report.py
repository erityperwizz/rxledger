"""Write the dbt test results and modeling checks into docs/data_quality_report.md.

Author: Erica Mathias

Reads dbt/target/run_results.json (from the last `dbt build` or `dbt test`) and queries
the DuckDB warehouse for match rates, suppression rates, and exclusions. Only aggregate
numbers are written. The ingest section written by to_parquet.py is kept as is.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

REPORT = config.DOCS_DIR / "data_quality_report.md"
RUN_RESULTS = config.ROOT / "dbt" / "target" / "build_results.json"  # saved after dbt build
START, END = "<!-- dbt:start -->", "<!-- dbt:end -->"


def test_section():
    results = json.loads(RUN_RESULTS.read_text())["results"]
    tests = [r for r in results if r["unique_id"].startswith("test.")]
    lines = [
        "## dbt tests",
        "",
        f"{sum(r['status'] == 'pass' for r in tests)} of {len(tests)} tests passed "
        f"in the last run.",
        "",
        "| Test | Status | Failing rows |",
        "|---|:---:|---:|",
    ]
    for r in sorted(tests, key=lambda r: r["unique_id"]):
        name = r["unique_id"].split(".")[2]
        lines.append(f"| {name} | {r['status']} | {r.get('failures') or 0} |")
    return lines


def checks_section(con):
    q = lambda s: con.execute(s).fetchone()  # noqa: E731
    lines = ["", "## Modeling checks", ""]

    n, sup, ge65_sup = q("""
        select count(*), avg(beneficiaries_suppressed::int),
               avg((ge65_suppression_flag is not null)::int)
        from staging.stg_partd__prescriber_drug""")
    lines += [
        "### Part D suppression",
        "",
        f"- Rows: {n:,}",
        f"- Tot_Benes suppressed (fewer than 11 beneficiaries, stored as NULL): {sup:.1%} of rows",
        f"- GE65 claim and cost fields suppressed ('*' or '#', stored as NULL): {ge65_sup:.1%} of rows",
        "- Unflagged GE65 values of 0 are real zeros (no patients aged 65+ for that drug) and are kept.",
        "",
    ]

    strict, refined = q("""
        select sum(claims) filter (where is_generic_strict_rule) / sum(claims),
               sum(claims) filter (where brand_generic = 'Generic') / sum(claims)
        from staging.stg_partd__prescriber_drug""")
    lines += [
        "### Brand vs generic rule",
        "",
        f"- Generic share of claims, strict rule (brand name = generic name): {strict:.1%}",
        f"- Generic share of claims, rule used (equal names or same first word): {refined:.1%}",
        "",
    ]

    teach_n, teach_usd, no_npi = q("""
        select count(*) filter (where is_teaching_hospital),
               sum(amount_usd) filter (where is_teaching_hospital),
               count(*) filter (where npi is null and not is_teaching_hospital)
        from staging.stg_op__general_payments""")
    bad_dates = q("select count(*) from staging.stg_op__general_payments where payment_date_invalid")[0]
    lines += [
        "### Open Payments exclusions",
        "",
        f"- Teaching hospital payments (no NPI, excluded from the prescriber join): "
        f"{teach_n:,} records, ${teach_usd:,.0f}",
        f"- Individual recipient payments with no NPI: {no_npi:,} records",
        f"- Payments with an invalid date (outside 2024, date set to NULL): {bad_dates:,}",
        "",
    ]

    rows = con.execute("""
        select match_method, count(*) as names, sum(payment_product_rows) as product_rows
        from (select distinct product_name_norm, match_method, payment_product_rows
              from intermediate.int_op_product_drug_map)
        group by 1 order by 3 desc""").fetchall()
    total = sum(r[2] for r in rows)
    matched = sum(r[2] for r in rows if r[0] != "unmatched")
    lines += [
        "### Drug name matching (Open Payments product to Part D drug)",
        "",
        "Drug and Biological product slots only, matched on normalized names.",
        "",
        "| Match method | Distinct product names | Payment product rows | Share of rows |",
        "|---|---:|---:|---:|",
    ]
    for method, names, prod_rows in rows:
        lines.append(f"| {method} | {names:,} | {prod_rows:,} | {prod_rows / total:.1%} |")
    lines += [
        "",
        f"Overall match rate: {matched / total:.1%} of drug and biological payment product rows.",
        "Unmatched names are mostly products not dispensed under Part D (vaccines and",
        "physician administered drugs billed to Part B, devices labeled as drugs).",
        "",
    ]

    pd_npis, paid_in_pd, op_only = q("""
        select count(*) filter (where in_partd),
               count(*) filter (where in_partd and received_general_payment),
               count(*) filter (where received_general_payment and not in_partd)
        from intermediate.int_prescribers""")
    lines += [
        "### Prescriber join (NPI)",
        "",
        f"- Part D prescribers: {pd_npis:,}",
        f"- Part D prescribers with at least one 2024 general payment: {paid_in_pd:,} "
        f"({paid_in_pd / pd_npis:.1%})",
        f"- Paid NPIs not in Part D (no qualifying Part D prescribing): {op_only:,}",
        "",
    ]
    return lines


def main():
    con = config.duckdb_connect(read_only=True)
    section = "\n".join(test_section() + checks_section(con)) + "\n"
    block = f"{START}\n{section}{END}"
    text = REPORT.read_text(encoding="utf-8")
    if START in text:
        text = text.split(START)[0] + block + text.split(END)[1]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    REPORT.write_text(text, encoding="utf-8")
    print(section)


if __name__ == "__main__":
    main()
