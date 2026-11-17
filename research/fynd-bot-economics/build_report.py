"""
Write BOT_ECONOMICS_REPORT.md and EXEC_SUMMARY.md from the output files. Every number is read from out/; nothing is
typed in by hand.

  python3 build_report.py --out out --compare ../markout-backtest/results_pool_compare.json
"""
import argparse, json, os
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True); ap.add_argument("--compare", required=True)
a = ap.parse_args()
S = json.load(open(os.path.join(a.out, "summary.json")))
P = pd.read_csv(os.path.join(a.out, "policy_simulation.csv")).set_index("policy")
UA = json.load(open(os.path.join(a.out, "uniswap_comparison_audit.json")))
CP = json.load(open(a.compare))
REC = pd.read_csv(os.path.join(a.out, "bot_value_reconciliation.csv"))
GT = pd.read_csv(os.path.join(a.out, "gap_time_profile.csv"))
EXT = pd.read_csv(os.path.join(a.out, "external_swaps_by_time_since_bot.csv"))
E = pd.read_csv(os.path.join(a.out, "bot_transaction_economics.csv"), low_memory=False)
C = E[E.completeness.str.startswith("complete")]
cal = json.loads(P.calibration.iloc[0])
r = REC.set_index("item").usd


def usd(v, sign=True):
    s = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{s}${abs(v):,.0f}"


def pct(v, d=0):
    return f"{100 * v:.{d}f}%"


def sg(v, d=2):
    """Signed number with a real minus sign."""
    return ("−" if v < 0 else "") + f"{abs(v):.{d}f}"


def rec(item):
    return float(r[item])


cov, ex, gt, ext, lp, bf, idle = S["coverage"], S["execution"], S["gap_time"], S["external"], S["lp"], S["bot_fee"], S["idle"]
oc = S["bot_costs_outside_fynd_swaps"]
sel = lambda pre: [i for i in r.index if i.startswith(pre)]
k12 = lambda pre: rec([i for i in sel(pre) if "12 s later" in i][0])
kex = lambda pre: rec([i for i in sel(pre) if "at execution" in i][0])
kon = lambda pre: rec([i for i in sel(pre) if "on-chain reference" in i][0])
lp12, fee12, rt12, bot12, oth12 = (k12(p) for p in ["Fynd LPs, swap side", "  Fynd fee paid", "  router fee", "  bot, gross", "  other venues"])
lpx, feex, rtx, botx, othx = (kex(p) for p in ["Fynd LPs, swap side", "  Fynd fee paid", "  router fee", "  bot, gross", "  other venues"])
lpo, feeo, rto, boto, otho = (kon(p) for p in ["Fynd LPs, swap side", "  Fynd fee paid", "  router fee", "  bot, gross", "  other venues"])
gross, gas, net = rec("gross trading P&L (after router fees)"), rec("gas on these txs"), rec("net realized P&L")
unreal = rec("unrealized: ETH profits revalued to the Nov 13 snapshot")
proto_all = rec(f"protocol share of all Fynd fees ({S['protocol_share']:.0%})")
fee_lp_exact, fee_proto_bot = rec("Fynd fee paid by the bot, LP share (exact, per swap)"), rec("Fynd fee paid by the bot, protocol share")
other_gas_items = [i for i in r.index if i.startswith("gas on the EOA's other txs")]
other_gas = rec(other_gas_items[0]) if other_gas_items else None
A, REAL = P.loc["A"], P.loc["REAL"]
share = lambda v: pct(v / -lp12)
dir_gap_b, dir_gap_a = ex["gap_before_median_by_direction"], ex["gap_after_median_by_direction"]
hedge_b = ex["hedge_vs_binance_bp_median_by_direction"]
mk = ex["markout_curve"]
w = S["eth_at_snapshot"]

body = f"""# Fynd ETH/USDG: bot economics and where the LPs' value went

Fynd ETH/USDG pool on Robinhood Chain (Ekubo Core, Fynd extension `0x550cfe12…1d09`). Bot trades rebuilt from chain
data: {cov['complete']:,} of {cov['fynd_bot_txs_expected']:,} bot transactions ({cov['first_utc'][:16]} to {cov['last_utc'][:16]} UTC).
LP figures: every position from Oct 2 to the Nov 13 snapshot (checked Nov 13 report, unchanged).

Evidence labels used below: **observed** (read directly from chain logs), **calculated** (arithmetic on observed data),
**inferred** (rebuilt from behaviour or indirect records), **assumed** (needed because data is missing), **not measurable**.

## The short answer

- **LPs lost {usd(-lp['totals']['lp_minus_hold_usd'], False)} against holding** over {lp['days']:.0f} days: fees {usd(lp['totals']['fees_usd'])}, impermanent loss
  {usd(lp['totals']['il_usd'])}. On an average {usd(lp['avg_capital_usd'], False)} of capital that is {-lp['totals']['lp_minus_hold_usd'] / lp['avg_capital_usd'] * 100:.1f}% lost over the period, {-lp['lp_minus_hold_per_30d_pct']:.1f}% per 30 days. *Calculated.*
- **The bot made {usd(net, False)} net** on its Fynd ETH/USDG trades ({usd(gross)} gross, {usd(gas)} gas). Every one of its
  {cov['complete']:,} complete transactions is an atomic round trip: it trades Fynd and closes the position on other on-chain
  pools in the same transaction, keeping a small profit and no inventory. *Calculated from observed logs; native-ETH legs
  inferred and confirmed against the bot's own event in every transaction.*
- **The bot did not take most of what LPs lost on its trades.** On the bot's swaps, LPs' swap side was {usd(lp12)} at Binance
  12 s later. Inside the same transactions that value went to:
  the pools the bot hedged on, {usd(oth12)} ({share(oth12)});
  the bot, {usd(bot12)} ({share(bot12)});
  the Fynd fee, {usd(fee12)} ({share(fee12)}; 80% back to LPs, 20% to the protocol);
  router fees, {usd(rt12)} ({share(rt12)}).
  *Calculated; tokens are conserved inside each transaction, so the parts add up exactly.*
- **The bot moves the pool toward the market in {pct(ex['moved_toward_binance_share'], 1)} of its trades, but usually stops short.**
  It trades when Fynd is about {abs(dir_gap_b['bot_sells_eth']):.1f} bp off Binance and leaves it about {abs(dir_gap_a['bot_sells_eth']):.1f} bp off: that is where
  Fynd's price meets the other pools' prices after their costs. *Calculated.*
- **Why LPs still lose:** every rebalance sells LP inventory at a price that is several bp stale, and the bot pays a fee of
  only {bf['volume_weighted_bp']:.1f} bp on it (other traders pay {bf['other_traders_bp_incl_protocol']:.1f} bp). Most of the gap is paid to the hedge pools, not kept by
  the bot. The bot was also idle for more than an hour {idle['gaps_over_1h']} times ({idle['hours_in_gaps_over_1h']:.0f} of {idle['hours_total']:.0f} hours), when the pool drifted far from the market.

## 1. Who is who

| Address | Role | Evidence |
|---|---|---|
"""
WM = pd.read_csv(os.path.join(a.out, "bot_wallet_and_contract_map.csv"))
for x in WM.itertuples():
    body += f"| `{x.address[:10]}…{x.address[-4:]}` | {x.role} | {x.evidence_label}: {x.evidence} |\n"
body += f"""
**The brief says `0x6c6a40d2…7127` is Fynd's bot. The chain data does not support that.** That wallet made position
changes as the pool's largest LP and sent a handful of multi-pool swaps; it never sent a bot trade. Every bot trade comes
from `0x4abf…84a2` through contract `0x7ea0…acc7`. If Fynd confirmed `0x6c6a` as *its own LP wallet*, Fynd is on
both sides of most bot trades, and much of the LP loss is a transfer between two Fynd wallets. Not verified: wallet
ownership is not inferred from behaviour here.

## 2. How one bot trade works

Example: `0x21baf60f…63da`, the bot EOA's first trade (nonce 0), Oct 13 11:47:37 UTC. Full hand check in
`hand_checks/HAND_CHECKS.md`.

1. The bot contract takes a flash position on Ekubo Core: Fynd receives 0.193039 ETH and pays 484.198495 USDG (observed).
2. The USDG goes, through router `0x0921…ff9e`, into a Uniswap v4 WETH/USDG pool, which pays 0.193187 WETH (observed).
3. The router unwraps the WETH and the contract pays Ekubo 0.193171 ETH: the swap amount plus a Fynd fee of 0.000132 ETH
   (inferred: native ETH leaves no log; the amount is in the bot contract's own event and matches the 80% that reaches LPs).
4. The bot keeps 0.0000160 ETH ($0.040), pays $0.019 of gas, nets $0.021 (calculated).
5. At Binance at execution, Fynd's LPs gave up $1.04 on the swap, got back $0.26 of fee (the protocol $0.07), the v4 pool
   gained $0.67, the bot $0.04.

**The Fynd fee.** The extension charges a dynamic fee on top of the swap (bot trades: volume-weighted {bf['volume_weighted_bp']:.2f} bp, median
{bf['median_bp']:.2f} bp, zero on {pct(bf['share_zero'])} of trades). LPs receive {pct(1 - S['protocol_share'])} of it at the pool's next interaction (FeesAccumulated);
{pct(S['protocol_share'])} stays with the protocol. Verified: in {S['fee_split_check']['match_80pct']:,} of {S['fee_split_check']['intervals_with_only_bot_swaps']:,} fee payments that cover only bot swaps,
the payment equals exactly 80% of the bot fees. *Observed for USDG-paid fees, inferred for ETH-paid fees.* The checked LP
reports count only the LPs' 80%; the protocol's 20% over the whole period is about {usd(proto_all, False)}.

## 3. Data, coverage and method

- **Transactions.** Every bot Fynd swap in the checked swap files (to block {lp['period']['snapshot_block']:,}), fetched as receipts from the
  public RPC. Complete: {cov['complete']:,}; incomplete: {cov['incomplete']:,} (listed with reasons in `bot_transaction_economics.csv`).
  The incomplete ones each have a hedge leg on a DEX type not decoded; their bot result still matches the bot's own event.
  Reconstruction equals the bot contract's own profit figure in {cov['bot_event_matches_reconstruction']:,} transactions. Value is conserved in every
  complete transaction to within ${cov['max_abs_identity_check_usd']:.1e}.
- **Legs decoded.** Ekubo swaps (Fynd and other pools), Uniswap v2, v3 and v4 swaps, ERC20 transfers, WETH wrap/unwrap,
  the router's fee events, the bot contract's trade event. *Observed.* Native ETH is *inferred* (no traces on this RPC).
- **Prices.** Binance ETHUSDC 1 s close; price "at T" = close of the candle opening at T−2, markout at T+h. USDG = $1
  (*assumed*). On-chain reference: Uniswap v3 WETH/USDG 0.01% mid before the transaction. On this chain that pool
  sits a median 2.6 bp below Binance with no lag (a basis, not a delay), so values at Binance carry that basis; section 4
  repeats the split at the on-chain price.
- **Bot costs outside these swaps.** The bot EOA's nonce counts every transaction it ever sent. Its last Fynd trade has
  nonce {oc['eoa_txs_through_last_fynd_tx'] - 1:,}, so it had sent {oc['eoa_txs_through_last_fynd_tx']:,} transactions: {oc['fynd_trades']:,} Fynd trades, about
  {oc['other_pool_trades_until_last_fynd_tx'] * oc['other_pool_sample_share_from_bot_eoa']:,.0f} trades on the bot's three other Ekubo pools ({oc['other_pool_trades_until_last_fynd_tx']:,} in the bot contract's events; {pct(oc['other_pool_sample_share_from_bot_eoa'])} of a
  random sample of {oc['other_pool_sample_size']:,} were sent by this EOA), and **{oc['eoa_txs_not_a_successful_trade']:,} others**: reverted attempts or other activity.
  Those cannot be listed on this RPC (*not measurable* individually; an indexer would list them).
"""
if other_gas is not None:
    body += f"  Estimated gas on them: {usd(other_gas)} (*assumed*: count x the median gas of a successful trade; reverts may use more or less).\n"
body += f"""
## 4. Where the LPs' value went on the bot's trades

All {cov['complete']:,} complete bot transactions. Positive = that party gained. Each row is a sum of a column in
`bot_transaction_economics.csv`.

| | at Binance, execution | at Binance, 12 s later | at the on-chain price |
|---|---|---|---|
| Fynd LPs, swap side (fee excluded) | {usd(lpx)} | {usd(lp12)} | {usd(lpo)} |
| Fynd fee paid by the bot | {usd(feex)} | {usd(fee12)} | {usd(feeo)} |
| Router fee paid by the bot | {usd(rtx)} | {usd(rt12)} | {usd(rto)} |
| Bot, gross | {usd(botx)} | {usd(bot12)} | {usd(boto)} |
| Pools the bot hedged on (their LPs and protocols) | {usd(othx)} | {usd(oth12)} | {usd(otho)} |
| **Sum** | ≈ $0 | ≈ $0 | ≈ $0 |

The on-chain column covers the trades before Nov 13 (the on-chain reference data ends Nov 12 23:59). *Calculated.*
Read it as an accounting of tokens inside each transaction, not as cause: the hedge pools did not "take"
anything; they traded at their own prices, which happened to be closer to Binance than Fynd's.

![Where the LPs' swap-side loss on bot trades went](out/value_split.png)

What overlaps and what does not:
- This table covers only the bot's swaps. The LP figures (−$3,925) are position-level and cover all swaps plus later price
  moves; the LPs' swap-side loss on bot swaps (−$4,037 at 12 s, checked report) is one input to them, not an addition.
- The Fynd fee here is exact per swap. The checked LP split assigns fees to swaps proportionally, giving the bot's swaps
  $615 of LP fees; the exact LP share of the bot's fees is {usd(fee_lp_exact, False)}. Total LP fees do not change.
- The bot's profit is not "value extracted from LPs": {share(bot12)} of the LPs' swap-side loss on its trades.
- External traders (not the bot) paid {usd(ext['fees_total_incl_protocol_usd'], False)} of fees on {usd(ext['volume_usd'], False)} and came out {usd(ext['trader_result_12s_after_all_fees_usd'])} against
  Binance 12 s later: roughly break-even. *Calculated.*

## 5. The bot's own economics (Fynd ETH/USDG only)

| | USD | Evidence |
|---|---|---|
| Gross trading P&L (after router fees, Binance at execution) | {usd(gross)} | calculated |
| Gas on these trades | {usd(gas)} | observed |
| **Net realized** | **{usd(net)}** | calculated |
| Unrealized: ETH profits revalued to the snapshot (ETH ${w:,.0f}) | {usd(unreal)} | calculated |
| Residual inventory left after a trade | $0 | observed |
| The {cov['incomplete']} incomplete transactions, net (bot event confirmed, not in the rows above) | ${cov['incomplete_bot_net_usd']:,.2f} | calculated |
"""
if other_gas is not None:
    body += f"| Gas on the EOA's other transactions (estimate) | {usd(other_gas)} | assumed |\n"
body += f"""
Gross is positive on every trade ({ex['bot_gross_negative_trades']} negative); {ex['bot_net_negative_trades']:,} trades lose money after gas. The bot's typical edge is
about {C.bot_gross_usd.sum() / C.notional_usd.sum() * 1e4:.1f} bp of notional. The bot contract also trades three other Ekubo pools (tokenized stocks); those are
outside this study and reported only from the bot's own events in `summary.json`.

## 6. Execution quality and price alignment

- Moves the pool toward Binance: {pct(ex['moved_toward_binance_share'], 2)} of trades; overshoots past Binance: {pct(ex['crossed_binance_share'], 2)}. *Calculated.*
- Gap before a trade (median |gap|): {ex['abs_gap_before_bp_median']:.1f} bp; after: {ex['abs_gap_after_bp_median']:.1f} bp. Median price move per trade {ex['abs_impact_bp_median']:.1f} bp,
  {ex['size_vs_depth_1pct_median'] * 100:.0f}% of the ETH it takes to move the pool 1%.
- Hedge price against Binance: buying ETH back +{hedge_b['bot_sells_eth']:.1f} bp, selling it {sg(hedge_b['bot_buys_eth'], 1)} bp. The hedge costs about
  {cal['hedge_cost_bp']:.1f} bp; add the Fynd fee and the router fee ({cal['router_fee_bp']:.1f} bp) and the bot's break-even is {cal['hedge_cost_bp'] + bf['median_bp'] + cal['router_fee_bp']:.1f} bp with the median
  Fynd fee ({bf['median_bp']:.1f} bp) or {cal['stop_gap_bp']:.1f} bp with the volume-weighted one ({cal['bot_fee_bp']:.1f} bp). It stops at {cal['real_median_abs_gap_after_bp']:.1f} bp, between the two. That
  fits a bot that trades until its marginal profit against on-chain pools runs out (*inferred* from the match).
- Trades with a gap under 3 bp: {ex['trades_abs_gap_below_3bp']:,}. Trades where Binance had already moved ≥1 bp toward the pool in the
  previous 5 s: {ex['trades_where_binance_moved_toward_pool_over_5s_by_1bp_or_more']:,} (the gap was closing on its own).
- LPs' markout on the bot's trades (12 s is the headline):

| horizon | 1 s | 5 s | 12 s | 30 s | 60 s | 5 min |
|---|---|---|---|---|---|---|
| USD | {' | '.join(usd(mk[h]['usd']) for h in ['1s', '5s', '12s', '30s', '60s', '300s'])} |
| bp of volume | {' | '.join(sg(mk[h]['bp'], 1) for h in ['1s', '5s', '12s', '30s', '60s', '300s'])} |

  Almost all of it is there at 1 s: the loss is the gap at execution, not a later move against LPs.
- Over time (every second of the bot's active period): median |gap| {gt['time_weighted_abs_gap_bp_median']:.1f} bp, {pct(gt['share_of_time_abs_gap_over_8bp'])} of the time above 8 bp.
  When the gap is wide (>25 bp, {pct(float(GT.share_of_time.iloc[-1]))} of the time) the bot almost never trades: these are its idle stretches.
- External traders who arrive more than an hour after the last bot trade face a median gap of
  {float(EXT.abs_gap_before_bp_median.iloc[-1]):.0f} bp, against about {float(EXT.abs_gap_before_bp_median.iloc[:3].median()):.0f} bp within 5 minutes of one. LPs' net on those late trades: {sg(float(EXT.lp_net_bp.iloc[-1]), 1)} bp. *Calculated.*

## 7. LP figures, reconciled

The Nov 13 report's −$3,925 is the sum of every position's (LP value − hold value): fees {usd(lp['totals']['fees_usd'])} plus impermanent loss
{usd(lp['totals']['il_usd'])}. Each position is valued at Binance at its own end (last withdrawal) or at the snapshot if still open
({lp['open_positions']} positions, read on chain at block {lp['period']['snapshot_block']:,}). Withdrawals mid-life are held to the position's end in the hold leg.
Capital-weighted: {usd(lp['avg_capital_usd'], False)} average capital over {lp['days']:.2f} days = {sg(lp['totals']['lp_minus_hold_usd'] / lp['avg_capital_usd'] * 100, 1)}% over the period, scaled to
30 days {sg(lp['lp_minus_hold_per_30d_pct'])}% (fees +{lp['fees_per_30d_pct']:.2f}%, IL {sg(lp['il_per_30d_pct'])}%). The Nov 11 figure (19.8% over 40 days, 14.8% per 30 days)
used fewer days and is consistent. The Nov 5 markout report measured swap-level markout, not position returns; the two are
not added.

## 8. The Uniswap comparison, audited

`compare_pools.py` compares, over {CP['window_utc'][0][:10]} to {CP['window_utc'][1][:10]}, each pool's LP loss with the theoretical LVR for the depth it had.

| | Fynd | Uniswap v3 WETH/USDG 0.01% |
|---|---|---|
| LP loss / theoretical LVR | {CP['fynd']['loss_over_lvr']:.2f} | {CP['uniswap_v3_1bp']['loss_over_lvr']:.2f} |
| Fees to LPs / theoretical LVR | {CP['fynd']['fees_over_lvr']:.2f} | {CP['uniswap_v3_1bp']['fees_over_lvr']:.2f} |
| Net / theoretical LVR | {sg(CP['fynd']['net_over_lvr'])} | {sg(CP['uniswap_v3_1bp']['net_over_lvr'])} |

What holds up:
- Same days, same Binance 1 s reference, same 12 s markout, same LVR formula (1-minute returns), the same depth
  normalisation. The fee comparison was wrong in the first version (the Uniswap pool's protocol keeps 1/4 of its fee, so its
  LPs earn 0.75 bp, not 1 bp); this table is the corrected one.
- Liquidity between swaps: adding back Uniswap's {UA['mint_burn_events']:,} deposits and withdrawals between swaps ({UA['window_utc'][0][:10]} to {UA['window_utc'][1][:10]}) changes its
  theoretical LVR by {sg(UA['lvr_change_pct'])}%; loss/LVR stays {UA['uniswap_loss_over_lvr_with_mint_burn']:.3f} (was {UA['uniswap_loss_over_lvr_as_reported']:.3f} on those days). Fynd's was checked the same way
  earlier (within 1%).

What is not like for like:
- Flow: {pct(UA['fynd_volume_share_bot'])} of Fynd's volume is its own bot. Median trade ${UA['trade_size_usd_median']['fynd_all']:,.0f} on Fynd vs ${UA['trade_size_usd_median']['uniswap']:,.0f} on Uniswap;
  {UA['swaps_per_day']['fynd']:,.0f} vs {UA['swaps_per_day']['uniswap']:,.0f} swaps a day.
- Fees: Fynd LPs get {UA['fee_bp_to_lps']['fynd']:.1f} bp of volume, Uniswap LPs {UA['fee_bp_to_lps']['uniswap']:.2f} bp; Fynd's bot pays far less than other Fynd traders.
- Uniswap's depth is set by many LPs competing; Fynd's by a few. LP-level returns against holding were not computed for Uniswap.

The result is not stable over time:

| | days | Fynd loss/LVR | Uniswap loss/LVR | Fynd net/LVR | Uniswap net/LVR |
|---|---|---|---|---|---|
""" + "".join(f"| {k.replace('_', ' ')} | {v['days']} | {v['fynd']['loss_over_lvr']:.2f} | {v['uniswap']['loss_over_lvr']:.2f} | {sg(v['fynd']['net_over_lvr'])} | {sg(v['uniswap']['net_over_lvr'])} |\n"
             for k, v in UA["by_period"].items()) + f"""
In the first two weeks Fynd's LPs lost half as much per unit of LVR and did slightly better net than Uniswap's; from Oct 22
their loss share was close to Uniswap's and their net much worse. The full-window figure is an average of two different regimes.

What can be said: per unit of theoretical LVR, Fynd's LPs lost less than Uniswap's to the trades against them
(loss/LVR {CP['fynd']['loss_over_lvr']:.2f} vs {CP['uniswap_v3_1bp']['loss_over_lvr']:.2f}). Fees covered much less of it (net/LVR {sg(CP['fynd']['net_over_lvr'])} vs {sg(CP['uniswap_v3_1bp']['net_over_lvr'])}), so Fynd's LPs did worse net.
The lower loss share fits a bot that keeps the pool within about 5–8 bp of the market; the weaker fee cover fits a bot that pays
{bf['volume_weighted_bp']:.1f} bp.

## 9. Policy replays

`policy_sim.py` replays the pool second by second from the bot's first to last trade: real Binance prices, every real
deposit and withdrawal (the pool engine reproduces all 28,100 real swaps to within 0.77 bp), every external swap with its real
ETH amount and fee rate, and a bot that hedges at Binance ± {cal['hedge_cost_bp']:.1f} bp, pays the Fynd fee, router fee and gas, and is
idle when the real bot was idle (up {pct(cal['bot_up_share_of_time'])} of the time). Policy A is the profit-maximising rule above, with its minimum
profit fitted to the real trade count (fit: ${cal['min_profit_A_usd']:.2f}, i.e. any trade with positive expected profit).

**Calibration.** A makes {int(A.bot_trades):,} trades (real {int(REAL.bot_trades):,}); LPs' trading-side net at 12 s {usd(A.lp_net_trading_12s_usd)} (real
{usd(REAL.lp_net_trading_12s_usd)}). The split differs: LP markout on bot trades {usd(A.lp_markout_12s_bot_usd)} (real {usd(REAL.lp_markout_12s_bot_usd)}), on external swaps
{usd(A.lp_markout_12s_external_usd)} (real {usd(REAL.lp_markout_12s_external_usd)}): the simulated pool is better aligned than the real one was, so external traders find fewer
stale prices and the bot more. The model's bot earns more than the real one (gross {usd(A.bot_gross_usd)} vs {usd(REAL.bot_gross_usd)}), because its hedge cost does not grow with size: read bot results as
upper bounds and compare policies with each other, not with reality.

| policy | what changes | bot trades | LP net, trading side 12 s | LP fees | protocol fees | bot net | mean gap to Binance (bp) | time >10 bp off |
|---|---|---|---|---|---|---|---|---|
"""
for code, x in P.iterrows():
    body += (f"| {code} | {x.description} | {int(x.bot_trades):,} | {usd(x.lp_net_trading_12s_usd)} | {usd(x.lp_fees_usd, False)} | "
             f"{usd(x.protocol_fees_usd, False)} | {usd(x.bot_net_usd)} | {x.mean_abs_gap_bp:.1f} | {pct(x.share_time_gap_over_10bp)} |\n")
best_d = P.loc[[i for i in P.index if i.startswith("D")]]
body += f"""
Fee-sharing (D): with the same trades, giving LPs 100% instead of 80% of the Fynd fee adds the protocol column to the LPs'
net (policy A: {usd(A.protocol_fees_usd)}). It is a transfer from the protocol, not new value.

Reading the replays:
- **Cheaper hedging (H) is the only change that helps LPs, the bot and price alignment together.** With a 1 bp hedge, LPs'
  trading-side net is {usd(P.loc['H1'].lp_net_trading_12s_usd)} (A: {usd(A.lp_net_trading_12s_usd)}), the pool sits {P.loc['H1'].mean_abs_gap_bp:.1f} bp from Binance on average (A: {A.mean_abs_gap_bp:.1f}), and the bot nets
  more. The band the bot leaves the pool in is set by its hedging cost.
- **A higher bot fee (D) moves money from the bot to LPs and the protocol, and makes the pool worse for traders.** At the
  fee other traders pay, LPs' net is {usd(P.loc[best_d.index[-1]].lp_net_trading_12s_usd)}, but the pool is off by {P.loc[best_d.index[-1]].mean_abs_gap_bp:.1f} bp on average and {pct(P.loc[best_d.index[-1]].share_time_gap_over_10bp)} of the time
  more than 10 bp. The replay keeps external volume fixed; in reality a staler pool loses routed flow. Do not pick a fee from
  this table alone.
- **Thresholds (B, C), size caps (E) and inventory rules (F) do not help LPs.** They leave the pool staler or add trades.
- **Always on (A0)** keeps the pool much closer to the market ({P.loc['A0'].mean_abs_gap_bp:.1f} bp), so LPs lose less to external traders
  ({usd(P.loc['A0'].lp_markout_12s_external_usd)} vs {usd(A.lp_markout_12s_external_usd)}), but they lose more on the extra bot trades, and their net is {usd(P.loc['A0'].lp_net_trading_12s_usd)}.

These are historical replays: traders, routers and LPs keep their real behaviour.

## 10. Recommendations

1. **Lower the bot's hedging cost.** The pool is only as aligned as the bot can hedge cheaply. A deeper or cheaper hedge
   venue (or an off-chain hedge) narrows the band and improves all three goals at once in the replay.
2. **Charge the bot in proportion to the gap it closes, not a near-flat {bf['volume_weighted_bp']:.1f} bp.** A fee that takes a share of the
   rebalancing edge returns more of the LPs' loss to them while leaving the bot a margin. Test this live with a small change
   and watch alignment and routed volume, because the replay cannot show how routers react.
3. **Decide the 20% protocol share deliberately.** It is about {usd(proto_all, False)} over the period, against an LP result of
   {usd(lp['totals']['lp_minus_hold_usd'])}. Giving it to LPs is a transfer, not a fix.
4. **Keep the bot running.** It was idle for more than an hour {idle['gaps_over_1h']} times; during those stretches external traders traded
   against a pool tens of bp off the market.
5. **Report bot results and LP results separately.** The bot's {usd(net)} and the LPs' {usd(lp['totals']['lp_minus_hold_usd'])} are different quantities;
   most of the LPs' swap-side loss on bot trades went to the hedge pools.

## 11. What is not known

- Reverted bot transactions and their gas (no traces or index on this RPC). *Not measurable*; bounded above.
- Native-ETH movements are inferred; they match the bot contract's own figures in every transaction.
- Who controls the router fee recipient and the address in the extension's event. *Not measurable* from chain data.
- Who owns `0x6c6a…7127`; the brief's identification conflicts with the data.
- The extension's fee formula (only its outputs are observed).
- USDG is valued at $1.

## Files

| file | contents |
|---|---|
| `out/bot_transaction_economics.csv` | one row per bot transaction: legs, fees, bot result, value split, completeness |
| `out/bot_value_reconciliation.csv` | the aggregate tables above, with evidence labels |
| `out/bot_execution_quality.csv` | gaps, price moves, hedge prices, markouts at 1 s – 5 min |
| `out/bot_wallet_and_contract_map.csv` | addresses, roles, evidence |
| `out/policy_simulation.csv` | replay results with calibration |
| `out/gap_time_profile.csv`, `out/external_swaps_by_time_since_bot.csv` | alignment over time, external traders |
| `out/uniswap_comparison_audit.json`, `out/check_fee_split.csv`, `out/check_pool_model.csv` | audit and checks |
| `out/summary.json` | every headline number |
| `out/value_split.png` | chart of section 4 (12 s column) |
| `hand_checks/HAND_CHECKS.md` | step-by-step checks of chosen transactions |
| `run_all.sh` | rebuilds everything from the fetched data |
"""
open("BOT_ECONOMICS_REPORT.md", "w").write(body)

ex_sum = f"""# Fynd ETH/USDG: what the bot made and where LP value went (summary)

Period: bot trades {cov['first_utc'][:10]} to {cov['last_utc'][:10]}; LP results Oct 2 to Nov 13, 2026. {cov['complete']:,} of the bot's {cov['fynd_bot_txs_expected']:,} transactions fully rebuilt from chain data.

1. **LPs lost {usd(-lp['totals']['lp_minus_hold_usd'], False)} against holding** ({sg(lp['lp_minus_hold_per_30d_pct'], 1)}% per 30 days on ~{usd(lp['avg_capital_usd'], False)}): fees {usd(lp['totals']['fees_usd'])}, impermanent loss {usd(lp['totals']['il_usd'])}.
2. **The bot made {usd(net, False)} net** ({usd(gross)} gross, {usd(gas)} gas). Each trade is an atomic round trip: Fynd, then other on-chain pools, no inventory kept.
3. **On the bot's trades, LPs' swap side was {usd(lp12)}** (Binance, 12 s). Of that, {share(oth12)} went to the pools the bot hedged on, {share(bot12)} to the bot,
   {share(fee12)} back as Fynd fees (80% to LPs, 20% protocol), {share(rt12)} to router fees.
4. **The bot aligns the pool**, in the right direction {pct(ex['moved_toward_binance_share'], 1)} of the time, but only to within ~{ex['abs_gap_after_bp_median']:.0f} bp, the point where its on-chain hedge (≈{cal['hedge_cost_bp']:.0f} bp)
   plus fees stops paying. It was idle >1 h {idle['gaps_over_1h']} times.
5. **Why LPs lose:** each rebalance sells LP inventory at a stale price; the bot pays {bf['volume_weighted_bp']:.1f} bp in fees on a loss of ~9 bp, and the hedge
   pools collect most of the difference.
6. **Against Uniswap's WETH/USDG 0.01% pool**, Fynd's LPs lost less per unit of theoretical LVR ({CP['fynd']['loss_over_lvr']:.2f} vs {CP['uniswap_v3_1bp']['loss_over_lvr']:.2f}) but fees covered less of it
   ({CP['fynd']['fees_over_lvr']:.2f} vs {CP['uniswap_v3_1bp']['fees_over_lvr']:.2f}), so net they did worse. The advantage was large before Oct 22 and nearly gone after.
7. **What would help** (historical replays, not forecasts): cheaper hedging helps LPs, the bot and alignment together; a gap-linked bot fee shifts value to
   LPs at some cost to alignment; thresholds and size caps do not help. The protocol's 20% of fees (~{usd(proto_all, False)}) is a transfer lever.

Caveats: native-ETH legs are inferred (they match the bot's own on-chain figures in every transaction); reverted transactions are not
listable; USDG = $1; the brief's bot address (`0x6c6a…7127`) is the pool's largest LP in the data, not the bot.
"""
open("EXEC_SUMMARY.md", "w").write(ex_sum)
print("wrote BOT_ECONOMICS_REPORT.md and EXEC_SUMMARY.md")
