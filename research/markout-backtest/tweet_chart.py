"""
One 16:9 chart for a social post: a normal $1M LP on one pool, without vs with the Oscillon gap fee, as two waterfalls
(fees -> 12 s markout -> everything else -> profit vs holding). Reads aqua0_backtest.py output.

  python3 tweet_chart.py results_aqua0_usdc_weth_calm.json --oscillon "oscillon_a5000_db20|eps2" \
      --pool "ETH/USDC 0.05%" --out charts_aqua0/T1_gap_fee_eth.png
"""
import argparse, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser(); ap.add_argument("results")
ap.add_argument("--oscillon", default="oscillon_a5000_db20|eps2"); ap.add_argument("--pool", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
plt.rcParams.update({"text.parse_math": False, "font.size": 13, "axes.spines.top": False, "axes.spines.right": False})
r = json.load(open(a.results))
ROWS = [("vanilla|eps0.5", "Normal pool"), (a.oscillon, "With Oscillon gap fee")]
STEPS = ["Fees", "Lost to informed\ntrades (12 s)", "Everything\nelse", "Profit vs\nholding"]
COL = ["#1b8f63", "#c4561f", "#9aa0a6", "#2a6fd6"]


def money(y):
    return ("−" if y < 0 else "+") + f"${abs(y) / 1e3:,.1f}k"


fig, axes = plt.subplots(1, 2, figsize=(12, 6.75), sharey=True, constrained_layout=True)
totals = []
for ax, (run, title) in zip(axes, ROWS):
    x = r["runs"][run]
    fees, mk, total = x["fees"], x["markout_12s"], x["net_vs_hold"]
    totals.append(total)
    steps = [(fees, 0), (mk, fees), (total - fees - mk, fees + mk), (total, 0)]
    for i, (v, b) in enumerate(steps):
        ax.bar(i, v, 0.64, bottom=b, color=COL[i])
        end = b + v
        ax.annotate(money(v), (i, max(b, end) if v >= 0 else min(b, end)), xytext=(0, 4 if v >= 0 else -4),
                    textcoords="offset points", ha="center", va="bottom" if v >= 0 else "top", fontsize=13, fontweight="bold", color="#222")
        if i < 3:
            ax.plot([i + 0.32, i + 0.68], [end, end], color="#bbb", lw=1)
    ax.axhline(0, color="#888", lw=1)
    ax.grid(axis="y", color="#e8e8e8", lw=0.8); ax.set_axisbelow(True)
    ax.set_xticks(range(4), STEPS, fontsize=11.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: money(y) if y else "$0"))
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold")
axes[0].set_ylim(-110_000, 125_000)
fig.suptitle(f"$1M LP on {a.pool}, {r['days']:.0f} days of real swaps: the gap fee adds {money(totals[1] - totals[0])} for LPs",
             x=0.01, ha="left", fontsize=17, fontweight="bold")
fig.text(0.01, -0.02, "Profit vs holding = fees + (LP value change − value of just holding the same tokens). Informed-trade loss = each fill "
         "valued at the Binance price 12 s later. Backtest, ±10% range; the price path is held fixed, so the gap fee gets no credit for "
         "smaller losses.", ha="left", va="top", fontsize=9.5, color="#555", wrap=True)
fig.savefig(a.out, dpi=150, bbox_inches="tight", facecolor="white")
print("wrote", a.out)
