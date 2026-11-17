# Audit of `final/il_vs_bot_capture.png`

Scope: every number in the chart, rebuilt from raw transaction receipts with a separate method (`audit/recon.py`), then compared
with the research outputs. Nothing in `out/`, `final/` or the checked LP report was modified; the chart was not regenerated.
Audit run: 2026-11-17 08:04 UTC.

Labels: **[V]** verified directly from on-chain data · **[R]** recomputed and independently reconciled · **[I]** inferred ·
**[E]** estimated · **[N]** not verifiable with available data.

## Verdict

| chart number | audit result | status |
|---|---|---|
| LP net loss on bot trades $3,422 | correct as a figure ($3,422.01), but it covers all 24,258 swaps with LP fees attributed from FeesAccumulated, while the bars below it cover the 24,199 complete transactions with fees at 80% per tx | **needs correction** (mixed populations) |
| pools the bot hedged on $2,352 | $2,351.77 [R]; valued 12 s after each trade; includes ~$440 of later market movement and $424 of routes that cannot be split; $3.70 too low (see fee finding) | **needs caveat and small correction** |
| gas $443 | $443.46 [V for ETH, R for USD]; complete trades only; excludes the 844 unexplained EOA transactions | correct; **caveat** |
| bot kept $295 | $295.09 [R], valued at execution; the same figure at 12 s is $295.05 | correct; **valuation mixed with the 12 s bars** |
| router fees $178 | $177.57 at execution, $177.52 at 12 s [R] | correct to the dollar |
| Fynd's 20% $152 | $152.06 at execution [R]; **$0.74 too high** | **needs small correction** |
| "before gas it made $739" | $738.55 [R] | correct |
| bottom panel, real history | reproduces history (re-anchored replay); per position within $0.18 of the checked report | can be presented |
| bottom panel, no bot / outside arbitrageur | model counterfactuals; cannot be validated against history; open-loop replays of this model drift | **present only with explicit caveats** |

## 1. Top panel: the $3,422 and its parts

**Per-transaction reconstruction** (`audit/top_panel_transaction_reconciliation.csv`, one row per tx, 24,258 rows). For every tx: hash,
block, Fynd amounts and execution price, Binance at execution and +12 s with the reference timestamps, U, LP swap side, fee and its source, 80/20
split, LP net, every hedge leg (route column; legs in `hedge_execution_costs.csv`), router fee, bot change per token, bot gross and net, gas.

**Every economic leg counted exactly once.** Each swap event belongs to one party: the Fynd leg to Fynd LPs, every other swap to "hedge pools".
The Fynd fee (charged by the extension outside the pool amounts) and router fees are separate legs. The bot's change is −(sum of all pools'
receipts) − Fynd fee − router fee per asset, so the five parts sum to zero by construction (max |residual| 2.5e-13 USD).
What makes this a test rather than an identity is that the bot's change is checked against three independent records:

| check | what it compares | result on the 24,199 complete txs | label |
|---|---|---|---|
| C1 | bot's USDG change vs USDG Transfer logs to/from the bot's two addresses | 0 mismatches (exact, raw units) | [V] |
| C2 | bot's change in the token it paid in vs the bot contract's profit event | 0 mismatches (exact) | [R] (bot's own event) |
| C3 | the token it did not pay in, left with the bot | 0 in every tx: no inventory kept | [R] |
| C4 | intermediate tokens net to zero over the legs | 104 txs keep an intermediate token inside Ekubo Core: the stock-pool extension's fee on that hedge venue, part of the hedge pools' result | [R] |
| unknown events | logs from contracts the decoder does not know | 59 txs (the same 59 the research excluded); 41 fail C1 | excluded |

**Rebuild vs research, per tx:** bot ETH/USDG change, Fynd fee, router fees, gas and Binance price agree exactly on all 24,199 complete txs. The on-chain reference U differs on 38 txs (max $0.06) because the two rebuilds define "the last Uniswap swap before" slightly differently.

**The chart mixes two populations and two valuation times.** Full precision:

| | chart | this audit, complete txs, 12 s | this audit, complete txs, at execution |
|---|---|---|---|
| LP net loss on bot trades | 3,422.01 (24,258 swaps; LP fee 615.27 from FeesAccumulated attribution) | 3,419.85 | 2,944.23 |
| hedge pools | 2,351.77 (12 s) | 2,351.77 | 1,876.05 |
| bot gross | 738.55 (execution) | 738.51 | 738.55 |
| gas | 443.46 | 443.46 | 443.46 |
| bot net | 295.09 (execution) | 295.05 | 295.09 |
| router | 177.57 (execution) | 177.52 | 177.57 |
| Fynd 20% | 152.06 (execution) | 152.04 | 152.06 |
| parts (hedge + gas + bot net + router + Fynd 20%) | 3,419.95 | 3,419.85 | 2,944.23 |
| residual (LP net loss − parts) | **2.06** | 0.00 | 0.00 |

The chart's 2.06 residual: 5.83 from the 59 incomplete txs,
-3.66 from LP fees attributed from FeesAccumulated (611.84 on complete swaps) instead of 0.8 × each tx's fee
(608.18), and -0.11 from mixing execution and 12 s values.
**$739 − $443 = $296 vs $295** is rounding: 738.55 − 443.46 = 295.09.

## 2. The fee finding: $3.70 counted as Fynd fee that was not

For a bot tx paying USDG into Fynd, the fee is the USDG Transfer net into Ekubo Core minus the USDG the Ekubo pools received. When the hedge
also goes through another Ekubo pool whose extension keeps USDG inside Core, that USDG lands in the "Fynd fee". The FeesAccumulated check
shows it: in 16 intervals (all bot-only, 16 txs with another Ekubo leg) LPs received less than 80% of the computed fee;
the excess is 3.699677 USDG. Every other checkable interval matches.

A second, independent source confirms it: the bot's own event reports the amount it paid in including the fee (word2), so word2 minus
the USDG Fynd received is the fee by the bot's account. Across all 11,512 complete txs where the bot paid USDG, it equals the
Transfer-based fee except in 16 txs, all with another Ekubo leg and all in the 16 flagged intervals; the
difference is 3.699668 USDG (vs 3.699677 from the LP payments; the gap is rounding). The research (`decode.py`) uses the same
Transfer rule, so the error is in both. [R]

Corrected (12 s, complete txs): Fynd fee 760.22 → 756.52; LPs' 80% 608.18 → 605.22;
Fynd's 20% 152.04 → 151.30; hedge pools 2,351.77 → 2,355.47; LP net loss 3,419.85 → 3,422.81.
Bot figures do not change. [R]

## 3. What the $2,352 measures

It is the sum over complete txs of what the other pools received, valued at Binance 12 s after the trade: ETH × B(T+12) + USDG. It is
the bot's hedge execution shortfall against Binance **plus** the market move over the next 12 s. It is not a gross volume and not anyone's
realized profit.

| part | USD | label |
|---|---|---|
| | at execution | 12 s later (the chart) | label |
|---|---|---|---|
| single direct ETH/USDG hedges (22,426 txs) | 1,488.18 | 1,928.09 | [R] |
| routes with several legs, Ekubo or v2 pools (1,773 txs), not split further | 387.87 | 423.68 | [R] |
| **all complete txs** | **1,876.05** | **2,351.77** | [R] |

The difference between the two columns (475.72) is the market move over 12 s on the ETH the pools took.

Decomposition of single direct Uniswap v3/v4 hedges with an on-chain reference (21,764 legs; exact per leg, max residual
1.4e-13; `hedge_execution_costs.csv`):

| part | USD | what it is | who has it |
|---|---|---|---|
| fees paid to the hedge pools | 898.65 | pool fee rate × input | the pools' LPs and, where switched on, their protocol (split not verifiable historically [N]) |
| price impact | 486.12 (all 22,413 decomposed legs) | pool mid before → execution price before fee | a gain to the pool's LPs marked at Binance, reversed by the next arbitrage if prices revert |
| pool already off the on-chain reference | 406.34 | U − pool mid before | same |
| on-chain vs Binance basis | -299.24 | B − U | a measurement effect, nobody's gain |

Pre-swap mid prices are rebuilt from the post-swap price and liquidity assuming constant liquidity inside the swap [I]; median distance from
U is 1.2 bp. By pool, direction and size: `audit/data/hedge_by_pool.csv`, `hedge_by_direction.csv`, `hedge_by_size.csv`;
by route: `hedge_by_route.csv`. Relative to the hedge notional (4,477,340.34 USD), the shortfall at execution is
4.19 bp.

## 4. Bot profitability (`bot_pnl_reconciliation.csv`)

- Gross $738.55 − gas $443.46 = **$295.09** on complete txs [R]. Kept: 0.180115952 ETH and
  325.195541 USDG; no other token left in any tx (C3) [R].
- The bot events sum to 0.180655536 ETH and 325.502350 USDG over all 24,258 txs; on the complete txs they equal the
  rebuild exactly (0.180115952 ETH, 325.195541 USDG). **Correction to the research wording:** "the bot's
  events add up to exactly the rebuilt amounts, 0.180656 ETH and 325.50 USDG" holds only for the complete txs (0.180116 / 325.20). The 59 other
  txs rest on the bot's own report.
- **Partly circular check:** when the bot pays ETH into Fynd, the Fynd fee comes from the bot's event (word2), so C2 then checks the hedge
  output, not the fee. The fee is checked independently by FeesAccumulated: all 8,911 bot-only ETH intervals pay LPs exactly 80% [R].
- 59 incomplete txs: bot event gross $1.39, gas $1.31 (bot's own report; not reconciled).
- **Gas from the 844 other transactions is not in the $443.** 36,024 nonces − 24,258 Fynd trades − 10,922 trades on other pools
  = 844 [I]. Their hashes are unknown (no tx-list API, no traces), so their gas is [N]; estimate $14.97
  (count × median trade gas × median price) [E]; the research used $12.51. Report separately; do not fold into a confirmed figure.

## 5. Fees (`fee_allocation_audit.csv`, intervals in `data/fee_intervals.csv`)

- Extension share field: 0x3333333333333333 on 52,903 events = 0.2 exactly [V].
- Each FeesAccumulated pays LPs the fees of the swaps since the previous one (it is emitted before the swap in the same tx). Intervals checked:
  ETH 8,914 / 8,914 at 80%; USDG 11,915 / 11,931 (exact or within the 6-decimal rounding unit), the 16 others
  being the fee finding above. External-only intervals: 2,154 / 2,154; mixed: 276 / 276 [V for USDG; ETH external fees are native and [N]].
- Bot fees (complete txs, at execution): $760.29 → LPs $608.23, Fynd $152.06 (before the $3.70 correction).
  5,511 bot txs paid no Fynd fee.
- External fees observed (USDG output): $893.15 on 2,434 of 3,843 external swaps.
- **$2,069 is the LPs' 80% share** (position-level, checked report: $2,068.59); FeesAccumulated valued when paid:
  $2,085.81 [V]. Gross implied $2,607.27; Fynd's 20% implied $521.45 [I]: the 20% is never
  emitted or transferred in these logs, so where it goes is [N].
- No overlap: the $152 is 0.2 × the Fynd fee legs; hedge pools are other pools' swap events, router fees the router's event; each token unit
  is in exactly one leg (C1–C3).

## 6. Bottom panel (`replay_validation.csv`)

- **Model, per swap** (all 28,100 Fynd swaps, re-anchored to the logged price after each): USDG amount error max
  0.77 bp ($0.0020), cumulative $0.0005;
  post-swap price max 0.28 bp; liquidity off by >1% on 1 swap (a price exactly on a range
  boundary; its amounts are still right); 2 swaps partly unfilled in the model [R].
- **Per position** (full period): 176 positions with one deposit and one withdrawal match the checked LP report within
  $0.18 each ($0.50 in total) [R].
- **Token conservation:** positions' token change vs swaps: -1.39e-05 ETH,
  +0.0304 USDG (from re-anchoring) [R].
- **Real history** (scenario A) re-anchors to logged prices, so it is history; its LP swap side on bot swaps equals the direct calculation to
  2.7e-04 USD. Its fees use the FeesAccumulated attribution for bot swaps ($615), not 0.8 × fee.
- **Open loop** (no re-anchoring, real trade sizes): the model's price first passes 100 bp from history on Oct 9 and later drifts without bound
  (median error 5.5 bp, 90th percentile 135,321 bp). Fixed historical trade sizes without the arbitrage that kept
  the price aligned are not self-correcting. Scenarios B and C are open loop by design, so they **cannot be validated against history**.
- How B and C treat orders: each external swap keeps its historical ETH amount and second; its limit is 2% from Binance; it fills along the
  curve up to the limit; the remainder is dropped (no retry, no rerouting) and counted as unfilled; fees are charged on the filled amount at
  that trader's historical rate, LPs get 80%. No order is rejected other than by the limit. B: no bot and no other arbitrage. C: an
  arbitrageur checks every second, trades when the gap exceeds hedge cost (3.89 bp) + its fee (19.8 bp) + router
  (0.40 bp), moves the pool to that band, and only if its profit covers gas.
- Rounding in C: -5,200.52 + 3,657.25 = -1,543.27; the displayed −5,201 + 3,657 = −1,544 is
  rounding of each part.

## 7. Sensitivity (`sensitivity_analysis.csv`)

| valuation | LP net loss | hedge pools | bot gross | bot share | hedge share |
|---|---|---|---|---|---|
| Binance at execution (T-1) | 2,944 | 1,876 | 738.6 | 25% | 64% |
| Binance 1s | 3,341 | 2,273 | 738.5 | 22% | 68% |
| Binance 5s | 3,404 | 2,336 | 738.5 | 22% | 69% |
| Binance 12s | 3,420 | 2,352 | 738.5 | 22% | 69% |
| Binance 30s | 3,467 | 2,399 | 738.5 | 21% | 69% |
| Binance 60s | 3,416 | 2,348 | 738.5 | 22% | 69% |
| Binance at execution, txs with an on-chain reference | 2,907 | 1,864 | 725.0 | 25% | 64% |
| on-chain reference (Uniswap v3 0.01%) at execution | 3,223 | 2,180 | 724.8 | 22% | 68% |

- **The horizon changes the LP loss, not the bot's result.** LP net loss on bot trades is $2,944 at execution and
  $3,341–$3,467 at 1–60 s; the bot's gross is $738.5–$738.6 at every horizon (it
  keeps almost nothing in ETH). Most of the change happens in the first second ("at execution" is Binance as of one second before the block's timestamp): the bot trades on moves Binance has started and that continue [I].
  The chart uses 12 s, near the top of the range; at execution the bot's share is 25%, at 12 s 22%.
- **Binance vs on-chain:** on the 23,543 txs with an on-chain reference, LP net loss is $2,907 at Binance and
  $3,223 at the Uniswap 0.01% price; the bot's gross barely moves.
- Missing transactions: the 59 incomplete txs change the LP figure by $5.83.
- Rounding: displayed parts differ from totals by at most $1–2; no rounding issue affects a conclusion.

## What can be presented to Fynd

**As is:** bot gross $738.55 and net $295.09 after trade gas (state "complete transactions; 59 others add +$0.08 by the bot's own
report"); gas; router fees; the 80/20 fee split and that $2,069 is the LPs' 80%; the horizon table; the real-history replay.

**Needs correction before presenting:**
1. Top panel on one population and one valuation time. At 12 s (complete txs, fee corrected): LP net loss $3,422.81 = hedge pools
   $2,355.47 + gas $443.46 + bot net $295.05 + router $177.52 + Fynd $151.30. Or the same at execution.
2. Fynd fee figures: subtract $3.70 (USDG kept by other Ekubo pools' extensions); Fynd's 20% on bot trades ≈ $151.32.
3. Wording: the bot events match the rebuild exactly on the 24,199 complete txs (0.180116 ETH, 325.20 USDG), not 0.180656 / 325.50.

**Needs explicit caveats:**
1. The hedge pools' figure is a shortfall against Binance plus 12 s of market movement; about $899 is fees; the rest is not profit anyone
   necessarily keeps.
2. Valuation horizon: state the LP loss range ($2,944–$3,467) and that the bot's figure does not depend on it.
3. Gas of the 844 other EOA transactions is estimated ($13–$15) and not verifiable.
4. Scenarios B and C are model counterfactuals that cannot be validated against history; present them as illustrations of the mechanism,
   not as estimates, and never as forecasts.
5. Fynd's 20% is inferred from the share field and the 80% LP payments; where it goes is not visible in these logs.

## Files

`audit/recon.py` (raw receipts → per-tx), `audit/analyze.py` (tables), `audit/replay_check.py` (model validation), `audit/write_audit.py` (this report),
`audit/run_audit.sh` (all). Formula for each column: `analyze.py` function `val()` and the docstring of `recon.py`.
