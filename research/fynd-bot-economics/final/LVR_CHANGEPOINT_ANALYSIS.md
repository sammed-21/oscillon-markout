# Why Fynd's loss/LVR ratio rose in October 2026

Question: Fynd's LP loss as a share of theoretical LVR was 0.48 over Oct 7–21 and 0.88 from Oct 22 (Uniswap's 0.01% pool: ~0.95 both times).
Data: `final/data/changepoint_daily.csv` (one row per day, all from local files). Ratios below are sums of loss over sums of LVR.

## The change is at Oct 17, not Oct 22

| period | Fynd loss/LVR | Uniswap loss / LVR | Fynd theoretical LVR ($/day) | Fynd depth ($ per 1% move) | LP range width (bp, capital-weighted) | mean |gap| to Binance (bp) | bot trades / day | bot idle hours / day (gaps >1 h) | bot share of volume | external volume ($/day) | bot Fynd fee (bp) | external fee to LPs (bp) | hedge cost (bp, median) | ETH volatility (% ann.) | bot trade size (median $) | active LPs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Oct 7–12 (no bot) | 0.28 | 0.98 | 443 | 35,528 | 51 | 17 | 0.00 | 24 | 0.00 | 59,756 | – | 12 | – | 42 | – | 2.00 |
| Oct 13–16 (bot starts, 54 h pause) | 0.58 | 0.92 | 555 | 11,972 | 120 | 23 | 468 | 20 | 0.53 | 73,528 | 2.34 | 16 | 3.36 | 54 | 228 | 2.50 |
| Oct 17–21 | 0.91 | 0.95 | 145 | 5,547 | 789 | 6.03 | 750 | 2.07 | 0.95 | 9,003 | 1.12 | 8.06 | 3.74 | 47 | 180 | 5.00 |
| Oct 22 – Nov 11 | 0.88 | 0.96 | 159 | 4,948 | 508 | 6.26 | 772 | 1.27 | 0.93 | 9,793 | 1.66 | 3.04 | 4.26 | 49 | 156 | 4.00 |

(Medians of daily values; LVR, external volume and bot trades are daily means.)

Oct 22 is where one of the Uniswap data files starts, not a market event. The step happens on Oct 17: from that day the bot trades every day
with little idle time, LP ranges are about 7x wider, depth per 1% is about
2.4x lower, and the pool sits 19 → 6 bp from Binance (medians).

## Candidate causes

Arrows compare medians of daily values before Oct 17 (Oct 7–16, including the six days with no bot) with Oct 17 onward.

| factor | what the data shows | supports the change? |
|---|---|---|
| Arbitrage activity | No bot before Oct 13; 54 h pause Oct 15–17; from Oct 17 the bot trades daily. On days with the bot idle <2 h, loss/LVR is 0.86 before Oct 22 and 0.94 after. | **yes**: most of the early gap disappears on comparable days |
| Liquidity and range width | Deep, narrow liquidity Oct 9–16; wide ranges and ~$5k per 1% after. Theoretical LVR scales with depth, so a deep pool nobody arbitrages has a large LVR and a small realized loss. | yes, together with the above |
| Bot vs external flow | Before: much of the loss came from external swaps; after: almost all from bot swaps (bot share of volume 0% → 94%). | consistent; a consequence of the bot running |
| Trade size | Bot median trade $228 → $158. | weak |
| Hedge venues and cost | Hedge cost median 3.4 → 4.2 bp. | weak |
| Fees | Bot fee 2.34 → 1.52 bp; external LP fee 13.2 → 3.2 bp (mix of traders, cause not observed). | affects fees/LVR, not loss/LVR |
| Volatility | 48% → 47% annualised. | no |
| Extension / configuration | Extension events: 0xd59d72ec 52,903; the per-block event's fields (`share`, address) never change. Code changes cannot be read (no historical state). | no evidence of a change |

Correlation of the daily ratio with each factor (36 days; these move together, so this is description, not cause):
Uniswap loss / LVR +0.27, Fynd theoretical LVR ($/day) -0.61, ETH volatility (% ann.) +0.26, Fynd depth ($ per 1% move) -0.83, mean |gap| to Binance (bp) +0.09, bot trades / day +0.58, bot idle hours / day (gaps >1 h) -0.66, bot Fynd fee (bp) -0.16, hedge cost (bp, median) -0.03, bot trade size (median $) -0.42, external volume ($/day) -0.48, external fee to LPs (bp) +0.08, bot share of volume +0.68, active LPs +0.55, LP range width (bp, capital-weighted) +0.63.

## Conclusion

The early "advantage" (loss/LVR 0.48) is mostly days when nobody was arbitraging the pool. The pool was stale and the LPs booked less loss
than the continuous-arbitrage theory assumes; stale prices are not protection, they are loss postponed or given to whoever trades next. With the bot running,
Fynd's ratio is close to Uniswap's. Arbitrage activity, depth and range width all changed around Oct 17, so the data cannot say which one
drives it. It does not show Fynd's design protecting LPs better than Uniswap's, or worse.
