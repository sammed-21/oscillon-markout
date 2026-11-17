"""Identities behind final/: the waterfall steps, the value-flow splits and the fee checks. Skipped if final/ is not built."""
import json, os
import pandas as pd
import pytest

F = os.path.join(os.path.dirname(__file__), "..", "final")
need = pytest.mark.skipif(not os.path.exists(os.path.join(F, "BOT_PNL_WATERFALL.csv")), reason="final outputs not built")


@need
def test_waterfall_steps_add_up():
    W = pd.read_csv(os.path.join(F, "BOT_PNL_WATERFALL.csv"))
    s = {r.step.split(".")[0]: r.usd for r in W.itertuples()}
    assert s["4"] == pytest.approx(s["1"] + s["2"] + s["3"], abs=1e-6)
    assert s["6"] == pytest.approx(s["4"] + s["5"], abs=1e-6)
    assert s["9"] == pytest.approx(s["6"] + s["7"] + s["8"], abs=1e-6)
    assert s["11"] == pytest.approx(s["9"] + s["10"], abs=1e-6)


@need
def test_value_flow_splits_add_up():
    V = pd.read_csv(os.path.join(F, "VALUE_FLOW_RECONCILIATION.csv"))
    d = V[V.section.str.startswith("D.")].usd.values
    assert d[:6].sum() == pytest.approx(d[6], abs=1e-6)
    e = V[V.section.str.startswith("E.")].usd.values
    assert e[:3].sum() == pytest.approx(e[3], abs=1e-6)
    res = V[V.item.str.startswith("  residual")].usd
    assert (res.abs() < 0.5).all()
    a = V[V.section.str.startswith("A.")].set_index("item").usd
    assert a.iloc[:3].sum() == pytest.approx(a["all LPs: LP vs hold (checked report)"], abs=0.01)


@need
def test_fee_split_holds_for_every_checkable_payment_with_external_fees():
    S = json.load(open(os.path.join(F, "data", "fee_split_all.json")))
    assert S["match_80pct_with_external_fees"] == S["fa_intervals_usdg_checkable_with_external_fees"] > 1000
    assert S["external_usdg_input_fee_max_usdg"] == 0.0


@need
def test_hedge_leg_split_is_exact():
    H = pd.read_csv(os.path.join(F, "data", "hedge_legs.csv"))
    assert H.h_check_usd.abs().max() < 1e-9


# ---------------------------------------------------------------- LP loss vs bot capture (final/il_attribution.py)
def _ia():
    p = os.path.join(F, "data", "il_attribution.json")
    if not os.path.exists(p):
        pytest.skip("il_attribution.json not built")
    return json.load(open(p))


def test_real_replay_reproduces_history():
    """The REAL replay (re-anchored to logged prices) gives the same LP swap side on the bot's swaps as the direct calculation."""
    d = _ia(); r = d["replays"]["REAL"]["lp_swap_side_at_execution_usd"]["bot"]; h = d["horizons"]["lp_swap_side_on_bot_swaps_usd"]
    assert abs(r - h["execution"]) < 1.0
    assert abs(d["replays"]["REAL"]["lp_swap_side_12s_usd"]["bot"] - h["12 s"]) < 1.0
    assert d["replays"]["REAL"]["swaps"]["bot"] == d["horizons"]["n_bot_swaps"]


def test_lp_vs_hold_groups_add_up():
    for r in _ia()["replays"].values():
        assert abs(sum(r["lp_vs_hold_ex_fees_by_group_usd"].values()) - r["lp_vs_hold_ex_fees_usd"]) < 1e-6
        assert abs(r["lp_vs_hold_usd"] - r["lp_vs_hold_ex_fees_usd"] - sum(r["lp_fees_usd"].values())) < 1e-6


def test_bot_capture_far_below_lp_loss():
    d = _ia()
    assert d["horizons"]["bot_gross_realized_usd"] < 0.25 * -d["horizons"]["lp_swap_side_on_bot_swaps_usd"]["12 s"]
