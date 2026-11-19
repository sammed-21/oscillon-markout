"""
LP-side review of the Fynd ETH/USDG pool: are LPs paid for the risk they take, who bears the loss, which trading flow it comes
from, and what would change it. Reads already-checked results only (nothing is re-derived from chain data here):

  <lp>/results_lp_fynd_positions.csv   position-level LP vs hold, Oct 2 - Nov 13 2026 (checked LP report)
  <lp>/results_lp_fynd_split.json      the same LP vs hold split by trading flow (checked LP report)
  <lp>/data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_events.csv   position events (for transaction senders)
  audit/data/audit_numbers.json        transaction-level re-check of the bot's trades
  out/bot_execution_quality.csv        per bot trade: gap to Binance before and after
  final/data/il_attribution.json       replays: real history / no arbitrage / outside arbitrageur (model)
  out/policy_simulation.csv, final/data/combo_sim.csv   bot-policy replays (model)

Writes lp_review/: LP_WALLET_RETURNS.csv, LP_FLOW_ATTRIBUTION.csv, LP_SCORECARD.csv, LP_REVIEW.md, lp_review.png

  python3 lp_review/build_lp_review.py --root . --lp ../markout-backtest
"""
import argparse, json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True)
a = ap.parse_args()
R = lambda *p: os.path.join(a.root, *p)
O = lambda *p: os.path.join(a.root, "lp_review", *p)
FYND = "0x6c6a40d2d1fc442e281e1f80314fd86516e17127"
short = lambda w: w if w.startswith("via") else f"{w[:6]}…{w[-4:]}"

# ------------------------------------------------------------------ inputs
P = pd.read_csv(os.path.join(a.lp, "results_lp_fynd_positions.csv"))
SP = json.load(open(os.path.join(a.lp, "results_lp_fynd_split.json")))
EV = pd.read_csv(os.path.join(a.lp, "data_swaps", "eth_usdg_ekubo_robinhood_lp_to1113_events.csv"))
AN = json.load(open(R("audit", "data", "audit_numbers.json")))
EQ = pd.read_csv(R("out", "bot_execution_quality.csv"), usecols=["moved_toward_binance", "crossed_binance"])
IA = json.load(open(R("final", "data", "il_attribution.json")))
PS = pd.read_csv(R("out", "policy_simulation.csv")).set_index("policy")
CS = pd.read_csv(R("final", "data", "combo_sim.csv")).set_index("policy")

t0, t1 = pd.to_datetime(P.start_utc.min()), pd.to_datetime(P.end_utc.max())
DAYS = (t1 - t0).total_seconds() / 86400
P["width_pct"] = 100 * (P.range_high / P.range_low - 1)
P["hours"] = 24 * P.days
P["group"] = np.where(P.owner.str.lower() == FYND, "0x6c6a…7127 (Fynd's, per Edouard)", "all other LPs (ownership unresolved)")

# ------------------------------------------------------------------ 1. wallet-level returns
senders = EV[EV.event == "position"].groupby("owner").tx_from.agg(lambda s: set(s.str.lower()))


def wmedian(x, w):
    o = np.argsort(x.values); c = np.cumsum(w.values[o])
    return float(x.values[o][np.searchsorted(c, c[-1] / 2)])


def summarise(d):
    cd = d.capital_days_usd.sum()
    net, fees, il = d.lp_minus_hold_usd.sum(), d.fees_usd.sum(), d.il_usd.sum()
    per = lambda x: 1000 * 30 * x / cd                                       # USD per $1,000 of capital per 30 days
    narrow = d[d.width_pct < 1].capital_days_usd.sum() / cd
    return pd.Series({
        "positions": len(d), "open_at_snapshot": int(d.open.sum()),
        "first_deposit_utc": d.start_utc.min(), "last_activity_utc": d.end_utc.max(),
        "capital_deposited_usd_sum": d.cost_usd.sum(),                        # sum of deposits; recycled capital counts each time
        "capital_days_usd": cd, "avg_capital_usd_over_period": cd / DAYS,
        "fees_usd": fees, "il_usd": il, "lp_minus_hold_usd": net,
        "fee_coverage_of_il": fees / -il if il < 0 else np.nan,
        "return_vs_hold_over_period": net / (cd / DAYS),
        "per_1000_per_30d_fees": per(fees), "per_1000_per_30d_il": per(il), "per_1000_per_30d_net": per(net),
        "lp_pnl_usd": d.lp_pnl_usd.sum(), "hold_pnl_usd": d.hold_pnl_usd.sum(),
        "median_range_width_pct": d.width_pct.median(), "capital_share_in_ranges_under_1pct": narrow,
        "median_position_hours": d.hours.median(),
        "capital_weighted_median_width_pct": wmedian(d.width_pct, d.capital_days_usd),
        "capital_weighted_median_hours": wmedian(d.hours, d.capital_days_usd),
        "in_range_share_capital_weighted": np.average(d.in_range_share, weights=d.capital_days_usd)})


W = P.groupby("owner").apply(summarise, include_groups=False)
W.insert(0, "wallet", [short(w) for w in W.index])
W.insert(1, "group", ["Fynd's, per Edouard (Nov 12)" if w.lower() == FYND else "unresolved" for w in W.index])
W["shares_a_sender_with"] = [", ".join(short(o) for o in senders.index if o != w and senders.get(w, set()) & senders[o]) for w in W.index]
G = P.groupby("group").apply(summarise, include_groups=False)
ALL = summarise(P)
G.loc["all LPs"] = ALL
W = W.sort_values("lp_minus_hold_usd")
Wout = pd.concat([W.reset_index(drop=True),
                  G.reset_index().rename(columns={"group": "wallet"}).assign(group="total")], ignore_index=True)
Wout.loc[Wout.avg_capital_usd_over_period < 50, "note"] = "under $50 average capital: per-$1,000 figures are noise"
Wout.to_csv(O("LP_WALLET_RETURNS.csv"), index=False, float_format="%.6g")
P["width_bucket"] = pd.cut(P.width_pct, [0, 1, 3, 10, 30, np.inf], labels=["under 1%", "1–3%", "3–10%", "10–30%", "over 30% / full range"])
WB = P.groupby(["group", "width_bucket"], observed=True).apply(
    lambda d: pd.Series({"positions": len(d), "capital_days_usd": d.capital_days_usd.sum(), "median_hours": d.hours.median(),
                         "fees_usd": d.fees_usd.sum(), "il_usd": d.il_usd.sum(), "lp_minus_hold_usd": d.lp_minus_hold_usd.sum()}),
    include_groups=False).reset_index()
WB["capital_share_of_group"] = WB.capital_days_usd / WB.groupby("group").capital_days_usd.transform("sum")
WB["per_1000_per_30d_net"] = 1000 * 30 * WB.lp_minus_hold_usd / WB.capital_days_usd
WB.to_csv(O("LP_RANGE_WIDTH.csv"), index=False, float_format="%.6g")

# reconciliation with the checked report
assert abs(ALL.lp_minus_hold_usd - SP["lp_minus_hold"]) < 1e-6
assert abs(ALL.fees_usd + ALL.il_usd - ALL.lp_minus_hold_usd) < 1e-6

# ------------------------------------------------------------------ 2. LP result by trading flow (checked LP report)
rows = []
for k, nm in [("bot", "Fynd's bot (0x4abf…84a2 via 0x7ea0…acc7)"), ("other", "everyone else (routers, traders)")]:
    s = SP[k]
    rows.append({"flow": nm, "swaps": s["swaps"], "volume_usd": s["volume"], "volume_share": s["volume"] / SP["all"]["volume"],
                 "lp_fee_usd": s["fee"], "lp_fee_bp": s["fee_bp"], "lp_loss_before_fees_12s_usd": -s["loss_12s"],
                 "lp_loss_before_fees_12s_bp": s["loss_bp"], "fee_coverage": s["fee"] / s["loss_12s"],
                 "lp_net_12s_usd": s["lp_net"], "per_1000_per_30d": SP["per_1000_per_30d"][k + "_wallet_swaps" if k == "bot" else "other_swaps"],
                 "ci95_per_1000_per_30d": SP["ci95_per_1000_per_30d"][k + "_lp_net"],
                 "breakeven_lp_fee_bp": s["loss_bp"]})
rows.append({"flow": "later price moves (after 12 s, to each position's end)", "lp_net_12s_usd": SP["drift"],
             "per_1000_per_30d": SP["per_1000_per_30d"]["later_price_moves"]})
rows.append({"flow": "total = LP vs hold", "swaps": SP["all"]["swaps"], "volume_usd": SP["all"]["volume"], "volume_share": 1.0,
             "lp_fee_usd": SP["all"]["fee"], "lp_fee_bp": SP["all"]["fee_bp"], "lp_loss_before_fees_12s_usd": -SP["all"]["loss_12s"],
             "lp_loss_before_fees_12s_bp": SP["all"]["loss_bp"], "fee_coverage": SP["all"]["fee"] / SP["all"]["loss_12s"],
             "lp_net_12s_usd": SP["lp_minus_hold"], "per_1000_per_30d": sum(SP["per_1000_per_30d"].values()),
             "ci95_per_1000_per_30d": SP["ci95_per_1000_per_30d"]["lp_net"],
             "breakeven_lp_fee_bp": SP["fee_sensitivity"]["breakeven_fee_bp_lp_minus_hold"]})
FL = pd.DataFrame(rows)
assert abs(FL.lp_net_12s_usd.iloc[:3].sum() - SP["lp_minus_hold"]) < 1e-6
FL.to_csv(O("LP_FLOW_ATTRIBUTION.csv"), index=False, float_format="%.6g")
fb, fo = FL.iloc[0], FL.iloc[1]

# ------------------------------------------------------------------ 3. bot, from the transaction-level re-check
fx = AN["fee_excess"]["usdg"]                                              # USDG wrongly counted as Fynd fee (16 trades)
bot = {"trades": AN["n_txs"], "complete": AN["n_complete"],
       "gross": AN["bot_gross_exec_complete"], "gas": AN["gas_usd_complete"], "net": AN["bot_net_exec_complete"],
       "lp_net_12s": -AN["lp_net_12s_complete"] + 0.8 * fx, "hedge_12s": AN["hedge_result_12s_complete"] + fx,
       "router_12s": AN["router_12s_complete"], "fynd20_12s": AN["fynd_protocol_12s_complete"] - 0.2 * fx,
       "bot_net_12s": AN["bot_gross_12s_complete"] - AN["gas_usd_complete"],
       "lp_net_exec": -AN["lp_net_exec_complete"] + 0.8 * fx,
       "toward": EQ.moved_toward_binance.mean(), "crossed": EQ.crossed_binance.mean()}
split = bot["hedge_12s"] + AN["gas_usd_complete"] + bot["bot_net_12s"] + bot["router_12s"] + bot["fynd20_12s"]
assert abs(split - bot["lp_net_12s"]) < 0.05, (split, bot["lp_net_12s"])

# ------------------------------------------------------------------ 4. what would change it (models)
rp = IA["replays"]
rep = {k: {"ex": rp[k]["lp_vs_hold_ex_fees_usd"], "fees": sum(rp[k]["lp_fees_usd"].values()), "net": rp[k]["lp_vs_hold_usd"],
           "gap": rp[k]["mean_abs_gap_bp"], "unfilled": rp[k]["external_eth_unfilled"]} for k in ("REAL", "OUTSIDE", "NO_BOT")}
pol = [("A", PS.loc["A"], "today's rules (model baseline)"),
       ("H1", PS.loc["H1"], "hedge at 1 bp instead of 3.9 bp"),
       ("Hdeep+D4", CS.loc["Hdeep+D4"], "hedge at 1 bp, bot pays 4 bp to the pool"),
       ("A0+Hdeep+D4", CS.loc["A0+Hdeep+D4"], "same, bot always on"),
       ("D19.8", PS.loc["D19.8"], "bot pays the normal 19.8 bp"),
       ("D0", PS.loc["D0"], "bot pays nothing")]

# ------------------------------------------------------------------ scorecard
f = ALL
SC = pd.DataFrame([
    ("LP vs holding, all LPs", f.lp_minus_hold_usd, "USD", "calculated from on-chain positions (checked report)"),
    ("  fees to LPs (80% share)", f.fees_usd, "USD", "on-chain"),
    ("  impermanent loss", f.il_usd, "USD", "calculated"),
    ("average capital", f.avg_capital_usd_over_period, "USD", "calculated"),
    ("LP vs holding per $1,000 per 30 days", f.per_1000_per_30d_net, "USD", "calculated"),
    ("  95% range", str([round(x) for x in SP["ci95_per_1000_per_30d"]["lp_net"]]), "USD", "calculated (day resampling)"),
    ("fees as share of impermanent loss", f.fee_coverage_of_il, "ratio", "calculated"),
    ("LPs' USD P&L (not vs holding)", f.lp_pnl_usd, "USD", "calculated"),
    ("share of LP shortfall on 0x6c6a…7127", G.lp_minus_hold_usd.iloc[0] / f.lp_minus_hold_usd if G.index[0].startswith("0x6c6a") else np.nan, "ratio", "calculated; ownership per Edouard"),
    ("other LPs per $1,000 per 30 days", G.loc["all other LPs (ownership unresolved)"].per_1000_per_30d_net, "USD", "calculated"),
    ("LP net on bot flow, 12 s", fb.lp_net_12s_usd, "USD", "calculated (checked report)"),
    ("  fee coverage on bot flow", fb.fee_coverage, "ratio", "calculated"),
    ("  fee bot pays vs fee LPs need to break even", f"{fb.lp_fee_bp:.1f} bp vs {fb.breakeven_lp_fee_bp:.1f} bp", "bp", "calculated"),
    ("LP net on everyone else's flow, 12 s", fo.lp_net_12s_usd, "USD", "calculated (95% range includes zero)"),
    ("  fee coverage on other flow", fo.fee_coverage, "ratio", "calculated"),
    ("bot gross / gas / net", f"{bot['gross']:.0f} / {bot['gas']:.0f} / {bot['net']:.0f}", "USD", "on-chain token flows + receipts"),
    ("bot trades moving pool toward Binance", bot["toward"], "ratio", "calculated"),
    ("replay: LP vs hold, real / outside arb / no arb", f"{rep['REAL']['net']:.0f} / {rep['OUTSIDE']['net']:.0f} / {rep['NO_BOT']['net']:.0f}", "USD", "model"),
], columns=["metric", "value", "unit", "evidence"])
SC.to_csv(O("LP_SCORECARD.csv"), index=False)

# ------------------------------------------------------------------ chart
BG, TEXT, TEXT2, MUTED, GRID = "#fcfcfb", "#1f1f1e", "#4a4a47", "#7a7a75", "#e6e5e0"
LOSS, FEE = "#d95926", "#2a7ab0"
plt.rcParams.update({"font.size": 10})
fig = plt.figure(figsize=(11, 9.6), dpi=150, facecolor=BG)


def style(ax, fmt):
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=TEXT2, length=0, labelsize=10)
    ax.xaxis.set_major_formatter(fmt)
    ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    ax.axvline(0, color=TEXT2, lw=0.8)


def pair(ax, y0, loss, fee, net, fmt_v, net_txt, sub, x_off):
    ax.barh(y0 + 0.17, loss, color=LOSS, height=0.32, edgecolor=BG, lw=1.5)
    ax.barh(y0 - 0.17, fee, color=FEE, height=0.32, edgecolor=BG, lw=1.5)
    ax.text(loss - x_off, y0 + 0.17, fmt_v(loss), va="center", ha="right", color=TEXT2, fontsize=9.5, parse_math=False)
    ax.text(fee + x_off, y0 - 0.17, fmt_v(fee), va="center", ha="left", color=TEXT2, fontsize=9.5, parse_math=False)
    tr = ax.get_yaxis_transform()
    ax.text(1.03, y0 + 0.2, net_txt, transform=tr, va="center", ha="left", color=TEXT, fontsize=11, fontweight="bold", parse_math=False)
    ax.text(1.03, y0 - 0.2, sub, transform=tr, va="center", ha="left", color=MUTED, fontsize=8.5, linespacing=1.4, parse_math=False)


usd = lambda v: f"−${-v:,.0f}" if v < 0 else f"+${v:,.0f}"
# top: per $1,000 per 30 days by owner group
ax = fig.add_axes([0.27, 0.6, 0.48, 0.25], facecolor=BG)
grp = [("0x6c6a…7127\n(Fynd's, per Edouard)", G.loc["0x6c6a…7127 (Fynd's, per Edouard)"]),
       ("All other LPs\n(ownership unresolved)", G.loc["all other LPs (ownership unresolved)"]), ("All LPs", ALL)]
for y0, (nm, s) in zip([2, 1, 0], grp):
    pair(ax, y0, s.per_1000_per_30d_il, s.per_1000_per_30d_fees, None, usd,
         f"net {usd(s.per_1000_per_30d_net)}  ({s.per_1000_per_30d_net / 10:+.1f}%)".replace("(-", "(−"),
         f"{int(s.positions)} positions, avg capital ${s.avg_capital_usd_over_period:,.0f}\nfees cover {s.fee_coverage_of_il:.0%} of the loss", 6)
ax.set_yticks([2, 1, 0]); ax.set_yticklabels([g[0] for g in grp])
style(ax, lambda v, _: usd(v) if v else "$0"); ax.set_xlim(-420, 170); ax.set_ylim(-0.6, 2.6)
fig.text(0.03, 0.955, f"LPs earned fees worth {f.fee_coverage_of_il:.0%} of their impermanent loss: {usd(f.per_1000_per_30d_net)} per $1,000 a month vs holding",
         color=TEXT, fontsize=14, fontweight="bold", parse_math=False)
fig.text(0.03, 0.925, f"Fynd ETH/USDG, {t0:%b %-d} – {t1:%b %-d %Y} ({DAYS:.0f} days), {len(P)} positions. Per $1,000 of capital per 30 days, LPs vs holding their deposited tokens.",
         color=MUTED, fontsize=9.5, parse_math=False)
fig.text(0.03, 0.902, f"Total: fees {usd(f.fees_usd)}, impermanent loss {usd(f.il_usd)}, net {usd(f.lp_minus_hold_usd)} on ${f.avg_capital_usd_over_period:,.0f} average capital.",
         color=MUTED, fontsize=9.5, parse_math=False)
lx = 0.03
for col, lab in [(LOSS, "loss before fees"), (FEE, "fees paid to LPs (80% share)")]:
    fig.patches.append(matplotlib.patches.Rectangle((lx, 0.873), 0.012, 0.012, color=col, transform=fig.transFigure))
    fig.text(lx + 0.017, 0.873, lab, color=TEXT2, fontsize=9.5, va="bottom"); lx += 0.2

# bottom: by trading flow
ax2 = fig.add_axes([0.27, 0.13, 0.48, 0.27], facecolor=BG)
fl = [("Fynd's bot\n(" + f"{fb.volume_share:.0%} of volume)", fb), ("Everyone else\n(" + f"{fo.volume_share:.0%} of volume)", fo)]
for y0, (nm, s) in zip([1, 0], fl):
    pair(ax2, y0, s.lp_loss_before_fees_12s_usd, s.lp_fee_usd, None, usd, f"net {usd(s.lp_net_12s_usd)}",
         f"LPs paid {s.lp_fee_bp:.1f} bp, lost {s.lp_loss_before_fees_12s_bp:.1f} bp\nfees cover {s.fee_coverage:.0%}", 80)
ax2.set_yticks([1, 0]); ax2.set_yticklabels([x[0] for x in fl])
style(ax2, lambda v, _: usd(v) if v else "$0"); ax2.set_xlim(-5200, 2400); ax2.set_ylim(-0.6, 1.6)
fig.text(0.03, 0.495, f"By trading flow: the bot pays LPs {fb.lp_fee_bp:.1f} bp a trade; they need about {fb.breakeven_lp_fee_bp:.0f} bp to break even",
         color=TEXT, fontsize=14, fontweight="bold", parse_math=False)
fig.text(0.03, 0.467, "LPs' loss on each trade against Binance 12 s later, and the fees that trade paid them. Later price moves add "
         f"{usd(SP['drift'])}; the three sum to {usd(SP['lp_minus_hold'])}.", color=MUTED, fontsize=9.5, parse_math=False)
fig.text(0.03, 0.035, f"The loss on the bot's trades is LVR any arbitrageur would realize (replay: about the same before fees). The bot kept ${bot['net']:,.0f} after gas;\n"
         "most went to the pools it hedged on, gas, routers and the 20% fee share. Source: lp_review/build_lp_review.py, LP_REVIEW.md.",
         color=MUTED, fontsize=8.3, linespacing=1.5, parse_math=False)
fig.savefig(O("lp_review.png"), facecolor=BG)

# ------------------------------------------------------------------ written review
g6, go = G.loc["0x6c6a…7127 (Fynd's, per Edouard)"], G.loc["all other LPs (ownership unresolved)"]
pb, pl = SP["periods"]["before"], SP["periods"]["last_15_days"]
pct = lambda v: f"{v:+.1%}".replace("-", "−")
wl = "\n".join(f"| `{r.wallet if not r.wallet.startswith('via') else 'via ' + short(r.wallet[4:])}` | {r.group} | {r.positions:.0f} | "
               f"${r.avg_capital_usd_over_period:,.0f} | {usd(r.fees_usd)} | {usd(r.il_usd)} | **{usd(r.lp_minus_hold_usd)}** | "
               f"{usd(r.per_1000_per_30d_net) if r.avg_capital_usd_over_period >= 50 else 'n/m'} | {r.fee_coverage_of_il:.0%} | "
               f"{r.capital_weighted_median_width_pct:.1f}% | {r.capital_weighted_median_hours:.0f} | {r.shares_a_sender_with or ''} |"
               for r in W.itertuples())
wbl = "\n".join(f"| {'`0x6c6a…7127`' if r.group.startswith('0x6c6a') else 'other LPs'} | {r.width_bucket} | {r.positions:.0f} | "
                f"{r.capital_share_of_group:.0%} | {r.median_hours:.0f} | {usd(r.fees_usd)} | {usd(r.il_usd)} | **{usd(r.lp_minus_hold_usd)}** | "
                f"{usd(r.per_1000_per_30d_net) if r.capital_days_usd >= 50 * DAYS else 'n/m'} |" for r in WB.itertuples())
w6 = WB[(WB.group == g6.name) & (WB.width_bucket == "1–3%")].iloc[0]
wo = WB[(WB.group == go.name) & (WB.width_bucket == "10–30%")].iloc[0]
pl_rows = "\n".join(f"| {d} | {usd(r.lp_net_trading_12s_usd)} | {usd(r.bot_net_usd)} | {r.mean_abs_gap_bp:.1f} bp |" for k, r, d in pol)

md = f"""# Fynd ETH/USDG: LP returns review

{t0:%b %-d} – {t1:%b %-d %Y} ({DAYS:.2f} days), {len(P)} LP positions. Built by `lp_review/build_lp_review.py` from the checked LP
report, the transaction-level re-check of the bot's trades (`audit/`) and the replays (`final/`). Evidence labels: **on-chain** (read
from logs or receipts), **calculated** (arithmetic on on-chain data with a stated price reference), **model** (replay; compare rows with
each other, not with history), **unconfirmed** (needs Fynd).

All "vs holding" figures compare each position with simply holding the tokens it deposited, valued at Binance at the position's end.

## 1. Are LPs paid for the risk they take?

**No, not in this period.** Fees covered **{f.fee_coverage_of_il:.1%}** of impermanent loss.

| | USD | per $1,000 per 30 days |
|---|---|---|
| fees to LPs (their 80% share) — *on-chain* | {usd(f.fees_usd)} | {usd(f.per_1000_per_30d_fees)} |
| impermanent loss — *calculated* | {usd(f.il_usd)} | {usd(f.per_1000_per_30d_il)} |
| **LPs vs holding** — *calculated* | **{usd(f.lp_minus_hold_usd)}** | **{usd(f.per_1000_per_30d_net)}** ({pct(f.per_1000_per_30d_net / 1000)}) |
| 95% range (day resampling) | | {usd(SP['ci95_per_1000_per_30d']['lp_net'][0])} to {usd(SP['ci95_per_1000_per_30d']['lp_net'][1])} |

- Average capital ${f.avg_capital_usd_over_period:,.0f} (capital-days ÷ {DAYS:.2f}); {pct(f.return_vs_hold_over_period)} vs holding over the period.
- In plain USD (not vs holding) LPs were {usd(f.lp_pnl_usd)}; holding would have been {usd(f.hold_pnl_usd)}. ETH fell over the period, so
  both lost money; LPing lost more.
- Trend (LP net on trades, per day): {usd(pb['lp_net_per_day'])} a day to Oct 28, {usd(pl['lp_net_per_day'])} a day after, with fees
  per day down from ${pb['fees_per_day']:.0f} to ${pl['fees_per_day']:.0f} and ETH volatility up ({pb['eth_vol_ann_pct_mean']:.0f}% → {pl['eth_vol_ann_pct_mean']:.0f}% annualised).
  Not a clear improvement.

## 2. Who bears the loss?

**One wallet.** `0x6c6a…7127` (Fynd's, per Edouard on Nov 12) holds {g6.positions:.0f} of {len(P)} positions and
**{g6.lp_minus_hold_usd / f.lp_minus_hold_usd:.0%}** of the shortfall.

| group | positions | avg capital | fees | IL | vs holding | per $1,000 / 30 d | fees cover | typical range width* | typical hours open* |
|---|---|---|---|---|---|---|---|---|---|
| `0x6c6a…7127` | {g6.positions:.0f} | ${g6.avg_capital_usd_over_period:,.0f} | {usd(g6.fees_usd)} | {usd(g6.il_usd)} | **{usd(g6.lp_minus_hold_usd)}** | {usd(g6.per_1000_per_30d_net)} | {g6.fee_coverage_of_il:.0%} | {g6.capital_weighted_median_width_pct:.1f}% | {g6.capital_weighted_median_hours:.0f} |
| all other LPs | {go.positions:.0f} | ${go.avg_capital_usd_over_period:,.0f} | {usd(go.fees_usd)} | {usd(go.il_usd)} | **{usd(go.lp_minus_hold_usd)}** | {usd(go.per_1000_per_30d_net)} | {go.fee_coverage_of_il:.0%} | {go.capital_weighted_median_width_pct:.1f}% | {go.capital_weighted_median_hours:.0f} |

\* capital-weighted median: the width and duration that the typical dollar sat in.

**The clearest difference is range width.** {w6.capital_share_of_group:.0%} of `0x6c6a…7127`'s capital sat in 1–3% ranges (median
position open ~{w6.median_hours:.0f} hours); that bucket is {usd(w6.lp_minus_hold_usd)} of its {usd(g6.lp_minus_hold_usd)}. {wo.capital_share_of_group:.0%} of the
other LPs' capital sat in 10–30% ranges held ~{wo.median_hours:.0f} hours, losing {usd(wo.per_1000_per_30d_net)} per $1,000 per 30 days
against {usd(g6.per_1000_per_30d_net)} for `0x6c6a…7127`. A narrower range earns more fees per dollar while the price is inside it but
takes proportionally more impermanent loss, and every reset locks the loss in. In this period the extra fees did not pay for it.
The other LPs' narrow-range buckets hold under 5% of their capital, too little to test this within one wallet group; timing and
size also differ between the groups. Treat it as the leading explanation, not a proven cause.

By range width (`LP_RANGE_WIDTH.csv`):

| LP | range width | positions | share of capital | median hours | fees | IL | vs holding | per $1,000 / 30 d |
|---|---|---|---|---|---|---|---|---|
{wbl}

By wallet (`LP_WALLET_RETURNS.csv`):

| wallet | ownership | positions | avg capital | fees | IL | vs holding | per $1,000 / 30 d | fees cover | typical width* | typical hours* | shares a tx sender with |
|---|---|---|---|---|---|---|---|---|---|---|---|
{wl}

n/m: under $50 average capital, too small for a per-$1,000 figure.

*Unconfirmed:* whether `0x6c6a…7127` is Fynd's own liquidity (on chain it acts as an LP and sends no bot trades), and whether
wallets sharing a transaction sender are one LP.

## 3. Which trading flow does the loss come from?

**Mostly the bot's flow, because it pays LPs almost nothing for it.** The checked report splits the {usd(SP['lp_minus_hold'])}
exactly into three parts (`LP_FLOW_ATTRIBUTION.csv`):

| flow | volume | fee LPs got | LPs' loss before fees (12 s) | fees cover | LP net | per $1,000 / 30 d (95% range) |
|---|---|---|---|---|---|---|
| Fynd's bot | ${fb.volume_usd / 1e6:.2f}M ({fb.volume_share:.0%}) | {fb.lp_fee_bp:.1f} bp, {usd(fb.lp_fee_usd)} | {fb.lp_loss_before_fees_12s_bp:.1f} bp, {usd(fb.lp_loss_before_fees_12s_usd)} | {fb.fee_coverage:.0%} | **{usd(fb.lp_net_12s_usd)}** | {usd(fb.per_1000_per_30d)} ({usd(fb.ci95_per_1000_per_30d[0])} to {usd(fb.ci95_per_1000_per_30d[1])}) |
| everyone else | ${fo.volume_usd / 1e6:.2f}M ({fo.volume_share:.0%}) | {fo.lp_fee_bp:.1f} bp, {usd(fo.lp_fee_usd)} | {fo.lp_loss_before_fees_12s_bp:.1f} bp, {usd(fo.lp_loss_before_fees_12s_usd)} | {fo.fee_coverage:.0%} | **{usd(fo.lp_net_12s_usd)}** | {usd(fo.per_1000_per_30d)} ({usd(fo.ci95_per_1000_per_30d[0])} to {usd(fo.ci95_per_1000_per_30d[1])}) |
| later price moves | | | | | {usd(SP['drift'])} | |
| **total** | | | | | **{usd(SP['lp_minus_hold'])}** | |

- Everyone else's flow roughly pays for itself (its 95% range includes zero). The bot's flow does not: it pays {fb.lp_fee_bp:.1f} bp,
  LPs would need about **{fb.breakeven_lp_fee_bp:.1f} bp** to break even on it.
- *Calculated.* The transaction-level re-check of {bot['complete']:,} of the bot's {bot['trades']:,} trades gives {usd(-bot['lp_net_12s'])}
  (12 s) and {usd(-bot['lp_net_exec'])} (at execution); the figure depends on the valuation time, the bot's profit does not.
- This is LVR: LPs lose it to whoever brings the pool back to the market. Before fees an outside arbitrageur realizes about the same
  ({usd(rep['OUTSIDE']['ex'])} vs {usd(rep['REAL']['ex'])} in the replay, *model*). It is **not** the bot's profit.

## 4. Is the rebalancing efficient?

**It aligns the pool, but most of what LPs give up on its trades goes to the pools it hedges on; the bot keeps about 9%.**

- Moves the pool toward Binance on **{bot['toward']:.1%}** of trades (*calculated*).
- Bot: {usd(bot['gross'])} before gas, gas {usd(-bot['gas'])}, **{usd(bot['net'])} after gas** (*on-chain token flows and receipts*;
  matches the bot contract's own profit events).
- Where the ${bot['lp_net_12s']:,.0f} LPs gave up on the bot's trades went (12 s, *calculated*; adds up to the cent):

  | to | USD | share |
  |---|---|---|
  | pools the bot hedged on (their swap fees ~$899, price impact ~$472, price differences and moves) | ${bot['hedge_12s']:,.0f} | {bot['hedge_12s'] / bot['lp_net_12s']:.0%} |
  | gas | ${AN['gas_usd_complete']:,.0f} | {AN['gas_usd_complete'] / bot['lp_net_12s']:.0%} |
  | bot, after gas | ${bot['bot_net_12s']:,.0f} | {bot['bot_net_12s'] / bot['lp_net_12s']:.0%} |
  | routers | ${bot['router_12s']:,.0f} | {bot['router_12s'] / bot['lp_net_12s']:.0%} |
  | 20% fee share (recipient *unconfirmed*) | ${bot['fynd20_12s']:,.0f} | {bot['fynd20_12s'] / bot['lp_net_12s']:.0%} |

  The pools' figure is not their profit: it is valued at Binance 12 s later and includes price moves.

## 5. What would improve LP returns? (*model*)

Replays of the same month; compare rows with each other. Higher fees help LPs but leave the pool further from the market:

| replay | LPs before fees | fees to LPs | LPs vs holding | gap to market | unfilled orders |
|---|---|---|---|---|---|
| real history (Fynd's bot arbitrages) | {usd(rep['REAL']['ex'])} | {usd(rep['REAL']['fees'])} | {usd(rep['REAL']['net'])} | {rep['REAL']['gap']:.0f} bp | {rep['REAL']['unfilled']:.0f} ETH |
| outside arbitrageur at the normal fee | {usd(rep['OUTSIDE']['ex'])} | {usd(rep['OUTSIDE']['fees'])} | {usd(rep['OUTSIDE']['net'])} | {rep['OUTSIDE']['gap']:.0f} bp | {rep['OUTSIDE']['unfilled']:.0f} ETH |
| no arbitrage at all (not realistic) | {usd(rep['NO_BOT']['ex'])} | {usd(rep['NO_BOT']['fees'])} | {usd(rep['NO_BOT']['net'])} | {rep['NO_BOT']['gap']:.0f} bp | {rep['NO_BOT']['unfilled']:.0f} ETH |

Bot-policy replays (`final/MECHANISM_RECOMMENDATIONS.md`; this model's bot earns more than the real one):

| policy | LPs' trading net (12 s) | bot net | gap to market |
|---|---|---|---|
{pl_rows}

The lever that helps everyone is **cheaper hedging** (the deepest on-chain pool costs ~0.3 bp vs ~4.3 bp today). Only then raise
the bot's fee to 3–4 bp: without cheaper hedging a higher fee makes the bot trade less and the pool staler. Two LP-side levers need
no mechanism change: **wider ranges and fewer resets** for `0x6c6a…7127` (§2; not replayed), and the protocol's 20% (giving it to LPs is a transfer, not a fix).

## Not established

- Who owns `0x6c6a…7127` and the other LP wallets (Edouard's Nov 12 statement is the only source for `0x6c6a…7127`).
- Where the 20% fee share goes.
- Gas on the bot wallet's 844 other transactions (~$13–15, estimated).
- How traders and routers would react to any change (replays hold them fixed).
"""
open(O("LP_REVIEW.md"), "w").write(md)
print(f"wrote lp_review/: {len(Wout)} wallet rows, flows sum {FL.lp_net_12s_usd.iloc[:3].sum():.2f}, "
      f"bot split {split:.2f} vs {bot['lp_net_12s']:.2f}")
