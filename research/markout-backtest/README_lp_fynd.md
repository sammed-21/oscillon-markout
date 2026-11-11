# Fynd AMM ETH/USDG: LP return vs holding

Same pool as `README_flow_fynd.md`. Every LP position from the pool's first deposit (2026-10-02 06:06 UTC) to snapshot
block 111,478,410 (2026-11-11 05:53 UTC).

## Run

```
python3 fetch_ekubo_lp_positions.py ...   # positions, owners, fees paid in, open positions read on chain (see docstring)
python3 fetch_ekubo_swaps.py ... --from-block 109619486 --to-block 111478410 --out data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv
python3 lp_returns.py --events data_swaps/eth_usdg_ekubo_robinhood_lp_events.csv \
    --open data_swaps/eth_usdg_ekubo_robinhood_lp_open.json --fees data_swaps/eth_usdg_ekubo_robinhood_lp_fees_accumulated.csv \
    --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv \
    --klines klines_eth_1s klines_eth_1s_lp --out-prefix results_lp_fynd
python3 lp_split.py --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv \
    --fees data_swaps/eth_usdg_ekubo_robinhood_lp_fees_accumulated.csv --klines klines_eth_1s klines_eth_1s_lp \
    --lp results_lp_fynd.json --bot 0x4abfdbac0afa181338dc9c38c9c1264128c684a2 --out-prefix results_lp_fynd_split
python3 lp_chart.py --prefix results_lp_fynd --split results_lp_fynd_split \
    --main 0x6c6a40d2d1fc442e281e1f80314fd86516e17127 --png charts_flow/F8_fynd_lp_vs_hold.png
python3 -m pytest -q test_lp.py
```

The open-position read (`Positions.getPositionFeesAndLiquidity`) only works near the chain head: this RPC keeps no
history. `klines_eth_1s_lp` holds Binance's Nov 9 and 10 daily files and Nov 11 to the snapshot from the REST API.

## Inputs

| Input | Source |
| --- | --- |
| Positions | `PositionUpdated` and `PositionFeesCollected` on Core, matched on poolId. positionId = salt (24 bytes), tick lower, tick upper |
| Owners | Ekubo Positions NFT `0x02d9876a…b66d`: the NFT id's low 24 bytes are the salt; owner = holder of the NFT. One position was held through another contract, `0x0db596af…ecd5`, and is labelled by that contract |
| Open positions | `getPositionFeesAndLiquidity` at the snapshot: principal and uncollected fees |
| Fees paid in | `FeesAccumulated` from the extension |
| Price | Binance ETHUSDC 1 s close, last at or before (block time − 1 s). USDG = $1 |

## Definitions

- **LP** = what a position paid out (withdrawals + fees collected) + what it still holds (principal + uncollected fees).
- **Hold** = the tokens it deposited, never put in the pool.
- Both valued at Binance at the position's end (last withdrawal, or the snapshot if open). ETH's own price move is
  therefore the same on both sides and drops out. Tokens taken out mid-life are held to the end, on both sides.
- **LP − hold = fees + impermanent loss.** Impermanent loss = (tokens out − tokens in) at that price, before fees.
- **Cost** = each deposit valued at Binance when made. **Capital-days** = cost basis × days open; a withdrawal removes
  the share of cost basis equal to the share of liquidity removed. **Per 30 days** = LP − hold / capital-days × 30.
- **Main LP** = `0x6c6a40d2d1fc442e281e1f80314fd86516e17127`, the largest by capital-days. Who controls it is not known.

## Checks (asserted in `lp_returns.py`, tested in `test_lp.py`)

- **Books close.** What the open positions hold on chain (2.841752 ETH, 9,103.616 USDG) equals all deposits − withdrawals
  − fees collected + fees paid in + every swap since the pool started (2.841752 ETH, 9,103.618 USDG).
- **All fees reach LPs.** Positions received 100.000% of the ETH and USDG the extension paid in (collected + uncollected).
  So any owner fee is taken before `FeesAccumulated`, not from LPs afterwards.
- **Liquidity math.** 176 deposits match liquidity × pool price before the deposit within 0.05%.
- **One position by hand.** The `0x0db596af` position recomputed from raw events and the raw Binance file.
- 19 positions show a small gain before fees ($80 in total). Impermanent loss is ≤ 0 at the pool's own price; at Binance
  it can be slightly positive when the pool's price was off Binance at the withdrawal.

## Where LP − hold comes from (`lp_split.py`, revised 2026-11-11)

Every token LPs gained or lost came from a swap or a fee, so LP − hold splits exactly. Per swap, with p_after the pool
price the swap leaves and B0 / B12 Binance just before / 12 s after:

- **Traders' capture** = amount0 × p_after + amount1: the trader's gain valued at the price it left the pool at (the
  triangle along the curve). This is what a trader that treats its own target price as fair books.
- **Pool lag** = amount0 × (B0 − p_after): the pool still differs from Binance after the trade, so LPs took on
  inventory at a stale price. A trader books this only if it hedges at Binance; otherwise it is the cost of the pool
  lagging the market.
- **After** = amount0 × (B12 − B0), and **drift** (remainder) = later price moves, to each position's end.
- Plus fees. Capture + lag + after = the 12 s markout of `flow_classify.py`, per swap.

Oct 6 – Nov 11, all swaps (including the 67 the markout report drops):

| | fees | capture | lag | after |
|---|---|---|---|---|
| Fynd's bot (1.38 bp fee, $3.9M) | +$539 | −$757 | −$2,558 | −$396 |
| Other traders (16.3 bp, $0.87M) | +$1,422 | −$659 | −$1,094 | −$32 |

Drift −$155. Total −$3,690 = LP − hold.

- **Revision.** The first version (earlier on 2026-11-11) called the whole 12 s markout on the bot's swaps "paid to the
  bot" (−$3,172 net of fees, "86%"). Fynd pointed out the bot does not capture that much. Split as above, the bot's
  capture at its own post-trade price is $757, or +$218 after the fees it pays; the rest is the pool lagging Binance.
  The bot-fee sensitivity was dropped with it.
- **Lag check.** After a bot swap the pool's price is closest to Binance from ~15 s earlier (median gap 2.9 bp, vs
  5.4 bp to Binance at the trade); 99% of bot swaps leave the pool on the same side of Binance as before. Smoothing
  Binance (5 s mean, or the bar's OHLC mean) only moves the bot's lag term from −$2,558 to −$2,104 / −$2,454, so this is
  not Binance noise. The chain's clock was within ~1.5 s of wall time when checked (2026-11-11).
- 95% intervals: resample the 37 days with replacement, 5,000 draws, seed 0, scaled to $ per $1,000 per 30 days.

## Hedging

An LP that shorts the ETH it deposits, at the moment it deposits, ends with exactly LP − hold (before hedge costs):
LP − cost + short P&L = LP − cost − (hold − cost). Hedging removes ETH's own move, which LP − hold already strips out;
it does not remove impermanent loss. Re-hedging during a position changes this a little; for the main LP's ~1-hour
positions the difference is small but not measured here.

## TVL vs GeckoTerminal

Holdings rebuilt from flows are $12.3–12.4k through Nov 9 (GeckoTerminal showed $10,490 that day). At the snapshot the
open positions hold $14,966 at GeckoTerminal's price; GeckoTerminal showed $12,795 eighteen minutes later. Leaving out
the one open position that is out of range (all ETH, $1,692) gives $13,274. GeckoTerminal's method is not published, so
this is a likely explanation, not a confirmed one. Our side closes to the token.

## What the data does not show

- Whether any LP hedges elsewhere. A hedged LP's result outside this pool is not here.
- Who controls the main LP, what price the bot targets, and how (or whether) it hedges. Whether anyone books the
  pool-lag term depends on that.
- One 40-day period in which ETH fell 24%. "Per 30 days" is a rate for this period, not an APR.
