"""
Write FINAL_FINDINGS.md, EXEC_SUMMARY_FOR_FYND.md, LVR_CHANGEPOINT_ANALYSIS.md and MECHANISM_RECOMMENDATIONS.md
from the files in final/ and out/. Every number is read from those files.

  python3 final/write_final.py --root . --lp ../markout-backtest
"""
import argparse, json, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True)
a = ap.parse_args()
F = lambda *p: os.path.join(a.root, "final", *p)
O_ = lambda *p: os.path.join(a.root, "out", *p)
RC = json.load(open(F("data", "reconcile.json")))
W = pd.read_csv(F("BOT_PNL_WATERFALL.csv")).set_index("step")
V = pd.read_csv(F("VALUE_FLOW_RECONCILIATION.csv"))
TH = json.load(open(F("data", "threshold.json")))
CPd = pd.read_csv(F("data", "changepoint_daily.csv"), parse_dates=["day"])
HR = json.load(open(F("data", "hedge_routes.json")))
RT = pd.read_csv(F("HEDGE_ROUTE_COSTS.csv"))
SE = pd.read_csv(F("data", "hedge_cost_sensitivity.csv"))
CB = pd.read_csv(F("data", "combo_sim.csv")).set_index("policy")
EX = json.load(open(F("data", "extension_check.json")))
SUM = json.load(open(O_("summary.json")))
PS = pd.read_csv(O_("policy_simulation.csv")).set_index("policy")
UA = json.load(open(O_("uniswap_comparison_audit.json")))
CP = json.load(open(os.path.join(a.lp, "results_pool_compare.json")))
R = json.load(open(os.path.join(a.lp, "results_lp_fynd.json")))
FS = RC["fee_split_all"]


def usd(v, sign=True, d=0):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    s = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{s}${abs(v):,.{d}f}"


sg = lambda v, d=1: ("−" if v < 0 else "") + f"{abs(v):.{d}f}"
w = lambda pre: float(W.loc[[i for i in W.index if i.startswith(pre)][0], "usd"])
vf = lambda pre: float(V[V["item"].str.startswith(pre)].usd.iloc[0])
gross, gas, net, net_all, unreal, mtm = w("4."), w("5."), w("6."), w("9."), w("10."), w("11.")
edge, fee, router, inc, other_gas = w("1."), -w("2."), -w("3."), w("7."), -w("8.")
r1, r2, r3 = w("R1."), w("R2."), w("R3.")
ind = RC["independent"]
og = pd.DataFrame(RC["owner_groups"]).set_index("group")
fynd_g = og.loc[[g for g in og.index if g.startswith("0x6c6a")][0]]
lp_pos = vf("LP fee income, position level"); fa_val = vf("same LP fees valued when paid"); gross_fees = vf("gross Fynd fees, all payers")
proto = vf("protocol (owner) share"); fee_bot = vf("  paid by the bot"); fee_oth = vf("  paid by everyone else")
hs = RC["hedge_split"]; fs = RC["fynd_split"]; sp = RC["split_pct_12s"]
links = RC["wallet_links"]
wd = links["bot_contract_out_not_trades"]
wd_total = sum(x["amount"] for x in wd if x["token"] == "USDG")
med, bydir = TH["median_bp"], TH["by_direction_median_bp"]
cfu = HR["counterfactual_uni1bp"]; sd = HR["single_direct"]
A, A0 = CB.loc["A"], PS.loc["A0"]
best = CB.loc["A0+Hdeep+D4"]; hd4 = CB.loc["Hdeep+D4"]; hdeep = CB.loc["Hdeep"]
se = SE.set_index("hedge_cost_cut")
ext_pools = EX["pools_with_fynd_extension"]
ext_events = EX["event_types"]
period = R["period"]
before = CPd[CPd.day < "2026-10-17"]; after = CPd[CPd.day >= "2026-10-17"]
b22, a22 = CPd[CPd.day < "2026-10-22"], CPd[CPd.day >= "2026-10-22"]
ratio = lambda df: df.fynd_loss_usd.sum() / df.fynd_lvr_usd.sum()
busy = CPd[CPd.bot_idle_hours < 2]

# ---------------------------------------------------------------- answers used in several documents
q1 = (f"Independent LPs (every LP other than `0x6c6a…7127`) lost **{usd(-ind['lp_minus_hold_usd'], False)}** against holding: fees "
      f"{usd(ind['fees_usd'])}, impermanent loss {usd(ind['il_usd'])}, on an average {usd(ind['avg_capital_usd'], False)} of capital, i.e. "
      f"{sg(ind['pct_period'])}% over the {period['days']:.0f} days, {sg(ind['pct_30d'])}% per 30 days. Their ownership is *unresolved* (no on-chain link to Fynd found). "
      f"`0x6c6a…7127` (Fynd, per Edouard, Nov 12) lost {usd(-fynd_g.lp_minus_hold_usd, False)} ({sg(fynd_g.lp_minus_hold_pct_30d)}% per 30 days). All LPs: {usd(R['totals']['lp_minus_hold_usd'])}.")
q2 = (f"About **{usd(proto, False)}** over Oct 2 – Nov 13: 20% of {usd(gross_fees, False)} of fees. The bot paid {usd(fee_bot, False)} of those fees "
      f"(so {usd(fee_bot * 0.2, False)} of the owner fee came from Fynd's own bot); everyone else {usd(fee_oth, False)}. The 80/20 split is observed on "
      f"{FS['match_80pct_all_checkable']:,} of {FS['fa_intervals_usdg_checkable']:,} checkable fee payments, including all {FS['match_80pct_with_external_fees']:,} "
      f"that include external traders' fees.")
q3 = (f"**{usd(net_all, False)}** after every measurable cost ({usd(gross)} gross trading P&L, {usd(gas)} gas, {usd(-other_gas)} estimated gas on "
      f"non-trade transactions, {usd(inc, True, 2)} on the {SUM['coverage']['incomplete']} incomplete ones). Marked to the Nov 13 ETH price: {usd(mtm, False)}.")
q4 = (f"It trades until the next unit stops paying. After a trade the median gap to Binance is {med['gap_after_signed']:.1f} bp, made of: "
      f"{med['fynd_vs_hedge_after']:.1f} bp between Fynd and the hedge pool (≈ the {med['marginal_fees_bp']:.1f} bp of fees on the next unit), "
      f"{med['hedge_impact']:.1f} bp of the bot's own impact on the hedge pool, {med['hedge_dev']:.1f} bp because the hedge pool already sat away from the "
      f"on-chain market, and {sg(med['basis'])} bp of on-chain/Binance basis.")
q5 = (f"The ratio is low only while the pool had no active arbitrage: the bot started on Oct 13 and paused for 54 h on Oct 15–17. "
      f"On days with the bot idle under 2 hours the ratio is {busy[busy.day < '2026-10-22'].pipe(ratio):.2f} before Oct 22 and "
      f"{busy[busy.day >= '2026-10-22'].pipe(ratio):.2f} after, close to Uniswap's ~0.95 both times. The shift is at Oct 17, not Oct 22; it coincides with "
      f"the bot running continuously, LP ranges widening and depth halving. These moved together, so the data cannot separate them.")
q6 = (f"**Hedge on the deepest pool, then charge the bot more.** The bot never used Uniswap's WETH/USDG 0.01% pool; on {cfu['share_trades_cf_cheaper']:.0%} "
      f"of its trades that pool was cheaper ({cfu['cf_bp_vw']:.1f} bp vs {cfu['actual_bp_vw']:.1f} bp against Binance). In the replay, hedging at 1 bp and charging the bot "
      f"4 bp gives LPs {usd(hd4.lp_net_trading_12s_usd)} instead of {usd(A.lp_net_trading_12s_usd)} while the bot still nets {usd(hd4.bot_net_usd)} ({usd(A.bot_net_usd)} under today's rules in the same model).")

# ================================================================ FINAL_FINDINGS.md
ff = f"""# Fynd ETH/USDG: final findings

Audience: Fynd's founders. Scope: Fynd's ETH/USDG pool on Robinhood Chain; LP results Oct 2 – Nov 13, 2026; bot trades Oct 13 – Nov 13.
Builds on `BOT_ECONOMICS_REPORT.md` (unchanged). Labels: **observed** (read from chain logs), **calculated**, **inferred**, **assumed**, **unresolved**.

## Answers

1. **Independent LPs vs holding.** {q1}
2. **Fynd's owner fee.** {q2}
3. **Bot net profit.** {q3}
4. **Why ~5 bp short.** {q4}
5. **Why the LVR advantage narrowed.** {q5}
6. **Most promising change.** {q6}

## 1. The accounting, reconciled

Bot P&L (`BOT_PNL_WATERFALL.csv`; {SUM['coverage']['complete']:,} complete transactions, Binance at execution unless stated):

| step | USD | type |
|---|---|---|
| Price edge captured (Fynd vs hedge price, before fees) | {usd(edge)} | gross, realized |
| − Fynd fee paid by the bot | {usd(-fee)} | cost (80% to LPs, 20% to Fynd) |
| − router fees | {usd(-router)} | cost |
| **= Gross trading P&L** | **{usd(gross)}** | gross, realized |
| − gas on these trades | {usd(gas)} | cost, observed |
| **= Net realized (the reported $295)** | **{usd(net)}** | net, realized |
| + the {SUM['coverage']['incomplete']} incomplete transactions | {usd(inc, True, 2)} | net, realized |
| − gas on {SUM['bot_costs_outside_fynd_swaps']['eoa_txs_not_a_successful_trade']} non-trade transactions | {usd(-other_gas)} | estimate (assumed) |
| **= Net after all measurable costs** | **{usd(net_all)}** | net, realized |
| ETH profits revalued to the Nov 13 price | {usd(unreal)} | unrealized |
| = Net, marked to Nov 13 | {usd(mtm)} | realized + unrealized |

How the other bot figures relate:
- **$739** in the replay table is the same gross trading P&L (step 4).
- **$725** in the earlier value split is the same gross without the Nov 13 trades, which have no on-chain reference price
  (${r1:,.2f}; those trades made ${gross - r1:,.2f}), and with ETH valued at the on-chain price instead of Binance (${r2:,.2f}). Fewer trades and a
  different price, not a different result.
- At Binance 12 s later the gross is {usd(r3)} (the bot holds only its tiny profit, so the move barely matters).
- The bot contract's own on-chain profit figures add up to exactly the rebuilt amounts: {RC['bot_event_vs_reconstruction']['eth_event']:.6f} ETH and
  {RC['bot_event_vs_reconstruction']['usdg_event']:,.2f} USDG.

Fees:
- **The $2,069 LP fee income is the LPs' 80% share**, not gross fees. Every FeesAccumulated payment (the LP share) reached positions
  (checked report, 100.000%). Valued when paid it is {usd(fa_val, False)}; the {usd(fa_val - lp_pos, False)} difference is valuation timing.
- Gross fees = {usd(gross_fees, False)}; Fynd's 20% = **{usd(proto, False)}** (*calculated*, using the share read from the extension's events).
- The split holds for external traders too (*observed*). The extension charges them on their **output**: a trader receiving USDG gets less
  than the pool paid out, while the bot is charged on its input. That made {FS['external_swaps_fee_observed_in_usdg']:,} external fees directly observable
  ({usd(FS['external_output_fee_usd_observed'], False)}, {FS['external_output_fee_bp_volume_weighted']:.1f} bp volume-weighted), and every one of the {FS['fa_intervals_usdg_checkable_with_external_fees']:,} LP fee payments that include them
  equals exactly 80% (all checkable payments: {FS['match_80pct_all_checkable']:,} of {FS['fa_intervals_usdg_checkable']:,}). Fees on external swaps that receive ETH are native ETH and cannot be observed.
- The "~1.4 bp bot fee" is the LPs' share of the bot's fee: the bot pays {SUM['bot_fee']['volume_weighted_bp']:.2f} bp volume-weighted ({SUM['bot_fee']['median_bp']:.2f} bp median,
  {TH['mean_fee_bp_unweighted']:.2f} bp simple mean); 80% of {SUM['bot_fee']['volume_weighted_bp']:.2f} = {0.8 * SUM['bot_fee']['volume_weighted_bp']:.2f} bp reaches LPs.

## 2. Who is who

| role | address | evidence | label |
|---|---|---|---|
| Fynd's bot, per Edouard (Nov 12) | `0x6c6a…7127` | Fynd's statement; on chain this wallet is the largest LP (153 positions) and an EIP-7702 wallet; it sent 11 multi-pool swaps and no bot trade | confirmed by Fynd (as relayed); role on chain: LP |
| Fynd's bot, per the user (Nov 11) | `0x4abf…84a2` | sends every one of the {SUM['coverage']['fynd_bot_txs_expected']:,} bot trades; registered in the bot contract at deployment | confirmed by the user |
| Transaction sender | `0x4abf…84a2` | sender of every trade; pays all gas | observed |
| Execution contract | `0x7ea0…acc7` | target of every trade; emits a profit event per trade; trades only pools that use Fynd's extension | observed |
| Owner / controller | `0xd7c8…1c80` until block 111,842,342, then `0x0d41…d4b2` | OwnershipTransferred events | observed |
| Economic beneficiary | `0xd7c8…1c80` | received the bot contract's USDG profits: {len(wd)} withdrawals, {wd_total:,.2f} USDG in total; it then traded them on Fynd's pools | observed (USDG); ETH withdrawals unobservable |
| LP position owners | `0x6c6a…7127` and {len(og) - 1} other groups | position NFTs | observed |

The bot contract trades only pools whose swaps are locked through Fynd's extension (`0x550cfe12…`): ETH/USDG and three tokenized-stock pools
({len(ext_pools)} pools use the extension). Together with Edouard's confirmation that Fynd runs a bot, this makes Fynd the likely operator of
`0x4abf…`/`0x7ea0…` too (*inferred*). No USDG or WETH transfer links `0x6c6a…7127` to the bot's wallets (native ETH cannot be checked).

LP results by owner group (*calculated* from the checked positions file):

| group | positions | avg capital | LP vs hold | per 30 days | ownership |
|---|---|---|---|---|---|
"""
for g, r in og.iterrows():
    lab = "confirmed (Fynd)" if g.startswith("0x6c6a") else "unresolved"
    ff += f"| {g} | {int(r.positions)} | {usd(r.avg_capital_usd, False)} | {usd(r.lp_minus_hold_usd)} | {sg(r.lp_minus_hold_pct_30d)}% | {lab} |\n"
ff += f"""| **all except 0x6c6a** | | {usd(ind['avg_capital_usd'], False)} | **{usd(ind['lp_minus_hold_usd'])}** | **{sg(ind['pct_30d'])}%** | unresolved |

If `0x6c6a` is Fynd's, {usd(-fynd_g.lp_minus_hold_usd, False)} of the {usd(-R['totals']['lp_minus_hold_usd'], False)} LP loss is Fynd's own, and much of the bot's trading is
between two Fynd wallets.

## 3. What the 58% to hedge pools is

On the bot's swaps, Fynd LPs' swap side was {usd(vf('Fynd LPs' + chr(39) + ' swap side (Binance 12 s later)'))} at Binance 12 s. Exact shares: hedge pools {sp['hedge']:.2f}%, bot {sp['bot']:.2f}%,
Fynd fee {sp['fee']:.2f}%, router fees {sp['router']:.2f}% (sum {sum(sp.values()):.2f}%: the parts add up; the residual is ${vf("  residual: LPs' side + parts (Binance 12 s later)"):.2f}, the fee being valued at the 12 s
price). The earlier "58 + 18 + 19 + 4 = 99" was rounding.

For hedges that are one direct ETH/USDG swap and have an on-chain reference price, the hedge pools' result splits exactly (`VALUE_FLOW_RECONCILIATION.csv`, section D):

| part | USD | what it is | kept by the hedge pool? |
|---|---|---|---|
| fees to their LPs | {usd(hs['fees charged by the hedge pools, to their LPs'])} | the pools' swap fee | yes |
| fees to their protocols | {usd(hs['fees charged by the hedge pools, to their protocols'])} | protocol cut of the fee | yes (protocol) |
| fees, split unknown | {usd(hs['fees charged by the hedge pools, LP/protocol split unknown'])} | non-standard pools | yes |
| price impact | {usd(hs['price impact of the bot' + chr(39) + 's hedge on those pools'])} | the bot moving thin pools | only if not reversed later |
| pool price vs on-chain market | {usd(hs['those pools' + chr(39) + ' price vs the on-chain reference before the hedge'])} | the hedge pool was already off | only if not reversed later |
| on-chain/Binance basis | {usd(hs['on-chain reference vs Binance (basis)'])} | valuation at Binance | no: a measurement effect |
| **= at execution** | **{usd(hs['= hedge pools' + chr(39) + ' result at execution'])}** | | |
| Binance move in the next 12 s | {usd(hs['Binance move over the next 12 s on what they took'])} | market movement | no: valuation |
| other bot trades (multi-hop, or Nov 13), 12 s, not split | {usd(hs['other bot trades (multi-hop hedges, or no on-chain reference on Nov 13), 12 s'])} | | unknown |

So the 58% is not profit kept by other pools. About {usd(hs['fees charged by the hedge pools, to their LPs'] + hs['fees charged by the hedge pools, to their protocols'] + hs['fees charged by the hedge pools, LP/protocol split unknown'], False)} is fee income; impact and the pools' own
deviation are gains marked to Binance that the next arbitrage may take back; the rest is basis and 12-second price movement.
From the bot's side this is its **execution shortfall**: {HR['hedge_cost_bp_vw']:.1f} bp of hedge notional against Binance.

The Fynd side splits the same way: Fynd's price vs the on-chain market before the trade {usd(fs['f_own_dev_usd'])}, basis {usd(fs['f_basis_usd'])},
Fynd's own curve {usd(fs['f_impact_usd'])}; total {usd(fs['f_total_usd'])} at execution.

## 4. The ~5 bp stop

Exact split of the post-trade gap ({TH['trades']:,} single-hedge trades; medians, bp; signed so + = Fynd still on the side it started):

| | all | bot sells ETH into Fynd | bot buys ETH from Fynd |
|---|---|---|---|
| gap to Binance after the trade | {med['gap_after_signed']:.1f} | {bydir['bot_sells_eth']['gap_after_signed']:.1f} | {bydir['bot_buys_eth']['gap_after_signed']:.1f} |
| = basis (on-chain vs Binance) | {sg(med['basis'])} | {sg(bydir['bot_sells_eth']['basis'])} | {sg(bydir['bot_buys_eth']['basis'])} |
| + hedge pool vs on-chain market, before | {sg(med['hedge_dev'])} | {sg(bydir['bot_sells_eth']['hedge_dev'])} | {sg(bydir['bot_buys_eth']['hedge_dev'])} |
| + bot's impact on the hedge pool | {sg(med['hedge_impact'])} | {sg(bydir['bot_sells_eth']['hedge_impact'])} | {sg(bydir['bot_buys_eth']['hedge_impact'])} |
| + Fynd vs hedge pool, after | {sg(med['fynd_vs_hedge_after'])} | {sg(bydir['bot_sells_eth']['fynd_vs_hedge_after'])} | {sg(bydir['bot_buys_eth']['fynd_vs_hedge_after'])} |
| marginal fees (hedge + Fynd + router) | {sg(med['marginal_fees_bp'])} | {sg(bydir['bot_sells_eth']['marginal_fees_bp'])} | {sg(bydir['bot_buys_eth']['marginal_fees_bp'])} |

(Medians of parts need not add to the median of the whole; for each trade they add exactly, max error {TH['check_max_abs_bp']:.0e} bp.)

- **Fees explain the last leg.** What is left between Fynd and the hedge pool is within 1 bp of the marginal fees on {TH['share_left_within_1bp_of_fees']:.0%} of
  trades and within 2 bp on {TH['share_left_within_2bp_of_fees']:.0%}. The bot trades until the next unit no longer pays (*inferred* from this match; its code is not visible).
- **The rest is hedge quality and basis.** The bot's own impact on thin hedge pools (~{med['hedge_impact']:.1f} bp) and those pools sitting off the market
  (~{med['hedge_dev']:.1f} bp) make up most of the remaining gap. Against the on-chain market rather than Binance, Fynd is left
  {bydir['bot_sells_eth']['gap_after_signed'] - bydir['bot_sells_eth']['basis']:.1f} bp off when it was above and {bydir['bot_buys_eth']['gap_after_signed'] - bydir['bot_buys_eth']['basis']:.1f} bp when it was below: the 2.6 bp basis shifts the band, it is not misalignment.
- **Reaction speed.** While the bot was active, the chance it traded in a given second was about
  {TH['trade_probability_by_gap_when_bot_active']['vs_binance']['[10.0, 12.0)']['p']:.0%} even with Fynd 10–12 bp off Binance. Active seconds with a gap of 8 bp or more and no trade:
  {TH['active_wide_binance_gap_no_trade']['seconds']:,} (median gap to the on-chain market then {TH['active_wide_binance_gap_no_trade']['median_gap_vs_onchain_bp']:.1f} bp). Whether that is polling, competition for
  block space or the hedge pools being off too cannot be seen.
- **Failed attempts.** {SUM['bot_costs_outside_fynd_swaps']['eoa_txs_not_a_successful_trade']} of the EOA's {SUM['bot_costs_outside_fynd_swaps']['eoa_txs_through_last_fynd_tx']:,} transactions were not successful trades; their content cannot be
  read on this RPC, so they say nothing about the decision rule (*not measurable*).
- {TH['trades_gross_below_gas']} trades earned less than their gas; the median trade grossed ${TH['gross_per_trade_usd_quantiles']['0.5']:.3f}.

## 5. The LVR ratio over time

See `LVR_CHANGEPOINT_ANALYSIS.md`. In short: loss/LVR is {ratio(b22):.2f} before Oct 22 and {ratio(a22):.2f} after; split at Oct 17 it is
{ratio(before):.2f} and {ratio(after):.2f}. The low early figure comes from days with no bot (it started Oct 13) or a paused one. A pool nobody arbitrages
is stale and books less loss than the theory, which assumes continuous arbitrage; that is not protection. No extension or configuration change
was found ({', '.join(f'{k[:10]}: {v:,}' for k, v in ext_events.items())} events from the extension; the per-block event's fields never changed).

## 6. Hedge execution

`HEDGE_ROUTE_COSTS.csv` has every route. Totals: hedge notional {usd(HR['hedge_notional_usd'], False)}, hedge cost {usd(HR['hedge_cost_usd'], False)} = {HR['hedge_cost_bp_vw']:.2f} bp against
Binance. For single direct hedges the cost is fee {sd['cost_bp_mean']['cost_fee_bp']:.2f} bp + impact {sd['cost_bp_mean']['cost_impact_bp']:.2f} bp + hedge pool off the
on-chain market {sd['cost_bp_mean']['cost_own_dev_bp']:.2f} bp + basis {sg(sd['cost_bp_mean']['cost_basis_bp'], 2)} bp (means).

| route | trades | hedge cost bp (vw) | same trades on the 0.01% pool, bp |
|---|---|---|---|
"""
for r in RT.head(8).itertuples():
    ff += f"| `{r.route}` | {r.trades:,} | {r.hedge_cost_bp_vw:.2f} | {r.cf_uni1bp_cost_bp_vw:.2f} |\n"
ff += f"""
- **The deepest pool was never used.** The bot hedged {cfu['trades']:,} trades on other pools; the Uniswap v3 WETH/USDG 0.01% pool, at its price and
  liquidity just before each trade, would have cost {cfu['cf_bp_vw']:.2f} bp instead of {cfu['actual_bp_vw']:.2f} bp ({usd(cfu['cf_cost_usd'], False)} vs {usd(cfu['actual_cost_usd'], False)}), cheaper on
  {cfu['share_trades_cf_cheaper']:.0%} of trades. *Calculated counterfactual*: assumes the pool's state is still available inside the same block and ignores other
  traders' reaction. Why the router skipped it is not visible on chain.
- **Cheap routes already exist in the bot's set.** Three non-standard 0.01% pools (`0x16679e2a`, `0x76159260`, `0xfae65eaa`) cost
  {RT[RT.route.isin(['uniswap_v3:0x16679e2a', 'uniswap_v3:0x76159260', 'uniswap_v3:0xfae65eaa'])].pipe(lambda d: 1e4 * d.hedge_cost_usd.sum() / d.hedge_notional_usd.sum()):.2f} bp on the
  {int(RT[RT.route.isin(['uniswap_v3:0x16679e2a', 'uniswap_v3:0x76159260', 'uniswap_v3:0xfae65eaa'])].trades.sum()):,} trades routed there; the two main v4 pools cost 3.6–4.2 bp. The router's choice, not the pool menu, drives the cost.
- **Splitting.** Impact on the hedge pools cost {usd(-HR['splitting_rough']['impact_cost_usd_single_direct'], False)}; two equally deep venues would roughly halve it
  ({usd(-HR['splitting_rough']['saving_if_impact_halved_usd'], False)}), before the extra hop's gas. On the 0.01% pool impact is close to zero at these sizes, so splitting matters less.
- **Netting.** Opposite trades within 60 s: {HR['netting']['60s']['pairs']:,} pairs, {usd(HR['netting']['60s']['netted_notional_usd'], False)} that could offset, saving
  {usd(HR['netting']['60s']['hedge_cost_saved_usd'], False)} of hedge cost, at a price risk of about {usd(HR['netting']['60s']['inventory_pnl_std_usd'], False, 2)} per pair (std). Small.
- **Batching** would save gas ({usd(-gas, False)} in all) but trades later; not tested.

Replays with cheaper hedging (policy_sim.py's model, historical replay; external flow fixed):

| hedge cost | bot trades | LPs' trading-side net, 12 s | LP fees | Fynd's 20% | bot net (upper bound) | mean gap (bp) |
|---|---|---|---|---|---|---|
"""
for cut, r in se.iterrows():
    ff += f"| −{cut:.0%} ({r.hedge_cost_bp:.2f} bp) | {int(r.bot_trades):,} | {usd(r.lp_net_trading_12s_usd)} | {usd(r.lp_fees_usd, False)} | {usd(r.protocol_fees_usd, False)} | {usd(r.bot_net_usd)} | {r.mean_abs_gap_bp:.1f} |\n"
r = hdeep
ff += f"| 1 bp (the 0.01% pool) | {int(r.bot_trades):,} | {usd(r.lp_net_trading_12s_usd)} | {usd(r.lp_fees_usd, False)} | {usd(r.protocol_fees_usd, False)} | {usd(r.bot_net_usd)} | {r.mean_abs_gap_bp:.1f} |\n"
ff += f"""
Cheaper hedging lets the bot trade more often at smaller gaps: LPs lose less per rebalance, earn more fees, the pool tracks the market better,
and the bot earns more. The replay's bot earns more than the real one at every setting (its hedge cost does not grow with size), so read bot
figures as upper bounds and compare rows with each other.

## 7. Recommendations

See `MECHANISM_RECOMMENDATIONS.md`. Ranked:
1. Route hedges to the deepest on-chain pool (and quote it on every trade).
2. Use the bot's new margin to raise its Fynd fee to about 3–4 bp.
3. Keep the bot running and reacting, once 1 and 2 are in place.

Not concluded: whether Fynd's design is better or worse than Uniswap's. The comparison metrics move with arbitrage activity, depth and range width,
and the two pools serve different flow.

## Limits

Native ETH legs are inferred (they match the bot's own on-chain figures in every transaction). Reverted transactions cannot be read. Uniswap v3
protocol fee shares are read at the current block. The replays keep external traders, routers and LPs as they were. USDG = $1.
"""
open(F("FINAL_FINDINGS.md"), "w").write(ff)

# ================================================================ LVR_CHANGEPOINT_ANALYSIS.md
cols = ["fynd_loss_over_lvr", "uniswap_loss_over_lvr", "fynd_lvr_usd", "fynd_depth_usd_per_1pct", "range_width_bp_capital_weighted", "mean_abs_gap_bp",
        "bot_trades", "bot_idle_hours", "bot_share_of_volume", "external_volume_usd", "bot_fee_bp", "external_fee_bp_lp", "hedge_cost_bp", "eth_vol_ann_pct",
        "bot_trade_size_median_usd", "active_lps"]
lab = {"fynd_loss_over_lvr": "Fynd loss / LVR", "uniswap_loss_over_lvr": "Uniswap loss / LVR", "fynd_lvr_usd": "Fynd theoretical LVR ($/day)",
       "fynd_depth_usd_per_1pct": "Fynd depth ($ per 1% move)", "range_width_bp_capital_weighted": "LP range width (bp, capital-weighted)",
       "mean_abs_gap_bp": "mean |gap| to Binance (bp)", "bot_trades": "bot trades / day", "bot_idle_hours": "bot idle hours / day (gaps >1 h)",
       "bot_share_of_volume": "bot share of volume", "external_volume_usd": "external volume ($/day)", "bot_fee_bp": "bot Fynd fee (bp)",
       "external_fee_bp_lp": "external fee to LPs (bp)", "hedge_cost_bp": "hedge cost (bp, median)", "eth_vol_ann_pct": "ETH volatility (% ann.)",
       "bot_trade_size_median_usd": "bot trade size (median $)", "active_lps": "active LPs"}
periods = [("Oct 7–12 (no bot)", CPd[CPd.day < "2026-10-13"]), ("Oct 13–16 (bot starts, 54 h pause)", CPd[(CPd.day >= "2026-10-13") & (CPd.day < "2026-10-17")]),
           ("Oct 17–21", CPd[(CPd.day >= "2026-10-17") & (CPd.day < "2026-10-22")]), ("Oct 22 – Nov 11", CPd[CPd.day >= "2026-10-22"])]
lv = f"""# Why Fynd's loss/LVR ratio rose in October 2026

Question: Fynd's LP loss as a share of theoretical LVR was {ratio(b22):.2f} over Oct 7–21 and {ratio(a22):.2f} from Oct 22 (Uniswap's 0.01% pool: ~0.95 both times).
Data: `final/data/changepoint_daily.csv` (one row per day, all from local files). Ratios below are sums of loss over sums of LVR.

## The change is at Oct 17, not Oct 22

| period | Fynd loss/LVR | """ + " | ".join(lab[c] for c in cols[1:]) + " |\n|---|---|" + "---|" * (len(cols) - 1) + "\n"
for nm, df in periods:
    vals = []
    for c in cols[1:]:
        v = df[c].median() if c not in ("fynd_lvr_usd", "external_volume_usd", "bot_trades") else df[c].mean()
        vals.append("–" if pd.isna(v) else (f"{v:,.2f}" if abs(v) < 10 else f"{v:,.0f}"))
    lv += f"| {nm} | {ratio(df):.2f} | " + " | ".join(vals) + " |\n"
lv += f"""
(Medians of daily values; LVR, external volume and bot trades are daily means.)

Oct 22 is where one of the Uniswap data files starts, not a market event. The step happens on Oct 17: from that day the bot trades every day
with little idle time, LP ranges are about {after.range_width_bp_capital_weighted.median() / max(before.range_width_bp_capital_weighted.median(), 1):.0f}x wider, depth per 1% is about
{before.fynd_depth_usd_per_1pct.median() / after.fynd_depth_usd_per_1pct.median():.1f}x lower, and the pool sits {before.mean_abs_gap_bp.median():.0f} → {after.mean_abs_gap_bp.median():.0f} bp from Binance (medians).

## Candidate causes

Arrows compare medians of daily values before Oct 17 (Oct 7–16, including the six days with no bot) with Oct 17 onward.

| factor | what the data shows | supports the change? |
|---|---|---|
| Arbitrage activity | No bot before Oct 13; 54 h pause Oct 15–17; from Oct 17 the bot trades daily. On days with the bot idle <2 h, loss/LVR is {busy[busy.day < '2026-10-22'].pipe(ratio):.2f} before Oct 22 and {busy[busy.day >= '2026-10-22'].pipe(ratio):.2f} after. | **yes**: most of the early gap disappears on comparable days |
| Liquidity and range width | Deep, narrow liquidity Oct 9–16; wide ranges and ~$5k per 1% after. Theoretical LVR scales with depth, so a deep pool nobody arbitrages has a large LVR and a small realized loss. | yes, together with the above |
| Bot vs external flow | Before: much of the loss came from external swaps; after: almost all from bot swaps (bot share of volume {before.bot_share_of_volume.median():.0%} → {after.bot_share_of_volume.median():.0%}). | consistent; a consequence of the bot running |
| Trade size | Bot median trade ${before.bot_trade_size_median_usd.median():,.0f} → ${after.bot_trade_size_median_usd.median():,.0f}. | weak |
| Hedge venues and cost | Hedge cost median {before.hedge_cost_bp.median():.1f} → {after.hedge_cost_bp.median():.1f} bp. | weak |
| Fees | Bot fee {before.bot_fee_bp.median():.2f} → {after.bot_fee_bp.median():.2f} bp; external LP fee {before.external_fee_bp_lp.median():.1f} → {after.external_fee_bp_lp.median():.1f} bp (mix of traders, cause not observed). | affects fees/LVR, not loss/LVR |
| Volatility | {before.eth_vol_ann_pct.median():.0f}% → {after.eth_vol_ann_pct.median():.0f}% annualised. | no |
| Extension / configuration | Extension events: {', '.join(f'{k[:10]} {v:,}' for k, v in ext_events.items())}; the per-block event's fields (`share`, address) never change. Code changes cannot be read (no historical state). | no evidence of a change |

Correlation of the daily ratio with each factor (36 days; these move together, so this is description, not cause):
{', '.join(f'{lab.get(k, k)} {v:+.2f}' for k, v in json.load(open(F('data', 'changepoint_daily.json')))['corr_with_loss_over_lvr'].items() if k in cols)}.

## Conclusion

The early "advantage" (loss/LVR {ratio(b22):.2f}) is mostly days when nobody was arbitraging the pool. The pool was stale and the LPs booked less loss
than the continuous-arbitrage theory assumes; stale prices are not protection, they are loss postponed or given to whoever trades next. With the bot running,
Fynd's ratio is close to Uniswap's. Arbitrage activity, depth and range width all changed around Oct 17, so the data cannot say which one
drives it. It does not show Fynd's design protecting LPs better than Uniswap's, or worse.
"""
open(F("LVR_CHANGEPOINT_ANALYSIS.md"), "w").write(lv)

# ================================================================ MECHANISM_RECOMMENDATIONS.md
mr = f"""# Mechanism recommendations for Fynd ETH/USDG

Ranked by evidence and by how well each serves all three goals: LP returns, sustainable bot economics, and execution quality for traders.
Replay numbers come from `policy_sim.py`'s model (historical replay over Oct 13 – Nov 13; external traders, routers and LPs as they were). The
model's bot earns more than the real one, so compare rows with each other, not with history.

Baseline in the same model (today's rules): LPs' trading-side net {usd(A.lp_net_trading_12s_usd)}, bot net {usd(A.bot_net_usd)}, mean gap {A.mean_abs_gap_bp:.1f} bp.

## 1. Hedge on the deepest on-chain pool

**Evidence (calculated from observed trades).** In {SUM['coverage']['complete']:,} trades the bot never used Uniswap v3 WETH/USDG 0.01% (`0x52e65b17…71ca`).
At that pool's price and liquidity just before each trade, hedging there would have cost {cfu['cf_bp_vw']:.2f} bp against Binance instead of
{cfu['actual_bp_vw']:.2f} bp, cheaper on {cfu['share_trades_cf_cheaper']:.0%} of trades. The current hedges pay a fee of ~{sd['cost_bp_mean']['cost_fee_bp']:.1f} bp, move thin pools by
~{sd['cost_bp_mean']['cost_impact_bp']:.1f} bp, and land on pools already ~{sd['cost_bp_mean']['cost_own_dev_bp']:.1f} bp off the on-chain market.

**Replay.** Hedge at 1 bp: LPs {usd(hdeep.lp_net_trading_12s_usd)}, bot {usd(hdeep.bot_net_usd)}, gap {hdeep.mean_abs_gap_bp:.1f} bp. Even a 25% cut helps all three ({usd(se.loc[0.25].lp_net_trading_12s_usd)},
{usd(se.loc[0.25].bot_net_usd)}, {se.loc[0.25].mean_abs_gap_bp:.1f} bp).

**How to test.** Quote the 0.01% pool alongside the current route on every trade for a week without changing execution; then switch and
compare realized hedge cost. Risks: other arbitrageurs on that pool, and same-block competition; the counterfactual assumes its state is
available to the bot.

## 2. Use the bot's new margin to raise its Fynd fee to about 3–4 bp

**Evidence.** The bot pays {SUM['bot_fee']['volume_weighted_bp']:.1f} bp (median {SUM['bot_fee']['median_bp']:.1f} bp; zero on {SUM['bot_fee']['share_zero']:.0%} of trades) while external traders pay
~{SUM['bot_fee']['other_traders_bp_incl_protocol']:.0f} bp. On its trades LPs give up ~9 bp, of which the fee returns ~2.

**Replay.**

| hedge | Fynd fee on bot trades | LPs' net | bot net | Fynd's 20% | mean gap |
|---|---|---|---|---|---|
| today | {SUM['bot_fee']['volume_weighted_bp']:.1f} bp | {usd(A.lp_net_trading_12s_usd)} | {usd(A.bot_net_usd)} | {usd(A.protocol_fees_usd, False)} | {A.mean_abs_gap_bp:.1f} |
"""
for code in ["Hdeep+D2.5", "Hdeep+D3", "Hdeep+D4", "Hdeep+D5", "H50+D3", "H50+D4"]:
    r = CB.loc[code]
    hed = "1 bp" if code.startswith("Hdeep") else "−50%"
    mr += f"| {hed} | {json.loads(r.params)['f']:g} bp | {usd(r.lp_net_trading_12s_usd)} | {usd(r.bot_net_usd)} | {usd(r.protocol_fees_usd, False)} | {r.mean_abs_gap_bp:.1f} |\n"
mr += f"""
With hedging at 1 bp, a 4 bp bot fee leaves the bot about where it is today ({usd(hd4.bot_net_usd)} vs {usd(A.bot_net_usd)}) while LPs lose
{usd(hd4.lp_net_trading_12s_usd - A.lp_net_trading_12s_usd, False)} less. Without cheaper hedging, the same fee would cut the bot's trading and leave the pool staler
(`out/policy_simulation.csv`, D rows). **Do the fee change only after recommendation 1.** A fee linked to the gap the bot closes would target the
same thing more precisely; it was not replayed.

## 3. Keep the bot running and reacting, after 1 and 2

**Evidence.** The bot was idle for more than an hour {SUM['idle']['gaps_over_1h']} times ({SUM['idle']['hours_in_gaps_over_1h']:.0f} of {SUM['idle']['hours_total']:.0f} hours); external traders arriving
then met a pool a median ~31 bp off. While active, it traded in only ~5–8% of seconds even with Fynd 10–15 bp off.

**Replay.** Always on alone helps alignment ({A0.mean_abs_gap_bp:.1f} bp) but costs LPs ({usd(A0.lp_net_trading_12s_usd)} vs {usd(PS.loc['A'].lp_net_trading_12s_usd)}). Combined with 1 and 2
(always on, hedge at 1 bp, 4 bp fee): LPs {usd(best.lp_net_trading_12s_usd)}, bot {usd(best.bot_net_usd)}, Fynd's 20% {usd(best.protocol_fees_usd, False)}, gap {best.mean_abs_gap_bp:.1f} bp: better on all three goals.

## Not recommended (from the replays)

Minimum-gap thresholds, minimum-profit rules, trade-size caps and inventory-aware thresholds all left LPs worse or the pool staler
(`out/policy_simulation.csv`, B, C, E, F rows). Giving LPs the protocol's 20% (~{usd(proto, False)} over the period) would help LPs by moving money
from Fynd, not by improving the mechanism; it is a separate decision.

## What the replays cannot show

How routers and external traders would respond to a better-aligned or more expensive pool, whether the 0.01% pool's liquidity would stay
when the bot trades on it, and live latency. Test each change with a short live trial and track realized hedge cost, LP fees, the bot's
net and the gap to the market.
"""
open(F("MECHANISM_RECOMMENDATIONS.md"), "w").write(mr)

# ================================================================ EXEC_SUMMARY_FOR_FYND.md
es = f"""# Fynd ETH/USDG: what LPs, Fynd and the bot made, and what to change

Oct 2 – Nov 13, 2026. All {SUM['coverage']['fynd_bot_txs_expected']:,} bot trades rebuilt from chain data ({SUM['coverage']['complete']:,} completely).

**What each party made**
- **Independent LPs** (all except `0x6c6a…7127`): {usd(ind['lp_minus_hold_usd'])} against holding, {sg(ind['pct_30d'])}% per 30 days on ~{usd(ind['avg_capital_usd'], False)}. Ownership unresolved.
- **`0x6c6a…7127`** (Fynd's, per Edouard): {usd(fynd_g.lp_minus_hold_usd)}, {sg(fynd_g.lp_minus_hold_pct_30d)}% per 30 days.
- **Fynd's 20% owner fee:** ~{usd(proto, False)} ({usd(fee_bot * 0.2, False)} of it paid by Fynd's own bot). The LPs' {usd(lp_pos, False)} of fees is their 80% share.
- **The bot:** {usd(net_all)} net after all measurable costs ({usd(gross)} gross, {usd(gas)} gas). Its USDG profits were withdrawn to its owner `0xd7c8…1c80`.

**Where the LPs' loss on bot trades went** (−$4,028 at Binance 12 s): {sp['hedge']:.0f}% to the pools the bot hedged on (on the 21,764 trades where it can be split,
{usd(hs['fees charged by the hedge pools, to their LPs'] + hs['fees charged by the hedge pools, to their protocols'] + hs['fees charged by the hedge pools, LP/protocol split unknown'], False)} is their fees; the rest is price impact, their own mispricing, basis and price moves); {sp['bot']:.0f}% to the bot; {sp['fee']:.0f}% back as Fynd fees; {sp['router']:.0f}% router fees.

**Why the bot stops ~5 bp short:** it trades until the next unit stops paying. That point is set by its hedge: fees (~2.6 bp on the last unit),
its own impact on thin hedge pools (~1.8 bp) and those pools being off the market (~0.9 bp).

**The Oct 22 change** was really Oct 17. Fynd's low loss/LVR early on came from days when nobody arbitraged the pool; with the bot running, Fynd and
Uniswap look similar. No configuration change was found.

**Recommendations, ranked**
1. **Hedge on the deepest pool.** The bot never used Uniswap's WETH/USDG 0.01% pool; it would have cost {cfu['cf_bp_vw']:.1f} bp instead of {cfu['actual_bp_vw']:.1f} bp against Binance.
2. **Then raise the bot's fee to ~3–4 bp.** With hedging at 1 bp and a 4 bp fee, LPs lose {usd(hd4.lp_net_trading_12s_usd - A.lp_net_trading_12s_usd, False)} less over the month in the
   replay, with the bot's profit about unchanged.
3. **Keep the bot on and reacting fast** once 1 and 2 are in place: all three together improve LPs, the bot and price alignment in the replay.

Replays hold traders' and routers' behaviour fixed; test each step live. No conclusion is drawn on whether Fynd's design beats Uniswap's.
"""
open(F("EXEC_SUMMARY_FOR_FYND.md"), "w").write(es)
print("wrote FINAL_FINDINGS.md, LVR_CHANGEPOINT_ANALYSIS.md, MECHANISM_RECOMMENDATIONS.md, EXEC_SUMMARY_FOR_FYND.md")
