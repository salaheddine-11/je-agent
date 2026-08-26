"""Generate the report's data visualizations (ink/paper/amber identity).

Run: uv run --with matplotlib python report/charts.py
Outputs PNGs (200 dpi) into report/assets/.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, INK_SOFT, FAINT = "#1f1e1c", "#57534e", "#a8a29e"
AMBER, EMERALD, PAPER = "#b45309", "#047857", "#ffffff"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": "#e5e7eb", "axes.linewidth": 1,
    "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "text.color": INK,
    "axes.labelcolor": INK_SOFT, "xtick.color": INK_SOFT, "ytick.color": INK_SOFT,
    "figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER,
})
OUT = Path(__file__).parent / "assets"
OUT.mkdir(exist_ok=True)


def strip(ax, grid_axis="y"):
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.grid(axis=grid_axis, color="#eeeeec", linewidth=1)
    ax.set_axisbelow(True)


# ——— 1 · Recall vs precision across scales ————————————————————————
fig, ax = plt.subplots(figsize=(8.2, 3.6))
scales = ["medium\n20,210 lines", "large\n100,354 lines", "huge\n200,562 lines"]
recall = [100.0, 98.87, 98.93]
precision = [18.9, 6.7, 6.4]
x = range(3)
w = 0.36
b1 = ax.bar([i - w/2 for i in x], recall, w, color=EMERALD, label="Recall")
b2 = ax.bar([i + w/2 for i in x], precision, w, color=AMBER, label="Precision")
for b in list(b1) + list(b2):
    v = b.get_height()
    ax.annotate(f"{v:.1f}%", (b.get_x() + b.get_width()/2, v),
                ha="center", va="bottom", fontsize=10, fontweight="bold",
                color=INK, xytext=(0, 2), textcoords="offset points")
ax.set_xticks(list(x)); ax.set_xticklabels(scales)
ax.set_ylim(0, 115); ax.set_yticks([0, 25, 50, 75, 100])
ax.set_ylabel("percent")
strip(ax)
ax.legend(frameon=False, loc="center right")
fig.tight_layout(); fig.savefig(OUT / "chart_scales.png", dpi=200); plt.close(fig)

# ——— 2 · Per-rule precision at 200k (structural vs pattern rules) ——
rules = [
    ("balance_check", 100.0, "structural"),
    ("reversals", 100.0, "structural"),
    ("unusual_users", 100.0, "structural"),
    ("unusual_pairs", 100.0, "structural"),
    ("round_amounts", 27.3, "pattern"),
    ("period_end", 6.3, "pattern"),
    ("entry_splitting", 4.8, "pattern"),
    ("high_risk_system_pairs", 0.9, "pattern"),
]
fig, ax = plt.subplots(figsize=(8.2, 4.2))
names = [r[0] for r in rules][::-1]
vals = [r[1] for r in rules][::-1]
cols = [EMERALD if r[2] == "structural" else AMBER for r in rules][::-1]
bars = ax.barh(names, vals, color=cols, height=0.62)
for b, v in zip(bars, vals):
    ax.annotate(f"{v:g}%" if v < 100 else "100%",
                (v, b.get_y() + b.get_height()/2),
                va="center", ha="left", fontsize=10, fontweight="bold",
                color=INK, xytext=(4, 0), textcoords="offset points")
ax.axvline(100, color="#e5e7eb", lw=1)
ax.set_xlim(0, 118); ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel("precision at 200,562 lines (recall ≈ 100% for every rule)")
strip(ax, grid_axis="x")
from matplotlib.patches import Patch
ax.legend(frameon=False, loc="lower right",
          handles=[Patch(color=EMERALD, label="structural facts — exact"),
                   Patch(color=AMBER, label="innocent-looking patterns — broad net")])
fig.tight_layout(); fig.savefig(OUT / "chart_rules.png", dpi=200); plt.close(fig)

# ——— 3 · Tuning A/B ————————————————————————————————————————————————
fig, ax = plt.subplots(figsize=(6.4, 3.5))
labels = ["default params", "tuned params"]
prec, rec, f1 = [18.9, 42.3], [100, 100], [31.8, 59.5]
x = range(2); w = 0.25
ax.bar([i - w for i in x], prec, w, color=AMBER, label="Precision")
ax.bar(list(x), rec, w, color=EMERALD, label="Recall")
ax.bar([i + w for i in x], f1, w, color=INK, label="F1")
for xs, vals in [(x, prec), (x, rec), ([i + w for i in x], f1)]:
    pass
for container, vals in [(ax.containers[0], prec), (ax.containers[1], rec), (ax.containers[2], f1)]:
    for b, v in zip(container, vals):
        ax.annotate(f"{v:g}", (b.get_x() + b.get_width()/2, v), ha="center",
                    va="bottom", fontsize=9.5, fontweight="bold", color=INK,
                    xytext=(0, 2), textcoords="offset points")
ax.set_xticks(list(x)); ax.set_xticklabels(labels)
ax.set_ylim(0, 118); ax.set_yticks([0, 25, 50, 75, 100])
ax.set_ylabel("percent · 20k-line scenario")
strip(ax)
ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.14))
fig.tight_layout(); fig.savefig(OUT / "chart_tuning.png", dpi=200); plt.close(fig)

# ——— 4 · Three-layer flow diagram ——————————————————————————————————
fig, ax = plt.subplots(figsize=(10.6, 2.9))
ax.axis("off"); ax.set_xlim(0, 12.2); ax.set_ylim(0, 3)
boxes = [
    (0.15, "CSV export", "#f4f2ef", INK_SOFT),
    (2.45, "Layer 1\nDeterministic rules\n10 transparent checks", INK, PAPER),
    (5.05, "Layer 2\nAI triage\nprioritizes,\nnever decides", AMBER, PAPER),
    (7.65, "Layer 3\nHuman review\ninspect / accept\n+ written reason", "#faf9f7", INK),
    (10.35, "Deliverables\nPDF · XLSX\naudit trail", "#f4f2ef", INK_SOFT),
]
W, H, Y = 2.3, 1.9, 0.55
for x0, txt, fc, tc in boxes:
    ax.add_patch(plt.Rectangle((x0, Y), W, H, facecolor=fc, edgecolor="#d6d3d1",
                               linewidth=1.2, zorder=2))
    ax.text(x0 + W/2, Y + H/2, txt, ha="center", va="center",
            fontsize=9.3, fontweight="bold", color=tc, zorder=3, linespacing=1.5)
arrow_style = dict(arrowprops=dict(arrowstyle="-|>", color=FAINT, lw=2))
for x0 in [2.45, 5.05, 7.65, 10.35]:
    ax.annotate("", xy=(x0 - 0.02, Y + H/2), xytext=(x0 - 0.32, Y + H/2), **arrow_style)
# captions centered over the gaps between boxes
gaps = [(2.30 + 2.45) / 2 + 0.15, (5.05 + 7.65) / 2 - W/2 + W/2, (7.65 + 10.35) / 2]
captions = ["flags everything suspicious", "ranks what matters", "hash-chained decisions"]
gap_centers = [(2.30 + 2.45) / 2, (4.75 + 5.05) / 2 + 1.28, (7.35 + 7.65) / 2 + 1.29]
for cx, cap in zip(gap_centers, captions):
    ax.text(cx, 2.72, cap, ha="center", fontsize=8.8, color=INK_SOFT, style="italic")
fig.tight_layout(pad=0.4); fig.savefig(OUT / "diagram_layers.png", dpi=200); plt.close(fig)

print("charts written:", sorted(p.name for p in OUT.glob('*.png')))
