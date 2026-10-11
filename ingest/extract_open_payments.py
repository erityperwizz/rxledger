"""Extract the Open Payments 2024 general and research CSVs from the CMS zip.

Author: Erica Mathias

Streams each member to a temporary file, checks the byte count against the
known size, then renames into place (overwriting any partial earlier copy).
Files that already have the expected size are skipped.
"""

import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def extract(zip_path=config.OP_ZIP, out_dir=config.OP_DIR, expected=config.OP_EXPECTED_SIZES):
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = {Path(i.filename).name: i for i in zf.infolist()}
        for name, size in expected.items():
            target = out_dir / name
            if target.exists() and target.stat().st_size == size:
                print(f"OK (already extracted) {name} {size:,} bytes")
                continue
            info = members[name]
            tmp = target.with_suffix(".partial")
            print(f"Extracting {name} ({info.file_size:,} bytes)...", flush=True)
            with zf.open(info) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
            got = tmp.stat().st_size
            if got != size:
                raise RuntimeError(f"{name}: expected {size:,} bytes, got {got:,}")
            tmp.replace(target)
            print(f"OK {name} {got:,} bytes", flush=True)


if __name__ == "__main__":
    extract()
