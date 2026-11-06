"""
Where an LP's money goes, per setup: fees -> 12 s markout -> everything else vs holding -> profit vs holding.
    profit vs holding = fees + (LP token value change - value change of just holding the starting tokens)
    12 s markout      = the part of that loss from trades valued 12 s after each one; the rest is everything else
                        (later price moves on the LP's inventory, rebalancing cost)
One column per pair, one row per setup (normal LP, Aqua0 shared, shared + Oscillon). Reads aqua0_shared.py output.

  python3 aqua0_waterfall_chart.py results_aqua0_shared_usdt.json results_aqua0_shared_weth.json \
      --oscillon oscillon_a5000_db20_feeLE500 --eps 2 --out charts_aqua0/A3_waterfall.png
"""
import argparse, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser(); ap.add_argument("results", nargs="+")
ap.add_argument("--oscillon", default="oscillon_a5000_db20_feeLE500"); ap.add_argument("--eps", default="2")
ap.add_argument("--out", required=True)
a = ap.parse_args()
plt.rcParams.update({"text.parse_math": False, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
ROWS = [("isolated|vanilla|eps0.5", "Normal LP (isolated)"), ("shared|vanilla|eps0.5", "Aqua0 shared"),
        (f"shared|{a.oscillon}|eps{a.eps}", "Aqua0 shared + Oscillon")]
STEPS = ["Fees", "12 s markout\n(informed trades)", "Everything else\nvs holding", "Profit\nvs holding"]
COL = {"Fees": "#1baf7a", "mk": "#eb6834", "rest": "#9aa0a6", "total": "#2a78d6"}


def money(y):
    return ("−" if y < 0 else "+") + f"${abs(y):,.0f}"


res = [json.load(open(f)) for f in a.results]
fig, axes = plt.subplots(len(ROWS), len(res), figsize=(6.5 * len(res), 3.3 * len(ROWS)), constrained_layout=True, squeeze=False)
for c, r in enumerate(res):
    ann = 365 / r["days"] / r["capital"] * 100
    pools = " + ".join(p.split(":")[0].split("_")[-1].replace("bp", " bp") for p in r["pools"])
    vals_all = []
    for row, (run, label) in enumerate(ROWS):
        x = r["runs"][run]
        fees, mk, total = x["fees"], x["markout_12s"], x["net_vs_hold"]
        rest = total - fees - mk
        ax = axes[row][c]
        steps = [(fees, 0, COL["Fees"]), (mk, fees, COL["mk"]), (rest, fees + mk, COL["rest"]), (total, 0, COL["total"])]
        for i, (v, bottom, col) in enumerate(steps):
            ax.bar(i, v, 0.62, bottom=bottom, color=col)
            top = bottom + v
            ax.annotate(f"{money(v)}\n{v * ann:+.2f}%/yr", (i, max(top, bottom) if v >= 0 else min(top, bottom)),
                        xytext=(0, 3 if v >= 0 else -3), textcoords="offset points", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=8.5, color="#222")
            if i < 3:
                ax.plot([i + 0.31, i + 0.69], [top, top], color="#bbb", lw=0.8)
            vals_all += [bottom, top]
        ax.axhline(0, color="#999", lw=1)
        ax.grid(axis="y", color="#e6e6e6", lw=0.8); ax.set_axisbelow(True)
        ax.set_xticks(range(4), STEPS, fontsize=8.5)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: money(y) if y else "$0"))
        ax.set_title(f"{r['pair']} ({pools} pools): {label}", loc="left", fontsize=10)
    lo, hi = min(vals_all), max(vals_all); pad = (hi - lo) * 0.3
    for row in range(len(ROWS)):
        axes[row][c].set_ylim(lo - pad, hi + pad)
fig.suptitle(f"Where the LP's money goes: same $1M, last {res[0]['days']:.0f} days of real swaps, each LP's share of every swap",
             x=0.01, ha="left", fontsize=12)
fig.text(0.01, -0.01, "Oscillon gap fee (α 0.5, deadband 20 bp, elasticity 2) is applied only to pools with a base fee ≤ 5 bp. "
         "This rule was chosen after seeing the results: with Oscillon on the 0.30% ETH pool too, shared ends at −$124,845 vs holding. "
         "To be confirmed on a different period.", ha="left", va="top", fontsize=9, color="#444", wrap=True)
fig.savefig(a.out, dpi=160, bbox_inches="tight")
print("wrote", a.out)
