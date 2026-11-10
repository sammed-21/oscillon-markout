"""
One PNG for a flow_classify.py run: where the LP loss comes from, and how to check it.
  A  cumulative fees, 12 s markout, LP net markout and theoretical LVR by hour
  B  LP net markout by wallet group (top wallet, other high-frequency wallets, everyone else)
  C  every swap: gap to Binance before the trade vs what LPs lost on it (bp) - a swap toward Binance closes the gap and
     the loss is about the gap
  D  one real toward-Binance swap worked through by hand, with its tx hash, so the numbers can be checked on an explorer
Internal flow (the run's internal_wallets) is labelled BOT in every panel. The example swap is written to
<prefix>_example.json so test_flow.py can recompute it to the cent.

--png2 adds a second PNG: fee sweep on external toward-Binance swaps (LP net, volume kept), theoretical vs measured LVR
by week, and daily TVL rebuilt from events.

  python3 flow_chart.py --prefix results_flow_fynd --name "Fynd AMM ETH/USDG (Ekubo, Robinhood)" \
      --explorer https://robinhoodchain.blockscout.com/tx/ --raw data_swaps/eth_usdg_ekubo_robinhood_to1108.csv \
      --png charts_flow/F5_fynd_toxic_flow.png --png2 charts_flow/F7_fynd_fee_sweep_lvr_tvl.png
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
ap.add_argument("--klines", default="klines_eth_1s"); ap.add_argument("--png2", default="")
a = ap.parse_args()
res = json.load(open(a.prefix + ".json"))
d = pd.read_csv(a.prefix + "_swaps.csv")
internal = set(res.get("internal_wallets", []))
IN = "#7a4fbf"                                                          # internal flow, in every panel
# Label for internal_wallets. The Fynd team has not confirmed the wallet; switch to "Fynd wallet (confirmed by team)"
# only once they do, and update SOURCE to say who confirmed it.
BOT, BOT_LC = "Likely Fynd bot", "likely Fynd bot"
SOURCE = ("Likely Fynd bot = 0x4abfdbac0afa181338dc9c38c9c1264128c684a2, listed in INTERNAL_WALLETS in flow_classify.py "
          "by us, not by Fynd: it sent every one of its {n:,} swaps through 0x7ea0ab3b. Not confirmed by the Fynd team.")
TOWARD = "swaps that moved the pool toward Binance"
if a.raw:
    d["tx_to"] = d.tx_hash.map(pd.read_csv(a.raw, usecols=["tx_hash", "tx_to"]).drop_duplicates("tx_hash").set_index("tx_hash").tx_to)
lvr = pd.read_csv(a.prefix + "_lvr_minute.csv", parse_dates=["t"]).set_index("t").lvr_theory
FEE, MK, LP, GREY = "#1b8f63", "#c4561f", "#2a6fd6", "#8a8986"
plt.rcParams.update({"text.parse_math": False, "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#ececec"})


def money(y):
    v = abs(y)
    return ("−" if y < 0 else "+") + (f"${v / 1e3:,.1f}k" if v >= 1e3 else f"${v:,.0f}" if v >= 100 else
                                      f"${v:,.2f}" if v >= 0.01 or v == 0 else f"${v:.4f}")


fig = plt.figure(figsize=(16, 11), constrained_layout=True)
gs = fig.add_gridspec(2, 2)

# A: cumulative by hour
ax = fig.add_subplot(gs[0, 0])
d["t"] = pd.to_datetime(d.ts, unit="s")
h = d.set_index("t")[["fee", "mk_12", "lp_pnl"]].resample("1h").sum().cumsum()
lv = -lvr.resample("1h").sum().cumsum()
ax.plot(h.index, h.fee, color=FEE, lw=2, label=f"Fees LPs earned {money(h.fee.iloc[-1])}")
ax.plot(h.index, h.mk_12, color=MK, lw=2, label=f"Lost to traders {money(h.mk_12.iloc[-1])}; {res['by_swap']['arbitrage']['volume'] / res['all']['volume']:.0%} of volume was\n{TOWARD}")
ax.plot(lv.index, lv, color=GREY, lw=1.5, ls="--", label=f"Theoretical LVR {money(lv.iloc[-1])}")
ax.plot(h.index, h.lp_pnl, color=LP, lw=2.5, label=f"LP net markout, all flow {money(h.lp_pnl.iloc[-1])}")
if internal:
    he = d[~d.internal].set_index("t").lp_pnl.resample("1h").sum().reindex(h.index, fill_value=0).cumsum()
    hi = d[d.internal].set_index("t").lp_pnl.resample("1h").sum().reindex(h.index, fill_value=0).cumsum()
    ax.plot(he.index, he, color=LP, lw=1.6, ls="--", label=f"LP net markout, external flow only {money(he.iloc[-1])}")
    ax.plot(hi.index, hi, color=IN, lw=1.6, label=f"of which {BOT_LC} {money(hi.iloc[-1])}")
ax.axhline(0, color="#999", lw=1)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{'−' if y < 0 else '+'}${abs(y) / 1e3:,.0f}k" if y else "$0"))
ax.legend(loc="lower left", fontsize=10, facecolor="white", edgecolor="none", framealpha=0.9)
ax.set_title("A. The pool's LPs vs the traders, running total\n(each swap valued at Binance 12 s after it)", loc="left", fontweight="bold")
ax.tick_params(axis="x", labelsize=9)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))

# B: by wallet group
ax = fig.add_subplot(gs[0, 1])
top = d.groupby("wallet").lp_pnl.sum().idxmin()
first = d.internal.astype(bool) if internal else d.wallet == top
via = lambda w: f"\nonly calls {d[d.wallet == w].tx_to.mode()[0][:10]}…" if a.raw else ""
ob = d[(d.cls == "arbitrage bot") & ~first].groupby("wallet").lp_pnl.sum().sort_values()
order = [(f"{BOT}\n{', '.join(w[:10] + '…' for w in sorted(internal))}{via(top) if top in internal else ''}"
          if internal else f"Top wallet\n{top[:10]}…{via(top)}"),
         f"{len(ob)} other wallets{' (external)' if internal else ''}\nlargest {ob.index[0][:10]}…\n= {ob.iloc[0] / ob.sum():.0%} of their loss",
         "Everyone else" + (" (external)" if internal else "")]
grp = np.where(first, order[0], np.where(d.cls == "arbitrage bot", order[1], order[2]))
s = d.groupby(grp).agg(fee=("fee", "sum"), mk=("mk_12", "sum"), lp=("lp_pnl", "sum"), n=("ts", "size"), v=("notional", "sum")).reindex(order)
w = 0.26
for j, (col, c, lab) in enumerate([("fee", FEE, "Fees"), ("mk", MK, "Lost at 12 s"), ("lp", LP, "LP net markout")]):
    for i, v in enumerate(s[col]):
        ax.bar(i + (j - 1) * w, v, w * 0.92, color=c, label=lab if i == 0 else None)
        ax.annotate(money(v), (i + (j - 1) * w, v), xytext=(0, 3 if v >= 0 else -3), textcoords="offset points",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=9, fontweight="bold")
ax.set_xticks(range(3), [f"{k}\n{int(r.n):,} swaps · ${r.v / 1e6:.2f}M" for k, r in s.iterrows()], fontsize=9)
if internal:
    ax.get_xticklabels()[0].set_color(IN); ax.get_xticklabels()[0].set_fontweight("bold")
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
xi, xa = x.internal.values.astype(bool), x.arb.values
ax.scatter(gap_toward[xa & ~xi], loss_bp[xa & ~xi], s=6, color=MK, alpha=0.35,
           label="Toward Binance, gap > fee" + (": external wallets" if internal else ""))
if internal:
    ax.scatter(gap_toward[xa & xi], loss_bp[xa & xi], s=6, color=IN, alpha=0.25, label=f"Toward Binance, gap > fee: {BOT_LC}")
lim = 60
ax.plot([0, lim], [0, lim], color="#333", lw=1, ls=":")
ax.text(lim * 0.62, lim * 0.70, "loss = gap", fontsize=9, color="#333", rotation=33)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim / 2, lim)
ax.axhline(0, color="#999", lw=1); ax.axvline(0, color="#999", lw=1)
ax.set_xlabel("Gap between pool and Binance before the trade (bp); right = trade closed the gap")
ax.set_ylabel("LP loss on the trade at the moment of the trade (bp)")
ax.legend(frameon=False, loc="upper left", fontsize=10, markerscale=3)
ax.text(0.99, 0.03, "Each dot is one swap.\nRight of 0: it moved the pool's price toward Binance.\n"
        "On the dotted line: the LP lost the whole gap.\nColoured = toward Binance, and the gap was bigger than the fee paid,\n"
        "so the trader beat Binance's price even after the fee.\nThe data can't tell arbitrageurs from routed users.", transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color="#444")
ax.set_title(f"C. Every swap over $50: {x[x.arb].notional.sum() / x.notional.sum():.0%} of volume closed a gap\nto Binance bigger than the fee paid",
             loc="left", fontweight="bold")

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
    ("Wallet", f"{ex.wallet}  ({BOT if ex.wallet in internal else ex.cls})"),
    ("Trade", f"trader {'sold' if sells else 'bought'} {eth:.6f} ETH for {usd:,.2f} USDG"),
    ("Pool price before", f"${ex.pre:,.2f}"),
    ("Binance price at the block", f"${ex.p_binance:,.2f}   → gap {ex.gap_bp:+.1f} bp"),
    ("Pool price after", f"${ex.price:,.2f}   (moved toward Binance)"),
    ("Price the trader got", f"${usd / eth:,.2f}"),
    ("LP loss at the trade", f"{'+' if sells else '−'}{eth:.6f} ETH × ${ex.p_binance:,.2f} {'−' if sells else '+'} {usd:,.2f} USDG = {money(ex.mk_0)}"),
    ("LP loss 12 s later", f"same ETH valued at Binance ${p12:,.2f} = {money(ex.mk_12)}  ({ex.mk_12 / ex.notional * 1e4:+.1f} bp)"),
    ("Fee LPs got", f"{money(ex.fee)}  ({ex.fee_bp:.2f} bp)"),
    ("LP net markout on this swap", money(ex.lp_pnl)),
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
E = res.get("external_only", {}).get("all")
fig.suptitle(f"{a.name}, {res['days']:.0f} days: LPs earned {money(A['fees'])} in fees and lost {money(A['markout_12'])} "
             f"to traders; {res['by_swap']['arbitrage']['volume'] / A['volume']:.0%} of volume was {TOWARD}"
             + (f"\nExternal flow only ({BOT_LC} removed): fees {money(E['fees'])}, lost {money(E['markout_12'])}, "
                f"LP {money(E['lp_pnl'])} ({E['lp_pnl_bp']:+.1f} bp of ${E['volume'] / 1e6:.2f}M)" if internal else ""),
             x=0.01, ha="left", fontsize=15, fontweight="bold")
fig.text(0.01, -0.015, f"{A['swaps']:,} swaps, ${A['volume'] / 1e6:.2f}M volume, {res['window'][0][:10]} – {res['window'][1][:10]}. "
         "Loss = LP's token change valued at Binance ETH/USDC (USDG = $1; last 1 s close before the block's second), fees excluded. "
         "Fees are the extension's FeesAccumulated events, which pay in at the pool's next interaction: each is split over "
         f"the swaps since the previous one. Theoretical LVR = σ²·L·√S/4 per minute. Swaps more than 1% from Binance excluded ({res['flagged_swaps']}, "
         f"listed in _excluded.csv). Toward Binance, gap > fee: {TOWARD}, from a gap bigger than the fee paid; the data can't "
         "tell arbitrageurs from routed users." + (" " + SOURCE.format(n=int(d.internal.sum())) if internal else ""),
         ha="left", va="top", fontsize=9, color="#555", wrap=True)
fig.savefig(a.png, dpi=140, bbox_inches="tight", facecolor="white")
json.dump({"tx_hash": ex.tx_hash, "raw": a.raw, "klines": a.klines, "mk_0": float(ex.mk_0), "fee": float(ex.fee)},
          open(a.prefix + "_example.json", "w"), indent=2)
print("wrote", a.png, "| example tx", ex.tx_hash)

if a.png2:
    sw_ = pd.read_csv(a.prefix + "_fee_sweep.csv")
    lw = pd.read_csv(a.prefix + "_lvr_weekly.csv", parse_dates=["week_start"])
    act = res["fee_sweep_actual"]
    fig, axs = plt.subplots(2, 2, figsize=(16, 10.5), constrained_layout=True)
    ax = axs[0, 0]
    ax.plot(sw_.fee_bp, sw_.lp_net, color=LP, lw=2.2, marker="o", ms=3)
    ax.axhline(0, color="#999", lw=1)
    ax.axhline(act["lp_pnl"], color=GREY, ls="--", lw=1)
    ax.text(sw_.fee_bp.max(), act["lp_pnl"], f"actual fees ({act['fee_bp']:.2f} bp): LP {money(act['lp_pnl'])}", ha="right", va="bottom", fontsize=9)
    be = sw_[sw_.lp_net >= 0].fee_bp.min()
    if pd.notna(be):
        ax.axvline(be, color=FEE, ls=":", lw=1)
        ax.text(be, ax.get_ylim()[0], f" LP net ≥ 0 from {be} bp", color=FEE, fontsize=9, va="bottom")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: money(y) if y else "$0"))
    ax.set_xlabel("Flat fee f on external toward-Binance swaps (bp)")
    ax.set_title(f"E. LP net on EXTERNAL toward-Binance swaps (gap > fee)\nif the fee were f ({BOT_LC} excluded)", loc="left", fontweight="bold")
    ax = axs[0, 1]
    ax.plot(sw_.fee_bp, sw_.volume_retained * 100, color=MK, lw=2.2, marker="o", ms=3)
    ax.set_ylim(0, 105); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())
    ax.set_xlabel("Flat fee f on external toward-Binance swaps (bp)")
    ax.set_title("F. External toward-Binance volume still traded at fee f\n(swaps whose gap to Binance was bigger than f)", loc="left", fontweight="bold")
    ax.text(0.98, 0.95, "Assumes these swaps happen only while gap > fee, at the same size.\nSays nothing about retail demand.",
            transform=ax.transAxes, ha="right", va="top", fontsize=9.5, color="#444")
    ax = axs[1, 0]
    xw = np.arange(len(lw)); bw = 0.27
    for j, (c, col, lab) in enumerate([("lvr_theory", GREY, "Theoretical LVR"), ("measured_loss_all", LP, "Measured loss at 12 s, all flow"),
                                       ("measured_loss_external", MK, "Measured loss at 12 s, external only")]):
        ax.bar(xw + (j - 1) * bw, lw[c], bw * 0.9, color=col, label=lab)
    for i, r in lw.iterrows():
        ax.annotate(f"{r.ratio_all:.2f}×\nσ {r.sigma_annual:.0%}", (i, max(r.lvr_theory, r.measured_loss_all)), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=8.5)
    ax.set_ylim(0, lw[["lvr_theory", "measured_loss_all"]].max().max() * 1.2)
    ax.set_xticks(xw, [f"wk {t:%b %d}\n{r.minutes / 1440:.1f} days" for t, (_, r) in zip(lw.week_start, lw.iterrows())], fontsize=9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.set_title("G. Theoretical LVR vs measured loss by week\n(label: measured/theory, all flow; σ = annualised ETH vol)", loc="left", fontweight="bold")
    ax = axs[1, 1]
    tv = pd.read_csv(a.prefix + "_tvl_daily.csv", parse_dates=["day"]) if res.get("tvl") else None
    if tv is not None:
        ax.plot(tv.day, tv.tvl_usd, color=LP, lw=2.2, drawstyle="steps-post")
        ax.axhline(res["tvl"]["average_in_window"], color=GREY, ls="--", lw=1)
        ax.text(tv.day.iloc[0], res["tvl"]["average_in_window"], f" average in window ${res['tvl']['average_in_window']:,.0f}",
                va="bottom", fontsize=9)
        # holdings are rebuilt from every event in the file, which can run past the analysis window: shade those days
        w_end = pd.Timestamp(res["window"][1]).normalize() + pd.Timedelta(days=1)
        if tv.day.iloc[-1] >= w_end:
            ax.axvspan(w_end, tv.day.iloc[-1] + pd.Timedelta(days=1), color="#ececec", zorder=0)
            ax.text(w_end + (tv.day.iloc[-1] + pd.Timedelta(days=1) - w_end) / 2, ax.get_ylim()[1] * 0.97,
                    "after the window,\nnot in the average", rotation=90, ha="center", va="top", fontsize=8.5, color="#555")
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"${y:,.0f}"))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))
        ax.set_title(f"H. Pool TVL by day, rebuilt from position, swap and fee events\n(valued at Binance end-of-day; "
                     f"analysis window {res['window'][0][:10]} to {res['window'][1][:10]})", loc="left", fontweight="bold")
    fig.suptitle(f"{a.name}: fee sweep, LVR reconciliation, TVL", x=0.01, ha="left", fontsize=15, fontweight="bold")
    fig.savefig(a.png2, dpi=130, bbox_inches="tight", facecolor="white")
    print("wrote", a.png2)
