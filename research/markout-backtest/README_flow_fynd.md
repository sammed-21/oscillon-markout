# Fynd AMM ETH/USDG markout: assumptions

Pool: Ekubo v3 Core `0x00000000000014aA86C5d3c41765bb24e11bd701` on Robinhood Chain (4663), ETH/USDG, fee 0, tick
spacing 1024, extension `0x550CFe1292d0D9c0d28f232b3F42Edb4439B1D09`, poolId `0xb67e0601…3546`.
Window: 2026-10-06 19:39 to 2026-11-05 23:57 UTC (30.2 days).

## Run

```
python3 fetch_ekubo_swaps.py ...        # swaps, fees per swap, block times, tx senders
python3 fetch_ekubo_positions.py ...    # PositionUpdated, PositionFeesCollected, FeesAccumulated, PoolInitialized
python3 verify_swaps.py data_swaps/eth_usdg_ekubo_robinhood_to1108.csv --gecko robinhood/pools/<pool>x
python3 flow_classify.py --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv --fee-mode events \
    --name "Fynd AMM ETH/USDG (Ekubo, Robinhood)" --tvl 10490 --end 2026-11-06 --persistence \
    --positions data_swaps/eth_usdg_ekubo_robinhood_positions.csv --out-prefix results_flow_fynd
python3 flow_chart.py --prefix results_flow_fynd --name "Fynd AMM ETH/USDG (Ekubo, Robinhood)" \
    --explorer https://robinhoodchain.blockscout.com/tx/ --raw data_swaps/eth_usdg_ekubo_robinhood_to1108.csv \
    --png charts_flow/F5_fynd_toxic_flow.png --png2 charts_flow/F7_fynd_fee_sweep_lvr_tvl.png
python3 -m pytest -q test_flow.py
```

## Inputs

| Input           | Source                                                                                                   |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| Swaps           | Core's anonymous swap log (116 bytes), matched on poolId. Amounts are the pool's side: + = pool received |
| Fees            | `FeesAccumulated(poolId, amount0, amount1)` from the extension. Core's own fee is 0                      |
| Liquidity       | `PositionUpdated` and `PositionFeesCollected` on Core, matched on poolId                                 |
| Reference price | Binance ETHUSDC 1 s klines (data.binance.vision), close price. USDG = $1                                 |
| Block times     | `eth_getBlockByNumber` per swap block (the RPC returns 0 for log timestamps)                             |
| Wallet          | transaction sender (`tx_from`)                                                                           |

## Definitions

- **Markout at h s** = `amount0 × Binance(t + h) + amount1`, fee excluded. Binance(t) is the last 1 s close at or before
  the second before the swap (block times are whole seconds). 1 s of timing error is about 0.9 bp at 50% annual vol. Negative = the swap hurt LPs. Horizons 0, 12 and 60 s; 12 s is the headline.
- **LP net** = fees + markout at 12 s.
- **Gap** = (pool price after the previous swap / Binance − 1) × 10,000 bp.
- **Toward Binance** = trader bought ETH while the pool was below Binance, or sold ETH while it was above.
- **Arbitrage swap** = toward Binance and |gap| > the fee that swap paid. Decided from the state before the trade.
- **Internal** = wallets in `INTERNAL_WALLETS` in `flow_classify.py`, labelled "Likely Fynd bot" on the charts. Currently
  `0x4abfdbac0afa181338dc9c38c9c1264128c684a2`, listed by us, not by Fynd: every one of its 17,146 swaps goes through
  `0x7ea0ab3b`. **Not confirmed by the Fynd team.** Every metric is
  reported for all flow and for external flow only.
- **Labels:** the code calls toward-Binance swaps with gap > fee "arbitrage" (`arb`, `by_swap.arbitrage`). The charts call
  them "swaps that moved the pool toward Binance", because the pool is exclusive (every swap enters through the
  extension) and the data can't tell arbitrageurs from routed users.
- **Wallet classes** (whole window, after the fact): arbitrage bot = ≥ 50% arbitrage swaps and ≥ 20 swaps; toxic = LPs
  lose on it after fees; genuine = the rest. `--persistence` labels on the first half and scores the second.

## Fee attribution (corrected 2026-11-10)

Fee events carry no swap id. The extension pays a swap's fee into the pool at the pool's next interaction in a later
block, and logs it before that interaction's own swap. So `--fee-mode events` (`flow_lib.attribute_fees`) splits each
FeesAccumulated event, by |USDG amount|, over the swaps since the previous fee event. Evidence in the data:

- In all 16,691 transactions with both a fee event and a swap, the fee log comes first (tested in `test_flow.py`).
- Fee size tracks the previous swap's size (log correlation 0.46), not the same transaction's swap (0.06).
- Every fee event has at least one swap since the previous one, and lands at least 2 blocks after it.
- 12,997 of 16,864 events cover a single swap. On those alone the bot pays 1.76 bp and external flow 13.28 bp, close to
  the full-split 1.36 bp and 12.95 bp.

Swaps after the last fee event in the file get no fee; with data to Nov 8 and the window ending Nov 5, none in the window.

History:
- Before 2026-11-09, fees were split by the token the pool received, which dropped fees paid in the token it paid out:
  $516 over the window.
- 2026-11-09 to 2026-11-10, fees were split over the same transaction's swaps, which credited each swap with an earlier
  swap's fee: $1,466 over the window, bot 1.62 bp, and an "other" group paying 80 bp that was an artifact.
- Now: $1,499. The markout never changed.

## TVL

Daily TVL rebuilds the pool's token holdings from position updates, fee collections, fees accumulated and swaps,
valued at the Binance close at the end of each day. Checks:

- Holdings never go negative, which would mean a missing or mis-signed event.
- 27 full withdrawals take holdings back to exactly 0.

On 2026-11-08 the rebuild gives $12,370. GeckoTerminal showed $10,490 on 2026-11-09, a day later; the data here stops
before that day. **This difference has not been reconciled.**

The results JSON also has `apr_extrapolated` (LP net / average daily TVL, scaled to a year). It is not used in the
report: TVL moved between $2k and $38k in the window and isn't reconciled, so the figure isn't defensible.

## Fee sweep

External arbitrage swaps only. For a flat fee f from 0 to 30 bp, a swap is kept only if |gap| > f, at its observed size
and markout, and pays f × notional. This assumes arbitrage trades only while the gap beats the fee. In reality an
arbitrageur would trade smaller, until the gap left equals the fee. **It says nothing about retail demand**, or about
whether Fynd would still win the order flow against other venues at that fee.

It cannot reach zero by construction: every kept swap has a gap above f, loses about its gap, and pays f. It is a bound
on this flow, not a fee recommendation.

## LVR reconciliation

Theoretical LVR per minute = σ² · L · √S / (4 · 10^((dec0+dec1)/2)):

- σ² is the squared 60 s Binance log return.
- L is the in-range liquidity from the latest swap event, forward-filled.
- S is the Binance price.

`results_flow_fynd_lvr_weekly.csv` gives, for each week, minutes covered, mean L, mean price, annualised σ, theoretical
LVR, measured loss (all flow and external only) and the ratio. The first and last weeks are partial.

The ratio is a comparison, not an explanation. The data does not show why measured loss sits below the theory (0.18× to
0.94× by week). Candidates include the extension's own pricing, and L from swap events missing liquidity changes between
swaps. None of these has been tested.

## Exclusions

All excluded swaps are listed in `results_flow_fynd_excluded.csv`:

- 67 swaps with execution price more than 100 bp from Binance (median 128 bp off, max 484 bp).
- 1 swap with no earlier swap to give the pre-swap price.

## Checks (`test_flow.py`, all pass)

- Sign conventions and the toward-Binance rule on synthetic cases.
- Fee attribution on a synthetic case, and its rule against the data: every fee log precedes the swap log in its tx.
- Every group split (internal/external, arbitrage/other, wallet class) adds back to its total, in both scopes. This is
  also asserted inside `flow_classify.py`.
- The chart's panel D swap is recomputed in Decimal from the raw on-chain amounts and the raw Binance file, and matches
  to the cent.
- Logged exclusions match the flagged count, and none appear in the swaps output.
- Data, from `verify_swaps.py`: 0 duplicates; daily volume within 0.2% of GeckoTerminal over 32 days.

## What the data does not show

- Who controls any wallet. "Internal" is an input.
- Why the pool's price lags Binance. Only that it does, by how much, and who trades the gap.
- What volume or LP result a different fee would produce once traders and routing respond.
