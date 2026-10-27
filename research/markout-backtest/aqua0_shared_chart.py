"""
Same $1M, three ways, per pair: normal isolated LP, Aqua0 shared, Aqua0 shared + Oscillon. Reads aqua0_shared.py output.
One row per pair (own scale), columns: fees to LPs, markout at 12 s, and LP profit against simply holding the starting
tokens (fees + markout + inventory moves), all annualized as % of capital with dollars over the window.

  python3 aqua0_shared_chart.py results_aqua0_shared_usdt.json results_aqua0_shared_weth.json \
      --oscillon oscillon_a5000_db20_feeLE500 --eps 2 --out charts_aqua0/A2_shared_oscillon_yield.png
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
BARS = [("isolated|vanilla|eps0.5", "Normal LP\n(isolated)", "#9aa0a6"),
        ("shared|vanilla|eps0.5", "Aqua0\nshared", "#2a78d6"),
        (f"shared|{a.oscillon}|eps{a.eps}", "Aqua0 shared\n+ Oscillon", "#eb6834")]
COLS = [("fees", "Fees to LPs"), ("markout_12s", "Markout at 12 s (informed-trade loss)"),
        ("net_vs_hold", "LP profit vs holding the tokens")]


def money(y):
    return ("−" if y < 0 else "+") + f"${abs(y):,.0f}"


res = [json.load(open(f)) for f in a.results]
fig, axes = plt.subplots(len(res), 3, figsize=(13, 3.9 * len(res)), constrained_layout=True, squeeze=False)
for row, r in zip(axes, res):
    pools = " + ".join(p.split(":")[0].split("_")[-1].replace("bp", " bp") for p in r["pools"])
    for ax, (key, title) in zip(row, COLS):
        vals = [r["runs"][run][key] / r["capital"] * 365 / r["days"] * 100 for run, _, _ in BARS]
        bars = ax.bar(range(3), vals, 0.6, color=[c for _, _, c in BARS])
        for i, (rect, v) in enumerate(zip(bars, vals)):
            ax.annotate(f"{v:+.2f}%/yr\n{money(r['runs'][BARS[i][0]][key])}", (rect.get_x() + rect.get_width() / 2, v),
                        xytext=(0, 3 if v >= 0 else -3), textcoords="offset points", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=8.5, color="#222")
        ax.axhline(0, color="#999", lw=1)
        ax.grid(axis="y", color="#e6e6e6", lw=0.8); ax.set_axisbelow(True)
        ax.set_xticks(range(3), [l for _, l, _ in BARS], fontsize=9)
        lo, hi = min(0, *vals), max(0, *vals); pad = (hi - lo) * 0.28
        ax.set_ylim(lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:g}%"))
        ax.set_title(title, loc="left", fontsize=10.5)
    row[0].set_ylabel(f"{r['pair']}  ({pools} pools)", fontsize=11, fontweight="bold")
fig.suptitle(f"Same $1M across two pools of one pair, last {res[0]['days']:.0f} days of real swaps. Oscillon gap fee on pools "
             f"with base fee ≤ 5 bp (α 0.5, deadband 20 bp, elasticity {a.eps})", x=0.01, ha="left", fontsize=11.5)
fig.savefig(a.out, dpi=160)
print("wrote", a.out)
