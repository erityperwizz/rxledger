"""Statistical helpers for Question 2, checked on synthetic data with known answers.

Author: Erica Mathias
"""

import numpy as np
import pandas as pd
import pytest

from analysis.payments_vs_prescribing import fit_family, matched_att, random_effects


def test_random_effects_equal_estimates_have_no_heterogeneity():
    r = random_effects([0.1, 0.1, 0.1], [0.01, 0.02, 0.03])
    assert r["pooled"] == pytest.approx(0.1)
    assert r["tau2"] == 0 and r["i2"] == 0
    assert r["lo"] < 0.1 < r["hi"]


def test_random_effects_detects_heterogeneity():
    r = random_effects([0.0, 0.5, 1.0], [0.01, 0.01, 0.01])
    assert r["i2"] > 0.9
    assert r["pooled"] == pytest.approx(0.5, abs=0.01)


def synthetic(n=20000, effect=0.10, seed=1):
    """Prescribers in 3 specialties x 4 states; payment more likely for high volume
    prescribers (confounding), true effect of payment on prescribing = effect."""
    rng = np.random.default_rng(seed)
    spec = rng.integers(0, 3, n)
    state = rng.integers(0, 4, n)
    other = rng.lognormal(7, 1, n)
    vol = (np.log(other) - 7)
    treat = (rng.random(n) < 1 / (1 + np.exp(-(vol - 1)))).astype(float)
    p = 0.2 + 0.05 * spec + 0.05 * vol.clip(-2, 2) + effect * treat
    any_rx = (rng.random(n) < p.clip(0, 1)).astype(float)
    claims = np.where(any_rx == 1, rng.integers(11, 200, n), 0)
    paid = np.where(treat == 1, rng.choice([50, 300, 2000, 9000], n), 0.0)
    return pd.DataFrame({
        "specialty_key": spec, "state_key": state, "other_claims": other,
        "bene_sum": other / 3, "family_claims": claims, "any_rx": any_rx, "treat": treat,
        "treat_product": treat, "paid_mfr_usd": paid, "log_other": np.log1p(other),
        "log_bene": np.log1p(other / 3) + rng.normal(0, 0.3, n),
        "log_other_pay": rng.exponential(2, n),
    })


def test_regression_recovers_effect_despite_confounding():
    d = synthetic()
    raw = d.loc[d.treat == 1, "any_rx"].mean() - d.loc[d.treat == 0, "any_rx"].mean()
    b, se, _ = fit_family(d)["lpm"]
    assert raw > 0.13  # confounded raw gap is too large
    assert abs(b - 0.10) < 3 * se + 0.01


def test_matched_att_recovers_effect_and_ci_covers_truth():
    d = synthetic()
    m = matched_att(d, n_boot=200)
    assert m["att_any_rx_lo"] < 0.10 + 0.02 and m["att_any_rx_hi"] > 0.10 - 0.02
    assert m["att_any_rx_lo"] < m["att_any_rx"] < m["att_any_rx_hi"]


def test_no_effect_gives_ci_around_zero():
    d = synthetic(effect=0.0, seed=7)
    b, se, _ = fit_family(d)["lpm"]
    assert abs(b) < 3 * se + 0.01


def test_payment_totals_are_rounded_to_cents():
    """Payment sums feed treatment flags and dose bins; unrounded float sums made a total
    on a bin edge land on either side from run to run. Every payment sum must be rounded."""
    import re

    from analysis.payments_vs_prescribing import BUILD_SQL
    sums = re.findall(r"(round\()?sum\((?:\w+\.)?(?:amount_usd|usd)\)", BUILD_SQL)
    assert sums and all(prefix == "round(" for prefix in sums)
