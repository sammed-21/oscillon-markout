# Markout backtest: vanilla vs dynamic fee vs markout fee

Replays a pool's real swaps against a reference price (CEX mid) and compares LP results under three fee policies:

| Policy | Fee for each swap |
|---|---|
| `vanilla` | The pool's historical fee (default 5 bp) |
| `dynamic_vol` | `base + a × realized volatility` of the reference over the previous `window` seconds |
| `markout` | `base + κ × max(0, −toxicity)`, where toxicity = volume-weighted LP markout of swaps that have already matured, over the last `lookback` seconds. Can be per direction. **It never drops below base**, which blocks the "cheap good trades unlock a discount" attack. |

The parameters for `dynamic_vol` and `markout` are fitted on the first 60% of days, frozen, then scored on the last 40%. Every fee uses only information available before the swap (no lookahead).

## LP accounting

```
LP PnL per swap = fee earned + LP markout at horizon h
LP markout      = what the LP received − what it gave, both marked at the reference price h seconds after the swap
```

This follows the markout decomposition in *Not All LPs Are Equal* (Moallemi group, 2026).

## Counterfactual (first-order)

- **Informed swaps:** a swap whose trader edge at `--h-decision` exceeds the historical fee. It still happens under a policy only if that edge beats the policy's fee.
- **Other swaps:** shrink with fee elasticity `ε` when the policy fee is above the historical fee: `kept = (fee / f0)^−ε`. No extra volume is assumed when the fee is lower.
- Sizes and the price path are unchanged.

## Data format

`swaps.csv`

| column | meaning |
|---|---|
| `ts` | Unix seconds |
| `dir` | `+1` trader bought token0 from the pool, `−1` trader sold token0 to the pool |
| `a0`, `a1` | Absolute gross amounts, decimals already applied |

`ref.csv`: `ts, mid`, where `mid` is the token0 price in token1 at 1-second resolution if possible (for example Binance or Coinbase 1s klines; close or mid).

**Converting from a subgraph or logs.** Check the sign convention of your source:

- **Uniswap v3 subgraph `Swap`:** amounts are from the **pool's** side (positive = pool received). Trader bought token0 ⇔ `amount0 < 0`, so `dir = +1 if amount0 < 0 else −1`, `a0 = |amount0|`, `a1 = |amount1|`.
- **Uniswap v4 `PoolManager` `Swap` event:** amounts are the **swapper's** balance delta (negative = swapper paid). Trader bought token0 ⇔ `amount0 > 0`. Apply each token's decimals.

## Run

```bash
python3 backtest.py --swaps swaps.csv --ref ref.csv --fee 0.0005            # one elasticity (default 0.5)
python3 backtest.py --swaps swaps.csv --ref ref.csv --fee 0.0005 --sweep 0.5,2,5
```

Options: `--h-decision` (default 12 s), `--h-eval` (default 60 s), `--fmin`, `--fmax`, `--train-frac`, `--out`.

**Output** (test period only):
- LP PnL, and LP PnL in bps of volume
- fee revenue
- markout loss
- volume kept %
- average fee
- **win % of days vs vanilla**
- total edge vs vanilla, with a 90% bootstrap confidence interval by day

Fitted parameters are printed. Everything is written to `results.json`.

## What the synthetic test shows (pipeline check only, not evidence)

`synth.py` generates fake data purely to check the code runs. On it, the conclusion **flips with elasticity**:

| Elasticity | dynamic_vol vs vanilla | markout vs vanilla |
|---|---|---|
| 0.5 (flow is sticky) | Much better, but keeps only 19% of volume at a 100 bp fee | Better |
| 2 | About the same or slightly worse | Slightly worse |
| 5 (a cheaper pool next door) | Worse | Worse |

The one input that decides whether dynamic fees help LPs is **how much flow leaves when the fee rises**. For a pair with a cheaper pool on the same chain, elasticity is high. That number has to come from real routing data. Don't assume it.

## One-year run and the Oscillon hook

`prepare_minute_year.py` rebuilds two-way flow (token0 sold / token0 bought) from per-minute pool bars when
per-swap logs aren't available. `--policies hook,hook_poolfee` with `--oracle` replays the on-chain Oscillon fee
(3 bp base, or the pool's own fee, plus the hybrid drain surcharge). Results now include a `by_direction` split, and
`--daily-out` writes per-day, per-direction rows for `make_charts.py`. See `REPORT_1Y.md` for the full run.

## Limits (state these when showing results)

1. **First-order counterfactual.** The price path doesn't change when trades are dropped, and informed trade sizes stay fixed.
2. **No gas, and no competing-pool model** beyond the elasticity setting.
3. **Swaps are not attributed to traders**, so there's no per-integrator tiering here.
4. **The reference price is the benchmark.** A wrong or stale reference makes the markouts wrong.
5. **Grid search can overfit.** That's why there's an out-of-sample split and confidence intervals. If a fitted parameter sits at the edge of its grid, widen the grid.
