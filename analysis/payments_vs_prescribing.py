"""Question 2: is receiving manufacturer payments associated with prescribing more of that
manufacturer's drugs?

Author: Erica Mathias

Design (observational; results are associations, not causal effects)
--------------------------------------------------------------------
Drugs        The top N_FAMILIES brand families by 2024 Part D cost that appear in Open
             Payments. A family groups Part D brand products by the first word of the
             normalized brand name (DUPIXENT PEN + DUPIXENT SYRINGE = DUPIXENT).
Manufacturer Every manufacturer making at least MFR_SHARE of the general payment lines that
             name the family (for example Eliquis: Pfizer and E.R. Squibb / BMS).
Population   All Part D prescribers, whether or not they prescribe the family, in the
             specialties that write 95% of the family's claims and in which at least 1% of
             the specialty's prescribers prescribe it.
Treatment    At least one 2024 general payment (any product) from an associated
             manufacturer. Sensitivity: a payment that names the family itself.
Outcomes     any_rx: the prescriber has a Part D row for the family (11+ claims; CMS hides
             1 to 10 claims, so "no row" means 0 to 10 claims).
             log_claims: log claims for the family among prescribers with a row.
Controls     Specialty and state fixed effects, log claims for all other drugs, log of the
             drug level beneficiary sum (volume proxy). Sensitivity adds log payments from
             other manufacturers (general industry engagement).
Model 1      OLS (linear probability for any_rx), HC1 robust standard errors, per family;
             pooled across families with a DerSimonian Laird random effects meta analysis.
Model 2      Exact matching on specialty x state x volume decile (decile of other drug
             claims within specialty); the effect on the paid is the paid weighted mean of
             within cell differences; 95% CI from a stratified Poisson bootstrap.
Dose         any_rx on payment amount bins (reference: unpaid), pooled per bin.

Outputs: outputs_public/q2_*.csv (family level and pooled only), docs/figures/q2_*.png,
the Question 2 section of docs/findings.md. Prescriber level data never leaves DuckDB.
"""

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis import charts  # noqa: E402
from analysis.common import MIN_CELL_PRESCRIBERS, write_section  # noqa: E402

N_FAMILIES = 30
MFR_SHARE = 0.05
SPECIALTY_COVERAGE = 0.95
MIN_SPECIALTY_RX_RATE = 0.01
N_BOOT = 500
DOSE_BINS = [0, 100, 500, 5000, np.inf]
DOSE_LABELS = ["$1 to $100", "$100 to $500", "$500 to $5,000", "over $5,000"]
FIG_DIR = config.DOCS_DIR / "figures"
RNG = np.random.default_rng(config.SEED)


# ---------------------------------------------------------------- data

BUILD_SQL = f"""
create or replace temp table fam_drug as
select distinct d.drug_key, split_part(d.brand_name_norm, ' ', 1) as family
from intermediate.int_op_product_drug_map m
join marts.dim_drug d using (drug_key)
where d.brand_generic = 'Brand';

create or replace temp table fam_lines as
select fd.family, g.manufacturer_id, count(*) as n_lines
from staging.stg_op__payment_products pp
join intermediate.int_op_product_drug_map m using (product_name_norm)
join fam_drug fd using (drug_key)
join staging.stg_op__general_payments g using (record_id)
where pp.product_type in ('Drug', 'Biological')
group by all;

create or replace temp table families as
select fd.family, sum(f.drug_cost) as partd_cost
from marts.fact_prescriptions f join fam_drug fd using (drug_key)
where fd.family in (select family from fam_lines)
group by 1
order by partd_cost desc
limit {N_FAMILIES};

create or replace temp table fam_mfr as
select l.family, l.manufacturer_id, dm.manufacturer_key, dm.manufacturer_name,
       l.n_lines / sum(l.n_lines) over (partition by l.family) as line_share
from fam_lines l
join marts.dim_manufacturer dm using (manufacturer_id)
where l.family in (select family from families)
qualify line_share >= {MFR_SHARE};

-- eligible specialties: among those writing the first 95% of the family's claims, keep
-- only specialties where at least MIN_SPECIALTY_RX_RATE of the specialty's Part D
-- prescribers prescribe the family (so oncology drugs are not compared across all
-- nurse practitioners, for example)
create or replace temp table fam_spec as
with s as (
    select fd.family, f.specialty_key, sum(f.claims) as claims,
           count(distinct f.prescriber_key) as prescribers_of_family
    from marts.fact_prescriptions f join fam_drug fd using (drug_key)
    where fd.family in (select family from families)
    group by all
), c as (
    select s.*, sp.prescribers as specialty_prescribers,
           sum(claims) over (partition by family order by claims desc
                             rows between unbounded preceding and 1 preceding)
           / sum(claims) over (partition by family) as share_before
    from s join marts.dim_specialty sp using (specialty_key)
)
select family, specialty_key from c
where coalesce(share_before, 0) < {SPECIALTY_COVERAGE}
  and prescribers_of_family / specialty_prescribers >= {MIN_SPECIALTY_RX_RATE};

create or replace temp table fam_rx as
select fd.family, f.prescriber_key, sum(f.claims) as family_claims
from marts.fact_prescriptions f join fam_drug fd using (drug_key)
where fd.family in (select family from families)
group by all;

-- Payment totals are rounded to cents at every aggregation. fact_payments.amount_usd is
-- a per product share (a double with fractions of a cent), and parallel summation can
-- add it in a different order on each run; without rounding, a total sitting on a dose
-- bin edge (for example exactly $100) could fall on either side from run to run.
create or replace temp table pay_mfr as
select prescriber_key, manufacturer_key, round(sum(amount_usd), 2) as usd
from marts.fact_payments
where prescriber_key is not null
group by all;

create or replace temp table pay_total as
select prescriber_key, round(sum(usd), 2) as usd from pay_mfr group by 1;

create or replace temp table pay_product as
select fd.family, p.prescriber_key, round(sum(p.amount_usd), 2) as usd
from marts.fact_payments p join fam_drug fd using (drug_key)
where p.prescriber_key is not null and fd.family in (select family from families)
group by all;

create or replace temp table analysis as
with elig as (
    select fs.family, dp.prescriber_key, dp.specialty_key, dp.state_key,
           dp.total_claims, coalesce(dp.drug_beneficiary_sum, 0) as bene_sum
    from fam_spec fs
    join marts.dim_prescriber dp on dp.specialty_key = fs.specialty_key and dp.in_partd
),
assoc_pay as (
    select fm.family, pm.prescriber_key, round(sum(pm.usd), 2) as usd
    from fam_mfr fm join pay_mfr pm using (manufacturer_key)
    group by all
)
select e.family, e.prescriber_key, e.specialty_key, e.state_key,
       coalesce(r.family_claims, 0)                      as family_claims,
       e.total_claims - coalesce(r.family_claims, 0)     as other_claims,
       e.bene_sum,
       coalesce(a.usd, 0)                                as paid_mfr_usd,
       coalesce(pp.usd, 0)                               as paid_product_usd,
       coalesce(pt.usd, 0) - coalesce(a.usd, 0)          as paid_other_mfr_usd
from elig e
left join fam_rx r using (family, prescriber_key)
left join assoc_pay a using (family, prescriber_key)
left join pay_product pp using (family, prescriber_key)
left join pay_total pt using (prescriber_key);
"""


def load(con):
    con.execute(BUILD_SQL)
    fams = con.execute("select family, partd_cost from families order by partd_cost desc").df()
    mfrs = con.execute("""
        select family, string_agg(manufacturer_name, '; ' order by line_share desc) as manufacturers
        from fam_mfr group by 1""").df()
    # Fixed row order: DuckDB returns rows in arbitrary order (preserve_insertion_order is
    # off), and the matched comparison depends on order through tie breaking in volume
    # deciles and through which row receives which bootstrap weight.
    df = con.execute("select * from analysis order by family, prescriber_key").df()
    for c in ["specialty_key", "state_key"]:
        df[c] = df[c].astype("int32")
    df["any_rx"] = (df["family_claims"] > 0).astype(float)
    df["treat"] = (df["paid_mfr_usd"] > 0).astype(float)
    df["treat_product"] = (df["paid_product_usd"] > 0).astype(float)
    df["log_other"] = np.log1p(df["other_claims"].clip(lower=0))
    df["log_bene"] = np.log1p(df["bene_sum"])
    df["log_other_pay"] = np.log1p(df["paid_other_mfr_usd"].clip(lower=0))
    return fams.merge(mfrs, on="family"), df


# ---------------------------------------------------------------- models

def design(d, treat_cols, extra=()):
    """Treatment columns + controls + specialty and state fixed effects (dummies)."""
    X = d[list(treat_cols) + ["log_other", "log_bene"] + list(extra)].astype(float)
    fe = pd.get_dummies(d[["specialty_key", "state_key"]].astype(str), drop_first=True,
                        dtype=float)
    return sm.add_constant(pd.concat([X, fe], axis=1), has_constant="add")


def ols(y, X, terms):
    res = sm.OLS(y.to_numpy(), X.to_numpy()).fit(cov_type="HC1")
    idx = [X.columns.get_loc(t) for t in terms]
    return {t: (res.params[i], res.bse[i], res.pvalues[i]) for t, i in zip(terms, idx)}


def fit_family(d):
    out = {}
    X = design(d, ["treat"])
    out["lpm"] = ols(d["any_rx"], X, ["treat"])["treat"]

    X2 = design(d, ["treat"], extra=["log_other_pay"])
    out["lpm_engagement"] = ols(d["any_rx"], X2, ["treat"])["treat"]

    Xp = design(d, ["treat_product"])
    out["lpm_product"] = ols(d["any_rx"], Xp, ["treat_product"])["treat_product"]

    rx = d[d["any_rx"] == 1]
    Xi = design(rx, ["treat"])
    out["log_claims"] = ols(np.log(rx["family_claims"]), Xi, ["treat"])["treat"]

    bins = pd.cut(d["paid_mfr_usd"], [-1] + DOSE_BINS[:-1] + [np.inf],
                  labels=["unpaid"] + DOSE_LABELS)
    dummies = pd.get_dummies(bins, dtype=float).drop(columns="unpaid")
    dd = pd.concat([d, dummies], axis=1)
    Xd = design(dd, DOSE_LABELS)
    out["dose"] = ols(dd["any_rx"], Xd, DOSE_LABELS)
    out["dose_n"] = bins.value_counts().to_dict()
    return out


def matched_att(d, n_boot=N_BOOT):
    """Exact match on specialty x state x volume decile; ATT with stratified Poisson bootstrap."""
    d = d.copy()
    d["decile"] = d.groupby("specialty_key")["other_claims"].rank(pct=True, method="first")
    d["decile"] = np.ceil(d["decile"] * 10).clip(1, 10).astype(int)
    cell = d.groupby(["specialty_key", "state_key", "decile"]).ngroup().to_numpy()
    t = d["treat"].to_numpy().astype(bool)
    n_cells = cell.max() + 1
    has_t = np.bincount(cell[t], minlength=n_cells) > 0
    has_c = np.bincount(cell[~t], minlength=n_cells) > 0
    keep = (has_t & has_c)[cell]
    cell, t = cell[keep], t[keep]
    ys = {"any_rx": d["any_rx"].to_numpy()[keep],
          "claims": d["family_claims"].to_numpy()[keep].astype(float)}

    def att(w):
        res = {}
        wt, wc = w * t, w * ~t
        nt = np.bincount(cell, wt, n_cells)
        nc = np.bincount(cell, wc, n_cells)
        ok = (nt > 0) & (nc > 0)
        for k, y in ys.items():
            mt = np.bincount(cell, wt * y, n_cells)[ok] / nt[ok]
            mc = np.bincount(cell, wc * y, n_cells)[ok] / nc[ok]
            res[k] = np.sum(nt[ok] * (mt - mc)) / nt[ok].sum()
        return res

    point = att(np.ones(len(cell)))
    boots = {k: [] for k in ys}
    for _ in range(n_boot):
        b = att(RNG.poisson(1.0, len(cell)).astype(float))
        for k in ys:
            boots[k].append(b[k])
    out = {"matched_paid": int(t.sum()), "matched_unpaid": int((~t).sum()),
           "paid_dropped_no_match": int(d["treat"].sum() - t.sum())}
    for k in ys:
        lo, hi = np.percentile(boots[k], [2.5, 97.5])
        out[f"att_{k}"], out[f"att_{k}_lo"], out[f"att_{k}_hi"] = point[k], lo, hi
    return out


def random_effects(est, se):
    """DerSimonian Laird random effects pooling. Returns pooled, se, ci, I^2, tau^2."""
    est, se = np.asarray(est, float), np.asarray(se, float)
    w = 1 / se**2
    fixed = np.sum(w * est) / np.sum(w)
    q = np.sum(w * (est - fixed) ** 2)
    k = len(est)
    c = np.sum(w) - np.sum(w**2) / np.sum(w)
    tau2 = max(0.0, (q - (k - 1)) / c)
    wr = 1 / (se**2 + tau2)
    pooled = np.sum(wr * est) / np.sum(wr)
    pse = np.sqrt(1 / np.sum(wr))
    i2 = max(0.0, (q - (k - 1)) / q) if q > 0 else 0.0
    return {"pooled": pooled, "se": pse, "lo": pooled - 1.96 * pse, "hi": pooled + 1.96 * pse,
            "i2": i2, "tau2": tau2, "k": k}


# ---------------------------------------------------------------- run

def run(fams, df):
    rows, dose_rows = [], []
    for fam in fams["family"]:
        t0 = time.time()
        d = df[df["family"] == fam].reset_index(drop=True)
        fit = fit_family(d)
        m = matched_att(d)
        unpaid, paid = d[d["treat"] == 0], d[d["treat"] == 1]
        r = {
            "family": fam,
            "eligible_prescribers": len(d),
            "specialties": d["specialty_key"].nunique(),
            "paid_prescribers": int(d["treat"].sum()),
            "paid_share": d["treat"].mean(),
            "product_paid_prescribers": int(d["treat_product"].sum()),
            "prescribing_rate_unpaid": unpaid["any_rx"].mean(),
            "prescribing_rate_paid": paid["any_rx"].mean(),
            "raw_difference_pp": paid["any_rx"].mean() - unpaid["any_rx"].mean(),
            "median_claims_prescribers_unpaid": unpaid.loc[unpaid.any_rx == 1, "family_claims"].median(),
            "median_claims_prescribers_paid": paid.loc[paid.any_rx == 1, "family_claims"].median(),
        }
        for key, (b, se, p) in [(k, fit[k]) for k in
                                ["lpm", "lpm_engagement", "lpm_product", "log_claims"]]:
            r[f"{key}_coef"], r[f"{key}_se"], r[f"{key}_p"] = b, se, p
            r[f"{key}_lo"], r[f"{key}_hi"] = b - 1.96 * se, b + 1.96 * se
        r.update(m)
        rows.append(r)
        for label in DOSE_LABELS:
            b, se, p = fit["dose"][label]
            dose_rows.append({"family": fam, "bin": label, "coef": b, "se": se, "p": p,
                              "n_prescribers": fit["dose_n"].get(label, 0)})
        print(f"{fam:12s} n={len(d):>8,} paid={r['paid_share']:.1%} "
              f"lpm={r['lpm_coef'] * 100:+.1f}pp att={r['att_any_rx'] * 100:+.1f}pp "
              f"({time.time() - t0:.0f}s)", flush=True)
    est = pd.DataFrame(rows).merge(fams, on="family")
    dose = pd.DataFrame(dose_rows)
    return est, dose


def pool(est, dose):
    rows = []
    specs = [
        ("lpm", "Prescribes the drug (11+ claims), percentage points", "lpm_coef", "lpm_se"),
        ("lpm_engagement", "Same, also controlling for payments from other manufacturers",
         "lpm_engagement_coef", "lpm_engagement_se"),
        ("lpm_product", "Same, treatment = payment naming the drug itself",
         "lpm_product_coef", "lpm_product_se"),
        ("log_claims", "Log claims among prescribers of the drug", "log_claims_coef", "log_claims_se"),
    ]
    for key, label, c, s in specs:
        ok = est[s] > 0
        p = random_effects(est.loc[ok, c], est.loc[ok, s])
        rows.append({"model": key, "description": label, **p})
    # matched ATT: pool with bootstrap SE approximated from CI width
    se = (est["att_any_rx_hi"] - est["att_any_rx_lo"]) / (2 * 1.96)
    p = random_effects(est["att_any_rx"], se)
    rows.append({"model": "matched_att", "description":
                 "Matched comparison (specialty x state x volume decile), percentage points", **p})
    pooled = pd.DataFrame(rows)

    drows = []
    for label in DOSE_LABELS:
        sub = dose[(dose["bin"] == label) & (dose["n_prescribers"] >= MIN_CELL_PRESCRIBERS)
                   & (dose["se"] > 0)]
        p = random_effects(sub["coef"], sub["se"])
        drows.append({"bin": label, "prescribers": int(sub["n_prescribers"].sum()), **p})
    return pooled, pd.DataFrame(drows)


# ---------------------------------------------------------------- charts

def fig_forest(est, pooled):
    e = est.sort_values("lpm_coef")
    pr = pooled.set_index("model").loc["lpm"]
    fig, ax = plt.subplots(figsize=(9, 9))
    y = np.arange(len(e))
    ax.hlines(y, e["lpm_lo"] * 100, e["lpm_hi"] * 100, color=charts.BLUE, linewidth=2)
    ax.plot(e["lpm_coef"] * 100, y, "o", color=charts.BLUE, markersize=6,
            markeredgecolor=charts.SURFACE, markeredgewidth=1)
    yp = -1.6
    ax.hlines(yp, pr["lo"] * 100, pr["hi"] * 100, color=charts.INK, linewidth=2)
    ax.plot(pr["pooled"] * 100, yp, "D", color=charts.INK, markersize=8,
            markeredgecolor=charts.SURFACE, markeredgewidth=1)
    ax.set_yticks(list(y) + [yp], [f.title() for f in e["family"]] + ["Pooled (random effects)"])
    ax.axvline(0, color=charts.AXIS, linewidth=1)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Difference in probability of prescribing the drug, percentage points (95% CI)")
    charts.title(ax, "Paid prescribers are more likely to prescribe the payer's drug",
                 "Adjusted for specialty, state, and prescribing volume. Association, not causation.")
    charts.source_note(fig, "Source: CMS Medicare Part D and Open Payments, 2024. "
                            "Linear probability models, robust standard errors.")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG_DIR / "q2_forest.png", dpi=160)
    plt.close(fig)


def fig_dose(dose_pooled):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(dose_pooled))
    lo = dose_pooled["pooled"] - dose_pooled["lo"]
    hi = dose_pooled["hi"] - dose_pooled["pooled"]
    ax.errorbar(x, dose_pooled["pooled"] * 100, yerr=[lo * 100, hi * 100], fmt="o",
                color=charts.BLUE, ecolor=charts.BLUE, elinewidth=2, capsize=0, markersize=8,
                markeredgecolor=charts.SURFACE, markeredgewidth=1)
    for xi, v in zip(x, dose_pooled["pooled"] * 100):
        ax.text(xi + 0.08, v, f"{v:+.1f} pp", va="center", fontsize=9, color=charts.INK_2)
    # escape $ so matplotlib does not read "$1 to $100" as math markup
    ax.set_xticks(x, [b.replace("$", r"\$") for b in dose_pooled["bin"]])
    ax.axhline(0, color=charts.AXIS, linewidth=1)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.set_ylabel("Percentage points vs unpaid")
    ax.set_xlabel("2024 general payments from the drug's manufacturer(s)")
    charts.title(ax, "The association grows with payment size",
                 "Pooled across 30 drugs; adjusted; 95% CI. Association, not causation.")
    charts.source_note(fig, "Source: CMS Medicare Part D and Open Payments, 2024.")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG_DIR / "q2_dose_response.png", dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- findings

def pct(x):
    return f"{x * 100:+.1f}"


def dose_sentence(dp):
    """Describe the dose response from the numbers, including where intervals overlap."""
    first, last = dp.iloc[0], dp.iloc[-1]
    rising = bool((dp["pooled"].diff().dropna() > 0).all())
    overlap = [f"{a['bin']} and {b['bin']}" for (_, a), (_, b) in
               zip(dp.iloc[:-1].iterrows(), dp.iloc[1:].iterrows()) if b["lo"] <= a["hi"]]
    text = (f"The gap {'rises with every step in' if rising else 'does not rise steadily with'} "
            f"payment size, from {pct(first['pooled'])} pp for {first['bin']} to "
            f"{pct(last['pooled'])} pp for {last['bin']}.")
    n_steps = len(dp) - 1
    if len(overlap) == n_steps:
        text += (" Each step's confidence interval overlaps its neighbor's, so the overall "
                 "trend is clearer than any single step")
        text += ("; the lowest and highest bins do not overlap."
                 if last["lo"] > first["hi"] else ".")
    elif overlap:
        text += (" Confidence intervals overlap between " + "; ".join(overlap)
                 + ", so those steps are not clearly distinguished.")
    return text


def findings_markdown(est, pooled, dose_pooled):
    P = pooled.set_index("model")
    lpm, eng, prod, lc, att = (P.loc[k] for k in
                               ["lpm", "lpm_engagement", "lpm_product", "log_claims", "matched_att"])
    n_pos = int((est["lpm_lo"] > 0).sum())
    raw = est["raw_difference_pp"].median()
    elig = est["eligible_prescribers"]
    lines = [
        "## Question 2: Are manufacturer payments associated with prescribing that manufacturer's drugs?",
        "",
        "**Short answer: yes, consistently, but this is an association and not evidence of "
        "influence or wrongdoing.** Manufacturers target prescribers who already treat the "
        "relevant patients, so some or all of the gap can run in the opposite direction.",
        "",
        "### Design",
        "",
        f"- **Drugs:** the {len(est)} brand families with the most 2024 Part D cost that appear "
        "in Open Payments (for example Eliquis, Ozempic, Jardiance). Pen and syringe forms of "
        "one brand are grouped.",
        "- **Population:** every Part D prescriber, whether or not they prescribe the drug, in "
        "the specialties that write 95% of its claims and where at least 1% of the specialty's "
        f"prescribers use it ({elig.min():,.0f} to {elig.max():,.0f} prescribers per drug). "
        "This keeps, for example, oncology drugs compared within oncology practice.",
        "- **Treatment:** at least one 2024 general payment (any product: meals, travel, "
        "speaking, consulting) from a manufacturer that markets the drug.",
        "- **Outcome:** whether the prescriber has 11 or more Part D claims for the drug (CMS "
        "hides 1 to 10), and log claims among those who do.",
        "- **Controls:** specialty and state fixed effects, the prescriber's claims for all other "
        "drugs, and a beneficiary volume proxy.",
        "",
        "### Results",
        "",
        f"Unadjusted, paid prescribers are more likely to prescribe the drug by a median of "
        f"{raw * 100:.1f} percentage points across the {len(est)} drugs. After adjustment the gap "
        f"shrinks but stays positive: the adjusted difference is above zero (95% CI excludes zero) "
        f"for **{n_pos} of {len(est)} drugs**.",
        "",
        "| Model (pooled across drugs, random effects) | Estimate | 95% CI | I² |",
        "|---|---:|---:|---:|",
        f"| 1. Regression: probability of prescribing, paid vs unpaid | {pct(lpm.pooled)} pp | "
        f"{pct(lpm.lo)} to {pct(lpm.hi)} | {lpm.i2:.1%} |",
        f"| 1b. Same, also controlling for payments from other manufacturers | {pct(eng.pooled)} pp | "
        f"{pct(eng.lo)} to {pct(eng.hi)} | {eng.i2:.1%} |",
        f"| 1c. Same, treatment = payment naming the drug itself | {pct(prod.pooled)} pp | "
        f"{pct(prod.lo)} to {pct(prod.hi)} | {prod.i2:.1%} |",
        f"| 1d. Claims among prescribers of the drug (log scale) | {np.expm1(lc.pooled) * 100:+.1f}% | "
        f"{np.expm1(lc.lo) * 100:+.1f}% to {np.expm1(lc.hi) * 100:+.1f}% | {lc.i2:.1%} |",
        f"| 2. Matched comparison (specialty x state x volume decile) | {pct(att.pooled)} pp | "
        f"{pct(att.lo)} to {pct(att.hi)} | {att.i2:.1%} |",
        "",
        "pp = percentage points. I² measures how much the drug level estimates differ beyond "
        "chance; high values mean the size of the association varies a lot by drug, so the "
        "pooled number is an average, not a constant.",
        "",
        f"The regression and the matched comparison agree ({pct(lpm.pooled)} pp vs "
        f"{pct(att.pooled)} pp). Restricting the treatment to payments that name the drug itself "
        f"gives a larger association ({pct(prod.pooled)} pp), consistent with drug specific "
        "promotion being aimed at the prescribers most engaged with that drug. Among prescribers "
        f"who do prescribe the drug, paid prescribers write about {np.expm1(lc.pooled):.0%} more "
        "claims for it, after the same adjustments.",
        "",
        "![Forest plot](figures/q2_forest.png)",
        "",
        "### Dose response",
        "",
        dose_sentence(dose_pooled),
        "",
        "| Payments from the drug's manufacturer(s) in 2024 | Prescriber x drug pairs | Difference vs unpaid | 95% CI |",
        "|---|---:|---:|---:|",
    ]
    for _, r in dose_pooled.iterrows():
        lines.append(f"| {r['bin']} | {r['prescribers']:,.0f} | {pct(r['pooled'])} pp | "
                     f"{pct(r['lo'])} to {pct(r['hi'])} |")
    lines += [
        "",
        "![Dose response](figures/q2_dose_response.png)",
        "",
        "A gradient is consistent with influence, but it is equally consistent with targeting: "
        "the prescribers a manufacturer most wants to reach (heavy prescribers in the therapeutic "
        "area) are also the ones invited to paid speaking and consulting roles.",
        "",
        "### Caveats",
        "",
        "- **Observational data.** No model here identifies a causal effect.",
        "- **Reverse causality and targeting.** Manufacturers direct payments to prescribers who "
        "already treat the condition and already use the drug. The 2024 payments and 2024 "
        "prescribing are measured in the same year, so the order of events is unknown.",
        "- **Unmeasured confounding.** Patient mix, practice setting, formulary access, and "
        "clinical interest are not observed. The specialty, state, and volume controls remove "
        "only part of it. Controlling for payments from other manufacturers (model 1b) moves "
        f"the pooled estimate from {pct(lpm.pooled)} pp to {pct(eng.pooled)} pp, so general "
        "industry engagement alone does not explain the gap.",
        "- **Censoring at 11 claims.** CMS hides prescriber and drug pairs with fewer than 11 "
        "claims, so the outcome is \"prescribes at a visible level\", not any use.",
        "- **Treatment is broad.** A payment from Pfizer counts for Eliquis even if the meal "
        "promoted another Pfizer product (model 1c narrows this to payments naming the drug). "
        "Most payments are small meals (food and beverage is over 90% of general payment "
        "records).",
        "- **Name matching.** Drugs link across datasets by normalized brand name (93.5% of drug "
        "product rows matched); see data_quality_report.md.",
        "- **Payments are legal and disclosed.** Industry payments for meals, education, "
        "consulting, and research are lawful and publicly reported. **A correlation between "
        "payments and prescribing is not evidence that any individual prescriber acted "
        "improperly**, and no individual is identified in this project.",
        "",
        "Outputs: `outputs_public/q2_*.csv` (drug level and pooled results only).",
    ]
    return "\n".join(lines)


def main(report_only=False):
    """Fit everything, or with report_only rebuild text and charts from the saved CSVs."""
    config.PUBLIC_OUT.mkdir(exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    charts.style()
    t0 = time.time()
    if report_only:
        est = pd.read_csv(config.PUBLIC_OUT / "q2_drug_estimates.csv")
        pooled = pd.read_csv(config.PUBLIC_OUT / "q2_pooled.csv")
        dose_pooled = pd.read_csv(config.PUBLIC_OUT / "q2_dose_response.csv")
    else:
        con = config.duckdb_connect(read_only=True)
        fams, df = load(con)
        print(f"analysis rows: {len(df):,} ({time.time() - t0:.0f}s)")
        est, dose = run(fams, df)
        pooled, dose_pooled = pool(est, dose)

        # drug level rows describe thousands of prescribers; enforce the rule anyway
        assert (est["paid_prescribers"] >= MIN_CELL_PRESCRIBERS).all()
        assert ((est["eligible_prescribers"] - est["paid_prescribers"])
                >= MIN_CELL_PRESCRIBERS).all()
        est.to_csv(config.PUBLIC_OUT / "q2_drug_estimates.csv", index=False)
        pooled.to_csv(config.PUBLIC_OUT / "q2_pooled.csv", index=False)
        dose_pooled.to_csv(config.PUBLIC_OUT / "q2_dose_response.csv", index=False)

    fig_forest(est, pooled)
    fig_dose(dose_pooled)
    md = findings_markdown(est, pooled, dose_pooled)
    write_section(config.DOCS_DIR / "findings.md", "q2", md)
    print(md)
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(report_only="--report-only" in sys.argv)
