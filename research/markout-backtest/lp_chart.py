"""
F8: LP return vs holding for the Fynd AMM ETH/USDG pool, from lp_returns.py.

  A  per $1,000 of LP capital for 30 days: fees, impermanent loss, and the net (LP minus holding), main LP vs the rest
  B  running totals in dollars, each position counted on the day it closed (open ones at the snapshot)
  C  LP minus holding split by the wallet that sent each swap (lp_split.py): the bot wallet's swaps, all others, later moves
  D  LPs' result on the bot wallet's swaps at other fees (same swaps: a transfer, not a forecast)
  E  the bot wallet's capture for a range of h, its cost per $ traded

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
fig = plt.figure(figsize=(21, 13.5), constrained_layout=True)
gs = fig.add_gridspec(2, 6)
axs = [fig.add_subplot(gs[0, :3]), fig.add_subplot(gs[0, 3:]), fig.add_subplot(gs[1, :2]),
       fig.add_subplot(gs[1, 2:4]), fig.add_subplot(gs[1, 4:])]

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

span_lbl = "$, " + " – ".join(pd.Timestamp(t).strftime("%b %-d") for t in sp["swaps_period"])
ax = axs[2]
ax.set_axisbelow(True)
b, o, ci = sp["bot"], sp["other"], sp["ci95_usd_over_period"]
groups_c = [("Swaps by the\nbot wallet", b, ci["bot_lp_net"]), ("All other\nswaps", o, ci["other_lp_net"])]
w = 0.26
for i, (lab, g, c) in enumerate(groups_c):
    for j, (v, col, name) in enumerate([(g["fee"], FEE, "Fees paid to LPs"), (-g["loss_12s"], MK, "Loss at Binance 12 s later"),
                                        (g["lp_net"], LP, "Net for LPs")]):
        ax.bar(i + (j - 1) * w, v, w * 0.92, color=col, label=name if i == 0 else None)
        if j == 2:
            ax.errorbar(i + (j - 1) * w, v, yerr=[[v - c[0]], [c[1] - v]], color="#333", capsize=4, lw=1.1)
        xo = i + (j - 1) * w + (0.15 if j == 2 else 0)
        ax.text(xo, v + (60 if v >= 0 else -60), money(v), ha="left" if j == 2 else "center",
                va="bottom" if v >= 0 else "top", fontsize=9.5, color="#222")
ax.bar(2, sp["drift"], w * 0.92, color=GREY, label="Later price moves")
ax.text(2, sp["drift"] - 60, money(sp["drift"]), ha="center", va="top", fontsize=9.5, color="#222")
ax.bar(3, sp["lp_minus_hold"], w * 1.4, color=LP)
ax.text(3, sp["lp_minus_hold"] - 60, money(sp["lp_minus_hold"]), ha="center", va="top", fontsize=9.5, color="#222")
ax.set_xticks(range(4)); ax.set_xticklabels([g[0] for g in groups_c] + ["Later price\nmoves", "Total:\nLP minus holding"], fontsize=9.5)
ax.axhline(0, color="#999", lw=1)
ax.set_ylim(-b["loss_12s"] * 1.3, o["fee"] * 1.7)
ax.set_ylabel(span_lbl)
ax.legend(loc="upper right", fontsize=9, facecolor="white", edgecolor="none", framealpha=0.9)
ax.set_title("C. Loss occurred on swaps by the bot wallet: an upper bound\non its capture, before hedging and other costs\n"
             "LP side of each swap at Binance 12 s later; whiskers = 95% intervals", fontsize=11.5, loc="left")

ax = axs[3]
fd = pd.read_csv(a.split + "_fee_sensitivity.csv")
fs = sp["fee_sensitivity"]
ax.plot(fd.fee_bp, fd.lp_on_bot_wallet_swaps_usd, color=LP, lw=2.4, label="LPs on the bot wallet's swaps")
ax.plot(fd.fee_bp, fd.lp_minus_hold_all_usd, color=LP, lw=1.6, ls="--", label="LP minus holding, all positions")
ax.axhline(0, color="#999", lw=1)
for xv, txt in [(fs["actual_fee_bp"], f"actual {fs['actual_fee_bp']:.2f} bp\n{money(b['lp_net'])}"),
                (fs["breakeven_fee_bp_bot_wallet_swaps"], f"{fs['breakeven_fee_bp_bot_wallet_swaps']:.1f} bp:\nLPs break even\non these swaps")]:
    ax.axvline(xv, color=GREY, ls=":", lw=1)
    ax.text(xv + 0.2, -b["loss_12s"] * (0.45 if xv > 5 else 0.6), txt, fontsize=9.5, color="#333", va="bottom")
ax.set_xlabel("Fee on the bot wallet's swaps, bp")
ax.set_ylabel(span_lbl)
ax.legend(loc="upper left", fontsize=9, facecolor="white", edgecolor="none", framealpha=0.9)
ax.set_title("D. If the bot wallet's swaps had paid a different fee\n"
             "assumes identical swaps at every fee: a transfer from\nthe bot wallet to LPs, not a forecast", fontsize=11.5, loc="left")

ax = axs[4]
hd = pd.read_csv(a.split + "_h_sensitivity.csv")
hs = sp["h_sensitivity"]
ax.fill_between(hd.h_bp, hd.ci_low, hd.ci_high, color=BOT, alpha=0.15, lw=0, label="95% interval")
ax.plot(hd.h_bp, hd.bot_capture_usd, color=BOT, lw=2.4, label="Bot wallet's capture")
ax.axhline(0, color="#999", lw=1)
ax.axvline(hs["breakeven_h_bp"], color=GREY, ls=":", lw=1)
ax.text(0.2, hs["upper_bound_at_h0"] * 1.04, f"h = 0: {money(hs['upper_bound_at_h0'])}, the upper bound", fontsize=9.5, color="#333", va="bottom")
lo_, hi_ = hs["breakeven_h_bp_ci95"]
ax.text(hs["breakeven_h_bp"] + 0.2, hs["upper_bound_at_h0"] * 0.45,
        f"zero at h = {hs['breakeven_h_bp']:.1f} bp\n(95%: {lo_:.1f} to {hi_:.1f} bp)", fontsize=9.5, color="#333")
ax.set_ylim(min(hd.ci_low) * 1.1, hs["upper_bound_at_h0"] * 1.25)
ax.set_xlabel("h: the bot wallet's cost per $ traded, bp\n(hedging, exchange fees, gas, hedge price vs Binance 12 s later)")
ax.set_ylabel(span_lbl)
ax.legend(loc="lower left", fontsize=9, facecolor="white", edgecolor="none", framealpha=0.9)
ax.set_title(f"E. Bot wallet's capture = loss on its swaps − fees it paid − h × volume\n"
             f"{money(b['loss_12s'])[1:]} − {money(b['fee'])[1:]} − h × ${b['volume'] / 1e6:.2f}M; "
             "we can't see h, Fynd can", fontsize=11.5, loc="left")

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
