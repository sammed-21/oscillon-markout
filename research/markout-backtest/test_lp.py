"""
Checks for lp_returns.py. Needs a finished run (results_lp_fynd*.{json,csv}), the events file and the Binance klines.

  python3 -m pytest -q test_lp.py
"""
import io, json, zipfile
import pandas as pd

PREFIX = "results_lp_fynd"
EVENTS = "data_swaps/eth_usdg_ekubo_robinhood_lp_events.csv"
res = json.load(open(PREFIX + ".json"))
P = pd.read_csv(PREFIX + "_positions.csv")


def test_lp_minus_hold_is_fees_plus_impermanent_loss():
    assert ((P.lp_minus_hold_usd - P.fees_usd - P.il_usd).abs() < 1e-6).all()


def test_owner_rows_add_up_to_total():
    O = pd.read_csv(PREFIX + "_owners.csv")
    for c in ["fees_usd", "il_usd", "lp_minus_hold_usd", "capital_days_usd"]:
        assert abs(O[c].sum() - res["totals"][c]) < 1e-6


def test_every_fee_paid_in_reached_a_position():
    c = res["checks"]
    assert abs(c["fees_to_positions_share_eth"] - 1) < 1e-6 and abs(c["fees_to_positions_share_usdg"] - 1) < 1e-6


def test_pool_books_close():
    # what the open positions hold on chain == deposits - withdrawals - fees collected + fees paid in + every swap
    (h0, h1), (f0, f1) = res["checks"]["holdings_on_chain"], res["checks"]["holdings_from_flows"]
    assert abs(h0 - f0) < 1e-6 and abs(h1 - f1) < 0.01


def test_one_position_by_hand():
    # the one position held through 0x0db596af: two deposits, three fee collections, a top-up after each, one full
    # withdrawal. Recomputed from the raw events and the raw Binance file, not from lp_returns.py.
    e = pd.read_csv(EVENTS)
    g = e[e.locker == "0x0db596af023b61c681c91c39e540829bf81becd5"]
    assert g.pos.nunique() == 1 and g.liquidity_delta.sum() == 0
    end = int(g.ts.max())
    day = pd.to_datetime(end, unit="s").strftime("%Y-%m-%d")
    with zipfile.ZipFile(f"klines_eth_1s/ETHUSDC-1s-{day}.zip") as z:
        k = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), header=None, usecols=[0, 4])
    open_s = k[0] // (10**6 if k[0].iloc[0] > 1e14 else 10**3)
    price = float(k[4][open_s + 1 <= end - 1].iloc[-1])            # last 1 s close at or before end - 1
    dep = g[g.liquidity_delta > 0]
    out = g[g.liquidity_delta <= 0]                                  # withdrawals and fee collections, pool side < 0
    lp = -out.amount0.sum() * price - out.amount1.sum()
    hold = dep.amount0.sum() * price + dep.amount1.sum()
    row = P[P.pos == g.pos.iloc[0]].iloc[0]
    assert abs(row.eth_price_end - price) < 1e-9
    assert abs(row.lp_minus_hold_usd - (lp - hold)) < 0.01


def test_split_adds_up():
    s = json.load(open(PREFIX + "_split.json"))
    for c in ["swaps", "volume", "fee", "capture", "lag", "after", "markout_12"]:
        assert abs(s["bot"][c] + s["external"][c] - s["all"][c]) < 1e-6
    for g in ["bot", "external", "all"]:                          # capture + lag + after is the 12 s markout
        assert abs(s[g]["capture"] + s[g]["lag"] + s[g]["after"] - s[g]["markout_12"]) < 1e-6
    assert abs(sum(s["buckets"].values()) - res["totals"]["lp_minus_hold_usd"]) < 1e-6
    d = pd.read_csv(PREFIX + "_split_daily.csv")
    assert abs(d.pool_lag.sum() - s["all"]["lag"]) < 1e-6 and abs(d.bot_net_own_view.sum() - s["bot"]["trader_net_own_view"]) < 1e-6


def test_capture_on_one_swap_by_hand():
    # a trader sells 1 ETH into a pool that was at 2,010 and ends at 2,000, for 2,005 USDG; Binance 2,000 before
    x, y, p_after, b0, b12 = 1.0, -2005.0, 2000.0, 2000.0, 1999.0
    capture, lag, after = x * p_after + y, x * (b0 - p_after), x * (b12 - b0)
    assert (capture, lag, after) == (-5.0, 0.0, -1.0) and capture + lag + after == x * b12 + y


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
