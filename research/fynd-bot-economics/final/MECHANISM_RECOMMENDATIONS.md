# Mechanism recommendations for Fynd ETH/USDG

Ranked by evidence and by how well each serves all three goals: LP returns, sustainable bot economics, and execution quality for traders.
Replay numbers come from `policy_sim.py`'s model (historical replay over Oct 13 – Nov 13; external traders, routers and LPs as they were). The
model's bot earns more than the real one, so compare rows with each other, not with history.

Baseline in the same model (today's rules): LPs' trading-side net −$3,442, bot net +$803, mean gap 9.2 bp.

## 1. Hedge on the deepest on-chain pool

**Evidence (calculated from observed trades).** In 24,199 trades the bot never used Uniswap v3 WETH/USDG 0.01% (`0x52e65b17…71ca`).
At that pool's price and liquidity just before each trade, hedging there would have cost 0.31 bp against Binance instead of
4.26 bp, cheaper on 95% of trades. The current hedges pay a fee of ~2.1 bp, move thin pools by
~1.2 bp, and land on pools already ~1.0 bp off the on-chain market.

**Replay.** Hedge at 1 bp: LPs −$3,072, bot +$1,096, gap 7.8 bp. Even a 25% cut helps all three (−$3,349,
+$870, 8.4 bp).

**How to test.** Quote the 0.01% pool alongside the current route on every trade for a week without changing execution; then switch and
compare realized hedge cost. Risks: other arbitrageurs on that pool, and same-block competition; the counterfactual assumes its state is
available to the bot.

## 2. Use the bot's new margin to raise its Fynd fee to about 3–4 bp

**Evidence.** The bot pays 1.7 bp (median 0.5 bp; zero on 23% of trades) while external traders pay
~20 bp. On its trades LPs give up ~9 bp, of which the fee returns ~2.

**Replay.**

| hedge | Fynd fee on bot trades | LPs' net | bot net | Fynd's 20% | mean gap |
|---|---|---|---|---|---|
| today | 1.7 bp | −$3,442 | +$803 | $370 | 9.2 |
| 1 bp | 2.5 bp | −$2,777 | +$977 | $544 | 8.0 |
| 1 bp | 3 bp | −$2,663 | +$959 | $581 | 8.8 |
| 1 bp | 4 bp | −$2,378 | +$836 | $638 | 8.9 |
| 1 bp | 5 bp | −$2,206 | +$773 | $679 | 9.6 |
| −50% | 3 bp | −$2,806 | +$841 | $531 | 8.9 |
| −50% | 4 bp | −$2,580 | +$775 | $585 | 9.6 |

With hedging at 1 bp, a 4 bp bot fee leaves the bot about where it is today (+$836 vs +$803) while LPs lose
$1,064 less. Without cheaper hedging, the same fee would cut the bot's trading and leave the pool staler
(`out/policy_simulation.csv`, D rows). **Do the fee change only after recommendation 1.** A fee linked to the gap the bot closes would target the
same thing more precisely; it was not replayed.

## 3. Keep the bot running and reacting, after 1 and 2

**Evidence.** The bot was idle for more than an hour 32 times (136 of 739 hours); external traders arriving
then met a pool a median ~31 bp off. While active, it traded in only ~5–8% of seconds even with Fynd 10–15 bp off.

**Replay.** Always on alone helps alignment (5.6 bp) but costs LPs (−$3,685 vs −$3,442). Combined with 1 and 2
(always on, hedge at 1 bp, 4 bp fee): LPs −$2,349, bot +$1,204, Fynd's 20% $725, gap 5.4 bp: better on all three goals.

## Not recommended (from the replays)

Minimum-gap thresholds, minimum-profit rules, trade-size caps and inventory-aware thresholds all left LPs worse or the pool staler
(`out/policy_simulation.csv`, B, C, E, F rows). Giving LPs the protocol's 20% (~$521 over the period) would help LPs by moving money
from Fynd, not by improving the mechanism; it is a separate decision.

## What the replays cannot show

How routers and external traders would respond to a better-aligned or more expensive pool, whether the 0.01% pool's liquidity would stay
when the bot trades on it, and live latency. Test each change with a short live trial and track realized hedge cost, LP fees, the bot's
net and the gap to the market.
