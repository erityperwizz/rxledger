"""Robust z scoring and scale transforms for Question 3.

Author: Erica Mathias
"""

import numpy as np
import pandas as pd

from analysis.outliers import Z_THRESHOLD, robust_z, score, transform


def test_robust_z_flags_extreme_value_only():
    x = np.array([10, 11, 9, 10, 12, 8, 10, 11, 9, 100], dtype=float)
    z, med, mad = robust_z(x)
    assert med == 10 and mad == 1
    assert (z > Z_THRESHOLD).tolist() == [False] * 9 + [True]


def test_robust_z_returns_nan_when_mad_is_zero():
    z, _, mad = robust_z(np.array([0, 0, 0, 0, 0.2]))
    assert mad == 0 and np.isnan(z).all()


def test_transform_log_treats_zero_as_missing():
    out = transform([0, 1, np.e], "log")
    assert np.isnan(out[0]) and out[1] == 0 and np.isclose(out[2], 1)


def test_transform_asin_sqrt_is_monotone_on_unit_interval():
    out = transform([0, 0.01, 0.25, 1], "asin_sqrt").to_numpy()
    assert out[0] == 0 and np.isclose(out[-1], np.pi / 2) and np.all(np.diff(out) > 0)


def test_score_skips_small_specialties_and_mad_zero_metrics():
    rng = np.random.default_rng(0)
    n = 150
    df = pd.DataFrame({
        "prescriber_key": range(n + 5),
        "specialty": ["A"] * n + ["tiny"] * 5,
        "cost_per_claim": rng.lognormal(4, 0.3, n + 5),
        "brand_share": rng.uniform(0.05, 0.15, n + 5),
        "cost_per_beneficiary": rng.lognormal(6, 0.3, n + 5),
        "opioid_share": np.zeros(n + 5),  # MAD = 0 -> not scored
    })
    df.loc[0, "cost_per_claim"] = 1e6
    scored, skipped = score(df)
    assert "tiny" not in set(scored["specialty"])
    assert bool(scored.loc[0, "cost_per_claim_flag"])
    assert scored["opioid_share_z"].isna().all()
    assert ("A", "opioid_share") in set(map(tuple, skipped.to_numpy()))
