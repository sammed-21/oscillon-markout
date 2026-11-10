"""
Checks for flow_classify.py / flow_chart.py.

  python3 -m pytest -q test_flow.py                     (or: python3 test_flow.py)

The data checks need a finished run: results_flow_fynd_swaps.csv, results_flow_fynd_example.json, the raw swaps file it
came from, and the Binance klines.
"""
import glob, io, json, os, zipfile
from decimal import Decimal
import numpy as np
import pandas as pd
from flow_lib import markout, toward_binance, is_arbitrage, attribute_fees

PREFIX = os.environ.get("FLOW_PREFIX", "results_flow_fynd")


# --- sign conventions: amounts are the pool's side, + = pool received -------------------------------------------------

def test_trader_buys_eth_below_market_hurts_lp():
    # pool pays 1 ETH, receives 2,000 USDG; ETH is worth 2,010 -> LP is 10 worse off
    assert markout(-1.0, 2000.0, 2010.0) == -10.0


def test_trader_sells_eth_above_market_hurts_lp():
    # pool receives 1 ETH, pays 2,010 USDG; ETH is worth 2,000 -> LP is 10 worse off
    assert markout(1.0, -2010.0, 2000.0) == -10.0


def test_fair_trade_is_zero():
    assert markout(-0.5, 1000.0, 2000.0) == 0.0


# --- toward Binance ---------------------------------------------------------------------------------------------------

def test_buy_when_pool_below_binance_is_toward():
    assert toward_binance(-1.0, -10.0)          # pool cheap, trader buys ETH, pool price rises toward Binance


def test_buy_when_pool_above_binance_is_away():
    assert not toward_binance(-1.0, +10.0)


def test_sell_when_pool_above_binance_is_toward():
    assert toward_binance(+1.0, +10.0)


def test_sell_when_pool_below_binance_is_away():
    assert not toward_binance(+1.0, -10.0)


def test_arbitrage_needs_gap_bigger_than_fee():
    assert is_arbitrage(-1.0, -10.0, 5.0)
    assert not is_arbitrage(-1.0, -10.0, 12.0)  # toward, but the fee ate the gap
    assert not is_arbitrage(-1.0, +10.0, 0.0)   # away from Binance


def test_vectorised():
    got = toward_binance(np.array([-1, -1, 1, 1]), np.array([-5, 5, 5, -5]))
    assert got.tolist() == [True, False, True, False]


# --- fee attribution: a fee event pays for the swaps since the previous fee event ------------------------------------

def test_fee_event_pays_the_swaps_before_it():
    sw = pd.DataFrame({"block": [10, 10, 12, 15], "log_index": [1, 3, 2, 1], "amount1": [100.0, -300.0, 50.0, 10.0]})
    fe = pd.DataFrame({"block": [12, 15], "log_index": [1, 0], "amount0": [0.0, 0.0], "amount1": [0.4, 0.05]})
    f0, f1 = attribute_fees(sw, fe)
    # event at block 12 (logged before that block's swap) pays the two block-10 swaps 1:3; the block-12 swap is paid
    # by the block-15 event; the block-15 swap has no later event yet
    assert np.allclose(f1, [0.1, 0.3, 0.05, 0.0])


def test_fee_events_on_chain_come_before_the_swap_in_their_tx():
    """Checks the attribution rule against the data: in a tx with both, the fee log precedes the swap log."""
    raw = pd.read_csv(json.load(open(PREFIX + "_example.json"))["raw"], usecols=["tx_hash", "log_index"])
    pe = pd.read_csv("data_swaps/eth_usdg_ekubo_robinhood_positions.csv")
    m = pe[pe.event == "fees_accumulated"].merge(raw, on="tx_hash", suffixes=("_f", "_s"))
    assert len(m) > 1000 and (m.log_index_f < m.log_index_s).all()


# --- the run's own numbers --------------------------------------------------------------------------------------------

def _run():
    return pd.read_csv(PREFIX + "_swaps.csv"), json.load(open(PREFIX + ".json"))


def test_groups_add_up_to_total():
    s, r = _run()
    for scope in (r, r["external_only"]):
        for k in ("by_flow", "by_swap", "by_wallet_class"):
            for m in ("volume", "fees", "markout_12", "lp_pnl"):
                assert np.isclose(sum(v[m] for v in scope[k].values()), scope["all"][m], rtol=1e-9, atol=1e-6), (k, m)
    assert np.isclose(s.lp_pnl.sum(), r["all"]["lp_pnl"])


def test_sign_and_classification_on_real_swaps():
    s, _ = _run()
    assert (s.mk_0 == 0).mean() < 0.01
    t = toward_binance(s.amount0.values, s.gap_bp.values)
    assert (s.arb == (t & (s.gap_bp.abs() > s.fee_bp))).all()
    # an arbitrage swap at trade time can only hurt LPs, by at most about the gap it closed
    arb = s[s.arb & (s.notional > 50)]
    assert (arb.mk_0 <= 1e-9).mean() > 0.99


def test_panel_d_swap_to_the_cent():
    """Recompute the chart's example swap from the raw on-chain amounts and the raw Binance file, in Decimal."""
    ex = json.load(open(PREFIX + "_example.json"))
    raw = pd.read_csv(ex["raw"], dtype={"amount0": str, "amount1": str})
    pe = pd.read_csv("data_swaps/eth_usdg_ekubo_robinhood_positions.csv")
    raw["fee0"], raw["fee1"] = attribute_fees(raw.assign(amount1=raw.amount1.astype(float)), pe[pe.event == "fees_accumulated"])
    raw[["fee0", "fee1"]] = raw[["fee0", "fee1"]].map(repr)
    row = raw[raw.tx_hash == ex["tx_hash"]].iloc[0]
    ts = int(row.ts)
    day = pd.to_datetime(ts - 1, unit="s").strftime("%Y-%m-%d")
    with zipfile.ZipFile(glob.glob(os.path.join(ex["klines"], f"*{day}.zip"))[0]) as z:
        k = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None, usecols=[0, 4], dtype={4: str})
    t = k[0].astype("int64"); t = np.where(t > 1e14, t // 10**6, t // 10**3) + 1   # same stamp as flow_classify: close second
    close = Decimal(k[4][t <= ts - 1].iloc[-1])                                   # last price known before the swap's second
    a0, a1 = Decimal(row.amount0), Decimal(row.amount1)
    mk0 = a0 * close + a1
    fee = Decimal(row.fee0) * close + Decimal(row.fee1)
    print(f"\n  {ex['tx_hash']}: {a0} ETH x {close} + {a1} USDG = {mk0:.6f}; fee {fee:.6f}")
    s, _ = _run()
    stored = s[s.tx_hash == ex["tx_hash"]].iloc[0]
    assert abs(float(mk0) - stored.mk_0) < 0.005, (mk0, stored.mk_0)
    assert abs(float(fee) - stored.fee) < 0.005, (fee, stored.fee)
    assert abs(float(close) - stored.p_binance) < 0.005
    assert f"{float(mk0):.2f}" == f"{ex['mk_0']:.2f}"                              # what the chart printed


def test_exclusions_logged():
    s, r = _run()
    e = pd.read_csv(PREFIX + "_excluded.csv")
    flagged = e[e.reason.str.contains("from Binance")]
    assert len(flagged) == r["flagged_swaps"]
    assert not s.tx_hash.isin(flagged.tx_hash).any()


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
