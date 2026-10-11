"""Rebuild RxLedger end to end with one command.

Author: Erica Mathias

    python run_pipeline.py                 run every step
    python run_pipeline.py --list          show the steps
    python run_pipeline.py --from dbt      start at a step and run the rest
    python run_pipeline.py --only spend    run one step

Raw CMS files are read from RXL_DATA_DIR (default: ~/Downloads/RXLData). Steps stop at
the first failure. Random seeds are fixed in config.py, so reruns give identical numbers.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
DBT = str(Path(PY).parent / ("dbt.exe" if sys.platform == "win32" else "dbt"))
DBT_DIR = ROOT / "dbt"

STEPS = [
    ("extract", "Extract Open Payments CSVs from the CMS zip (skips if sizes match)",
     [PY, "ingest/extract_open_payments.py"], ROOT),
    ("ingest", "Convert raw CSVs to text only Parquet and check row counts",
     [PY, "ingest/to_parquet.py"], ROOT),
    ("dbt", "Build and test all dbt models (staging, intermediate, marts)",
     [DBT, "build", "--profiles-dir", "."], DBT_DIR),
    ("dbt_results", "Save the dbt build results (later dbt commands overwrite run_results.json)",
     [PY, "-c", "import shutil; shutil.copy('dbt/target/run_results.json', "
      "'dbt/target/build_results.json')"], ROOT),
    ("dbt_docs", "Generate dbt documentation (catalog for the data dictionary)",
     [DBT, "docs", "generate", "--profiles-dir", "."], DBT_DIR),
    ("dq_report", "Write dbt test results and modeling checks to the data quality report",
     [PY, "ingest/dq_report.py"], ROOT),
    ("data_dictionary", "Generate docs/data_dictionary.md",
     [PY, "ingest/data_dictionary.py"], ROOT),
    ("spend", "Question 1: spend, brand vs generic, generic substitution savings",
     [PY, "analysis/spend.py"], ROOT),
    ("payments", "Question 2: payments vs prescribing (regression, matching, dose response)",
     [PY, "analysis/payments_vs_prescribing.py"], ROOT),
    ("outliers", "Question 3: outliers within specialty (aggregates only)",
     [PY, "analysis/outliers.py"], ROOT),
    ("summary", "Headline numbers for findings.md and the README check",
     [PY, "analysis/summary.py"], ROOT),
    ("powerbi", "Export the aggregated star schema for Power BI",
     [PY, "powerbi/export_powerbi.py"], ROOT),
    ("process_map", "Draw docs/process_map.png",
     [PY, "docs/process_map.py"], ROOT),
    ("tests", "Run pytest", [PY, "-m", "pytest", "-q"], ROOT),
]


def main():
    names = [s[0] for s in STEPS]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list the steps and exit")
    ap.add_argument("--from", dest="start", choices=names, help="start at this step")
    ap.add_argument("--only", choices=names, help="run only this step")
    args = ap.parse_args()

    if args.list:
        for name, desc, *_ in STEPS:
            print(f"{name:16s} {desc}")
        return
    steps = STEPS
    if args.only:
        steps = [s for s in STEPS if s[0] == args.only]
    elif args.start:
        steps = STEPS[names.index(args.start):]

    t_all = time.time()
    for name, desc, cmd, cwd in steps:
        print(f"\n=== {name}: {desc}", flush=True)
        t0 = time.time()
        result = subprocess.run(cmd, cwd=cwd)
        if result.returncode != 0:
            print(f"\nStep '{name}' failed (exit {result.returncode}). "
                  f"Fix it, then resume with: python run_pipeline.py --from {name}")
            sys.exit(result.returncode)
        print(f"=== {name} done in {time.time() - t0:.0f}s", flush=True)
    print(f"\nPipeline finished in {(time.time() - t_all) / 60:.1f} minutes.")


if __name__ == "__main__":
    main()
