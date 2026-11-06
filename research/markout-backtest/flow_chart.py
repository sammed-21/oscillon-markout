"""
One PNG for a flow_classify.py run: where the LP loss comes from, and how to check it.
  A  cumulative fees, 12 s markout, LP profit and theoretical LVR by hour
  B  LP profit by wallet group (top wallet, other arbitrage bots, everyone else)
  C  every swap: gap to Binance before the trade vs what LPs lost on it (bp) - arbitrage closes the gap and the loss
     is about the gap
  D  one real arbitrage swap worked through by hand, with its tx hash, so the numbers can be checked on an explorer

  python3 flow_chart.py --prefix results_flow_fynd --name "Fynd AMM ETH/USDG (Ekubo, Robinhood)" \
      --explorer https://robinhoodchain.blockscout.com/tx/ --png charts_flow/F5_fynd_toxic_flow.png
"""
import argparse, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--prefix", required=True); ap.add_argument("--name", required=True)
ap.add_argument("--explorer", default=""); ap.add_argument("--png", required=True)
ap.add_argument("--raw", default="", help="fetched swaps CSV with tx_to, to name the contract each wallet calls")
a = ap.parse_args()
res = json.load(open(a.prefix + ".json"))
d = pd.read_csv(a.prefix + "_swaps.csv")
if a.raw:
    d["tx_to"] = d.tx_hash.map(pd.read_csv(a.raw, usecols=["tx_hash", "tx_to"]).drop_duplicates("tx_hash").set_index("tx_hash").tx_to)
lvr = pd.read_csv(a.prefix + "_lvr_minute.csv", parse_dates=["t"]).set_index("t").lvr_theory
FEE, MK, LP, GREY = "#1b8f63", "#c4561f", "#2a6fd6", "#8a8986"
plt.rcParams.update({"text.parse_math": False, "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#ececec"})


def money(y):
    v = abs(y)
    return ("−" if y < 0 else "+") + (f"${v / 1e3:,.1f}k" if v >= 1e3 else f"${v:,.0f}" if v >= 100 else f"${v:,.2f}")


fig = plt.figure(figsize=(16, 11), constrained_layout=True)
gs = fig.add_gridspec(2, 2)

# A: cumulative by hour
ax = fig.add_subplot(gs[0, 0])
d["t"] = pd.to_datetime(d.ts, unit="s")
h = d.set_index("t")[["fee", "mk_12", "lp_pnl"]].resample("1h").sum().cumsum()
lv = -lvr.resample("1h").sum().cumsum()
ax.plot(h.index, h.fee, color=FEE, lw=2, label=f"Fees LPs earned {money(h.fee.iloc[-1])}")
ax.plot(h.index, h.mk_12, color=MK, lw=2, label=f"Lost to traders, {res['by_swap']['arbitrage']['volume'] / res['all']['volume']:.0%} of it arbitrage {money(h.mk_12.iloc[-1])}")
ax.plot(lv.index, lv, color=GREY, lw=1.5, ls="--", label=f"Theoretical LVR {money(lv.iloc[-1])}")
ax.plot(h.index, h.lp_pnl, color=LP, lw=2.5, label=f"LP profit {money(h.lp_pnl.iloc[-1])}")
ax.axhline(0, color="#999", lw=1)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{'−' if y < 0 else '+'}${abs(y) / 1e3:,.0f}k" if y else "$0"))
ax.legend(frameon=False, loc="lower left", fontsize=10)
ax.set_title("A. The pool's LPs vs the traders, running total\n(each swap valued at Binance 12 s after it)", loc="left", fontweight="bold")
ax.tick_params(axis="x", labelsize=9)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))

# B: by wallet group
ax = fig.add_subplot(gs[0, 1])
top = d.groupby("wallet").lp_pnl.sum().idxmin()
ob = d[(d.cls == "arbitrage bot") & (d.wallet != top)].groupby("wallet").lp_pnl.sum().sort_values()
via = lambda w: f"\nonly calls {d[d.wallet == w].tx_to.mode()[0][:10]}…" if a.raw else ""
order = [f"Top wallet\n{top[:10]}…{via(top)}",
         f"{len(ob)} other\narbitrage bots\nlargest {ob.index[0][:10]}…\n= {ob.iloc[0] / ob.sum():.0%} of their loss",
         "Everyone else"]
grp = np.where(d.wallet == top, order[0], np.where(d.cls == "arbitrage bot", order[1], order[2]))
s = d.groupby(grp).agg(fee=("fee", "sum"), mk=("mk_12", "sum"), lp=("lp_pnl", "sum"), n=("ts", "size"), v=("notional", "sum")).reindex(order)
w = 0.26
for j, (col, c, lab) in enumerate([("fee", FEE, "Fees"), ("mk", MK, "Lost at 12 s"), ("lp", LP, "LP profit")]):
    for i, v in enumerate(s[col]):
        ax.bar(i + (j - 1) * w, v, w * 0.92, color=c, label=lab if i == 0 else None)
        ax.annotate(money(v), (i + (j - 1) * w, v), xytext=(0, 3 if v >= 0 else -3), textcoords="offset points",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=9, fontweight="bold")
ax.set_xticks(range(3), [f"{k}\n{int(r.n):,} swaps · ${r.v / 1e6:.2f}M" for k, r in s.iterrows()], fontsize=9)
ax.axhline(0, color="#999", lw=1)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: money(y) if y else "$0"))
ax.legend(frameon=False, loc="lower right", fontsize=10)
ax.set_title("B. Who the loss went to (grouped by the wallet that sent each transaction)", loc="left", fontweight="bold")

# C: gap before vs loss, per swap
ax = fig.add_subplot(gs[1, 0])
x = d[d.notional > 50]
toward = np.where(x.amount0 < 0, x.gap_bp < 0, x.gap_bp > 0)              # trade moved the pool toward Binance
gap_toward = np.where(toward, x.gap_bp.abs(), -x.gap_bp.abs())
loss_bp = -x.mk_0 / x.notional * 1e4
ax.scatter(gap_toward[~x.arb], loss_bp[~x.arb], s=6, color=GREY, alpha=0.5, label="Other swaps (moved away, or fee above the gap)")
ax.scatter(gap_toward[x.arb], loss_bp[x.arb], s=6, color=MK, alpha=0.35, label="Arbitrage: moved the pool toward Binance")
lim = 60
ax.plot([0, lim], [0, lim], color="#333", lw=1, ls=":")
ax.text(lim * 0.62, lim * 0.70, "loss = gap", fontsize=9, color="#333", rotation=33)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim / 2, lim)
ax.axhline(0, color="#999", lw=1); ax.axvline(0, color="#999", lw=1)
ax.set_xlabel("Gap between pool and Binance before the trade (bp); right = trade closed the gap")
ax.set_ylabel("LP loss on the trade at the moment of the trade (bp)")
ax.legend(frameon=False, loc="upper left", fontsize=10, markerscale=3)
ax.text(0.99, 0.03, "Each dot is one swap.\nRight of 0: it moved the pool's price toward Binance.\n"
        "On the dotted line: the LP lost the whole gap.\nArbitrage = toward Binance, and the gap was bigger than the fee paid,\n"
        "so the trader beat Binance's price even after the fee.", transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color="#444")
ax.set_title(f"C. Every swap: {x.arb.mean():.0%} closed a gap to Binance\nbigger than the fee they paid", loc="left", fontweight="bold")

# D: a worked example
ax = fig.add_subplot(gs[1, 1]); ax.axis("off")
cand = d[(d.wallet == top) & d.arb & d.notional.between(300, 1000) & (d.fee > 0)]
ex = cand.iloc[(cand.mk_12 / cand.notional * 1e4 - (cand.mk_12.sum() / cand.notional.sum() * 1e4)).abs().argsort().iloc[0]]
sells = ex.amount0 > 0
eth, usd = abs(ex.amount0), abs(ex.amount1)
p12 = (ex.mk_12 - ex.amount1) / ex.amount0
lines = [
    ("Transaction", f"{ex.tx_hash[:18]}…{ex.tx_hash[-6:]}  (block {int(ex.block):,})"),
    ("Time (UTC)", str(pd.to_datetime(ex.ts, unit="s"))),
    ("Wallet", f"{ex.wallet}  ({ex.cls})"),
    ("Trade", f"trader {'sold' if sells else 'bought'} {eth:.6f} ETH for {usd:,.2f} USDG"),
    ("Pool price before", f"${ex.pre:,.2f}"),
    ("Binance price at the block", f"${ex.p_binance:,.2f}   → gap {ex.gap_bp:+.1f} bp"),
    ("Pool price after", f"${ex.price:,.2f}   (moved toward Binance)"),
    ("Price the trader got", f"${usd / eth:,.2f}"),
    ("LP loss at the trade", f"{'+' if sells else '−'}{eth:.6f} ETH × ${ex.p_binance:,.2f} {'−' if sells else '+'} {usd:,.2f} USDG = {money(ex.mk_0)}"),
    ("LP loss 12 s later", f"same ETH valued at Binance ${p12:,.2f} = {money(ex.mk_12)}  ({ex.mk_12 / ex.notional * 1e4:+.1f} bp)"),
    ("Fee LPs got", f"{money(ex.fee)}  ({ex.fee_bp:.2f} bp)"),
    ("LP profit on this swap", money(ex.lp_pnl)),
]
ax.set_title("D. Check one swap yourself", loc="left", fontweight="bold")
y = 0.95
for k, v in lines:
    ax.text(0.0, y, k, fontsize=10.5, color="#555", va="top", transform=ax.transAxes)
    ax.text(0.37, y, v, fontsize=10.5, color="#111", va="top", transform=ax.transAxes, family="DejaVu Sans Mono")
    y -= 0.068
ax.text(0.0, y - 0.02, (f"Open {a.explorer}{ex.tx_hash}\n" if a.explorer else "") +
        "The pool's Swap log gives the amounts; Binance ETHUSDC 1 s klines give the prices.\n"
        "Every swap in the file is scored the same way and summed into panels A–C.",
        fontsize=9.5, color="#555", va="top", transform=ax.transAxes)

A = res["all"]
fig.suptitle(f"{a.name}, {res['days']:.0f} days: LPs earned {money(A['fees'])} in fees and lost {money(A['markout_12'])} "
             f"to traders, {res['by_swap']['arbitrage']['volume'] / A['volume']:.0%} of it arbitrage on a stale price",
             x=0.01, ha="left", fontsize=15, fontweight="bold")
fig.text(0.01, -0.015, f"{A['swaps']:,} swaps, ${A['volume'] / 1e6:.2f}M volume, {res['window'][0][:10]} – {res['window'][1][:10]}. "
         "Loss = LP's token change valued at Binance ETH/USDC (USDG = $1), fees excluded; fees are the extension's FeesAccumulated "
         f"events. Theoretical LVR = σ²·L·√S/4 per minute. Swaps more than 1% from Binance excluded ({res['flagged_swaps']}).",
         ha="left", va="top", fontsize=9, color="#555", wrap=True)
fig.savefig(a.png, dpi=140, bbox_inches="tight", facecolor="white")
print("wrote", a.png, "| example tx", ex.tx_hash)
