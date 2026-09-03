"""Publication-ready figure output (SVG for typesetting + 600-dpi PNG).

All figures in the study are produced through save_fig() so they share:
- journal column geometry (85 mm single / 175 mm double)
- 8 pt Arial/Helvetica, thin axes, colour-blind-safe Okabe-Ito palette
- text kept as text in SVG (svg.fonttype="none")
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  

import config  

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "legend.title_fontsize": 7,
    "axes.linewidth": 0.6, "lines.linewidth": 1.0, "lines.markersize": 3.5,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 150, "savefig.dpi": 600, "savefig.bbox": "tight",
    "savefig.pad_inches": 0.08, "svg.fonttype": "none",
    "pdf.fonttype": 42, "ps.fonttype": 42,
})

SINGLE_COL, DOUBLE_COL = 3.35, 6.9  # inches

COLORS = {
    "gemini": "#0072B2", "cohere": "#E69F00", "ollama": "#009E73",
    "include": "#0072B2", "exclude": "#D55E00", "maybe": "#CC79A7",
    "tier1": "#0072B2", "tier2": "#E69F00", "override": "#CC79A7",
    "fallback": "#009E73", "grey": "#7F7F7F",
}
MODEL_LABELS = {"gemini": "Gemini 3.6 Flash", "cohere": "Command-A",
                "ollama": "Llama3.2-3B (local)"}


def new_fig(width: float = SINGLE_COL, height: float | None = None,
            ncols: int = 1, nrows: int = 1, **kw):
    if height is None:
        height = width * 0.75
    return plt.subplots(nrows, ncols, figsize=(width, height), **kw)


def save_fig(fig, name: str, formats=("svg", "png")):
    config.FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for fmt in formats:
        p = config.FIG_DIR / f"{name}.{fmt}"
        fig.savefig(p, format=fmt)
        out.append(p)
    plt.close(fig)
    print("[viz] saved " + ", ".join(p.name for p in out))
    return out
