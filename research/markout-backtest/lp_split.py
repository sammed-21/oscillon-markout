"""
Where the Fynd AMM LPs' loss vs holding comes from, over the same period as lp_returns.py.

Every token LPs gained or lost between deposit and withdrawal came from a swap or a fee, so LP - hold splits exactly.
Per swap, with p_exec its average price, p_after the pool price it leaves, B0 Binance just before and B12 12 s later
(Binance timing as in flow_classify.py), the LP result marked at B12 splits into:
  capture  = amount0 x p_after + amount1            what the trader made, valued at the price it left the pool at:
                                                    the trader's own view of its gain (the triangle along the curve)
  lag      = amount0 x (B0 - p_after)               the pool still differs from Binance after the trade; LPs took on
                                                    inventory at a stale price. A trader only books this if it hedges
                                                    at Binance; otherwise it is the cost of the pool lagging the market
  after    = amount0 x (B12 - B0)                   the market's move in the 12 s after the trade
plus fees paid, plus drift (the remainder): the swapped tokens' price move from 12 s after the swap to the
position's end. All swaps are kept (the books close with them). Grouped by who traded: Fynd's bot vs everyone else.

Lag check: for the bot's swaps, how far the pool price it leaves is from Binance L seconds earlier. The L with the
smallest gap is roughly how stale the bot's target price is.

Error bars: 95% interval from resampling days (5,000 draws), as $ per $1,000 of LP capital per 30 days.

  python3 lp_split.py --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv \
      --fees data_swaps/eth_usdg_ekubo_robinhood_lp_fees_accumulated.csv --klines klines_eth_1s klines_eth_1s_lp \
      --lp results_lp_fynd.json --bot 0x4abfdbac0afa181338dc9c38c9c1264128c684a2 --out-prefix results_lp_fynd_split
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd
from flow_lib import markout, attribute_fees

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", nargs="+", required=True); ap.add_argument("--fees", required=True)
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--lp", required=True)
ap.add_argument("--bot", required=True); ap.add_argument("--out-prefix", required=True)
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
at = lambda ts: pd.merge_asof(pd.DataFrame({"ts": np.asarray(ts, dtype="int64")}), ref, on="ts")["mid"].values

lp = json.load(open(a.lp))
sw = pd.concat([pd.read_csv(f) for f in a.swaps]).drop_duplicates(["block", "log_index"]) \
    .sort_values(["block", "log_index"]).reset_index(drop=True)
fa = pd.read_csv(a.fees)
sw["fee0"], sw["fee1"] = attribute_fees(sw, fa)
assert abs(sw.fee0.sum() - fa.amount0.sum()) < 1e-9 and abs(sw.fee1.sum() - fa.amount1.sum()) < 1e-6, "a fee event paid no swap"
b0, b12 = at(sw.ts - 1), at(sw.ts + 12)
x, y, pa = sw.amount0.values, sw.amount1.values, sw.price.values
sw["bot"] = sw.tx_from.str.lower() == a.bot.lower()
sw["volume"] = np.abs(x) * b0
sw["fee"] = sw.fee0 * b0 + sw.fee1
sw["capture"] = x * pa + y
sw["lag"] = x * (b0 - pa)
sw["after"] = x * (b12 - b0)
sw["mk_12"] = markout(x, y, b12)
assert np.allclose(sw.capture + sw.lag + sw.after, sw.mk_12) and not np.isnan(sw.mk_12).any()
sw["day"] = pd.to_datetime(sw.ts, unit="s").dt.floor("D")
parts = ["fee", "capture", "lag", "after"]

grp = lambda g: {"swaps": int(len(g)), "volume": float(g.volume.sum()), "fee_bp": float(1e4 * g.fee.sum() / g.volume.sum()),
                 "capture_bp": float(-1e4 * g.capture.sum() / g.volume.sum()),
                 **{c: float(g[c].sum()) for c in parts}, "markout_12": float(g.mk_12.sum()),
                 "trader_net_own_view": float(-(g.capture.sum() + g.fee.sum()))}
res = {"swaps_period": [str(pd.to_datetime(sw.ts.min(), unit="s")), str(pd.to_datetime(sw.ts.max(), unit="s"))],
       "bot": grp(sw[sw.bot]), "external": grp(sw[~sw.bot]), "all": grp(sw)}
lp_minus_hold = lp["totals"]["lp_minus_hold_usd"]
res["drift"] = lp_minus_hold - float((sw.fee + sw.mk_12).sum())
res["lp_minus_hold"] = lp_minus_hold
res["buckets"] = {"fees": res["all"]["fee"], "trader_capture": res["all"]["capture"], "pool_lag": res["all"]["lag"],
                  "price_moves_after_trades": res["all"]["after"] + res["drift"]}
assert abs(sum(res["buckets"].values()) - lp_minus_hold) < 1e-6
cap_days = lp["totals"]["capital_days_usd"]
res["per_1000_per_30d"] = {k_: 30_000 * v / cap_days for k_, v in res["buckets"].items()}

# 95% intervals by resampling days, $ per $1,000 of capital per 30 days
daily = sw.groupby("day").agg(fees=("fee", "sum"), trader_capture=("capture", "sum"), pool_lag=("lag", "sum"), after=("after", "sum"))
bd = sw[sw.bot].groupby("day")
daily["bot_net_own_view"] = -(bd.capture.sum() + bd.fee.sum()).reindex(daily.index, fill_value=0.0)
daily["lp_net_of_swaps"] = daily.fees + daily.trader_capture + daily.pool_lag + daily.after
rng = np.random.default_rng(0)
idx = rng.integers(0, len(daily), size=(5000, len(daily)))
avg_cap = cap_days / lp["period"]["days"]
res["ci95_per_1000_per_30d"] = {c: [float(np.percentile(daily[c].values[idx].mean(axis=1) * 30 / avg_cap * 1000, q)) for q in (2.5, 97.5)]
                                for c in ["trader_capture", "pool_lag", "bot_net_own_view", "lp_net_of_swaps"]}
res["days_resampled"] = int(len(daily))

# How stale is the price the bot leaves the pool at?
bs = sw[sw.bot]
lag_rows = []
for L in [0, 1, 2, 3, 5, 8, 10, 15, 20, 30, 60]:
    gap_after = np.abs(bs.price.values / at(bs.ts - 1 - L) - 1) * 1e4
    lag_rows.append({"seconds_earlier": L, "median_gap_after_bot_swap_bp": float(np.median(gap_after))})
lagdf = pd.DataFrame(lag_rows)
pre = sw.price.shift(1)[sw.bot].values
res["bot_gap_bp"] = {"median_before": float(np.median(np.abs(pre / b0[sw.bot.values] - 1)) * 1e4),
                     "median_after": float(np.median(np.abs(bs.price.values / b0[sw.bot.values] - 1)) * 1e4),
                     "same_side_after": float(np.mean(np.sign(pre / b0[sw.bot.values] - 1) == np.sign(bs.price.values / b0[sw.bot.values] - 1))),
                     "best_match_seconds_earlier": int(lagdf.loc[lagdf.median_gap_after_bot_swap_bp.idxmin(), "seconds_earlier"])}

json.dump(res, open(a.out_prefix + ".json", "w"), indent=1)
daily.to_csv(a.out_prefix + "_daily.csv")
lagdf.to_csv(a.out_prefix + "_bot_lag.csv", index=False)
print(json.dumps({k_: res[k_] for k_ in ["bot", "external", "drift", "buckets", "per_1000_per_30d", "ci95_per_1000_per_30d", "bot_gap_bp"]}, indent=1))
print(lagdf.round(2).to_string(index=False))
