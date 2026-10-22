"""
Per-swap markout: did the price move against the LP's fill after the fact?

Sign convention (defined here explicitly, since the brief this was built from
stated a convention — "negative = LP lost to the trader" — without pinning
down signedSize's own sign, which made the formula ambiguous as written):

  lp_markout_bps < 0  ->  bad for the LP (the trader got a fill that looks
                           cheap in hindsight: price kept moving their way)
  lp_markout_bps > 0  ->  good for the LP (price reverted after the trade)

Reference price source (REF_SOURCE): this module supports two, and every
result is labeled with which one produced it —

  "pool_forward"  the pool's own price h blocks later. Available right now
                   from data we've already verified, but weaker: you're
                   partly measuring the trade's own lingering price impact,
                   not an independent market move. This is the only source
                   wired up so far.
  "cex"           an independent CEX mid price h "blocks" (by timestamp)
                   later. Not implemented — no CEX price series has been
                   sourced yet. Calling compute_markouts(ref_source="cex")
                   raises rather than silently falling back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

Q96 = 2**96


def _price_from_sqrt(sqrt_price_x96: np.ndarray, decimals0: int, decimals1: int) -> np.ndarray:
    """token1 per token0, i.e. (e.g.) USDT per USDe."""
    raw = (sqrt_price_x96 / Q96) ** 2
    return raw * (10.0**decimals0) / (10.0**decimals1)


def compute_markouts(
    swaps: pd.DataFrame,
    horizons_blocks: list[int],
    decimals0: int,
    decimals1: int,
    ref_source: str = "pool_forward",
) -> pd.DataFrame:
    """
    swaps: must be sorted by (blk, idx) ascending, columns blk, idx, amount0,
           amount1, sqrtPriceX96 (raw v4 Swap-event values, TRADER perspective
           — amount0 > 0 means the trader received token0, i.e. bought it;
           this is the opposite sign from the pool-perspective convention
           used in src/lp_inventory_replay.py, and that's intentional: a
           markout is about the trader's fill, not the pool's inventory).

    Returns `swaps` with one `lp_markout_bps_h{h}` column per horizon. A row
    with no swap at or beyond blk+h within the tape gets NaN for that
    horizon — dropped, never filled or extrapolated.
    """
    if ref_source != "pool_forward":
        raise NotImplementedError(
            f"ref_source={ref_source!r} needs an external price series not sourced yet; "
            "only 'pool_forward' (the pool's own later price) is implemented."
        )

    df = swaps.sort_values(["blk", "idx"]).reset_index(drop=True).copy()
    # float64, not int64: amount0 is 18-decimal USDe raw units and can exceed
    # int64 range on large trades. Nothing downstream here needs exact
    # integer arithmetic (unlike src/lp_inventory_replay.py's inventory sums),
    # only sign and a decimals-scaled ratio, so float64 is safe and sufficient.
    a0 = df["amount0"].apply(float).to_numpy()
    a1 = df["amount1"].apply(float).to_numpy()
    sqrt_px = df["sqrtPriceX96"].astype(float).to_numpy()
    blk = df["blk"].to_numpy()

    price = _price_from_sqrt(sqrt_px, decimals0, decimals1)
    # Execution price = the actual ratio the trader paid, not the pool's
    # post-trade marginal quote — those differ by this trade's own slippage.
    with np.errstate(divide="ignore", invalid="ignore"):
        exec_price = np.abs(a1.astype(float) / (10.0**decimals1)) / np.abs(a0.astype(float) / (10.0**decimals0))
    direction = np.sign(a0)  # +1 trader bought token0, -1 trader sold token0
    # Dust trades (amount1 rounds to 0 at this decimals scale) give
    # exec_price == 0 -> markout would be +-inf, which then poisons any
    # weighted average downstream via 0*inf = NaN even though the trade's
    # own (zero) notional should make it harmless. Treat as unknown, same
    # as "no future swap in range" -- never fabricate a value for it.
    exec_price = np.where((exec_price == 0) | ~np.isfinite(exec_price), np.nan, exec_price)

    n = len(df)
    for h in horizons_blocks:
        ref_price = np.full(n, np.nan)
        j = 0
        for i in range(n):
            target = blk[i] + h
            if j < i:
                j = i
            while j < n and blk[j] < target:
                j += 1
            if j < n and blk[j] >= target:
                ref_price[i] = price[j]
        with np.errstate(divide="ignore", invalid="ignore"):
            df[f"lp_markout_bps_h{h}"] = -direction * (ref_price - exec_price) / exec_price * 10_000

    df["exec_price"] = exec_price
    df["direction"] = direction  # +1 = trader bought token0 ("drain" if token0 is the stable at risk)
    df["ref_source"] = ref_source
    return df
