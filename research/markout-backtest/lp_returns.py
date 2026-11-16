"""
LP return vs holding, per position and per owner, for one Ekubo pool (from fetch_ekubo_lp_positions.py).

For each position, from its first deposit to its last withdrawal (or the snapshot block, if still open):
  LP     = tokens it paid out (withdrawals + fees collected) + what is still in it (principal + uncollected fees)
  hold   = the tokens deposited, never put in the pool
Both are valued at the Binance price at the position's end, so the gap is only what the pool did to the tokens:
  LP - hold = fees + (principal out - tokens in)   the second term is impermanent loss, always <= 0 at one price
Tokens taken out mid-life are held to the end, on both sides.
Cost = each deposit valued at Binance when it was made. Capital-days = cost basis x days open; a withdrawal
removes the share of cost basis equal to the share of liquidity removed. USDG = $1.

  python3 lp_returns.py --events data_swaps/eth_usdg_ekubo_robinhood_lp_events.csv \
      --open data_swaps/eth_usdg_ekubo_robinhood_lp_open.json --fees data_swaps/eth_usdg_ekubo_robinhood_lp_fees_accumulated.csv \
      --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv \
      --klines klines_eth_1s klines_eth_1s_lp --out-prefix results_lp_fynd
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--events", required=True); ap.add_argument("--open", required=True); ap.add_argument("--fees", required=True)
ap.add_argument("--swaps", nargs="+", required=True, help="pool swap files (tick, sqrtRatioFixed) up to the snapshot block")
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--dec0", type=int, default=18); ap.add_argument("--dec1", type=int, default=6)
ap.add_argument("--window", nargs=2, default=["2026-10-06 19:39", "2026-11-05 23:58"], help="the markout report's window, UTC")
ap.add_argument("--out-prefix", required=True)
a = ap.parse_args()

frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist()]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames)
t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}) \
    .drop_duplicates("ts").sort_values("ts")


def binance(ts):
    """Last 1 s close at or before ts - 1 (block times are whole seconds), as in flow_classify.py."""
    ts = np.atleast_1d(np.asarray(ts, dtype="int64"))
    i = np.searchsorted(ref.ts.values, ts - 1, side="right") - 1
    assert (i >= 0).all() and (ts - 1 - ref.ts.values[i] < 60).all(), "Binance price missing near an event"
    return ref.mid.values[i]


def amounts(liq, tick_lo, tick_hi, sqrt_p):
    """Tokens (whole units) held by `liq` on [tick_lo, tick_hi) at sqrt price sqrt_p (raw token1/token0)."""
    sa, sb = 1.000001 ** (tick_lo / 2), 1.000001 ** (tick_hi / 2)
    s = min(max(sqrt_p, sa), sb)
    return liq * (1 / s - 1 / sb) / 10**a.dec0, liq * (s - sa) / 10**a.dec1


ev = pd.read_csv(a.events).sort_values(["block", "log_index"]).reset_index(drop=True)
snap = json.load(open(a.open))
op = {o["pos"]: o for o in snap["open"]}
end_ts = snap["to_ts"]
ev["p"] = binance(ev.ts)
sw = pd.concat([pd.read_csv(f) for f in a.swaps]).drop_duplicates(["block", "log_index"]) \
    .sort_values(["block", "log_index"]).reset_index(drop=True)
sw_key = sw.block.values * 1_000_000 + sw.log_index.values

rows, dep_err = [], []
for pos, g in ev.groupby("pos", sort=False):
    g = g.sort_values(["block", "log_index"])
    dep, wd, col = g[(g.event == "position") & (g.liquidity_delta > 0)], g[(g.event == "position") & (g.liquidity_delta < 0)], g[g.event == "fees_collected"]
    o = op.get(pos)
    end = end_ts if o else int(g.ts.max())
    pe = float(binance(end)[0])
    in0, in1 = dep.amount0.sum(), dep.amount1.sum()
    out0, out1 = -wd.amount0.sum() + (o["principal0"] if o else 0), -wd.amount1.sum() + (o["principal1"] if o else 0)
    fee0, fee1 = -col.amount0.sum() + (o["fees0"] if o else 0), -col.amount1.sum() + (o["fees1"] if o else 0)
    # cost basis and capital-days, event by event
    basis = liq = cap_days = 0.0; last = int(g.ts.iloc[0])
    for r in g[g.event == "position"].itertuples():
        cap_days += basis * (r.ts - last) / 86400; last = r.ts
        if r.liquidity_delta > 0:
            basis += r.amount0 * r.p + r.amount1
        elif liq > 0:
            basis *= 1 - (-r.liquidity_delta) / liq
        liq += r.liquidity_delta
        j = np.searchsorted(sw_key, r.block * 1_000_000 + r.log_index) - 1   # last swap before this deposit
        if r.liquidity_delta > 0 and 0 <= j and r.ts <= sw.ts.iloc[-1]:
            e0, e1 = amounts(r.liquidity_delta, r.tick_lower, r.tick_upper, int(sw.sqrtRatioFixed.iloc[j]) / 2**128)
            dep_err.append(max(abs(e0 - r.amount0) / max(abs(r.amount0), 1e-12) if r.amount0 > 1e-9 else 0,
                               abs(e1 - r.amount1) / max(abs(r.amount1), 1e-12) if r.amount1 > 1e-6 else 0))
    cap_days += basis * (end - last) / 86400
    # share of its life the pool price was inside the range (swap data only)
    t0, t1 = int(g.ts.iloc[0]), min(end, int(sw.ts.iloc[-1]))
    s = sw[(sw.ts >= t0) & (sw.ts <= t1)]
    before = sw[sw.ts < t0].tick.iloc[-1:] if (sw.ts < t0).any() else s.tick.iloc[:1]
    tk = np.r_[before.values, s.tick.values]; tt = np.r_[t0, s.ts.values, t1]
    inr = ((tk >= g.tick_lower.iloc[0]) & (tk < g.tick_upper.iloc[0])).astype(float)
    dur = np.diff(tt)
    rows.append({
        "pos": pos, "owner": g.owner.iloc[0] if pd.notna(g.owner.iloc[0]) else "via " + g.locker.iloc[0],
        "nft_id": g.nft_id.iloc[0], "open": bool(o), "start_utc": pd.to_datetime(g.ts.iloc[0], unit="s"),
        "end_utc": pd.to_datetime(end, unit="s"), "days": (end - g.ts.iloc[0]) / 86400,
        "range_low": 1.000001 ** g.tick_lower.iloc[0] * 10 ** (a.dec0 - a.dec1),
        "range_high": 1.000001 ** g.tick_upper.iloc[0] * 10 ** (a.dec0 - a.dec1),
        "in_range_share": float((inr * dur).sum() / dur.sum()) if dur.sum() > 0 else np.nan,
        "eth_in": in0, "usdg_in": in1, "eth_out": out0, "usdg_out": out1, "eth_fees": fee0, "usdg_fees": fee1,
        "cost_usd": float((dep.amount0 * dep.p + dep.amount1).sum()), "capital_days_usd": cap_days, "eth_price_end": pe,
        "hold_usd": in0 * pe + in1, "lp_usd": (out0 + fee0) * pe + out1 + fee1,
        "fees_usd": fee0 * pe + fee1, "il_usd": (out0 - in0) * pe + out1 - in1})
P = pd.DataFrame(rows)
P["lp_minus_hold_usd"] = P.lp_usd - P.hold_usd
P["hold_pnl_usd"], P["lp_pnl_usd"] = P.hold_usd - P.cost_usd, P.lp_usd - P.cost_usd
assert np.allclose(P.lp_minus_hold_usd, P.fees_usd + P.il_usd)
# IL <= 0 holds at the pool's own price. At Binance it can be a little positive when the pool's price was off Binance
# at the withdrawal, so those positions are counted, not rejected.
assert max(dep_err) < 1e-3, f"deposit amounts don't match liquidity x price (max rel err {max(dep_err):.2e})"

# Owners, totals, and the share of positions inside the markout window
sum_cols = ["cost_usd", "capital_days_usd", "hold_usd", "lp_usd", "fees_usd", "il_usd", "lp_minus_hold_usd", "hold_pnl_usd", "lp_pnl_usd"]
O = P.groupby("owner").agg(positions=("pos", "size"), open=("open", "sum"), first=("start_utc", "min"), last=("end_utc", "max"),
                           **{c: (c, "sum") for c in sum_cols}).sort_values("capital_days_usd", ascending=False)
days = (end_ts - ev.ts.min()) / 86400
for df in (O,):
    df["avg_capital_usd"] = df.capital_days_usd / days
    df["lp_minus_hold_pct_of_capital_days"] = 100 * df.lp_minus_hold_usd / df.capital_days_usd * 30
tot = P[sum_cols].sum()
w0, w1 = (pd.Timestamp(x, tz="UTC").timestamp() for x in a.window)
inwin = P[(P.start_utc.astype("int64") // 10**9 >= w0) & (P.end_utc.astype("int64") // 10**9 <= w1)]

fa = pd.read_csv(a.fees)
fee_share = (P.eth_fees.sum() / fa.amount0.sum(), P.usdg_fees.sum() / fa.amount1.sum())
assert all(abs(s - 1) < 1e-6 for s in fee_share), f"fees to positions != fees paid into the pool: {fee_share}"
# Pool holdings at the snapshot, two ways: what the open positions hold on chain, and every token flow summed
held = (sum(o["principal0"] + o["fees0"] for o in snap["open"]), sum(o["principal1"] + o["fees1"] for o in snap["open"]))
flows = (ev.amount0.sum() + fa.amount0.sum() + sw.amount0.sum(), ev.amount1.sum() + fa.amount1.sum() + sw.amount1.sum())
assert abs(held[0] - flows[0]) < 1e-6 and abs(held[1] - flows[1]) < 0.01, \
    f"pool holdings don't close: on chain {held}, from flows {flows} (do the swap files reach the snapshot block?)"
res = {
    "period": {"start_utc": str(pd.to_datetime(ev.ts.min(), unit="s")), "end_utc": str(pd.to_datetime(end_ts, unit="s")),
               "days": days, "snapshot_block": snap["to_block"], "eth_start": float(binance(ev.ts.min())[0]), "eth_end": float(binance(end_ts)[0])},
    "positions": int(len(P)), "open_positions": int(P.open.sum()), "owners": int(P.owner.nunique()),
    "totals": {c: float(tot[c]) for c in sum_cols},
    "avg_capital_usd": float(tot.capital_days_usd / days),
    "lp_minus_hold_per_30d_pct": float(100 * tot.lp_minus_hold_usd / tot.capital_days_usd * 30),
    "fees_per_30d_pct": float(100 * tot.fees_usd / tot.capital_days_usd * 30),
    "il_per_30d_pct": float(100 * tot.il_usd / tot.capital_days_usd * 30),
    "positions_in_range_share_capital_weighted": float((P.in_range_share * P.capital_days_usd).sum() / P.capital_days_usd[P.in_range_share.notna()].sum()),
    "positions_beating_hold": int((P.lp_minus_hold_usd > 0).sum()),
    "positions_with_il_above_zero": {"positions": int((P.il_usd > 0).sum()), "usd": float(P.il_usd[P.il_usd > 0].sum())},
    "inside_markout_window": {"positions": int(len(inwin)), **{c: float(inwin[c].sum()) for c in ["fees_usd", "il_usd", "lp_minus_hold_usd", "capital_days_usd"]}},
    "checks": {"deposit_amounts_vs_liquidity_math_max_rel_err": float(max(dep_err)), "deposits_checked": len(dep_err),
               "fees_paid_in_eth": float(fa.amount0.sum()), "fees_paid_in_usdg": float(fa.amount1.sum()),
               "fees_to_positions_share_eth": float(fee_share[0]), "fees_to_positions_share_usdg": float(fee_share[1]),
               "holdings_on_chain": held, "holdings_from_flows": flows, "swaps_used": int(len(sw))},
}
json.dump(res, open(a.out_prefix + ".json", "w"), indent=1, default=str)
P.sort_values("start_utc").to_csv(a.out_prefix + "_positions.csv", index=False)
O.to_csv(a.out_prefix + "_owners.csv", index_label="owner")

print(f"{res['period']['start_utc']} -> {res['period']['end_utc']} ({days:.1f} d), ETH ${res['period']['eth_start']:,.0f} -> ${res['period']['eth_end']:,.0f}")
print(f"{len(P)} positions ({res['open_positions']} open), {res['owners']} owners, average capital ${res['avg_capital_usd']:,.0f}")
print(f"cost ${tot.cost_usd:,.0f}  hold ${tot.hold_usd:,.0f}  LP ${tot.lp_usd:,.0f}")
print(f"LP - hold ${tot.lp_minus_hold_usd:,.0f} = fees ${tot.fees_usd:,.0f} + IL ${tot.il_usd:,.0f}; "
      f"per 30 days of capital: {res['lp_minus_hold_per_30d_pct']:+.2f}% (fees {res['fees_per_30d_pct']:+.2f}%, IL {res['il_per_30d_pct']:+.2f}%)")
print(f"in range {100 * res['positions_in_range_share_capital_weighted']:.0f}% of capital-time; {res['positions_beating_hold']} of {len(P)} beat holding")
print(f"checks: {res['checks']}")
print(O[["positions", "open", "avg_capital_usd", "fees_usd", "il_usd", "lp_minus_hold_usd", "lp_minus_hold_pct_of_capital_days", "lp_pnl_usd"]].round(2).to_string())
