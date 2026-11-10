# Fynd AMM ETH/USDG: LP net markout vs Binance, Oct 6 – Nov 5, 2026

Pool: Ekubo Core `0x0000…bd701` on Robinhood Chain, ETH/USDG, Fynd extension `0x550CFe12…1D09`. 30.2 days.

## Summary

- **LP net markout** = fees minus what LPs lost on each swap, valued at Binance 12 s later. It is the trading side of LP
  returns, **not position P&L or return on capital**.
- Over 20,326 swaps and $4.13M: fees $1,499 (3.63 bp), loss $4,694 (−11.37 bp), net **−$3,196 (−7.74 bp)**.
- One wallet I believe is Fynd's bot (not confirmed) is 80% of volume and −$2,699 of the net. It pays 1.36 bp in fees;
  external flow pays 12.95 bp. External flow nets −$496 (−6.13 bp).
- 92% of the loss is already there at the moment of the trade: the pool's price was behind Binance before the swap.
  99% of volume moved the pool toward Binance across a gap bigger than its fee.

## Results

| Flow | Swaps | Volume | Fees | Loss at 12 s | LP net markout |
|---|--:|--:|--:|--:|--:|
| **All** | 20,326 | $4.13M | $1,499 (3.63 bp) | −$4,694 (−11.37 bp) | **−$3,196 (−7.74 bp)** |
| **Likely Fynd bot** | 17,146 | $3.32M | $450 (1.36 bp) | −$3,149 (−9.49 bp) | **−$2,699 (−8.14 bp)** |
| **External** | 3,180 | $0.81M | $1,049 (12.95 bp) | −$1,545 (−19.08 bp) | **−$496 (−6.13 bp)** |
| External, toward Binance, gap > fee | 2,664 | $759k | $1,029 (13.57 bp) | −$1,545 (−20.36 bp) | −$515 (−6.79 bp) |
| External, other | 516 | $51k | $20 (3.84 bp) | −$0.46 (−0.09 bp) | +$19 (+3.75 bp) |

bp = per dollar of swap volume. Measured loss is 0.58× theoretical LVR ($8,041). Charts: Figure 1 (where the loss
goes), Figure 2 (fee sweep, LVR by week, daily TVL).

## Method

- Swaps from Ekubo Core logs; daily volume within 0.2% of GeckoTerminal. Binance ETHUSDC 1 s close before the block.
- Fees from the extension's FeesAccumulated events. Each pays in at the pool's next interaction, so it is split by size
  over the swaps since the previous event. On events covering a single swap, the bot pays 1.76 bp and external 13.28 bp.
- 68 swaps excluded (listed in the zip). 15 tests pass, including one swap recomputed by hand to the cent.
- Code written with AI assistance; I reviewed the outputs and hand-checked one swap end to end.

## What the data can't show

- Who controls any wallet, or whether a swap was an arbitrageur or a routed user.
- Why the pool lags Binance, or why measured loss sits below theoretical LVR.
- Position P&L for any LP, or what a different fee would do once traders and routers respond.

## Open questions

- Is `0x4abfdbac0afa181338dc9c38c9c1264128c684a2` your bot? All its 17,146 swaps go through `0x7ea0ab3b`.
- Fees are what the extension paid into the pool; LP positions have collected 91–96% of them, the rest is still in open
  positions. If Fynd takes an owner fee, I assume it comes off before this. Is that right?
- TVL rebuilt from events ($12,370 on Nov 8) doesn't yet match GeckoTerminal ($10,490 on Nov 9).
- Next, if useful: position-level LP return vs holding, and a comparison with Uniswap's USDG/WETH 0.01% pool.

Data, code and every assumption: see the zip and `README_flow_fynd.md`.
