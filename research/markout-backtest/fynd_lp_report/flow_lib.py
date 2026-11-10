"""
Sign conventions and swap classification shared by flow_classify.py and its tests.

Swap amounts are from the pool's side: + = the pool received the token. token0 = ETH, token1 = a USD stable.
"""
import numpy as np


def markout(amount0, amount1, price):
    """LP value change of a swap valued at `price` (stable per ETH). Negative = the trade hurt LPs."""
    return amount0 * price + amount1


def toward_binance(amount0, gap_bp):
    """True when the swap moved the pool price toward Binance. gap_bp = (pool price before / Binance - 1) * 1e4.
    Trader buys ETH (pool pays ETH, amount0 < 0) -> pool price rises -> toward Binance when the pool was below (gap < 0).
    Trader sells ETH (amount0 > 0) -> pool price falls -> toward Binance when the pool was above (gap > 0)."""
    return np.where(np.asarray(amount0) < 0, np.asarray(gap_bp) < 0, np.asarray(gap_bp) > 0)


def attribute_fees(swaps, fees):
    """fee0, fee1 per swap from the extension's FeesAccumulated events (both frames need block, log_index, amount0,
    amount1). The extension pays a swap's fee into the pool at the pool's next interaction in a later block, logged
    before that interaction's own swap, so each fee event pays for the swaps since the previous fee event. It is split
    across them by swap size (|amount1|). Swaps after the last fee event get 0: their fee isn't paid in yet."""
    key = lambda x: x.block.values.astype("int64") * 1_000_000 + x.log_index.values.astype("int64")
    f = fees.iloc[np.argsort(key(fees), kind="stable")]
    i = np.searchsorted(key(f), key(swaps), side="right")         # first fee event after each swap
    w = np.abs(swaps.amount1.values)
    tot = np.bincount(i, weights=w, minlength=len(f) + 1)
    share = np.where(tot[i] > 0, w / np.where(tot[i] > 0, tot[i], 1), 0.0)
    paid = i < len(f)
    j = np.minimum(i, len(f) - 1)
    return (np.where(paid, share * f.amount0.values[j], 0.0), np.where(paid, share * f.amount1.values[j], 0.0))


def is_arbitrage(amount0, gap_bp, fee_bp):
    """Toward Binance and the gap was bigger than the fee paid: the trader beat Binance's price after the fee."""
    return toward_binance(amount0, gap_bp) & (np.abs(np.asarray(gap_bp)) > np.asarray(fee_bp))
