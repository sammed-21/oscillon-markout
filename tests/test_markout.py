import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from markout import compute_markouts  # noqa: E402

Q96 = 2**96


def _row(blk, idx, a0, a1, price):
    """price = token1 per token0; sqrtPriceX96 = sqrt(price) * Q96 at 0 decimals for simplicity."""
    return {"blk": blk, "idx": idx, "amount0": a0, "amount1": a1, "sqrtPriceX96": int((price**0.5) * Q96)}


def test_buy_then_price_rises_is_bad_for_lp():
    # Trader buys token0 (a0 > 0) at price 1.00, pool price 10 blocks later rises to 1.02.
    swaps = pd.DataFrame([
        _row(100, 0, 1000, -1000, 1.00),      # the trade itself
        _row(110, 0, -1, 1, 1.02),            # a later swap setting the forward price
    ])
    out = compute_markouts(swaps, horizons_blocks=[10], decimals0=0, decimals1=0)
    m = out.iloc[0]["lp_markout_bps_h10"]
    assert m < 0, "trader bought, price kept rising -> bad for the LP, must be negative"
    assert m == pytest.approx(-200, rel=1e-2)  # (1.02/1.00 - 1) * 10000 = 200 bps, sign flipped


def test_buy_then_price_falls_is_good_for_lp():
    swaps = pd.DataFrame([
        _row(100, 0, 1000, -1000, 1.00),
        _row(110, 0, -1, 1, 0.98),
    ])
    out = compute_markouts(swaps, horizons_blocks=[10], decimals0=0, decimals1=0)
    assert out.iloc[0]["lp_markout_bps_h10"] > 0


def test_sell_then_price_rises_is_good_for_lp():
    # Trader sells token0 (a0 < 0) at price 1.00; price then rises -> pool now
    # holds less of the thing that went up -> bad in general, but for THIS
    # fill specifically: LP bought token0 cheap before it rose -> good for LP.
    swaps = pd.DataFrame([
        _row(100, 0, -1000, 1000, 1.00),
        _row(110, 0, -1, 1, 1.02),
    ])
    out = compute_markouts(swaps, horizons_blocks=[10], decimals0=0, decimals1=0)
    assert out.iloc[0]["lp_markout_bps_h10"] > 0


def test_no_swap_within_horizon_is_nan_not_extrapolated():
    swaps = pd.DataFrame([_row(100, 0, 1000, -1000, 1.00)])
    out = compute_markouts(swaps, horizons_blocks=[10], decimals0=0, decimals1=0)
    assert pd.isna(out.iloc[0]["lp_markout_bps_h10"])


def test_multiple_horizons_independent():
    swaps = pd.DataFrame([
        _row(100, 0, 1000, -1000, 1.00),
        _row(101, 0, -1, 1, 1.01),   # inside h=1 window
        _row(200, 0, -1, 1, 1.05),   # inside h=60 window, not h=1
    ])
    out = compute_markouts(swaps, horizons_blocks=[1, 60], decimals0=0, decimals1=0)
    row = out.iloc[0]
    assert row["lp_markout_bps_h1"] == pytest.approx(-100, rel=1e-2)
    assert row["lp_markout_bps_h60"] == pytest.approx(-500, rel=1e-2)


def test_cex_source_not_silently_faked():
    swaps = pd.DataFrame([_row(100, 0, 1000, -1000, 1.00)])
    with pytest.raises(NotImplementedError):
        compute_markouts(swaps, horizons_blocks=[1], decimals0=0, decimals1=0, ref_source="cex")


def test_dust_trade_zero_exec_price_is_nan_not_inf():
    # amount1 rounds to 0 at these decimals -> exec_price would be 0 -> must
    # be NaN, never inf (an inf silently poisons any downstream weighted
    # average via 0*inf = NaN, even when its own weight is correctly zero).
    swaps = pd.DataFrame([
        _row(100, 0, -10, 0, 1.00),
        _row(110, 0, -1, 1, 1.02),
    ])
    out = compute_markouts(swaps, horizons_blocks=[10], decimals0=0, decimals1=0)
    m = out.iloc[0]["lp_markout_bps_h10"]
    assert pd.isna(m)
    assert not np.isinf(m)
