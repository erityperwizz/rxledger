"""Bronze layer: convert raw CMS CSVs to Parquet with every column as text.

Author: Erica Mathias

All columns are read as VARCHAR so nothing is silently type-guessed; typing
happens later in dbt staging models. For every file the row count is taken
three ways and must agree exactly:

  1. csv_rows_python: records counted by Python's csv module (independent parser)
  2. csv_rows_duckdb: records parsed by DuckDB's CSV reader
  3. parquet_rows:    rows in the written Parquet file

Results are written to docs/ingest_row_counts.json and rendered into
docs/data_quality_report.md.
"""

import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

SOURCES = {
    "partd_prescriber_drug": config.PARTD_CSV,
    "op_general": config.OP_GENERAL_CSV,
    "op_research": config.OP_RESEARCH_CSV,
    "op_ownership": config.OP_OWNERSHIP_CSV,
    "op_removed_deleted": config.OP_DIR / "OP_REMOVED_DELETED_PGYR2024_P06302026_06032026.csv",
    "op_recipient_profile": config.OP_RECIPIENT_CSV,
}

ROW_COUNT_JSON = config.DOCS_DIR / "ingest_row_counts.json"

csv.field_size_limit(2**31 - 1)


def count_csv_records(path):
    """Count data records (excluding header) with Python's csv parser."""
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)
        return sum(1 for _ in reader)


def to_parquet(con, name, csv_path, out_path):
    src = csv_path.as_posix()
    rel = (
        f"read_csv('{src}', all_varchar=true, header=true, delim=',', quote='\"', "
        f"escape='\"', strict_mode=true, sample_size=-1)"
    )
    ncols = len(con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall())
    tmp = out_path.with_suffix(".parquet.tmp")
    con.execute(
        f"COPY (SELECT * FROM {rel}) TO '{tmp.as_posix()}' "
        "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 500000)"
    )
    tmp.replace(out_path)
    csv_rows_duckdb = con.execute(f"SELECT count(*) FROM {rel}").fetchone()[0]
    parquet_rows = con.execute(
        f"SELECT count(*) FROM read_parquet('{out_path.as_posix()}')"
    ).fetchone()[0]
    return ncols, csv_rows_duckdb, parquet_rows


def render_markdown(results):
    lines = [
        "## Ingest row counts (bronze layer)",
        "",
        "Every raw CSV is converted to Parquet with all columns as text. Rows are counted by an",
        "independent parser (Python csv module), by DuckDB's CSV reader, and in the written",
        "Parquet file. All three must match exactly.",
        "",
        "| Source | Columns | CSV rows (Python) | CSV rows (DuckDB) | Parquet rows | CSV size (bytes) | Match |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['source']} | {r['columns']} | {r['csv_rows_python']:,} | "
            f"{r['csv_rows_duckdb']:,} | {r['parquet_rows']:,} | {r['csv_bytes']:,} | "
            f"{'yes' if r['match'] else 'NO'} |"
        )
    return "\n".join(lines) + "\n"


def write_report_section(md_section):
    """Replace the ingest section of docs/data_quality_report.md, keeping other sections."""
    report = config.DOCS_DIR / "data_quality_report.md"
    start, end = "<!-- ingest:start -->", "<!-- ingest:end -->"
    block = f"{start}\n{md_section}{end}"
    if report.exists():
        text = report.read_text(encoding="utf-8")
        if start in text and end in text:
            pre = text.split(start)[0]
            post = text.split(end)[1]
            report.write_text(pre + block + post, encoding="utf-8")
            return
        report.write_text(text.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
    else:
        report.write_text("# Data Quality Report\n\n" + block + "\n", encoding="utf-8")


def main(only=None):
    config.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    names = [n for n in SOURCES if only is None or n in only]

    # Python csv counts are single-threaded per file, so run them in parallel
    # with DuckDB doing the conversions.
    with ProcessPoolExecutor(max_workers=len(names)) as pool:
        py_counts = {n: pool.submit(count_csv_records, SOURCES[n]) for n in names}
        con = config.duckdb_connect(":memory:")
        results = []
        for name in names:
            t0 = time.time()
            csv_path = SOURCES[name]
            out_path = config.BRONZE_DIR / f"{name}.parquet"
            ncols, n_duck, n_pq = to_parquet(con, name, csv_path, out_path)
            print(f"{name}: {ncols} cols, duckdb={n_duck:,} parquet={n_pq:,} "
                  f"({time.time() - t0:.0f}s)", flush=True)
            results.append({
                "source": name,
                "csv_file": csv_path.name,
                "csv_bytes": csv_path.stat().st_size,
                "columns": ncols,
                "csv_rows_duckdb": n_duck,
                "parquet_rows": n_pq,
            })
        for r in results:
            r["csv_rows_python"] = py_counts[r["source"]].result()
            r["match"] = r["csv_rows_python"] == r["csv_rows_duckdb"] == r["parquet_rows"]
            print(f"{r['source']}: python={r['csv_rows_python']:,} match={r['match']}")

    previous = {}
    if ROW_COUNT_JSON.exists():
        previous = {r["source"]: r for r in json.loads(ROW_COUNT_JSON.read_text())}
    previous.update({r["source"]: r for r in results})
    merged = [previous[n] for n in SOURCES if n in previous]
    ROW_COUNT_JSON.write_text(json.dumps(merged, indent=2))
    write_report_section(render_markdown(merged))

    if not all(r["match"] for r in results):
        raise SystemExit("Row count mismatch, see docs/ingest_row_counts.json")


if __name__ == "__main__":
    main(only=sys.argv[1:] or None)
