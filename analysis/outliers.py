"""Question 3: which prescribers are statistical outliers within their specialty?

Author: Erica Mathias

Only aggregates are published. Individual flags are written to outputs_private/
(git-ignored) and never appear in the README, charts, or committed CSVs. An outlier is
a prescriber whose pattern is unusual for their specialty label; it is not a finding of
fraud, waste, or poor care.

Population  Part D prescribers with at least MIN_CLAIMS claims, in specialties with at
            least MIN_SPECIALTY_SIZE such prescribers.
Metrics     cost_per_claim       total drug cost / total claims (log scale for scoring)
            brand_share          brand claims / total claims
            cost_per_beneficiary drug cost / beneficiaries, computed only over drug rows
                                 where CMS did not suppress beneficiaries (a proxy: the
                                 same patient counts once per drug; log scale)
            opioid_share         opioid claims / total claims (dim_drug.is_opioid,
                                 buprenorphine excluded)
Robust z    modified z = 0.6745 x (x - specialty median) / specialty MAD (Iglewicz and
            Hoaglin), on a log scale for costs and an arcsine square root scale for shares
            (raw shares near zero are so skewed that a few percent looks extreme). Flag
            when z > Z_THRESHOLD (high side only). When a specialty's MAD
            is 0 for a metric (for example most prescribers write no opioids), the metric
            is not scored for that specialty rather than flagging every nonzero value.
Isolation   scikit-learn IsolationForest per specialty on the robust scaled metrics, fixed
Forest      seed, contamination IF_CONTAMINATION; used as a second opinion (overlap).
"""

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis import charts  # noqa: E402
from analysis.common import MIN_CELL_PRESCRIBERS, suppress_small_cells, write_section  # noqa: E402

MIN_CLAIMS = 100
MIN_SPECIALTY_SIZE = 100
Z_THRESHOLD = 3.5
IF_CONTAMINATION = 0.01
FIG_DIR = config.DOCS_DIR / "figures"

METRICS = {
    # name: (column, scale used for scoring, label)
    "cost_per_claim": ("cost_per_claim", "log", "Cost per claim"),
    "brand_share": ("brand_share", "asin_sqrt", "Brand share of claims"),
    "cost_per_beneficiary": ("cost_per_beneficiary", "log", "Cost per beneficiary (proxy)"),
    "opioid_share": ("opioid_share", "asin_sqrt", "Opioid share of claims"),
}


def transform(x, scale):
    """Scoring scale: log for costs (zero or negative -> missing), arcsine square root
    for shares (the standard variance stabilizing transform for proportions)."""
    x = pd.Series(x, dtype=float)
    if scale == "log":
        return np.log(x.where(x > 0))
    return np.arcsin(np.sqrt(x.clip(0, 1)))

PRESCRIBER_SQL = f"""
with m as (
    select
        f.prescriber_key,
        sum(f.claims)                                                   as total_claims,
        sum(f.drug_cost)                                                as total_cost,
        sum(f.claims) filter (where d.brand_generic = 'Brand')          as brand_claims,
        sum(f.claims) filter (where d.is_opioid)                        as opioid_claims,
        sum(f.drug_cost) filter (where not f.beneficiaries_suppressed)  as cost_unsuppressed,
        sum(f.beneficiaries)                                            as beneficiaries_unsuppressed
    from marts.fact_prescriptions f
    join marts.dim_drug d using (drug_key)
    group by 1
)
select
    p.prescriber_key, p.npi, p.last_org_name, p.first_name, p.city,
    sp.specialty, st.state_code, st.state_name, st.is_us_state_or_dc,
    m.total_claims, m.total_cost,
    m.total_cost / m.total_claims                                       as cost_per_claim,
    coalesce(m.brand_claims, 0) / m.total_claims                        as brand_share,
    coalesce(m.opioid_claims, 0) / m.total_claims                       as opioid_share,
    m.cost_unsuppressed / nullif(m.beneficiaries_unsuppressed, 0)       as cost_per_beneficiary
from m
join marts.dim_prescriber p using (prescriber_key)
join marts.dim_specialty sp using (specialty_key)
left join marts.dim_state st using (state_key)
where m.total_claims >= {MIN_CLAIMS}
"""


def robust_z(x):
    """Modified z score; NaN for every row when MAD is 0 (spread undefined)."""
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    if not np.isfinite(mad) or mad == 0:
        return np.full(len(x), np.nan), med, mad
    return 0.6745 * (x - med) / mad, med, mad


def score(df):
    df = df.copy()
    sizes = df.groupby("specialty")["prescriber_key"].transform("size")
    df = df[sizes >= MIN_SPECIALTY_SIZE].reset_index(drop=True)
    skipped = []
    for name, (col, scale, _) in METRICS.items():
        x = transform(df[col], scale)
        df[f"{name}_z"] = np.nan
        for spec, idx in df.groupby("specialty").groups.items():
            z, _, mad = robust_z(x.loc[idx].to_numpy(dtype=float))
            if np.isnan(z).all():
                skipped.append((spec, name))
            df.loc[idx, f"{name}_z"] = z
        df[f"{name}_flag"] = df[f"{name}_z"] > Z_THRESHOLD
    flags = [f"{m}_flag" for m in METRICS]
    df["flags"] = df[flags].sum(axis=1)
    df["any_flag"] = df["flags"] >= 1
    df["multi_flag"] = df["flags"] >= 2
    return df, pd.DataFrame(skipped, columns=["specialty", "metric"])


def isolation_forest(df):
    """Per specialty Isolation Forest on robust scaled metrics (missing -> specialty median)."""
    df = df.copy()
    df["if_score"] = np.nan
    df["if_flag"] = False
    for spec, idx in df.groupby("specialty").groups.items():
        cols = []
        for name, (col, scale, _) in METRICS.items():
            x = transform(df.loc[idx, col], scale)
            x = x.fillna(x.median())
            med = x.median()
            iqr = x.quantile(0.75) - x.quantile(0.25)
            cols.append(((x - med) / iqr) if iqr > 0 else (x - med))
        X = np.column_stack(cols)
        model = IsolationForest(n_estimators=200, contamination=IF_CONTAMINATION,
                                random_state=config.SEED)
        model.fit(X)
        df.loc[idx, "if_score"] = -model.score_samples(X)
        df.loc[idx, "if_flag"] = model.predict(X) == -1
    return df


def small(n):
    """Counts of 1 to 10 are suppressed in public outputs (CMS small cell rule)."""
    return np.where((n > 0) & (n < MIN_CELL_PRESCRIBERS), np.nan, n)


def specialty_summary(df):
    rows = []
    for spec, g in df.groupby("specialty"):
        r = {"specialty": spec, "prescribers": len(g)}
        for name, (col, _, _) in METRICS.items():
            v = g[col].dropna()
            r[f"{name}_median"] = v.median()
            r[f"{name}_p25"] = v.quantile(0.25)
            r[f"{name}_p75"] = v.quantile(0.75)
            scored = g[f"{name}_z"].notna().any()
            r[f"{name}_scored"] = scored
            r[f"{name}_flagged"] = int(g[f"{name}_flag"].sum()) if scored else np.nan
        r["any_flagged"] = int(g["any_flag"].sum())
        r["multi_flagged"] = int(g["multi_flag"].sum())
        r["if_flagged"] = int(g["if_flag"].sum())
        r["if_also_robust_flagged"] = int((g["if_flag"] & g["any_flag"]).sum())
        rows.append(r)
    s = pd.DataFrame(rows).sort_values("prescribers", ascending=False)
    for c in [c for c in s.columns if c.endswith("_flagged")]:
        s[f"{c.replace('_flagged', '')}_flag_rate"] = s[c] / s["prescribers"]
        s[c] = small(s[c].to_numpy(dtype=float))
    return suppress_small_cells(s.reset_index(drop=True))


def state_summary(df):
    g = df.groupby(["state_code", "state_name", "is_us_state_or_dc"], dropna=False)
    s = g.agg(prescribers=("prescriber_key", "size"), any_flagged=("any_flag", "sum"),
              multi_flagged=("multi_flag", "sum")).reset_index()
    s["any_flag_rate"] = s["any_flagged"] / s["prescribers"]
    s["multi_flag_rate"] = s["multi_flagged"] / s["prescribers"]
    for c in ["any_flagged", "multi_flagged"]:
        s[c] = small(s[c].to_numpy(dtype=float))
    return suppress_small_cells(s.sort_values("any_flag_rate", ascending=False)
                                .reset_index(drop=True))


def overall(df, skipped):
    rows = [("prescribers_analyzed", len(df)),
            ("specialties_analyzed", df["specialty"].nunique()),
            ("any_flag_rate", df["any_flag"].mean()),
            ("multi_flag_rate", df["multi_flag"].mean()),
            ("any_flagged", int(df["any_flag"].sum())),
            ("multi_flagged", int(df["multi_flag"].sum())),
            ("if_flagged", int(df["if_flag"].sum())),
            ("if_also_robust_flagged_share",
             (df["if_flag"] & df["any_flag"]).sum() / df["if_flag"].sum()),
            ("robust_multi_also_if_share",
             (df["if_flag"] & df["multi_flag"]).sum() / df["multi_flag"].sum())]
    for name in METRICS:
        scored = df[f"{name}_z"].notna()
        rows += [(f"{name}_scored_prescribers", int(scored.sum())),
                 (f"{name}_flagged", int(df[f"{name}_flag"].sum())),
                 (f"{name}_flag_rate_among_scored", df.loc[scored, f"{name}_flag"].mean()),
                 (f"{name}_specialties_not_scored",
                  int((skipped["metric"] == name).sum()))]
    return pd.DataFrame(rows, columns=["metric", "value"])


# ---------------------------------------------------------------- chart and findings

def fig_flag_rates(spec):
    t = spec.head(15).sort_values("any_flag_rate")  # 15 largest, ranked by rate
    fig, ax = plt.subplots(figsize=(9, 6))
    y = np.arange(len(t))
    ax.barh(y, t["any_flag_rate"] * 100, height=0.62, color=charts.BLUE,
            edgecolor=charts.SURFACE, linewidth=2)
    for yi, v in zip(y, t["any_flag_rate"] * 100):
        ax.text(v + 0.15, yi, f"{v:.1f}%", va="center", fontsize=9, color=charts.INK_2)
    ax.set_yticks(y, t["specialty"])
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, (t["any_flag_rate"].max() * 100) * 1.18)
    ax.set_xlabel("Share of prescribers flagged on at least one metric (%)")
    charts.title(ax, "Outlier rates in the 15 largest specialties",
                 f"Robust z above {Z_THRESHOLD} within specialty on cost per claim, brand share, "
                 "cost per beneficiary, or opioid share")
    charts.source_note(fig)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "q3_flag_rates.png", dpi=160)
    plt.close(fig)


def findings_markdown(o, spec, state):
    v = dict(zip(o["metric"], o["value"]))
    us = state[state["is_us_state_or_dc"] == True]  # noqa: E712
    hi = us.nlargest(3, "any_flag_rate")
    lo = us.nsmallest(3, "any_flag_rate")
    big = spec.head(10)
    lines = [
        "## Question 3: Which prescribers are statistical outliers within their specialty?",
        "",
        "**Only aggregate results are published.** Individual flags stay in a local, "
        "git-ignored folder. An outlier here means a prescribing pattern that is unusual for "
        "the prescriber's specialty label. It is not a finding of fraud, waste, or poor care: "
        "a subspecialist, a hospice or oncology focused practice, or a clinic serving very sick "
        "patients will look unusual by design.",
        "",
        "### Method",
        "",
        f"- **Population:** {v['prescribers_analyzed']:,.0f} Part D prescribers with at least "
        f"{MIN_CLAIMS} claims, in {v['specialties_analyzed']:,.0f} specialties with at least "
        f"{MIN_SPECIALTY_SIZE} such prescribers.",
        "- **Metrics:** cost per claim, brand share of claims, cost per beneficiary (proxy, "
        "using only drug rows where CMS did not suppress beneficiaries), and opioid share of "
        "claims (buprenorphine excluded because it mostly treats opioid use disorder).",
        f"- **Robust z score** within specialty: 0.6745 x (value minus specialty median) / "
        f"median absolute deviation. Flag when above {Z_THRESHOLD} (high side). Median and MAD "
        "are not pulled around by the extremes the "
        "way a mean and standard deviation are.",
        "- **Scales.** Costs are scored on a log scale and shares on an arcsine square root "
        "scale. On the raw scale, a specialty whose median opioid share is under 1% would "
        "flag anyone above about 5%, which is not unusual in practice.",
        "- **Isolation Forest** per specialty on the same four metrics (fixed seed, top "
        f"{IF_CONTAMINATION:.0%} most isolated), as a second, multivariate opinion.",
        "",
        "### Results",
        "",
        f"{v['any_flag_rate']:.1%} of analyzed prescribers are flagged on at least one metric "
        f"and **{v['multi_flag_rate']:.2%} on two or more**.",
        "",
        "| Metric | Prescribers scored | Flagged | Rate | Specialties not scored (MAD = 0) |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, (_, _, label) in METRICS.items():
        lines.append(f"| {label} | {v[f'{name}_scored_prescribers']:,.0f} | "
                     f"{v[f'{name}_flagged']:,.0f} | {v[f'{name}_flag_rate_among_scored']:.1%} | "
                     f"{v[f'{name}_specialties_not_scored']:,.0f} |")
    lines += [
        "",
        f"The Isolation Forest flagged {v['if_flagged']:,.0f} prescribers; "
        f"{v['if_also_robust_flagged_share']:.0%} of them are also flagged by the robust z "
        f"rule, and {v['robust_multi_also_if_share']:.0%} of the prescribers flagged on two or "
        "more metrics are also isolated by the forest. Agreement between a univariate and a "
        "multivariate method makes the multi metric flags the most robust group.",
        "",
        "Ten largest specialties:",
        "",
        "| Specialty | Prescribers | Median cost per claim | Median brand share | Flagged (any) | Flagged (2+) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for _, r in big.iterrows():
        lines.append(f"| {r.specialty} | {r.prescribers:,.0f} | ${r.cost_per_claim_median:,.0f} | "
                     f"{r.brand_share_median:.1%} | {r.any_flag_rate:.1%} | {r.multi_flag_rate:.2%} |")
    large = spec[spec["prescribers"] >= 10_000].nlargest(2, "any_flag_rate")
    lines += [
        "",
        "Among specialties with 10,000+ prescribers, the highest flag rates are in "
        + " and ".join(f"{r.specialty} ({r.any_flag_rate:.1%}, median cost per claim "
                       f"${r.cost_per_claim_median:,.0f})" for _, r in large.iterrows())
        + ". These labels cover very different practices (an emergency medicine clinician "
        "who also manages chronic disease, an internist who mainly treats cancer or HIV), so "
        "the flags mostly mark practices that do not fit the label rather than unusual "
        "prescribing for the patients actually seen.",
        "",
        "![Outlier rates by specialty](figures/q3_flag_rates.png)",
        "",
        "By state (50 states and DC), the share of prescribers flagged on at least one metric "
        "ranges from "
        + ", ".join(f"{r.state_name} {r.any_flag_rate:.1%}" for _, r in lo.iterrows())
        + " at the low end to "
        + ", ".join(f"{r.state_name} {r.any_flag_rate:.1%}" for _, r in hi.iterrows())
        + " at the high end. Flags are computed within specialty nationally, so state "
        "differences reflect practice patterns, payer mix, and patient populations, and are "
        "descriptive only.",
        "",
        "### Caveats",
        "",
        "- **Specialty labels are coarse.** CMS assigns one specialty per NPI; an internist "
        "who mostly treats cancer or HIV is compared with general internists.",
        "- **Patient mix is unobserved.** Higher cost or brand share can be clinically "
        "appropriate (sicker patients, newer guideline therapies, prior generic failure).",
        "- **Suppression.** Drug rows with fewer than 11 claims are not in the data, and the "
        "cost per beneficiary proxy uses only rows with unsuppressed beneficiary counts.",
        "- **Threshold choice.** The 3.5 cutoff is a common convention, not a law; rates "
        "scale with it. Results are a screening view for where to look, not a list of "
        "wrongdoers.",
        "- **Privacy.** Public tables suppress any count from 1 to 10 and any group with "
        "fewer than 11 prescribers. No prescriber is named anywhere in this repository.",
        "",
        "Outputs: `outputs_public/q3_*.csv` (specialty, state, and overall aggregates).",
    ]
    return "\n".join(lines)


def main():
    config.PUBLIC_OUT.mkdir(exist_ok=True)
    config.PRIVATE_OUT.mkdir(exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    charts.style()
    t0 = time.time()
    con = config.duckdb_connect(read_only=True)
    df = con.execute(PRESCRIBER_SQL).df()
    print(f"prescribers with {MIN_CLAIMS}+ claims: {len(df):,} ({time.time() - t0:.0f}s)")
    df, skipped = score(df)
    df = isolation_forest(df)
    print(f"scored and forest fit ({time.time() - t0:.0f}s)")

    # individual level: private, git-ignored
    df.to_parquet(config.PRIVATE_OUT / "q3_prescriber_flags.parquet", index=False)

    spec = specialty_summary(df)
    state = state_summary(df)
    o = overall(df, skipped)
    spec.to_csv(config.PUBLIC_OUT / "q3_specialty_summary.csv", index=False)
    state.to_csv(config.PUBLIC_OUT / "q3_state_summary.csv", index=False)
    o.to_csv(config.PUBLIC_OUT / "q3_overall.csv", index=False)
    skipped.to_csv(config.PUBLIC_OUT / "q3_metrics_not_scored.csv", index=False)

    fig_flag_rates(spec)
    md = findings_markdown(o, spec, state)
    write_section(config.DOCS_DIR / "findings.md", "q3", md)
    print(md)
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
