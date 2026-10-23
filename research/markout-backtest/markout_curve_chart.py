"""
Markout-by-horizon chart from markout_horizons.py outputs (one panel per pool, one line per side, fee level marked).

  python3 markout_curve_chart.py --inputs results_markout_usdc_weth.json results_markout_usdc_usdt.json \
      --png charts_flow/F1_markout_by_horizon.png
"""
import argparse, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--inputs", nargs="+", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID})
lab = {0: "at trade", 12: "12 s", 60: "1 min", 300: "5 min", 3600: "1 h"}
fig, axes = plt.subplots(1, len(a.inputs), figsize=(7.2 * len(a.inputs), 5.2))
for ax, path in zip(np.atleast_1d(axes), a.inputs):
    r = json.load(open(path)); H = r["horizons"]; x = np.arange(len(H))
    tot = np.zeros(len(H)); vol = 0
    for (side, d), col in zip(r["sides"].items(), ("#e34948", "#2a78d6")):
        y = [d["markout"][str(h)]["net_bp"] for h in H]
        ax.plot(x, y, color=col, lw=2, marker="o", ms=5, label=side)
        ax.annotate(f"{y[-1]:+.2f} bp", (x[-1], y[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8.5, color=INK)
        tot += np.array([d["markout"][str(h)]["net"] for h in H]); vol += d["volume"]
    both = tot / vol * 1e4
    ax.plot(x, both, color=INK, lw=2.4, marker="D", ms=5, label="both sides")
    ax.axhline(-r["fee_bp"], color="#1baf7a", lw=1.4, ls=(0, (5, 3)))
    ax.text(x[len(x) // 2], -r["fee_bp"], f"−fee ({r['fee_bp']:g} bp): below this line LPs lose net", va="top", ha="center",
            fontsize=8.5, color=INK2, bbox=dict(fc=SURF, ec="none", pad=1))
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(x); ax.set_xticklabels([lab.get(h, f"{h}s") for h in H])
    ax.set_title(f"{r['pool']} · {r['swaps']:,} swaps · ${r['volume'] / 1e9:,.2f}B", loc="left", fontsize=11)
    ax.set_ylabel("Net LP markout, bp of volume (fee excluded)")
    ax.legend(frameon=False, fontsize=8.5, loc="best")
fig.suptitle("When do LPs lose money? Markout by time after the trade, per side · Jul 24 – Oct 21, 2026", x=0.06, ha="left", fontsize=14, y=1.0)
fig.text(0.06, 0.93, "Individual swaps from the chain, priced on Binance 1-second closes. Off-market swaps (>100 bp from Binance at the trade) excluded. "
         "The 1 h column includes price drift.", fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.84, wspace=0.18)
fig.savefig(a.png, dpi=160, bbox_inches="tight"); print("wrote", a.png)
