"""Draw docs/process_map.png: the RxLedger pipeline from raw CMS files to outputs.

Author: Erica Mathias

Counts shown on the map (rows, tests, match rate) are read from the pipeline outputs so
the diagram stays in sync with the data.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from analysis import charts  # noqa: E402

TINT = "#eaf2fc"        # light step of the blue ramp for box fills
PRIVATE_TINT = "#fdeee7"  # light step of the orange ramp for the private output


def facts():
    ingest = {r["source"]: r for r in
              json.loads((config.DOCS_DIR / "ingest_row_counts.json").read_text())}
    results = json.loads((config.ROOT / "dbt" / "target" / "build_results.json").read_text())
    n_tests = sum(r["unique_id"].startswith("test.") for r in results["results"])
    head = dict(pd.read_csv(config.PUBLIC_OUT / "headline_numbers.csv").values)
    return {
        "partd": ingest["partd_prescriber_drug"]["parquet_rows"] / 1e6,
        "op": ingest["op_general"]["parquet_rows"] / 1e6,
        "tests": n_tests,
        "match": head["drug_match_rate"],
    }


def box(ax, x, y, w, h, text, fill=TINT, bold_first=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12",
                                linewidth=1, edgecolor=charts.AXIS, facecolor=fill))
    lines = text.split("\n")
    if bold_first:
        ax.text(x + w / 2, y + h - 0.22, lines[0], ha="center", va="top", fontsize=9.5,
                fontweight="bold", color=charts.INK)
        if len(lines) > 1:
            ax.text(x + w / 2, y + h - 0.52, "\n".join(lines[1:]), ha="center", va="top",
                    fontsize=8.5, color=charts.INK_2, linespacing=1.35)
    else:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9,
                color=charts.INK_2)


def arrow(ax, x0, y0, x1, y1):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=12,
                                 linewidth=1.5, color=charts.MUTED))


def main():
    f = facts()
    charts.style()
    fig, ax = plt.subplots(figsize=(16, 8.2))
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 12)
    ax.axis("off")

    cols = [
        ("1  Sources", "CMS public files"),
        ("2  Bronze", "Python + DuckDB"),
        ("3  Silver", "dbt staging and intermediate"),
        ("4  Gold", "dbt marts (star schema)"),
        ("5  Analysis", "Python, statsmodels, scikit-learn"),
        ("6  Outputs", "aggregates only in public"),
    ]
    xs = [0.3, 4.3, 8.3, 12.3, 16.3, 20.3]
    w = 3.4
    for (title, sub), x in zip(cols, xs):
        ax.text(x, 11.5, title, fontsize=12, fontweight="bold", color=charts.INK, va="center")
        ax.text(x, 11.0, sub, fontsize=9, color=charts.INK_2, va="center")

    # boxes: (column index, y, height, text, fill)
    B = {}

    def put(key, ci, y, h, text, fill=TINT):
        box(ax, xs[ci], y, w, h, text, fill)
        B[key] = (xs[ci], y, w, h)

    put("partd", 0, 7.6, 2.2, f"Medicare Part D 2024\nPrescribers by Provider\nand Drug\n{f['partd']:.1f}M rows, 4.1 GB")
    put("op", 0, 3.8, 2.6, f"Open Payments 2024\nGeneral payments\n{f['op']:.1f}M rows, 9.0 GB\nplus research, ownership,\nrecipient profiles")

    put("bronze", 1, 4.9, 3.0, "Parquet, every column text\nNo silent type guessing\n\nRow counts checked 3 ways:\nPython csv, DuckDB,\nParquet (must match)")

    put("stg", 2, 8.0, 2.0, "Staging\nTyped and trimmed\nSuppressed values = NULL\nnever zero")
    put("rules", 2, 5.0, 2.0, "Business rules\nBrand vs generic rule\nName normalization\nOpioid flag (seed)")
    put("match", 2, 2.0, 2.0, f"Payments to drugs\n5 product slots unpivoted\nStaged name matching\n{f['match']} of drug rows")

    put("star", 3, 4.2, 3.4, "Star schema\nfact_prescriptions\nfact_payments\ndim drug, specialty, state,\nmanufacturer, date, prescriber")
    put("tests", 3, 1.2, 2.1, f"{f['tests']} dbt tests\nkeys, relationships,\naccepted values,\nreconciliation, suppression")

    put("q1", 4, 8.3, 1.9, "Q1 Spend\nBrand vs generic, specialty,\nstate, generic savings")
    put("q2", 4, 5.6, 2.1, "Q2 Payments vs prescribing\nRegression with fixed effects\nMatched comparison\nRandom effects pooling")
    put("q3", 4, 1.9, 2.1, "Q3 Outliers\nRobust z within specialty\nIsolation Forest\n(fixed seed)")

    put("public", 5, 8.0, 2.1, "Public (committed)\nfindings.md, charts\noutputs_public CSVs\ngroups of 11+ prescribers")
    put("pbi", 5, 3.9, 2.0, "Power BI report\nAggregated export\nDAX measures, 4 pages\nPDF and screenshots")
    put("private", 5, 1.2, 2.1, "Private (git-ignored)\nIndividual level flags\noutputs_private/\nnever published",
        fill=PRIVATE_TINT)

    def right(k):
        x, y, w_, h = B[k]
        return x + w_, y + h / 2

    def left(k):
        x, y, w_, h = B[k]
        return x, y + h / 2

    for a, b in [("partd", "bronze"), ("op", "bronze"), ("bronze", "stg"), ("bronze", "rules"),
                 ("bronze", "match"), ("stg", "star"), ("rules", "star"), ("match", "star"),
                 ("star", "q1"), ("star", "q2"), ("star", "q3"), ("q1", "public"),
                 ("q2", "public"), ("q3", "public"), ("q3", "private")]:
        arrow(ax, *right(a), *left(b))
    # star schema to Power BI: horizontal lane between the Q2 and Q3 boxes
    lane = 4.8
    arrow(ax, B["star"][0] + w, lane, B["pbi"][0], lane)
    # tests check the star schema (vertical)
    x, y, w_, h = B["tests"]
    arrow(ax, x + w_ / 2, y + h, x + w_ / 2, B["star"][1])

    ax.text(0.3, 0.55, "Privacy rule: no prescriber is named or published; every public "
            "number describes at least 11 prescribers. Payments correlating with prescribing "
            "is not evidence of wrongdoing.", fontsize=9, color=charts.INK_2)
    fig.suptitle("RxLedger pipeline: raw CMS files to findings and a Power BI report",
                 x=0.012, y=0.985, ha="left", fontsize=14, fontweight="bold", color=charts.INK)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = config.DOCS_DIR / "process_map.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
