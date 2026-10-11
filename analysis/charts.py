"""Shared matplotlib styling for RxLedger figures (static PNGs for the README and docs).

Author: Erica Mathias

Colors come from a validated categorical palette (blue, orange: CVD and contrast checks
pass on the light surface). Text always uses ink tokens, never series colors.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"


def style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
        "font.size": 10,
        "text.color": INK,
        "axes.labelcolor": INK_2,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 1,
        "xtick.color": MUTED,
        "ytick.color": INK_2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "grid.color": GRID,
        "grid.linewidth": 1,
        "grid.linestyle": "-",
    })


def title(ax, text, subtitle=None):
    ax.set_title(text, loc="left", fontsize=13, fontweight="bold", color=INK, pad=24)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9.5, color=INK_2,
                va="bottom")


def dollars(scale, suffix, decimals=0):
    return FuncFormatter(lambda v, _: f"${v / scale:,.{decimals}f}{suffix}")


def source_note(fig, text="Source: CMS Medicare Part D Prescribers by Provider and Drug, 2024."):
    fig.text(0.01, 0.01, text, fontsize=8, color=MUTED, ha="left", va="bottom")


def hbar(ax, labels, values, color=BLUE, fmt=lambda v: f"{v:,.0f}"):
    """Horizontal ranked bars, largest on top, value at the tip, hairline x grid."""
    y = range(len(labels))[::-1]
    ax.barh(list(y), values, height=0.62, color=color, edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(list(y), labels)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    xmax = max(values)
    for yi, v in zip(y, values):
        ax.text(v + xmax * 0.01, yi, fmt(v), va="center", fontsize=9, color=INK_2)
    ax.set_xlim(0, xmax * 1.15)
