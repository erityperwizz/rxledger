"""Headline numbers for the README and the summary at the top of docs/findings.md.

Author: Erica Mathias

Reads the public outputs written by the analysis scripts (and two totals from the
warehouse), writes outputs_public/headline_numbers.csv with each number already formatted
as it appears in prose, and refreshes the summary section of docs/findings.md.
tests/test_readme_numbers.py checks that every formatted number quoted in README.md
matches this file, so the README cannot drift from the pipeline.
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis.common import write_section  # noqa: E402

OUT = config.PUBLIC_OUT / "headline_numbers.csv"


def kv(path, key="metric", value="value"):
    d = pd.read_csv(path)
    return dict(zip(d[key], d[value]))


def build():
    pub = config.PUBLIC_OUT
    h = kv(pub / "q1_headline.csv")
    sav = kv(pub / "q1_generic_savings_summary.csv")
    top = pd.read_csv(pub / "q1_top_drugs.csv")
    pooled = pd.read_csv(pub / "q2_pooled.csv").set_index("model")
    est = pd.read_csv(pub / "q2_drug_estimates.csv")
    dose = pd.read_csv(pub / "q2_dose_response.csv")
    q3 = kv(pub / "q3_overall.csv")
    ingest = {r["source"]: r for r in json.loads((config.DOCS_DIR / "ingest_row_counts.json").read_text())}

    con = config.duckdb_connect(read_only=True)
    total_pay, paid_pct, match_rate = con.execute("""
        select (select sum(amount_usd) from marts.fact_payments),
               (select avg(received_general_payment::int) from marts.dim_prescriber where in_partd),
               (select sum(payment_product_rows) filter (where match_method <> 'unmatched')
                       / sum(payment_product_rows)
                from (select distinct product_name_norm, match_method, payment_product_rows
                      from intermediate.int_op_product_drug_map))""").fetchone()

    lpm, att = pooled.loc["lpm"], pooled.loc["matched_att"]
    rows = {
        "partd_rows": f"{ingest['partd_prescriber_drug']['parquet_rows']:,}",
        "op_general_rows": f"{ingest['op_general']['parquet_rows']:,}",
        "total_drug_cost": f"${float(h['total_drug_cost']) / 1e9:,.1f} billion",
        "total_claims": f"{float(h['total_claims']) / 1e9:,.2f} billion",
        "prescribers": f"{float(h['prescribers']):,.0f}",
        "generic_share_claims": f"{float(h['generic_share_claims']):.1%}",
        "generic_share_cost": f"{float(h['generic_share_cost']):.1%}",
        "top10_share_of_cost": f"{top.head(10)['share_of_total_cost'].sum():.1%}",
        "savings_upper_bound": f"${sav['savings_upper_bound'] / 1e9:,.2f} billion",
        "savings_reviewed": f"${sav['savings_reviewed_estimate'] / 1e9:,.2f} billion",
        "total_payments": f"${float(total_pay) / 1e9:,.2f} billion",
        "paid_prescriber_pct": f"{paid_pct:.1%}",
        "drug_match_rate": f"{match_rate:.1%}",
        "q2_drugs": f"{len(est)}",
        "q2_positive_drugs": f"{int((est['lpm_lo'] > 0).sum())} of {len(est)}",
        "q2_lpm": f"{lpm['pooled'] * 100:.1f} percentage points",
        "q2_lpm_ci": f"{lpm['lo'] * 100:+.1f} to {lpm['hi'] * 100:+.1f}",
        "q2_matched": f"{att['pooled'] * 100:.1f} percentage points",
        "q2_matched_ci": f"{att['lo'] * 100:+.1f} to {att['hi'] * 100:+.1f}",
        "q2_dose_low": f"{dose.iloc[0]['pooled'] * 100:+.1f}",
        "q2_dose_high": f"{dose.iloc[-1]['pooled'] * 100:+.1f}",
        "q3_prescribers": f"{q3['prescribers_analyzed']:,.0f}",
        "q3_any_flag": f"{q3['any_flag_rate']:.1%}",
        "q3_multi_flag": f"{q3['multi_flag_rate']:.2%}",
    }
    genai = pub / "genai_validation.csv"
    if genai.exists():
        g = kv(genai)
        rows.update({
            "genai_accuracy": f"{float(g['accuracy']):.0%}",
            "genai_accuracy_ci": f"{float(g['accuracy_ci_low']):.0%} to {float(g['accuracy_ci_high']):.0%}",
            "genai_threshold": f"{float(g['acceptance_threshold']):.0%}",
            "genai_lenient": f"{float(g['accuracy_including_noted_alternates']):.0%}",
            "genai_cost_weighted": f"{float(g['cost_weighted_accuracy']):.0%}",
        })
    return rows


def summary_markdown(r):
    return "\n".join([
        "## Summary",
        "",
        f"- **Spend.** Medicare Part D paid {r['total_drug_cost']} for {r['total_claims']} "
        f"claims in 2024. Generics were {r['generic_share_claims']} of claims but only "
        f"{r['generic_share_cost']} of cost, and the ten costliest drugs took "
        f"{r['top10_share_of_cost']} of all spending.",
        f"- **Generic substitution.** Dispensing an interchangeable generic in place of each brand would have "
        f"saved an estimated {r['savings_reviewed']} (gross, before rebates), after removing "
        f"pairs that are not interchangeable from a formula upper bound of "
        f"{r['savings_upper_bound']}.",
        f"- **Payments and prescribing.** Across the {r['q2_drugs']} biggest brand drugs, "
        f"prescribers paid by the drug's manufacturer were {r['q2_lpm']} more likely to "
        f"prescribe it (95% CI {r['q2_lpm_ci']}; matched comparison {r['q2_matched']}), with "
        f"a positive gap for {r['q2_positive_drugs']} drugs. This is an association, not "
        "evidence of influence or wrongdoing.",
        f"- **Outliers.** {r['q3_any_flag']} of {r['q3_prescribers']} prescribers are "
        f"unusual for their specialty on at least one metric and {r['q3_multi_flag']} on two "
        "or more; results are published only in aggregate.",
    ])


def main():
    r = build()
    pd.DataFrame(list(r.items()), columns=["key", "formatted"]).to_csv(OUT, index=False)
    write_section(config.DOCS_DIR / "findings.md", "summary", summary_markdown(r))
    for k, v in r.items():
        print(f"{k:22s} {v}")


if __name__ == "__main__":
    main()
