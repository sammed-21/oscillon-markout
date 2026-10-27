"""Cumulative LP profit of Aqua0 + Oscillon minus vanilla Aqua0, per day, one panel per pool. Reads aqua0_backtest.py output.

  python3 aqua0_chart.py results_aqua0_usdc_usdt_calm.json results_aqua0_usdc_weth_calm.json --out charts_aqua0/A1_oscillon_vs_vanilla.png
"""
import argparse, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def money(y, sign=False):
    return ("−" if y < 0 else "+" if sign and y > 0 else "") + f"${abs(y):,.0f}"


ap = argparse.ArgumentParser(); ap.add_argument("results", nargs="+"); ap.add_argument("--out", required=True)
a = ap.parse_args()
plt.rcParams.update({"text.parse_math": False, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
SERIES = [("oscillon_a5000_db20|eps2", "α 0.5, deadband 20 bp", "#2a78d6"), ("oscillon_a5000_db5|eps2", "α 0.5, deadband 5 bp", "#eb6834")]
fig, axes = plt.subplots(1, len(a.results), figsize=(6 * len(a.results), 4.4), constrained_layout=True)
for ax, f in zip(np.atleast_1d(axes), a.results):
    r = json.load(open(f)); v = r["runs"]["vanilla|eps0.5"]; days = sorted(v["daily"])
    for key, label, col in SERIES:
        x = r["runs"][key]
        cum = np.cumsum([x["daily"].get(d, 0) - v["daily"][d] for d in days])
        t = pd.to_datetime(days)
        ax.plot(t, cum, color=col, lw=2, label=label)
        ax.annotate(money(cum[-1], True), (t[-1], cum[-1]), xytext=(4, 0), textcoords="offset points", va="center", color="#333")
    ax.axhline(0, color="#999", lw=1)
    ax.grid(axis="y", color="#e6e6e6", lw=0.8)
    ax.set_title(f"{r['pool']}: vanilla Aqua0 earns ${v['net']:,.0f} on ${r['capital'] / 1e6:g}M", loc="left", fontsize=11)
    ax.set_ylabel("Oscillon minus vanilla, cumulative ($)")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: money(y)))
    ax.tick_params(axis="x", labelrotation=30)
np.atleast_1d(axes)[0].legend(frameon=False, loc="upper left")
fig.suptitle(f"Extra LP profit from the Oscillon gap fee on Aqua0, last 90 days, real swaps (elasticity 2)", x=0.01, ha="left", fontsize=12)
fig.savefig(a.out, dpi=160)
print("wrote", a.out)
