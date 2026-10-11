"""Question 1: where does Medicare Part D drug money go?

Author: Erica Mathias

Reads the gold star schema (dbt marts) and writes:
  outputs_public/q1_*.csv        national, drug, specialty, and state aggregates only
  docs/figures/q1_*.png          charts for the README and findings
  docs/findings.md               the Question 1 section (between q1 markers)

Generic substitution savings
----------------------------
For every Brand drug whose generic name also has Generic products in Part D:
    savings = brand 30 day fills x max(brand cost per fill - generic cost per fill, 0)
where the generic cost per fill pools all Generic rows with the same generic name.
Part D has no dosage form or strength field, so a generic name group can mix forms
(extended vs immediate release, injection vs tablet, inhaler vs nebulizer). The formula
total is therefore reported as an upper bound. The top REVIEW_DEPTH brands by upper bound
savings were reviewed by hand; brands whose generic group is a different form, route,
device, or strength are listed with reasons in dbt/seeds/generic_substitution_exclusions.csv
and removed for the reviewed estimate. Costs are gross (before manufacturer rebates).
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis import charts  # noqa: E402
from analysis.common import suppress_small_cells, write_section  # noqa: E402

REVIEW_DEPTH = 120
FIG_DIR = config.DOCS_DIR / "figures"


def query(con, sql):
    return con.execute(sql).df()


def headline(con):
    h = query(con, """
        select
            sum(f.drug_cost)                                    as total_drug_cost,
            sum(f.claims)                                       as total_claims,
            sum(f.fills_30day)                                  as total_fills_30day,
            count(distinct f.prescriber_key)                    as prescribers,
            count(distinct f.drug_key)                          as drugs,
            count(distinct d.generic_name_norm)                 as generic_names,
            count(distinct f.specialty_key)                     as specialties,
            count(*)                                            as prescriber_drug_rows,
            sum(f.claims) filter (where d.brand_generic = 'Generic') / sum(f.claims)
                                                                as generic_share_claims,
            sum(f.drug_cost) filter (where d.brand_generic = 'Generic') / sum(f.drug_cost)
                                                                as generic_share_cost,
            sum(f.claims) filter (where d.is_generic_strict_rule) / sum(f.claims)
                                                                as generic_share_claims_strict,
            sum(f.drug_cost) filter (where d.is_generic_strict_rule) / sum(f.drug_cost)
                                                                as generic_share_cost_strict,
            sum(f.drug_cost) filter (where d.brand_generic = 'Brand') / sum(f.claims) filter (where d.brand_generic = 'Brand')
                                                                as brand_cost_per_claim,
            sum(f.drug_cost) filter (where d.brand_generic = 'Generic') / sum(f.claims) filter (where d.brand_generic = 'Generic')
                                                                as generic_cost_per_claim
        from marts.fact_prescriptions f
        join marts.dim_drug d using (drug_key)""")
    return h.iloc[0]


def brand_generic(con):
    return query(con, """
        select d.brand_generic,
               count(distinct f.drug_key)       as drugs,
               sum(f.claims)                    as claims,
               sum(f.fills_30day)               as fills_30day,
               sum(f.drug_cost)                 as drug_cost,
               sum(f.drug_cost) / sum(f.claims) as cost_per_claim,
               sum(f.claims) / sum(sum(f.claims)) over ()       as share_of_claims,
               sum(f.drug_cost) / sum(sum(f.drug_cost)) over () as share_of_cost
        from marts.fact_prescriptions f join marts.dim_drug d using (drug_key)
        group by 1 order by 1""")


def top_drugs(con, n=25):
    return query(con, f"""
        select d.brand_name, d.generic_name, d.brand_generic,
               count(*)                         as prescribers,
               sum(f.claims)                    as claims,
               sum(f.fills_30day)               as fills_30day,
               sum(f.drug_cost)                 as drug_cost,
               sum(f.drug_cost) / sum(f.claims) as cost_per_claim,
               sum(f.drug_cost) / sum(sum(f.drug_cost)) over () as share_of_total_cost
        from marts.fact_prescriptions f join marts.dim_drug d using (drug_key)
        group by d.brand_name, d.generic_name, d.brand_generic
        order by drug_cost desc, d.brand_name, d.generic_name
        limit {n}""")


def by_group(con, dim_sql, group_cols):
    cols = ", ".join(group_cols)
    return query(con, f"""
        select {cols},
               count(distinct f.prescriber_key)                         as prescribers,
               sum(f.claims)                                            as claims,
               sum(f.drug_cost)                                         as drug_cost,
               sum(f.drug_cost) / sum(f.claims)                         as cost_per_claim,
               sum(f.drug_cost) / count(distinct f.prescriber_key)      as cost_per_prescriber,
               sum(f.claims) filter (where d.brand_generic = 'Brand') / sum(f.claims)
                                                                        as brand_share_claims,
               sum(f.drug_cost) filter (where d.brand_generic = 'Brand') / sum(f.drug_cost)
                                                                        as brand_share_cost,
               sum(f.drug_cost) / sum(sum(f.drug_cost)) over ()         as share_of_total_cost
        from marts.fact_prescriptions f
        join marts.dim_drug d using (drug_key)
        {dim_sql}
        group by all
        order by drug_cost desc, 1""")


def savings(con):
    s = query(con, f"""
        with drug_totals as (
            select d.drug_key, d.brand_name, d.generic_name, d.brand_name_norm,
                   d.generic_name_norm, d.brand_generic,
                   sum(f.fills_30day) as fills_30day, sum(f.drug_cost) as drug_cost,
                   count(*) as prescribers
            from marts.fact_prescriptions f join marts.dim_drug d using (drug_key)
            group by all
        ),
        generic_price as (
            select generic_name_norm,
                   sum(drug_cost) / sum(fills_30day) as generic_cost_per_fill,
                   sum(fills_30day)                  as generic_fills_30day
            from drug_totals where brand_generic = 'Generic'
            group by 1
        ),
        excl as (
            select {normalize('brand_name')} as brand_name_norm, reason_category, reason
            from main.generic_substitution_exclusions
        ),
        s as (
            select b.drug_key, b.brand_name, b.generic_name, b.prescribers,
                   b.fills_30day                         as brand_fills_30day,
                   b.drug_cost                           as brand_drug_cost,
                   b.drug_cost / b.fills_30day           as brand_cost_per_fill,
                   g.generic_cost_per_fill,
                   g.generic_fills_30day,
                   greatest(b.drug_cost / b.fills_30day - g.generic_cost_per_fill, 0)
                       * b.fills_30day                   as savings_upper_bound,
                   e.reason_category                     as excluded_reason_category,
                   e.reason                              as excluded_reason
            from drug_totals b
            join generic_price g using (generic_name_norm)
            left join excl e using (brand_name_norm)
            where b.brand_generic = 'Brand'
        )
        select *,
               row_number() over (order by savings_upper_bound desc, drug_key) as upper_bound_rank,
               case when excluded_reason_category is null then savings_upper_bound else 0 end
                                                         as savings_reviewed
        from s
        order by savings_upper_bound desc, drug_key""")
    s["reviewed_by_hand"] = s["upper_bound_rank"] <= REVIEW_DEPTH
    return s


def normalize(col):
    return f"nullif(trim(regexp_replace(upper({col}), '[^A-Z0-9]+', ' ', 'g')), '')"


def savings_summary(s):
    upper = s["savings_upper_bound"].sum()
    reviewed = s["savings_reviewed"].sum()
    excluded = upper - reviewed
    tail = s.loc[~s["reviewed_by_hand"], "savings_upper_bound"].sum()
    reliable = s.loc[s["generic_fills_30day"] >= 10_000, "savings_reviewed"].sum()
    rows = [
        ("brands_with_generic_equivalent", len(s), "Brand drugs whose generic name has Generic products in Part D"),
        ("brand_cost_with_generic_equivalent", s["brand_drug_cost"].sum(), "2024 Part D cost of those brands, USD"),
        ("savings_upper_bound", upper, "Formula applied to every pair, USD"),
        ("savings_excluded_after_review", excluded, "Pairs judged not interchangeable (different form, route, device, strength)"),
        ("savings_reviewed_estimate", reviewed, "Upper bound minus excluded pairs, USD (headline)"),
        ("savings_reviewed_generic_fills_10k", reliable, "Reviewed estimate, only generic prices based on 10,000+ fills"),
        ("brands_reviewed_by_hand", int(s["reviewed_by_hand"].sum()), f"Top {REVIEW_DEPTH} brands by upper bound savings"),
        ("share_of_upper_bound_reviewed", 1 - tail / upper, "Share of upper bound savings covered by the hand review"),
        ("brands_excluded", int(s["excluded_reason_category"].notna().sum()), "Brands excluded after review"),
    ]
    import pandas as pd
    return pd.DataFrame(rows, columns=["metric", "value", "definition"])


# ---------------------------------------------------------------- charts

def fig_top_drugs(top):
    t = top.head(15)
    labels = [f"{b}  ({g})" if b.upper() != g.upper() else b
              for b, g in zip(t["brand_name"], t["generic_name"])]
    fig, ax = plt.subplots(figsize=(9, 6.2))
    charts.hbar(ax, labels, (t["drug_cost"] / 1e9).tolist(), fmt=lambda v: f"${v:.1f}B")
    ax.xaxis.set_major_formatter(charts.dollars(1, "B"))
    charts.title(ax, "Top 15 drugs by Medicare Part D cost, 2024",
                 "Total drug cost paid, all payers, before manufacturer rebates")
    charts.source_note(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "q1_top_drugs.png", dpi=160)
    plt.close(fig)


def fig_brand_generic(bg):
    b = bg.set_index("brand_generic")
    metrics = [("Claims", "share_of_claims"), ("Drug cost", "share_of_cost")]
    fig, ax = plt.subplots(figsize=(9, 2.9))
    for i, (label, col) in enumerate(metrics[::-1]):
        gen, brand = b.loc["Generic", col], b.loc["Brand", col]
        ax.barh(i, gen, height=0.5, color=charts.BLUE, edgecolor=charts.SURFACE, linewidth=2,
                label="Generic" if i == 0 else None)
        ax.barh(i, brand, left=gen, height=0.5, color=charts.ORANGE, edgecolor=charts.SURFACE,
                linewidth=2, label="Brand" if i == 0 else None)
        for start, width in ((0, gen), (gen, brand)):
            if width > 0.08:
                ax.text(start + width / 2, i, f"{width:.0%}", ha="center", va="center",
                        color="white", fontsize=10, fontweight="bold")
    ax.set_yticks([0, 1], [m[0] for m in metrics[::-1]])
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2, frameon=False, fontsize=9)
    charts.title(ax, "Generics fill most prescriptions; brands take most of the money",
                 "Share of 2024 Medicare Part D claims and drug cost")
    charts.source_note(fig)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(FIG_DIR / "q1_brand_vs_generic.png", dpi=160)
    plt.close(fig)


def fig_savings(s):
    t = s[s["savings_reviewed"] > 0].nlargest(12, "savings_reviewed")
    labels = [f"{b}  ({g})" for b, g in zip(t["brand_name"], t["generic_name"])]
    fig, ax = plt.subplots(figsize=(9, 5.4))
    charts.hbar(ax, labels, (t["savings_reviewed"] / 1e6).tolist(), fmt=lambda v: f"${v:,.0f}M")
    ax.xaxis.set_major_formatter(charts.dollars(1, "M"))
    charts.title(ax, "Largest generic substitution opportunities, 2024",
                 "Brand 30 day fills x (brand minus generic cost per fill); gross of rebates")
    charts.source_note(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "q1_generic_savings.png", dpi=160)
    plt.close(fig)


def fig_specialty(spec):
    t = spec.head(12)
    fig, ax = plt.subplots(figsize=(9, 5.4))
    charts.hbar(ax, t["specialty"].tolist(), (t["drug_cost"] / 1e9).tolist(),
                fmt=lambda v: f"${v:.1f}B")
    ax.xaxis.set_major_formatter(charts.dollars(1, "B"))
    charts.title(ax, "Part D drug cost by prescriber specialty, 2024 (top 12)",
                 "Total drug cost paid; specialty as assigned by CMS")
    charts.source_note(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "q1_specialty_cost.png", dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- findings text

def findings_markdown(h, bg, top, spec, state, s, summ):
    v = dict(zip(summ["metric"], summ["value"]))
    us = state[state["is_us_state_or_dc"]]
    top3 = top.head(3)
    top10_share = top.head(10)["share_of_total_cost"].sum()
    excl = s[s["excluded_reason_category"].notna()]
    excl_cats = excl.groupby("excluded_reason_category")["savings_upper_bound"].sum() \
        .sort_values(ascending=False)
    spec_top = spec.head(5)
    lines = [
        "## Question 1: Where does Medicare Part D drug money go?",
        "",
        f"Medicare Part D paid **${h.total_drug_cost / 1e9:,.1f} billion** for "
        f"**{h.total_claims / 1e9:,.2f} billion claims** written by **{h.prescribers:,.0f} prescribers** "
        f"across {h.drugs:,.0f} drug products ({h.generic_names:,.0f} generic names) in 2024. "
        "Costs are gross: they include what plans, beneficiaries, and subsidies paid, before "
        "manufacturer rebates, which CMS does not publish at the drug level.",
        "",
        "### Brand vs generic",
        "",
        f"Generics are **{h.generic_share_claims:.1%} of claims but {h.generic_share_cost:.1%} of cost**. "
        f"A brand claim cost ${h.brand_cost_per_claim:,.0f} on average vs ${h.generic_cost_per_claim:,.0f} "
        "for a generic claim.",
        "",
        "![Brand vs generic share](figures/q1_brand_vs_generic.png)",
        "",
        "The brand or generic label is derived from names (CMS publishes no flag). The strict "
        "rule (brand name equals generic name) would put generics at "
        f"{h.generic_share_claims_strict:.1%} of claims and {h.generic_share_cost_strict:.1%} of cost, because many "
        "generic products carry a reformatted name (for example \"Clopidogrel\" for clopidogrel "
        "bisulfate). The rule used is documented in data_dictionary.md.",
        "",
        "### Concentration in a few drugs",
        "",
        f"The top 10 drugs account for **{top10_share:.1%}** of all Part D cost. The three largest:",
        "",
    ]
    for _, r in top3.iterrows():
        lines.append(f"- **{r.brand_name}** ({r.generic_name.lower()}): ${r.drug_cost / 1e9:,.2f}B, "
                     f"{r.share_of_total_cost:.1%} of total, ${r.cost_per_claim:,.0f} per claim")
    lines += [
        "",
        "![Top drugs](figures/q1_top_drugs.png)",
        "",
        "### Specialties and states",
        "",
        "The five specialties with the most Part D cost:",
        "",
        "| Specialty | Prescribers | Drug cost | Share of total | Brand share of cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, r in spec_top.iterrows():
        lines.append(f"| {r.specialty} | {r.prescribers:,.0f} | ${r.drug_cost / 1e9:,.1f}B | "
                     f"{r.share_of_total_cost:.1%} | {r.brand_share_cost:.1%} |")
    big = us.nlargest(1, "drug_cost").iloc[0]
    hi = us.nlargest(1, "brand_share_cost").iloc[0]
    lo = us.nsmallest(1, "brand_share_cost").iloc[0]
    lead = spec.iloc[0]
    per = spec[spec["prescribers"] >= 1000].nlargest(3, "cost_per_prescriber")
    per_txt = ", ".join(f"{r.specialty} (${r.cost_per_prescriber / 1e6:,.2f}M)"
                        for _, r in per.iterrows())
    lines += [
        "",
        f"Specialty totals mostly reflect headcount: {lead.specialty} ranks first because "
        f"{lead.prescribers:,.0f} of them prescribe in Part D. Per prescriber, the highest cost "
        f"specialties (among those with 1,000+ prescribers) are {per_txt}, driven by specialty "
        "drugs such as oral cancer and immunology therapies.",
        "",
        f"By state, {big.state_name} has the largest total (${big.drug_cost / 1e9:,.1f}B). Among the "
        f"50 states and DC, brand share of cost ranges from {lo.brand_share_cost:.1%} "
        f"({lo.state_name}) to {hi.brand_share_cost:.1%} ({hi.state_name}). State totals follow "
        "Medicare enrollment, so they are not per capita comparisons.",
        "",
        "![Specialty cost](figures/q1_specialty_cost.png)",
        "",
        "### Generic substitution savings",
        "",
        f"{v['brands_with_generic_equivalent']:,.0f} brand products share a generic name with at least one "
        f"generic product in Part D. Together they cost ${v['brand_cost_with_generic_equivalent'] / 1e9:,.1f}B.",
        "",
        "Method: for each such brand, savings = brand 30 day fills x (brand cost per 30 day fill "
        "minus the pooled generic cost per 30 day fill for the same generic name), floored at zero.",
        "",
        "| Estimate | Savings |",
        "|---|---:|",
        f"| Formula applied to every pair (upper bound) | ${v['savings_upper_bound'] / 1e9:,.2f}B |",
        f"| Minus pairs judged not interchangeable on review | -${v['savings_excluded_after_review'] / 1e9:,.2f}B |",
        f"| **Reviewed estimate** | **${v['savings_reviewed_estimate'] / 1e9:,.2f}B** |",
        f"| Reviewed, generic price based on 10,000+ fills only | ${v['savings_reviewed_generic_fills_10k'] / 1e9:,.2f}B |",
        "",
        f"The reviewed estimate is about **{v['savings_reviewed_estimate'] / h.total_drug_cost:.1%} of total Part D "
        "cost**.",
        "",
        "![Generic savings](figures/q1_generic_savings.png)",
        "",
        "Why a hand review: Part D has no dosage form or strength field, so a generic name "
        "group can mix forms. Long acting injections priced against oral tablets, extended "
        "release brands priced against immediate release generics, and inhalers priced against "
        "nebulizer solution all inflate the formula. The top "
        f"{v['brands_reviewed_by_hand']:,.0f} brands by upper bound savings ({v['share_of_upper_bound_reviewed']:.0%} of the upper "
        f"bound) were reviewed and {v['brands_excluded']:,.0f} were excluded, with a written reason for each in "
        "`dbt/seeds/generic_substitution_exclusions.csv`. Excluded upper bound savings by reason:",
        "",
    ]
    for cat, amt in excl_cats.items():
        lines.append(f"- {cat}: ${amt / 1e9:,.2f}B")
    lines += [
        "",
        "Limitations:",
        "",
        "- **Gross cost, before rebates.** Brands with generic competition often carry large "
        "manufacturer rebates, so the net savings to Medicare would be smaller than shown.",
        "- **Full substitution is not realistic.** Some patients need the brand (allergy to an "
        "inactive ingredient, narrow therapeutic index drugs, failed generic trials); the "
        "estimate is an opportunity size, not a forecast.",
        "- **Pooled generic price.** The generic cost per fill averages all generic strengths and "
        "manufacturers for the generic name over all of 2024. For generics that entered the "
        "market recently, the 2024 generic price may still be high, which understates the gap.",
        f"- **Review depth.** Brands below rank {REVIEW_DEPTH} ({1 - v['share_of_upper_bound_reviewed']:.0%} of the upper "
        "bound) were not reviewed by hand and may include a few similar mismatches.",
        "",
        "Outputs: `outputs_public/q1_*.csv`.",
    ]
    return "\n".join(lines)


def main():
    config.PUBLIC_OUT.mkdir(exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    charts.style()
    con = config.duckdb_connect(read_only=True)

    h = headline(con)
    bg = brand_generic(con)
    top = top_drugs(con)
    spec = suppress_small_cells(by_group(
        con, "join marts.dim_specialty sp using (specialty_key)", ["sp.specialty"]))
    state = suppress_small_cells(by_group(
        con, "join marts.dim_state st using (state_key)",
        ["st.state_code", "st.state_name", "st.census_region", "st.is_us_state_or_dc"]))
    s = savings(con)
    summ = savings_summary(s)

    h.to_frame("value").rename_axis("metric").to_csv(config.PUBLIC_OUT / "q1_headline.csv")
    bg.to_csv(config.PUBLIC_OUT / "q1_brand_vs_generic.csv", index=False)
    top.to_csv(config.PUBLIC_OUT / "q1_top_drugs.csv", index=False)
    spec.to_csv(config.PUBLIC_OUT / "q1_specialty.csv", index=False)
    state.to_csv(config.PUBLIC_OUT / "q1_state.csv", index=False)
    # brand level rows: drop brands with fewer than 11 prescribers (totals above use all rows)
    suppress_small_cells(s).to_csv(config.PUBLIC_OUT / "q1_generic_savings_by_brand.csv",
                                   index=False)
    summ.to_csv(config.PUBLIC_OUT / "q1_generic_savings_summary.csv", index=False)

    fig_top_drugs(top)
    fig_brand_generic(bg)
    fig_savings(s)
    fig_specialty(spec)

    md = findings_markdown(h, bg, top, spec, state, s, summ)
    write_section(config.DOCS_DIR / "findings.md", "q1", md)
    print(md)


if __name__ == "__main__":
    main()
