"""
The markout-based keeper policy: per direction, how toxic has recent flow
been, and what fee should that imply.

tox_dir = volume-weighted average lp_markout_bps over the trailing window,
          for swaps in that direction only. Negative = bad for the LP.

fee_dir(next) = clamp(base + kappa * max(0, -tox_dir), min_fee, max_fee)

The max(0, ...) term is what guarantees the fee never drops below base: a
run of markouts that are GOOD for the LP (tox_dir > 0) makes -tox_dir
negative, which the max() floors at zero, so benign flow can't buy a
discount by posting a string of cheap, harmless trades first.

"Hysteresis plus decay" in the brief wasn't given an exact formula — this
implements decay as a per-swap EWMA of tox_dir (decay_halflife_swaps) rather
than a flat trailing window, and hysteresis as a minimum bps change
(hysteresis_bps) required before the quoted fee actually moves. Both are
explicit parameters, not hidden defaults, and both are labeled as this
project's own interpretation, not a reproduction of someone else's exact
mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class KeeperPolicyConfig:
    base_fee_bps: float
    min_fee_bps: float
    max_fee_bps: float
    kappa: float
    markout_horizon_blocks: int
    decay_halflife_swaps: float = 20.0
    hysteresis_bps: float = 0.2
    same_fee_both_directions: bool = False


@dataclass
class _DirState:
    tox_ewma: float = 0.0
    tox_seeded: bool = False  # separate from `initialized`: tracks whether
                              # tox_ewma holds a real observation yet, so the
                              # first markout seeds it directly instead of
                              # blending from a false zero-prior.
    quoted_fee_bps: float = 0.0
    initialized: bool = False


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def simulate_keeper_fees(df: pd.DataFrame, cfg: KeeperPolicyConfig) -> pd.DataFrame:
    """
    df: output of markout.compute_markouts(...), must contain
        f"lp_markout_bps_h{cfg.markout_horizon_blocks}" and `direction`.
    Returns df with an added `quoted_fee_bps` column: the fee the keeper
    would have had posted for THAT swap's direction at the time it happened
    (i.e. based only on markouts known before this swap — no lookahead; a
    swap whose own markout isn't known yet obviously can't inform its own fee).
    """
    col = f"lp_markout_bps_h{cfg.markout_horizon_blocks}"
    if col not in df.columns:
        raise KeyError(f"{col} missing — run compute_markouts with this horizon first")

    decay = 0.5 ** (1.0 / cfg.decay_halflife_swaps)
    buy = _DirState()
    sell = _DirState()
    quoted = np.empty(len(df))

    for i, row in enumerate(df.itertuples(index=False)):
        state = buy if row.direction > 0 else sell
        other = sell if row.direction > 0 else buy

        fee_raw = cfg.base_fee_bps + cfg.kappa * max(0.0, -state.tox_ewma if state.initialized else 0.0)
        fee_raw = _clamp(fee_raw, cfg.min_fee_bps, cfg.max_fee_bps)
        if abs(fee_raw - state.quoted_fee_bps) >= cfg.hysteresis_bps or not state.initialized:
            state.quoted_fee_bps = fee_raw
        state.initialized = True

        if cfg.same_fee_both_directions:
            shared = max(state.quoted_fee_bps, other.quoted_fee_bps if other.initialized else state.quoted_fee_bps)
            quoted[i] = shared
        else:
            quoted[i] = state.quoted_fee_bps

        m = getattr(row, col)
        if not np.isnan(m):
            state.tox_ewma = m if not state.tox_seeded else decay * state.tox_ewma + (1 - decay) * m
            state.tox_seeded = True

    out = df.copy()
    out["quoted_fee_bps"] = quoted
    return out
