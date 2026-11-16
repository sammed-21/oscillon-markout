# Fynd AMM ETH/USDG: LP return vs holding

Same pool as `README_flow_fynd.md`. Every LP position from the pool's first deposit (2026-10-02 06:06 UTC) to snapshot
block 113,153,559 (2026-11-13 06:35 UTC). Numbers below are for that snapshot; the 2026-11-11 snapshot (block 111,478,410)
is in git history.

## Run

```
L=data_swaps/eth_usdg_ekubo_robinhood_lp_to1113
S="data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv data_swaps/eth_usdg_ekubo_robinhood_nov11_13.csv"
python3 fetch_ekubo_lp_positions.py ... --to-block latest --out-prefix $L    # see docstring; prints the snapshot block
python3 fetch_ekubo_swaps.py ... --from-block 111478411 --to-block <snapshot block> --out data_swaps/eth_usdg_ekubo_robinhood_nov11_13.csv
python3 lp_returns.py --events ${L}_events.csv --open ${L}_open.json --fees ${L}_fees_accumulated.csv --swaps $S \
    --klines klines_eth_1s klines_eth_1s_lp --out-prefix results_lp_fynd
python3 lp_split.py --swaps $S --fees ${L}_fees_accumulated.csv --klines klines_eth_1s klines_eth_1s_lp \
    --lp results_lp_fynd.json --bot 0x4abfdbac0afa181338dc9c38c9c1264128c684a2 --out-prefix results_lp_fynd_split
python3 lp_chart.py --prefix results_lp_fynd --split results_lp_fynd_split \
    --main 0x6c6a40d2d1fc442e281e1f80314fd86516e17127 --png charts_flow/F8_fynd_lp_vs_hold.png
python3 check_pool_scope.py --rpc-url https://rpc.mainnet.chain.robinhood.com --pool-key <token0,token1,config> \
    --swaps $S --events ${L}_events.csv --to-block <snapshot block>
python3 -m pytest -q test_lp.py
python3 build_lp_report.py --prefix results_lp_fynd --split results_lp_fynd_split --flow results_flow_fynd.json \
    --main 0x6c6a40d2d1fc442e281e1f80314fd86516e17127 --png charts_flow/F8_fynd_lp_vs_hold.png --tests 24 --revised "Nov 13" --out-dir <dir>
python3 build_lp_zip.py --prefix results_lp_fynd --split results_lp_fynd_split --pdf <dir>/Fynd_LP_returns_2026-11-13.pdf \
    --stage <dir2> --zip fynd_eth_usdg_lp_returns_2026-10-02_to_2026-11-13.zip
```

The report and the zip README are generated from the results files: no hand-typed numbers.

The open-position read (`Positions.getPositionFeesAndLiquidity`) only works at the chain head: this RPC keeps no
history, not even ~10 minutes back. `fetch_ekubo_lp_positions.py` therefore scans to the head, reads, and accepts the
snapshot only if no position change, fee payment or swap hit the pool during the read (else it catches up and re-reads).
An earlier version fell back to the head silently after a long scan, so state and events were ~10 minutes apart; the
fee check (fees to positions = fees paid in) caught it. `klines_eth_1s_lp` holds Binance's Nov 9–12 daily files
(checksums verified) and Nov 13 to the snapshot from the market-data API (data-api.binance.vision).

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

- **Books close.** What the open positions hold on chain (4.055064 ETH, 6,399.155 USDG) equals all deposits − withdrawals
  − fees collected + fees paid in + every swap since the pool started (4.055064 ETH, 6,399.157 USDG).
- **All fees reach LPs.** Positions received 100.000% of the ETH and USDG the extension paid in (collected + uncollected).
  So any owner fee is taken before `FeesAccumulated`, not from LPs afterwards.
- **Only the Fynd pool.** `check_pool_scope.py`: 14 ETH/USDG pools exist on Ekubo Core here; ours is the only one with
  extension `0x550cfe…1d09`. Over the swaps' blocks it has 28,101 swaps and 354 position updates on chain, exactly the
  rows in our files; the 66,565 swaps on the other active ETH/USDG pools are not in them.
- **Liquidity math.** 181 deposits match liquidity × pool price before the deposit within 0.05%.
- **One position by hand.** The `0x0db596af` position recomputed from raw events and the raw Binance file.
- 19 positions show a small gain before fees ($80 in total). Impermanent loss is ≤ 0 at the pool's own price; at Binance
  it can be slightly positive when the pool's price was off Binance at the withdrawal.

## Where LP − hold comes from (`lp_split.py`, revised 2026-11-12)

Every token LPs gained or lost came from a swap or a fee, so LP − hold splits exactly: fees on each swap + the LP side
of each swap valued at Binance 12 s later (the 12 s markout of `flow_classify.py`) + drift (later price moves, to each
position's end). Swaps are grouped by the wallet that sent them. Oct 6 – Nov 13, all swaps (including the 67 the
markout report drops):

| Swaps | volume | fee | fees | loss at Binance 12 s | net for LPs | per $1k / 30 d (95%) |
|---|---|---|---|---|---|---|
| bot wallet `0x4abf…84a2` | $4.48M | 1.37 bp | +$615 | −$4,037 | −$3,422 | −$132 (−175 to −109) |
| all other | $0.93M | 15.8 bp | +$1,470 | −$1,873 | −$403 | −$16 (−37 to +6) |
| later price moves | | | | | −$100 | −$4 |
| total = LP − hold | $5.41M | 3.9 bp | +$2,086 | −$5,911 | −$3,925 | −$151 |

Fees in this table are valued when paid (+$2,086); the LP − hold headline values them at each position's end (+$2,069).

- **The −$3,422 is an upper bound on the bot wallet's capture**, before its hedging and other costs. "Loss" is the LPs'
  side; it is not what the counterparty earned.
- **h sensitivity.** Bot wallet's capture = $4,037 − $615 − h × $4.48M, h = its cost per $ traded (hedging, exchange
  fees, gas, hedge price vs Binance 12 s later). Zero at h = 7.6 bp (95%: 6.9–8.3). We can't see h.
- **Fee sensitivity.** Same swaps at fee f on the bot wallet's swaps: LPs break even on them at 9.0 bp, and LP − hold
  overall at 10.1 bp. Assumes identical swaps at every fee: a transfer, not a forecast.
- **Last 15 days** (Oct 29 – Nov 13 06:35) vs Oct 6–28, per day of swaps: ETH 1-min realised vol 57% vs 46% annualised,
  but LP loss at Binance 12 s 9.3 vs 12.1 bp of volume and $140 vs $170 per day (net of fees −$95 vs −$107).
- **Revisions.** The 2026-11-11 first version called the whole loss on the bot's swaps "paid to the bot"; Fynd pointed
  out it does not capture that much. A second version split the loss at the pool's own post-trade price (capture,
  $757; +$218 net of fees) vs the pool's gap to Binance (lag, $2,558). That split is still computed (`capture`, `lag`,
  `after` and `bot_gap_bp` in the JSON, `_bot_lag.csv`) but no longer reported: in the h framing it is one value of h
  (≈ 7.6 bp), and which value is right depends on how the bot hedges, which only Fynd knows.
- 95% intervals: resample the 37 days with replacement, 5,000 draws, seed 0.
- **Matches the markout report:** positions inside its window (Oct 6 – Nov 5) are −$3,108 vs holding; its markout was
  −$3,196 (asserted within 5% in `test_lp.py`).

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
- Who controls the main LP, and h: the bot wallet's cost per $ traded and anything it books outside this pool.
- One 40-day period in which ETH fell 24%. "Per 30 days" is a rate for this period, not an APR.
