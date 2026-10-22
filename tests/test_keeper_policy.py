import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from keeper_policy import KeeperPolicyConfig, simulate_keeper_fees  # noqa: E402


def _cfg(**kw):
    base = dict(base_fee_bps=1.0, min_fee_bps=1.0, max_fee_bps=50.0, kappa=1.0,
                markout_horizon_blocks=12, hysteresis_bps=0.0)
    base.update(kw)
    return KeeperPolicyConfig(**base)


def test_no_lookahead_first_swap_is_base_fee():
    df = pd.DataFrame({"direction": [1], "lp_markout_bps_h12": [-999.0]})
    out = simulate_keeper_fees(df, _cfg())
    assert out.iloc[0]["quoted_fee_bps"] == 1.0  # nothing known yet -> base, not reacting to its own outcome


def test_fee_never_drops_below_base_on_good_flow():
    # A long run of markouts that are GOOD for the LP must never discount below base.
    df = pd.DataFrame({"direction": [1] * 10, "lp_markout_bps_h12": [500.0] * 10})
    out = simulate_keeper_fees(df, _cfg())
    assert (out["quoted_fee_bps"] >= 1.0).all()
    assert out.iloc[-1]["quoted_fee_bps"] == 1.0


def test_fee_rises_on_sustained_toxic_flow_and_is_capped():
    df = pd.DataFrame({"direction": [1] * 10, "lp_markout_bps_h12": [-200.0] * 10})
    out = simulate_keeper_fees(df, _cfg(max_fee_bps=20.0))
    assert out.iloc[-1]["quoted_fee_bps"] == 20.0
    assert (out["quoted_fee_bps"].diff().dropna() >= 0).all()  # monotonically rising into the cap


def test_directions_tracked_independently():
    df = pd.DataFrame({
        "direction": [1, 1, 1, -1],
        "lp_markout_bps_h12": [-500.0, -500.0, -500.0, None],
    })
    out = simulate_keeper_fees(df, _cfg())
    # the untouched sell side should still be quoting base, unaffected by buy-side toxicity
    assert out.iloc[-1]["quoted_fee_bps"] == 1.0


def test_hysteresis_suppresses_small_moves():
    df = pd.DataFrame({"direction": [1, 1], "lp_markout_bps_h12": [-0.01, -0.01]})
    out = simulate_keeper_fees(df, _cfg(hysteresis_bps=5.0, kappa=1.0))
    assert out.iloc[1]["quoted_fee_bps"] == out.iloc[0]["quoted_fee_bps"]


def test_same_fee_both_directions_uses_the_worse_side():
    df = pd.DataFrame({
        "direction": [1, -1],
        "lp_markout_bps_h12": [-1000.0, 1000.0],
    })
    out = simulate_keeper_fees(df, _cfg(same_fee_both_directions=True, max_fee_bps=50.0))
    # after the first (toxic buy) swap, a same-fee sell-side swap should see the elevated fee
    assert out.iloc[1]["quoted_fee_bps"] >= out.iloc[0]["quoted_fee_bps"]


def test_missing_horizon_column_raises():
    df = pd.DataFrame({"direction": [1], "lp_markout_bps_h12": [1.0]})
    with pytest.raises(KeyError):
        simulate_keeper_fees(df, _cfg(markout_horizon_blocks=60))
