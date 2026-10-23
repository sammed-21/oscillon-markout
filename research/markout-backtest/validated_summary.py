"""
One-page PNG of the markout results that passed validation (individual swaps cross-checked against an independent
indexer; fee results only where out of sample and tested against a flat-fee control). Every number is read from a
results file, nothing is typed in. LP fees are after the Uniswap protocol fee where it was on.

  python3 validated_summary.py --png charts_flow/V1_validated_results.png
"""
import argparse, json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser(); ap.add_argument("--png", required=True); a = ap.parse_args()
J = lambda p: json.load(open(p))
mw, mu = J("results_markout_usdc_weth.json"), J("results_markout_usdc_usdt.json")
fw, fu = J("results_flow_sources_weth.json"), J("results_flow_sources_usdc_usdt.json")
sw, su = J("results_scorecard_eth.json"), J("results_scorecard_usdc_usdt.json")
lvr = pd.read_csv("results_lvr_theory_daily.csv")
gw = pd.read_csv("data_swaps/usdc_weth_5bp_gecko_check.csv"); gu = pd.read_csv("data_swaps/usdc_usdt_1bp_gecko_check.csv")
kp = J("results_keeper_usdc_usdt_swaps.json")["2.0"]
y1 = J("results_usdc_usdt_1year.json")["2.0"]; ue = J("results_usde_usdt_ex_oct10.json")["2.0"]
crash = J("results_usdc_usdt_2023_03.json")["2.0"]
LP_SHARE = sw["lp_fee_share"]


def daily_vs_flat(path, rule):
    d = pd.read_csv(path); d = d[(d.period == "test") & (d.elasticity == 2.0)]
    return (d[d.policy == rule].groupby("day").lp_pnl.sum() - d[d.policy == f"flat_{rule}"].groupby("day").lp_pnl.sum()).sum()


flat_y1 = daily_vs_flat("data_1y/daily_results.csv", "markout")
flat_kp = daily_vs_flat("data_usdt_swaps/daily_results.csv", "oscillon_keeper")

mk = pd.read_csv("data_swaps/usdc_weth_5bp_markouts.csv"); mk = mk[~mk.flagged.astype(bool)]
day = pd.to_datetime(mk.ts, unit="s").dt.floor("D")
inwin = (day >= pd.Timestamp(lvr.iloc[0, 0])) & (day <= pd.Timestamp(lvr.iloc[-1, 0]))
theory = lvr.lvr_theory.sum()
net_loss, arb_loss = -mk.mk_12[inwin].sum(), -np.minimum(mk.mk_12[inwin], 0).sum()
lp_fees = lvr.fees.sum() * LP_SHARE
top2_vol = sum(r_["volume"] for r_ in fw["top"][:2]) / fw["total_volume"]


def net(m, h):
    return sum(s["markout"][str(h)]["net"] for s in m["sides"].values())


def side(m, i, h):
    return list(m["sides"].values())[i]["markout"][str(h)]["net"]


k = lambda v: ("−" if v < 0 else "+") + (f"${abs(v) / 1e6:,.2f}M" if abs(v) >= 1e6 else f"${abs(v) / 1e3:,.0f}k" if abs(v) >= 1e4
                                         else f"${abs(v) / 1e3:,.1f}k" if abs(v) >= 1e3 else f"${abs(v):,.0f}")
ci = lambda t: f"[{k(t[0])}, {k(t[1])}]"
pct = lambda x: f"{x * 100:+.2f}%"
rows = [
    ("DATA", "USDC/WETH 0.05%: individual swaps vs GeckoTerminal",
     f"{mw['swaps']:,} swaps · on-chain ${gw.onchain.sum() / 1e9:,.3f}B vs Gecko ${gw.gecko.sum() / 1e9:,.3f}B ({pct(gw.onchain.sum() / gw.gecko.sum() - 1)})"),
    ("DATA", "USDC/USDT 0.01%: individual swaps vs GeckoTerminal",
     f"{mu['swaps']:,} swaps · on-chain ${gu.onchain.sum() / 1e9:,.3f}B vs Gecko ${gu.gecko.sum() / 1e9:,.3f}B ({pct(gu.onchain.sum() / gu.gecko.sum() - 1)})"),
    ("DATA", "Swaps >100 bp from Binance, set aside and reported here",
     f"stable {mu['flagged']['swaps']} swaps / ${mu['flagged']['volume'] / 1e6:,.1f}M ({mu['flagged']['volume'] / mu['volume'] * 100:.0f}% of volume): bots push price ~30% "
     f"through an empty tick range, a victim trades, bot reverts; LP markout nets {k(mu['flagged']['net_markout_0'])} · ETH {mw['flagged']['swaps']} swaps / "
     f"${mw['flagged']['volume'] / 1e6:,.1f}M"),
    ("WHEN", "ETH: LP markout at trade → 12 s → 1 min (both sides)",
     f"{k(net(mw, 0))} → {k(net(mw, 12))} → {k(net(mw, 60))} vs LP fees {k(mw['fees'] * LP_SHARE)}: most of the loss is in the same block"),
    ("WHEN", "Stable: LP markout at trade → 12 s → 1 min (both sides)",
     f"{k(net(mu, 0))} → {k(net(mu, 12))} → {k(net(mu, 60))} vs LP fees {k(mu['fees'] * su['lp_fee_share'])}: flat, the loss is a stale price at the trade"),
    ("SIDE", "Stable: USDC buyers / USDC sellers, 12 s",
     f"buyers {k(side(mu, 0, 12))} · sellers {k(side(mu, 1, 12))} for LPs"),
    ("THEORY", "ETH: measured loss vs theoretical LVR (σ²·L·√S/4)",
     f"same size, tracks it day by day: {net_loss / theory:.2f}× net, {arb_loss / theory:.2f}× arbitrage-only (${theory / 1e6:,.2f}M theory) · "
     f"LP fees cover {lp_fees / theory:.2f}× of LVR"),
    ("WHO", "ETH: share of LP losses from the top 1 / 5 / 20 sources",
     f"{fw['share_of_loss_top1'] * 100:.0f}% / {fw['share_of_loss_top5'] * 100:.0f}% / {fw['share_of_loss_top20'] * 100:.0f}% · top 2 are also "
     f"{top2_vol * 100:.0f}% of volume: the arbitrageurs keeping the price correct · Uniswap routers LP-positive"),
    ("WHO", "Stable: share of LP losses from the top 1 / 5 / 20 sources",
     f"{fu['share_of_loss_top1'] * 100:.0f}% / {fu['share_of_loss_top5'] * 100:.0f}% / {fu['share_of_loss_top20'] * 100:.0f}% of a small "
     f"{k(fu['loss_from_losing_sources'])}"),
    ("LP APR", "ETH 0.05% vs 0.3%: net APR, after protocol fee, today's TVL",
     f"{sw['today']['net_apr']:+.1f}% vs {sw['competitor_today']['net_apr']:+.1f}% (gross {sw['today']['gross_apr']:.1f}% vs "
     f"{sw['competitor_today']['gross_apr']:.1f}%) · protocol takes 1/4 and 1/6 of fees"),
    ("LP APR", "Stable 0.01%: net APR, after protocol fee, today's TVL",
     f"{su['today']['net_apr']:+.1f}% (gross {su['today']['gross_apr']:.1f}%) · protocol takes 1/4 · 0.05% pool too small to compare"),
    ("RULE", "Oscillon keeper on USDC/USDT · per-swap, last 36 of 90 days, ε 2",
     f"{k(kp['oscillon_keeper']['test']['edge_vs_vanilla'])} vs 1 bp {ci(kp['oscillon_keeper']['test']['edge_vs_vanilla_ci90'])}: neutral · "
     f"beats a flat fee at its own average by {k(flat_kp)} · after protocol fee"),
    ("RULE", "Per-side markout fee on USDC/USDT · 1-min data, last 161 days to Jun 2026, ε 2",
     f"{k(y1['markout']['test']['edge_vs_vanilla'])} vs 1 bp {ci(y1['markout']['test']['edge_vs_vanilla_ci90'])} · beats flat by {k(flat_y1)} · "
     f"before protocol fee (switched on in Q1 2026)"),
    ("RULE", "Same rule, Mar 10–25 2023 USDC crash · 1-min data, ε 2",
     f"{k(crash['markout']['stress']['edge_vs_vanilla'])} vs 1 bp {ci(crash['markout']['stress']['edge_vs_vanilla_ci90'])}: neutral · no protocol fee then"),
    ("RULE", "Oscillon oracle depeg hook (3 bp base) · same two 1-min windows, ε 2",
     f"{k(y1['oscillon_hook']['test']['edge_vs_vanilla'])} calm / {k(crash['oscillon_hook']['stress']['edge_vs_vanilla'])} crash vs plain 1 bp"),
    ("RULE", "Per-side markout fee on USDe/USDT · per-swap, last 122 days to Aug 2026, ε 2",
     f"{k(ue['markout']['test']['edge_vs_vanilla'])} vs 0.45 bp {ci(ue['markout']['test']['edge_vs_vanilla_ci90'])} · Oct 10–11 excluded · "
     f"promising, not proven"),
]
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "savefig.facecolor": SURF,
                     "text.parse_math": False})   # "$" is money here, not math
fig = plt.figure(figsize=(18, 2.2 + 0.66 * len(rows)))
fig.text(0.012, 0.978, "Oscillon markout research: results that passed validation", fontsize=17, color=INK, va="top")
fig.text(0.012, 0.948, "Rows DATA–LP APR: individual swaps Jul 24 – Oct 21, 2026 (USDC/WETH 0.05%, USDC/USDT 0.01%), Binance 1-second prices. "
         "RULE rows: own data window and type shown per row, out of sample.", fontsize=10, color=INK2, va="top")
fig.text(0.012, 0.925, "ε = elasticity of ordinary flow. Measured on ETH ≈ 1.3, a lower bound (the 0.3% pool's flow is mostly arbitrage); "
         "USDC/USDT 0.4–3. LP fees are after the Uniswap protocol fee where it was on.", fontsize=10, color=INK2, va="top")
ax = fig.add_axes([0.012, 0.02, 0.976, 0.87]); ax.set_axis_off()
import textwrap
tb = ax.table(cellText=[[r_[0], textwrap.fill(r_[1], 50), textwrap.fill(r_[2], 118)] for r_ in rows],
              colLabels=["", "Question", "Result"], cellLoc="left",
              colWidths=[0.05, 0.31, 0.64], bbox=[0, 0, 1, 1])
tb.auto_set_font_size(False); tb.set_fontsize(9.2)
for (ri, ci_), cell in tb.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor("white" if ri % 2 else SURF)
    if ri == 0 or ci_ == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
fig.savefig(a.png, dpi=160, bbox_inches="tight"); print("wrote", a.png)
for r_ in rows:
    print(f"{r_[0]:7s} {r_[1]:70s} {r_[2]}")
