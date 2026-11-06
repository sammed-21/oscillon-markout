"""
What LPs would earn without toxic flow. Each source (the Swap event's `sender`) is called toxic if its net LP markout
at 12 s is negative over the window. That is decided after the fact, so "without toxic flow" is an upper bound on what
any mechanism could recover, not a forecast. Fees are the LP share after the protocol fee. Flagged swaps excluded.

  python3 toxic_split.py --swaps data_swaps/usdc_weth_5bp.csv --markouts data_swaps/usdc_weth_5bp_markouts.csv \
      --name "ETH/USDC 0.05%" --lp-fee-share 0.75 --png charts_flow/F4_toxic_split_weth.png
"""
import argparse
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--markouts", required=True); ap.add_argument("--name", required=True)
ap.add_argument("--lp-fee-share", type=float, default=0.75); ap.add_argument("--png", required=True)
ap.add_argument("--start", default=""); ap.add_argument("--end", default="", help="exclusive; dates, UTC")
a = ap.parse_args()

sw = pd.read_csv(a.swaps, usecols=["ts", "sender", "block", "log_index"]).sort_values(["block", "log_index"]).reset_index(drop=True)
d = pd.concat([sw, pd.read_csv(a.markouts)], axis=1)
d = d.loc[:, ~d.columns.duplicated(keep="last")]                # markouts' ts
t0 = pd.Timestamp(a.start, tz="UTC").timestamp() if a.start else -1
t1 = pd.Timestamp(a.end, tz="UTC").timestamp() if a.end else 1e12
days = ((min(d.ts.max(), t1) - max(d.ts.min(), t0)) / 86400)
d = d[~d.flagged.astype(bool) & (d.ts >= t0) & (d.ts < t1)]
d["sender"] = d.sender.str.lower()
d["fee"] *= a.lp_fee_share
g = d.groupby("sender").agg(swaps=("notional", "size"), vol=("notional", "sum"), fees=("fee", "sum"), mk=("mk_12", "sum"))
top2 = g.sort_values("mk").index[:2]
groups = {"All flow": g, "Toxic sources": g[g.mk < 0], "Other sources": g[g.mk >= 0],
          "Top 2 bots": g.loc[top2], "All except top 2": g.drop(top2)}

rows = []
for k, x in groups.items():
    fees, mk = x.fees.sum(), x.mk.sum()
    rows.append((k, len(x), x.swaps.sum(), x.vol.sum(), fees, mk, fees + mk, mk / x.vol.sum() * 1e4))
    print(f"{k:18s} sources {len(x):>5,} swaps {x.swaps.sum():>8,.0f} vol ${x.vol.sum() / 1e9:5.2f}B fees ${fees / 1e6:5.2f}M "
          f"markout ${mk / 1e6:+6.2f}M LP ${(fees + mk) / 1e6:+6.2f}M ({mk / x.vol.sum() * 1e4:+.1f} bp)")


def money(y):
    return ("−" if y < 0 else "+") + f"${abs(y) / 1e6:,.2f}M"


plt.rcParams.update({"text.parse_math": False, "font.size": 12, "axes.spines.top": False, "axes.spines.right": False})
show = [r for r in rows if r[0] in ("All flow", "Top 2 bots", "All except top 2")]
fig, ax = plt.subplots(figsize=(12, 6.75), constrained_layout=True)
w = 0.26
for j, (lab, col) in enumerate([("Fees LPs kept", "#1b8f63"), ("Markout at 12 s", "#c4561f"), ("LP profit", "#2a6fd6")]):
    for i, r in enumerate(show):
        v = r[4 + j]
        ax.bar(i + (j - 1) * w, v, w * 0.92, color=col, label=lab if i == 0 else None)
        ax.annotate(money(v), (i + (j - 1) * w, v), xytext=(0, 4 if v >= 0 else -4), textcoords="offset points",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=10.5, fontweight="bold", color="#222")
ax.set_xticks(range(len(show)), [f"{r[0]}\n{r[2]:,.0f} swaps · ${r[3] / 1e9:.1f}B · {r[7]:+.1f} bp" for r in show])
ax.axhline(0, color="#888", lw=1); ax.grid(axis="y", color="#e8e8e8"); ax.set_axisbelow(True)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: money(y) if y else "$0"))
ax.legend(frameon=False, loc="lower right")
ex = rows[4]
ax.set_title(f"{a.name}, {days:.0f} days: two bots turn LP profit of {money(ex[6])} into {money(rows[0][6])}",
             loc="left", fontsize=15, fontweight="bold")
fig.text(0.01, -0.03, "Source = contract that called the pool. bp = markout per $ of volume. Toxic is decided after the fact, so the "
         "right-hand group is an upper bound: without those bots the pool's price would go stale and other flow would trade worse.",
         ha="left", va="top", fontsize=9.5, color="#555", wrap=True)
fig.savefig(a.png, dpi=150, bbox_inches="tight", facecolor="white")
print("wrote", a.png)
