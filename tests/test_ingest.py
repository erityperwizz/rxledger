"""Bronze ingest: text only Parquet conversion and the three way row count check.

Author: Erica Mathias
"""

import json
from pathlib import Path

import duckdb
import pytest

from ingest.to_parquet import count_csv_records, render_markdown, to_parquet

ROOT = Path(__file__).resolve().parents[1]

# Quoted commas, a quoted embedded newline, an empty field, and a leading zero: a physical
# line count would say 5 records; the true count is 4.
CSV = (
    'npi,name,amount,zip\n'
    '0012345678,"Smith, Jane",10.50,02139\n'
    '0098765432,"Line one\nline two",,90210\n'
    '1111111111,Plain,0,00501\n'
    '2222222222,"Quote ""inside""",3,10001\n'
)


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "sample.csv"
    p.write_text(CSV, encoding="utf-8", newline="")
    return p


def test_python_counter_handles_quoted_newlines(csv_file):
    assert count_csv_records(csv_file) == 4


def test_parquet_round_trip_counts_match_and_types_stay_text(csv_file, tmp_path):
    con = duckdb.connect()
    out = tmp_path / "sample.parquet"
    ncols, n_duck, n_pq = to_parquet(con, "sample", csv_file, out)
    assert (ncols, n_duck, n_pq) == (4, 4, 4)
    types = dict(con.execute(f"describe select * from '{out.as_posix()}'").fetchall()[i][:2]
                 for i in range(4))
    assert set(types.values()) == {"VARCHAR"}  # no silent type guessing
    npi = con.execute(f"select npi from '{out.as_posix()}' order by npi").fetchall()
    assert npi[0][0] == "0012345678"  # leading zeros preserved


def test_report_marks_mismatches():
    rows = [{"source": "a", "columns": 2, "csv_rows_python": 5, "csv_rows_duckdb": 5,
             "parquet_rows": 5, "csv_bytes": 10, "match": True},
            {"source": "b", "columns": 2, "csv_rows_python": 5, "csv_rows_duckdb": 4,
             "parquet_rows": 4, "csv_bytes": 10, "match": False}]
    md = render_markdown(rows)
    assert "| a |" in md and "| yes |" in md and "| NO |" in md


def test_recorded_ingest_counts_all_match():
    path = ROOT / "docs" / "ingest_row_counts.json"
    records = json.loads(path.read_text())
    assert len(records) == 6
    assert all(r["match"] for r in records)
    assert all(r["csv_rows_python"] == r["csv_rows_duckdb"] == r["parquet_rows"] for r in records)
