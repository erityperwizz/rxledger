"""Shared helpers for RxLedger analysis scripts.

Author: Erica Mathias
"""

import re
from pathlib import Path

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

# Public outputs never show a group with fewer prescribers than this (mirrors the CMS
# small cell rule), so no committed number describes one or a few individuals.
MIN_CELL_PRESCRIBERS = 11


def write_section(path, key, markdown, title="# Findings"):
    """Replace the block between <!-- key:start --> and <!-- key:end --> in a Markdown file.

    Creates the file (with the given title) or appends the block if it is missing, and
    leaves every other section untouched.
    """
    path = Path(path)
    start, end = f"<!-- {key}:start -->", f"<!-- {key}:end -->"
    block = f"{start}\n{markdown.rstrip()}\n{end}"
    text = path.read_text(encoding="utf-8") if path.exists() else f"{title}\n"
    if start in text and end in text:
        text = text.split(start)[0] + block + text.split(end, 1)[1]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def suppress_small_cells(df, count_col="prescribers", min_cell=MIN_CELL_PRESCRIBERS):
    """Drop aggregate rows describing fewer than min_cell prescribers."""
    return df[df[count_col] >= min_cell].reset_index(drop=True)


def normalize_name(name):
    """Normalize a drug or product name for matching.

    Mirrors the dbt macro normalize_name: upper case, every run of characters other than
    A to Z and 0 to 9 becomes one space, trimmed. Empty results become None.
    """
    if name is None:
        return None
    out = _NON_ALNUM.sub(" ", str(name).upper()).strip()
    return out or None


def classify_brand_generic(brand_name, generic_name):
    """Brand or Generic using the documented name rule (see docs/data_dictionary.md)."""
    b, g = normalize_name(brand_name), normalize_name(generic_name)
    if b is None or g is None:
        return None
    if b == g or b.split(" ")[0] == g.split(" ")[0]:
        return "Generic"
    return "Brand"
