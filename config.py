"""Central paths and settings for RxLedger.

Author: Erica Mathias

Raw data location is read from the RXL_DATA_DIR environment variable so the
pipeline runs on any machine. Everything derived (Parquet, DuckDB) lives under
data/ inside the repo, which is git-ignored.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

RAW_DIR = Path(os.environ.get("RXL_DATA_DIR", Path.home() / "Downloads" / "RXLData"))

# Raw source files (CMS release identifiers are part of the file names)
PARTD_CSV = RAW_DIR / "MUP_DPR_RY26_P04_V10_DY24_NPIBN.csv"
OP_ZIP = RAW_DIR / "PGYR2024_P06302026_06032026.zip"
OP_DIR = RAW_DIR / "open_payments_2024"
OP_GENERAL_CSV = OP_DIR / "OP_DTL_GNRL_PGYR2024_P06302026_06032026.csv"
OP_RESEARCH_CSV = OP_DIR / "OP_DTL_RSRCH_PGYR2024_P06302026_06032026.csv"
OP_OWNERSHIP_CSV = OP_DIR / "OP_DTL_OWNRSHP_PGYR2024_P06302026_06032026.csv"
OP_RECIPIENT_CSV = (
    RAW_DIR / "open_payments_recipients" / "OP_CVRD_RCPNT_PRFL_SPLMTL_P06302026_04032026.csv"
)

# Expected byte sizes of files extracted from OP_ZIP
OP_EXPECTED_SIZES = {
    OP_GENERAL_CSV.name: 8_970_316_799,
    OP_RESEARCH_CSV.name: 787_357_633,
}

# Derived data (git-ignored)
DATA_DIR = ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
DUCKDB_PATH = DATA_DIR / "rxledger.duckdb"
DUCKDB_TEMP_DIR = DATA_DIR / "duckdb_tmp"
POWERBI_EXPORT_DIR = DATA_DIR / "powerbi"

# Outputs
DOCS_DIR = ROOT / "docs"
PUBLIC_OUT = ROOT / "outputs_public"
PRIVATE_OUT = ROOT / "outputs_private"

# DuckDB: about 60% of physical RAM, spill to disk for big joins
DUCKDB_MEMORY_LIMIT = os.environ.get("RXL_DUCKDB_MEMORY", "9GB")
DUCKDB_THREADS = int(os.environ.get("RXL_DUCKDB_THREADS", "8"))

SEED = 2024


def duckdb_connect(path=DUCKDB_PATH, read_only=False):
    """Open DuckDB with the project memory and spill settings."""
    import duckdb

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DUCKDB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    con.execute(f"SET threads={DUCKDB_THREADS}")
    con.execute(f"SET temp_directory='{DUCKDB_TEMP_DIR.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    return con
