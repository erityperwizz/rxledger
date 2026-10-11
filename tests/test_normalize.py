"""Name normalization and brand/generic rule, and parity with the dbt SQL macro.

Author: Erica Mathias
"""

import duckdb
import pytest

from analysis.common import classify_brand_generic, normalize_name

CASES = [
    ("Ozempic", "OZEMPIC"),
    ("  NURTEC ODT ", "NURTEC ODT"),
    ("Hydrocodone-Acetaminophen", "HYDROCODONE ACETAMINOPHEN"),
    ("Insulin Glargine,hum.Rec.Anlog", "INSULIN GLARGINE HUM REC ANLOG"),
    ("Diltiazem 24hr Er (Cd)", "DILTIAZEM 24HR ER CD"),
    ("0.9 % Sodium Chloride", "0 9 SODIUM CHLORIDE"),
    ("---", None),
    (None, None),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_python_matches_sql_macro():
    """The Python helper and the SQL expression in dbt/macros/normalize_name.sql agree."""
    con = duckdb.connect()
    for raw, expected in CASES:
        sql = "select nullif(trim(regexp_replace(upper(?), '[^A-Z0-9]+', ' ', 'g')), '')"
        assert con.execute(sql, [raw]).fetchone()[0] == expected == normalize_name(raw)


@pytest.mark.parametrize("brand,generic,expected", [
    ("Atorvastatin Calcium", "Atorvastatin Calcium", "Generic"),
    ("Clopidogrel", "Clopidogrel Bisulfate", "Generic"),
    ("Hydrocodone-Acetaminophen", "Hydrocodone/Acetaminophen", "Generic"),
    ("Metformin Hcl Er", "Metformin Hcl", "Generic"),
    ("Eliquis", "Apixaban", "Brand"),
    ("Ozempic", "Semaglutide", "Brand"),
    ("Jantoven", "Warfarin Sodium", "Brand"),  # branded generic: documented limitation
])
def test_classify_brand_generic(brand, generic, expected):
    assert classify_brand_generic(brand, generic) == expected


def test_suppress_small_cells_drops_groups_under_11():
    import pandas as pd

    from analysis.common import suppress_small_cells
    df = pd.DataFrame({"g": ["a", "b", "c"], "prescribers": [10, 11, 500]})
    assert suppress_small_cells(df)["g"].tolist() == ["b", "c"]


def test_write_section_replaces_only_its_block(tmp_path):
    from analysis.common import write_section
    p = tmp_path / "f.md"
    write_section(p, "q1", "first")
    write_section(p, "q2", "second")
    write_section(p, "q1", "updated")
    text = p.read_text()
    assert "updated" in text and "first" not in text and "second" in text
    assert text.index("q1:start") < text.index("q2:start")
