"""Export an aggregated star schema for Power BI Desktop.

Author: Erica Mathias

The .pbix is committed to GitHub, so nothing exported here is prescriber level:
  fact_rx            drug x specialty x state                       (Part D 2024)
  fact_pay           manufacturer x drug x month x nature of payment x recipient type
                     (national; a finer geographic grain would leave most cells under 11)
  prescriber_counts  specialty x state: Part D prescribers, paid prescribers, and the
                     general payments they received (geography of payments)
  dim_drug, dim_specialty, dim_state, dim_manufacturer, dim_date

Small cell rule: any cell describing fewer than 11 prescribers is merged into a
"Small cells (combined)" member, one dimension at a time (prescriptions: state, then
specialty, then drug; payments: nature, then drug, then manufacturer), recounting
distinct prescribers after each step. National totals are unchanged; the share of dollars that
ends up in combined cells is reported in data/powerbi/export_checks.csv.

Teaching hospitals are organizations, not prescribers, so their payments are not subject
to the prescriber small cell rule (recipient_type identifies them).

Usage: python powerbi/export_powerbi.py   (writes CSVs to data/powerbi/)
"""

import math
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis.common import MIN_CELL_PRESCRIBERS  # noqa: E402
from analysis.spend import savings  # noqa: E402

OUT = config.POWERBI_EXPORT_DIR
OTHER_KEY = -1            # "Small cells (combined)" member in every dimension
NO_DRUG_KEY = 0           # payment names no Part D drug
OTHER_TEXT = "Small cells (combined)"


def rollup(con, table, entity, steps, fixed=()):
    """Merge small cells into OTHER, one key at a time.

    table:  temp table at line level with key columns and an entity column (prescriber)
    steps:  ordered list of (column, other_value) to merge, in order
    fixed:  other grouping columns that are never merged (for example month)
    """
    keys = list(fixed) + [c for c, _ in steps]
    for col, other in steps:
        on = " and ".join(f"t.{k} is not distinct from s.{k}" for k in keys)
        con.execute(f"""
            create or replace temp table small as
            select {", ".join(keys)}
            from {table}
            where not exempt
            group by all
            having count(distinct {entity}) < {MIN_CELL_PRESCRIBERS}""")
        n = con.execute("select count(*) from small").fetchone()[0]
        con.execute(f"""
            update {table} t set {col} = {other!r}
            from small s
            where {on} and not t.exempt""")
        print(f"  {table}: {n:,} small cells merged on {col}", flush=True)


def export_fact_rx(con, sav):
    # savings per brand fill (reviewed estimate, Question 1) applied per line before the
    # rollup, so merged small cells keep their share of the savings
    per_fill = sav.assign(savings_per_fill=sav["savings_reviewed"] / sav["brand_fills_30day"])
    con.register("savings_per_fill_df", per_fill[["drug_key", "savings_per_fill"]])
    con.execute("""
        create or replace temp table rx_lines as
        select f.prescriber_key, f.drug_key, f.specialty_key, f.state_key,
               f.claims, f.fills_30day, f.day_supply, f.drug_cost,
               f.fills_30day * coalesce(s.savings_per_fill, 0) as savings_usd,
               false as exempt
        from marts.fact_prescriptions f
        left join savings_per_fill_df s using (drug_key)""")
    rollup(con, "rx_lines", "prescriber_key",
           [("state_key", OTHER_KEY), ("specialty_key", OTHER_KEY), ("drug_key", OTHER_KEY)])
    return con.execute("""
        select drug_key, specialty_key, state_key,
               count(distinct prescriber_key)   as prescribers,
               sum(claims)                      as claims,
               sum(fills_30day)                 as fills_30day,
               sum(day_supply)                  as day_supply,
               sum(drug_cost)                   as drug_cost,
               sum(savings_usd)                 as generic_savings_usd
        from rx_lines group by all""").df()


def export_fact_pay(con):
    """National payments: manufacturer x drug x month x nature x recipient type.

    Geography of payments to Part D prescribers comes from prescriber_counts instead;
    a state x specialty x manufacturer x drug grain would leave most cells under 11.
    """
    con.execute(f"""
        create or replace temp table pay_lines as
        select
            coalesce(cast(p.prescriber_key as varchar), 'payment ' || p.record_id) as entity,
            coalesce(p.drug_key, {NO_DRUG_KEY})                          as drug_key,
            p.manufacturer_key,
            cast((p.date_key // 100) * 100 + 1 as integer)              as date_key,
            p.nature_of_payment,
            p.recipient_type,
            p.amount_usd,
            p.record_id,
            p.is_teaching_hospital                                       as exempt
        from marts.fact_payments p""")
    rollup(con, "pay_lines", "entity",
           [("nature_of_payment", OTHER_TEXT), ("drug_key", OTHER_KEY),
            ("manufacturer_key", OTHER_KEY)],
           fixed=("date_key", "recipient_type"))
    return con.execute("""
        select manufacturer_key, drug_key, date_key, nature_of_payment, recipient_type,
               count(distinct record_id)        as payment_records,
               count(distinct entity) filter (where not exempt) as recipients,
               sum(amount_usd)                  as amount_usd
        from pay_lines group by all""").df()


def export_prescriber_counts(con):
    con.execute("""
        create or replace temp table pc_lines as
        select prescriber_key, specialty_key, state_key, received_general_payment,
               general_payment_usd, false as exempt
        from marts.dim_prescriber where in_partd""")
    rollup(con, "pc_lines", "prescriber_key",
           [("state_key", OTHER_KEY), ("specialty_key", OTHER_KEY)])
    return con.execute("""
        select specialty_key, state_key,
               count(*)                                         as partd_prescribers,
               count(*) filter (where received_general_payment) as paid_prescribers,
               sum(general_payment_usd)                         as general_payment_usd
        from pc_lines group by all""").df()


def dims(con, sav):
    drug = con.execute("""
        select drug_key, brand_name, generic_name, brand_generic, generic_available,
               brand_with_generic_equivalent, is_opioid, therapeutic_area
        from marts.dim_drug""").df()
    sav = sav[["drug_key", "savings_reviewed", "brand_fills_30day", "excluded_reason_category"]]
    drug = drug.merge(sav, on="drug_key", how="left")
    drug["savings_per_fill"] = (drug["savings_reviewed"] / drug["brand_fills_30day"]).fillna(0)
    drug["substitution_review"] = drug["excluded_reason_category"].fillna(
        drug["savings_reviewed"].gt(0).map({True: "Included", False: "Not applicable"}))
    drug = drug.drop(columns=["savings_reviewed", "brand_fills_30day", "excluded_reason_category"])
    drug["drug_label"] = drug["brand_name"].where(
        drug["brand_name"].str.upper() == drug["generic_name"].str.upper(),
        drug["brand_name"] + " (" + drug["generic_name"] + ")")
    extra = pd.DataFrame([
        {"drug_key": OTHER_KEY, "brand_name": OTHER_TEXT, "generic_name": OTHER_TEXT,
         "drug_label": OTHER_TEXT, "brand_generic": "Small cells", "savings_per_fill": 0},
        {"drug_key": NO_DRUG_KEY, "brand_name": "No Part D drug named",
         "generic_name": "No Part D drug named", "drug_label": "No Part D drug named",
         "brand_generic": "Not applicable", "savings_per_fill": 0}])
    drug = pd.concat([drug, extra], ignore_index=True)
    for c in ["generic_available", "brand_with_generic_equivalent", "is_opioid"]:
        drug[c] = drug[c].astype("boolean").fillna(False)

    spec = con.execute("select specialty_key, specialty from marts.dim_specialty").df()
    spec = pd.concat([spec, pd.DataFrame([{"specialty_key": OTHER_KEY, "specialty": OTHER_TEXT}])])

    state = con.execute("""
        select state_key, state_code, state_name, census_region, is_us_state_or_dc
        from marts.dim_state""").df()
    state = pd.concat([state, pd.DataFrame([
        {"state_key": OTHER_KEY, "state_code": "--", "state_name": OTHER_TEXT,
         "census_region": OTHER_TEXT, "is_us_state_or_dc": False}])])

    mfr = con.execute("""
        select manufacturer_key, manufacturer_name, manufacturer_state, manufacturer_country
        from marts.dim_manufacturer""").df()
    mfr = pd.concat([mfr, pd.DataFrame([
        {"manufacturer_key": OTHER_KEY, "manufacturer_name": OTHER_TEXT}])])

    date = con.execute("""
        select date_key, date, year, quarter, month, month_name, month_label,
               day_of_week, day_name, is_weekend
        from marts.dim_date""").df()
    return {"dim_drug": drug, "dim_specialty": spec, "dim_state": state,
            "dim_manufacturer": mfr, "dim_date": date}


def quality_tables(con):
    """Small tables for the Data quality and methodology page."""
    import json
    ingest = pd.DataFrame(json.loads((config.DOCS_DIR / "ingest_row_counts.json").read_text()))
    ingest = ingest[["source", "csv_file", "columns", "csv_rows_python", "csv_rows_duckdb",
                     "parquet_rows", "match"]]
    results = json.loads((config.ROOT / "dbt" / "target" / "build_results.json").read_text())
    tests = pd.DataFrame([{"test": r["unique_id"].split(".")[2], "status": r["status"],
                           "failing_rows": r.get("failures") or 0}
                          for r in results["results"] if r["unique_id"].startswith("test.")])
    tests["test_type"] = tests["test"].str.extract(
        r"^(unique_combination_of_columns|unique|not_null|relationships|accepted_values|assert)",
        expand=False).fillna("other")
    matching = con.execute("""
        select match_method, count(*) as product_names,
               sum(payment_product_rows) as payment_product_rows
        from (select distinct product_name_norm, match_method, payment_product_rows
              from intermediate.int_op_product_drug_map)
        group by 1 order by 3 desc""").df()
    return {"dq_ingest": ingest, "dq_tests": tests, "dq_matching": matching}


def results_tables():
    """Question 2 and 3 results (already aggregate) for the report pages."""
    q2 = pd.read_csv(config.PUBLIC_OUT / "q2_drug_estimates.csv")
    q2 = q2[["family", "eligible_prescribers", "paid_prescribers", "paid_share",
             "prescribing_rate_unpaid", "prescribing_rate_paid", "lpm_coef", "lpm_lo",
             "lpm_hi", "att_any_rx", "att_any_rx_lo", "att_any_rx_hi"]].copy()
    q2["drug"] = q2.pop("family").str.title()
    q2_pooled = pd.read_csv(config.PUBLIC_OUT / "q2_pooled.csv")[
        ["model", "description", "pooled", "lo", "hi", "i2", "k"]]
    q3 = pd.read_csv(config.PUBLIC_OUT / "q3_specialty_summary.csv")[
        ["specialty", "prescribers", "cost_per_claim_median", "brand_share_median",
         "opioid_share_median", "any_flag_rate", "multi_flag_rate"]]
    return {"q2_results": q2, "q2_pooled": q2_pooled, "q3_specialty": q3}


def checks(con, rx, pay, pc, sav_total):
    truth = con.execute("""
        select (select sum(drug_cost) from marts.fact_prescriptions),
               (select sum(claims) from marts.fact_prescriptions),
               (select sum(amount_usd) from marts.fact_payments),
               (select count(*) filter (where received_general_payment) / count(*)
                from marts.dim_prescriber where in_partd)""").fetchone()
    rows = [
        ("Total Drug Cost", truth[0], rx["drug_cost"].sum()),
        ("Total Claims", truth[1], rx["claims"].sum()),
        ("Total Payments", truth[2], pay["amount_usd"].sum()),
        ("Paid Prescriber %", truth[3],
         pc["paid_prescribers"].sum() / pc["partd_prescribers"].sum()),
        ("Cost per Claim", float(truth[0]) / truth[1], rx["drug_cost"].sum() / rx["claims"].sum()),
        ("Generic Savings Opportunity", float(sav_total), rx["generic_savings_usd"].sum()),
        ("Cost in combined small cells (share)", None,
         rx.loc[(rx[["drug_key", "specialty_key", "state_key"]] == OTHER_KEY).any(axis=1),
                "drug_cost"].sum() / rx["drug_cost"].sum()),
        ("Payments in combined small cells (share)", None,
         pay.loc[(pay[["drug_key", "manufacturer_key"]] == OTHER_KEY).any(axis=1)
                 | (pay["nature_of_payment"] == OTHER_TEXT), "amount_usd"].sum()
         / pay["amount_usd"].sum()),
        ("Smallest prescriber count in fact_rx", None, rx["prescribers"].min()),
        ("Smallest recipient count in fact_pay (cells with prescriber recipients)", None,
         pay.loc[pay["recipients"] > 0, "recipients"].min()),
        ("Smallest prescriber count in prescriber_counts", None, pc["partd_prescribers"].min()),
    ]
    out = pd.DataFrame(rows, columns=["check", "warehouse_value", "export_value"])
    out["match"] = out.apply(
        lambda r: None if pd.isna(r.warehouse_value)
        else math.isclose(float(r.export_value), float(r.warehouse_value),
                          rel_tol=1e-9, abs_tol=1e-6),
        axis=1)
    return out


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    con = config.duckdb_connect(read_only=True)
    print("fact_rx ...", flush=True)
    sav = savings(con)
    rx = export_fact_rx(con, sav)
    print("fact_pay ...", flush=True)
    pay = export_fact_pay(con)
    print("prescriber_counts ...", flush=True)
    pc = export_prescriber_counts(con)
    d = dims(con, sav)
    tables = {"fact_rx": rx, "fact_pay": pay, "prescriber_counts": pc, **d,
              **quality_tables(con), **results_tables()}
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8")
        print(f"  {name}: {len(df):,} rows")
    c = checks(con, rx, pay, pc, sav["savings_reviewed"].sum())
    brand = rx.merge(d["dim_drug"][["drug_key", "brand_generic"]], on="drug_key")
    c.loc[len(c)] = ["Brand Share % (claims)", None,
                     brand.loc[brand.brand_generic == "Brand", "claims"].sum() / rx["claims"].sum(),
                     None]
    c.to_csv(OUT / "export_checks.csv", index=False)
    print(c.to_string())
    assert c["match"].dropna().all(), "export totals do not reconcile"
    assert rx["prescribers"].min() >= MIN_CELL_PRESCRIBERS
    assert pc["partd_prescribers"].min() >= MIN_CELL_PRESCRIBERS
    print(f"done in {time.time() - t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
