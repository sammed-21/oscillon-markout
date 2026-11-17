"""
Checks on the written outputs: the identities the report relies on, and that its aggregates come from the CSVs.
Skipped if the outputs have not been built yet.
"""
import json, os
import numpy as np
import pandas as pd
import pytest

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
need = pytest.mark.skipif(not os.path.exists(os.path.join(OUT, "bot_transaction_economics.csv")), reason="outputs not built")


@need
def test_value_conserved_in_every_complete_tx():
    E = pd.read_csv(os.path.join(OUT, "bot_transaction_economics.csv"))
    C = E[E.completeness.str.startswith("complete")]
    assert C.identity_check_usd.abs().max() < 1e-6


@need
def test_reconstruction_matches_bot_event_everywhere():
    E = pd.read_csv(os.path.join(OUT, "bot_transaction_economics.csv"))
    C = E[E.completeness.str.startswith("complete")]
    assert (C.bot_event_check_gap.abs() < 1e-12).all()


@need
def test_gross_net_gas_and_fee_split():
    E = pd.read_csv(os.path.join(OUT, "bot_transaction_economics.csv"))
    assert np.allclose(E.bot_net_usd, E.bot_gross_usd - E.gas_usd, equal_nan=True)
    assert np.allclose(E.fynd_fee_to_lps_usd + E.fynd_fee_to_protocol_usd, E.fynd_fee_usd, equal_nan=True)
    assert np.allclose(E.fynd_fee_to_protocol_usd, 0.2 * E.fynd_fee_usd, equal_nan=True)


@need
def test_reconciliation_rows_come_from_the_csv():
    E = pd.read_csv(os.path.join(OUT, "bot_transaction_economics.csv"))
    C = E[E.completeness.str.startswith("complete")]
    R = pd.read_csv(os.path.join(OUT, "bot_value_reconciliation.csv")).set_index("item")
    assert R.loc["net realized P&L", "usd"] == pytest.approx(C.bot_net_usd.sum())
    assert R.loc["gross trading P&L (after router fees)", "usd"] == pytest.approx(C.bot_gross_usd.sum())
    assert R.loc["Fynd fee paid by the bot, protocol share", "usd"] == pytest.approx(C.fynd_fee_to_protocol_usd.sum())
    s = R[R.index.str.startswith("check: sum of the five")].usd
    assert (s.abs() < 1.0).all()


@need
def test_lp_section_two_adds_up_to_lp_vs_hold():
    R = pd.read_csv(os.path.join(OUT, "bot_value_reconciliation.csv"))
    s2 = R[R.section.str.startswith("2.")].set_index("item").usd
    parts = s2.drop("total = LP vs holding").sum()
    assert parts == pytest.approx(s2["total = LP vs holding"], abs=0.05)


@need
def test_fee_split_verified_on_bot_only_intervals():
    S = json.load(open(os.path.join(OUT, "summary.json")))
    f = S["fee_split_check"]
    assert f["match_80pct"] / f["intervals_with_only_bot_swaps"] > 0.99
