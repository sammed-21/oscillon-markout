"""
F8: LP return vs holding for the Fynd AMM ETH/USDG pool, from lp_returns.py.

  A  per $1,000 of LP capital for 30 days: fees, impermanent loss, and the net (LP minus holding), main LP vs the rest
  B  running totals in dollars, each position counted on the day it closed (open ones at the snapshot)
  C  where LP minus holding comes from (lp_split.py): fees, traders' capture, the pool lagging Binance, later price moves
  D  how stale the price is that Fynd's bot moves the pool to

  python3 lp_chart.py --prefix results_lp_fynd --split results_lp_fynd_split \
      --main 0x6c6a40d2d1fc442e281e1f80314fd86516e17127 --png charts_flow/F8_fynd_lp_vs_hold.png
"""
import argparse, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--prefix", required=True); ap.add_argument("--split", required=True)
ap.add_argument("--main", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
res = json.load(open(a.prefix + ".json"))
sp = json.load(open(a.split + ".json"))
P = pd.read_csv(a.prefix + "_positions.csv", parse_dates=["start_utc", "end_utc"])
FEE, MK, LP, BOT, GREY = "#1b8f63", "#c4561f", "#2a6fd6", "#7a4fbf", "#8a8986"    # same roles as F5 and F7
plt.rcParams.update({"text.parse_math": False, "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#ececec"})
money = lambda v: f"{'-' if v < 0 else '+'}${abs(v):,.0f}"
width = lambda g: 100 * ((g.range_high / g.range_low - 1) * g.capital_days_usd)[g.range_high < 1e9].sum() / g.capital_days_usd[g.range_high < 1e9].sum()

main = P.owner.str.lower() == a.main.lower()
groups = [(f"Main LP {a.main[:6]}…{a.main[-4:]}\n{main.sum()} positions\nranges ~{width(P[main]):.1f}% wide", P[main]),
          (f"Other {P[~main].owner.nunique()} LPs\n{(~main).sum()} positions\nranges ~{width(P[~main]):.0f}% wide", P[~main]),
          (f"All LPs\n{len(P)} positions", P)]
fig, axs = plt.subplots(2, 2, figsize=(16, 13), constrained_layout=True, gridspec_kw={"width_ratios": [1, 1.25]})
axs = axs.ravel()

ax = axs[0]
ax.set_axisbelow(True)
w = 0.26
for i, (lab, g) in enumerate(groups):
    per = lambda c: 1000 * 30 * g[c].sum() / g.capital_days_usd.sum()
    for j, (c, col, name) in enumerate([("fees_usd", FEE, "Fees earned"), ("il_usd", MK, "Impermanent loss"),
                                        ("lp_minus_hold_usd", LP, "Net: LP minus holding")]):
        v = per(c)
        ax.bar(i + (j - 1) * w, v, w * 0.92, color=col, label=name if i == 0 else None)
        ax.text(i + (j - 1) * w, v + (4 if v >= 0 else -4), money(v), ha="center", va="bottom" if v >= 0 else "top", fontsize=9.5, color="#222")
ax.set_xticks(range(len(groups))); ax.set_xticklabels([g[0] for g in groups], fontsize=9.5)
ax.axhline(0, color="#999", lw=1)
ax.set_ylabel("$ per $1,000 of LP capital, per 30 days")
lo = min(1000 * 30 * g.il_usd.sum() / g.capital_days_usd.sum() for _, g in groups)
ax.set_ylim(lo * 1.25, 1000 * 30 * max(g.fees_usd.sum() / g.capital_days_usd.sum() for _, g in groups) * 1.6)
ax.legend(loc="upper right", fontsize=9.5, facecolor="white", edgecolor="none", framealpha=0.9)
ax.set_title("A. Every LP group earned less in fees than it lost to price moves\n"
             "narrower ranges earn more fees and lose more, but lose faster than they earn", fontsize=11.5, loc="left")

ax = axs[1]
c = P.sort_values("end_utc")
for col, colr, name, lw_ in [("fees_usd", FEE, "Fees earned", 2), ("il_usd", MK, "Impermanent loss", 2),
                             ("lp_minus_hold_usd", LP, "Net: LP minus holding", 2.6)]:
    y = c[col].cumsum()
    ax.plot(c.end_utc, y, color=colr, lw=lw_, drawstyle="steps-post", label=f"{name} {money(y.iloc[-1])}")
ax.axhline(0, color="#999", lw=1)
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
ax.set_ylabel("$, running total")
ax.legend(loc="lower left", fontsize=10, facecolor="white", edgecolor="none", framealpha=0.9)
pr = res["period"]
ax.set_title(f"B. All {res['positions']} positions, {pr['start_utc'][:10]} to {pr['end_utc'][:10]} "
             f"(ETH ${pr['eth_start']:,.0f} → ${pr['eth_end']:,.0f})\n"
             "each position counted when it closed; the 6 still open at the snapshot", fontsize=11.5, loc="left")

ax = axs[2]
ax.set_axisbelow(True)
pk, ci, bk = sp["per_1000_per_30d"], sp["ci95_per_1000_per_30d"], sp["buckets"]
per = lambda v: 30_000 * v / res["totals"]["capital_days_usd"]
bars = [("Fees paid\nto LPs", pk["fees"], FEE, None),
        ("Traders' capture\nat the price they\nleft the pool", pk["trader_capture"], BOT, ci["trader_capture"]),
        ("Pool still behind\nBinance after\nthe trade", pk["pool_lag"], MK, ci["pool_lag"]),
        ("Price moves\nafter trades", pk["price_moves_after_trades"], GREY, None),
        ("Total\nLP minus holding", per(sp["lp_minus_hold"]), LP, ci["lp_net_of_swaps"])]
for i, (lab, v, col, c) in enumerate(bars):
    ax.bar(i, v, 0.6, color=col)
    if c:
        ax.errorbar(i, v, yerr=[[v - c[0]], [c[1] - v]], color="#333", capsize=5, lw=1.2)
    if c:
        ax.text(i + 0.33, v / 2, money(v), va="center", fontsize=9.5, color="#222")
    else:
        ax.text(i, v + (6 if v >= 0 else -6), money(v), ha="center", va="bottom" if v >= 0 else "top", fontsize=9.5, color="#222")
ax.set_xticks(range(len(bars))); ax.set_xticklabels([b[0] for b in bars], fontsize=9.5)
ax.axhline(0, color="#999", lw=1)
ax.set_ylim(min(c[0] for *_, c in bars if c) * 1.18, pk["fees"] * 1.5)
ax.set_ylabel("$ per $1,000 of LP capital, per 30 days")
b = sp["bot"]
ax.text(0.99, 0.97, f"Fynd's bot: capture {money(-b['capture'])} ({b['capture_bp']:.2f} bp), fees paid {money(-b['fee'])} ({b['fee_bp']:.2f} bp)\n"
        f"= {money(b['trader_net_own_view'])} for the bot over {(pd.Timestamp(sp['swaps_period'][1]) - pd.Timestamp(sp['swaps_period'][0])).days} days, before its costs elsewhere",
        transform=ax.transAxes, ha="right", va="top", fontsize=9.5, color="#333")
ax.set_title(f"C. Most of the loss is the pool lagging the market, not what traders capture\n"
             "per swap, valued at Binance 12 s later; whiskers = 95% intervals", fontsize=11.5, loc="left")

ax = axs[3]
lg = pd.read_csv(a.split + "_bot_lag.csv")
g = sp["bot_gap_bp"]
ax.plot(lg.seconds_earlier, lg.median_gap_after_bot_swap_bp, color=BOT, lw=2.4, marker="o", ms=5)
ax.axvline(g["best_match_seconds_earlier"], color=GREY, ls=":", lw=1)
ax.text(g["best_match_seconds_earlier"] + 1, lg.median_gap_after_bot_swap_bp.max() * 0.97,
        f"closest match: Binance\n~{g['best_match_seconds_earlier']} s before the trade", fontsize=9.5, color="#333", va="top")
ax.set_xlabel("Binance price taken this many seconds before the bot's trade")
ax.set_ylabel("Median gap between the pool price the bot\nleaves and Binance, bp")
ax.set_ylim(0, lg.median_gap_after_bot_swap_bp.max() * 1.15)
ax.set_title(f"D. The bot moves the pool toward a price ~{g['best_match_seconds_earlier']} s old\n"
             f"gap to Binance {g['median_before']:.1f} bp before its trade, {g['median_after']:.1f} bp after (medians); same side {g['same_side_after']:.0%} of the time", fontsize=11.5, loc="left")

t = res["totals"]
fig.suptitle(f"Fynd AMM ETH/USDG LPs vs simply holding the same tokens: {money(t['lp_minus_hold_usd'])} "
             f"on ${res['avg_capital_usd']:,.0f} average capital "
             f"({res['lp_minus_hold_per_30d_pct']:+.1f}% per 30 days)", fontsize=14, x=0.01, ha="left")
fig.text(0.01, -0.06,
         "LP = what each position paid out (withdrawals + fees collected) plus what it still holds; holding = the tokens it deposited. "
         "Both valued at Binance ETHUSDC at the position's end, so ETH's own price move cancels.\n"
         "Impermanent loss = tokens out minus tokens in at that price, before fees. Capital = cost of deposits x days held. "
         f"Snapshot block {res['period']['snapshot_block']:,}. Books close: the open positions on chain hold exactly what all "
         "deposits, withdrawals, fees and swaps add up to.",
         ha="left", va="top", fontsize=9, color="#555")
fig.savefig(a.png, dpi=140, bbox_inches="tight", facecolor="white")
print("wrote", a.png)
