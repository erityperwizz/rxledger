"""Guards for the published documents.

Author: Erica Mathias

1. Every headline number quoted in README.md matches outputs_public/headline_numbers.csv,
   which the pipeline regenerates (analysis/summary.py).
2. The dbt test count quoted in README.md and docs/requirements.md matches the last build.
3. No em dashes in code, docs, or the README (project style rule).
4. Public CSVs carry no prescriber names or NPIs.
"""

import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
HEADLINE = ROOT / "outputs_public" / "headline_numbers.csv"
BUILD_RESULTS = ROOT / "dbt" / "target" / "build_results.json"

README_KEYS = [
    "partd_rows", "op_general_rows", "total_drug_cost", "total_claims", "prescribers",
    "generic_share_claims", "generic_share_cost", "top10_share_of_cost",
    "savings_upper_bound", "savings_reviewed", "total_payments", "paid_prescriber_pct",
    "drug_match_rate", "q2_positive_drugs", "q2_lpm", "q2_lpm_ci", "q2_matched",
    "q2_matched_ci", "q2_dose_low", "q2_dose_high", "q3_prescribers", "q3_any_flag",
    "q3_multi_flag", "genai_accuracy", "genai_accuracy_ci", "genai_threshold",
    "genai_lenient", "genai_cost_weighted",
]


@pytest.mark.skipif(not HEADLINE.exists(), reason="run the pipeline first")
@pytest.mark.parametrize("key", README_KEYS)
def test_readme_quotes_current_number(key):
    numbers = dict(pd.read_csv(HEADLINE, dtype=str).values)
    assert numbers[key] in README, (
        f"README is missing or has a stale value for {key}: {numbers[key]}")


@pytest.mark.skipif(not BUILD_RESULTS.exists(), reason="run dbt build first")
def test_dbt_test_count_quoted_correctly():
    results = json.loads(BUILD_RESULTS.read_text())["results"]
    n = sum(r["unique_id"].startswith("test.") for r in results)
    assert f"{n} data tests" in README
    assert f"({n} tests)" in (ROOT / "docs" / "requirements.md").read_text(encoding="utf-8")


def tracked_text_files():
    skip = {".venv", "data", "target", "logs", "dbt_packages", "outputs_private", ".git"}
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & skip) \
                and p.suffix in {".py", ".md", ".sql", ".yml", ".csv", ".json", ".toml", ".txt"}:
            yield p


EM_DASH = chr(0x2014)  # built at runtime so this file contains none


def test_no_em_dashes():
    offenders = [str(p.relative_to(ROOT)) for p in tracked_text_files()
                 if EM_DASH in p.read_text(encoding="utf-8", errors="ignore")]
    assert offenders == []


def test_public_outputs_have_no_identifiers():
    for f in (ROOT / "outputs_public").glob("*.csv"):
        cols = pd.read_csv(f, nrows=0).columns
        bad = [c for c in cols if re.search(r"npi|first_name|last_name|last_org", c, re.I)]
        assert not bad, f"{f.name} has identifier columns {bad}"
