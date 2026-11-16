"""
Where the Fynd AMM LPs' result vs holding comes from, over the same period as lp_returns.py.

Every token LPs gained or lost between deposit and withdrawal came from a swap or a fee, so LP - hold splits exactly
into: fees paid on each swap + the LP side of each swap valued at Binance 12 s later (the 12 s markout of
flow_classify.py, timing as there) + drift (the remainder: the swapped tokens' later price move to each position's
end). All swaps are kept (the books close with them). Swaps are grouped by the wallet that sent them: the bot wallet
(--bot) vs all others.

The loss on the bot wallet's swaps (net of the fees it paid) is an upper bound on what that wallet captured, before its
hedging and other costs. Two sensitivities, both on the same swaps:
  h      bot wallet's capture = loss on its swaps - fees it paid - h x its volume, h = its cost per $ traded
         (hedging, exchange fees, gas, and any gap between its hedge price and Binance 12 s later). We can't see h.
  fee    LPs' result on the bot wallet's swaps if those swaps had paid fee f instead: f x volume - loss.
         Assumes identical swaps at every fee, so it is a transfer, not a forecast.

Also kept for reference (not in the report): loss split at the pool's own post-trade price (capture) vs the pool's
gap to Binance after the trade (lag), and how far the pool price the bot leaves is from Binance L seconds earlier.

Error bars: 95% interval from resampling days (5,000 draws).

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

sw["lp_net"] = sw.fee + sw.mk_12
grp = lambda g: {"swaps": int(len(g)), "volume": float(g.volume.sum()), "fee_bp": float(1e4 * g.fee.sum() / g.volume.sum()),
                 "fee": float(g.fee.sum()), "loss_12s": float(-g.mk_12.sum()), "loss_bp": float(-1e4 * g.mk_12.sum() / g.volume.sum()),
                 "lp_net": float(g.lp_net.sum()), "capture": float(g.capture.sum()), "lag": float(g.lag.sum()),
                 "after": float(g.after.sum()), "markout_12": float(g.mk_12.sum())}
res = {"swaps_period": [str(pd.to_datetime(sw.ts.min(), unit="s")), str(pd.to_datetime(sw.ts.max(), unit="s"))],
       "bot_wallet": a.bot, "bot": grp(sw[sw.bot]), "other": grp(sw[~sw.bot]), "all": grp(sw)}
lp_minus_hold = lp["totals"]["lp_minus_hold_usd"]
res["drift"] = lp_minus_hold - float(sw.lp_net.sum())
res["lp_minus_hold"] = lp_minus_hold
res["rows"] = {"bot_wallet_swaps": res["bot"]["lp_net"], "other_swaps": res["other"]["lp_net"], "later_price_moves": res["drift"]}
assert abs(sum(res["rows"].values()) - lp_minus_hold) < 1e-6
cap_days = lp["totals"]["capital_days_usd"]
res["per_1000_per_30d"] = {k_: 30_000 * v / cap_days for k_, v in res["rows"].items()}

# 95% intervals by resampling days
daily = sw.groupby("day").agg(fees=("fee", "sum"), loss_12s=("mk_12", lambda v: -v.sum()), lp_net=("lp_net", "sum"))
bd = sw[sw.bot].groupby("day")
for c, s in [("bot_fees", bd.fee.sum()), ("bot_loss_12s", -bd.mk_12.sum()), ("bot_volume", bd.volume.sum())]:
    daily[c] = s.reindex(daily.index, fill_value=0.0)
daily["bot_lp_net"] = daily.bot_fees - daily.bot_loss_12s
daily["volume"] = sw.groupby("day").volume.sum()
m = ref.assign(t=pd.to_datetime(ref.ts - 1, unit="s")).set_index("t").mid.resample("1min").last().dropna()
r = np.log(m).diff().dropna()
daily["eth_vol_ann_pct"] = (r.groupby(r.index.floor("D")).std() * np.sqrt(1440 * 365) * 100).reindex(daily.index)
daily["other_lp_net"] = daily.lp_net - daily.bot_lp_net
rng = np.random.default_rng(0)
idx = rng.integers(0, len(daily), size=(5000, len(daily)))
n = len(daily)
avg_cap = cap_days / lp["period"]["days"]
ci = lambda draws: [float(np.percentile(draws, q)) for q in (2.5, 97.5)]
res["ci95_per_1000_per_30d"] = {c: ci(daily[c].values[idx].mean(axis=1) * 30 / avg_cap * 1000)
                                for c in ["bot_lp_net", "other_lp_net", "lp_net"]}
res["ci95_usd_over_period"] = {c: ci(daily[c].values[idx].sum(axis=1)) for c in ["bot_lp_net", "other_lp_net", "lp_net"]}
res["days_resampled"] = int(n)

# Last 15 days vs before: per day of swaps (the last day counts by the hours covered)
cut = pd.Timestamp(sw.day.max()) - pd.Timedelta(days=15)
span = lambda g: (g.ts.max() - g.ts.min()) / 86400 if len(g) else 0.0
res["periods"] = {}
for name, g in [("before", sw[sw.day < cut]), ("last_15_days", sw[sw.day >= cut])]:
    dd = daily[(daily.index < cut) if name == "before" else (daily.index >= cut)]
    days = span(g)
    res["periods"][name] = {"from": str(g.day.min().date()), "to": str(pd.to_datetime(g.ts.max(), unit="s")), "days": days,
                            "volume_per_day": float(g.volume.sum() / days), "fees_per_day": float(g.fee.sum() / days),
                            "loss_12s_per_day": float(-g.mk_12.sum() / days), "lp_net_per_day": float(g.lp_net.sum() / days),
                            "loss_bp": float(-1e4 * g.mk_12.sum() / g.volume.sum()), "eth_vol_ann_pct_mean": float(dd.eth_vol_ann_pct.mean())}

# Sensitivity 1: bot wallet's capture = loss - fees - h x volume
b = res["bot"]
L_, F_, V_ = b["loss_12s"], b["fee"], b["volume"]
draw_cap, draw_vol = (daily.bot_loss_12s - daily.bot_fees).values[idx].sum(axis=1), daily.bot_volume.values[idx].sum(axis=1)
hs = np.round(np.arange(0, 12.01, 0.25), 2)
hdf = pd.DataFrame({"h_bp": hs, "bot_capture_usd": L_ - F_ - hs * 1e-4 * V_})
hdf["ci_low"], hdf["ci_high"] = zip(*[ci(draw_cap - h * 1e-4 * draw_vol) for h in hs])
res["h_sensitivity"] = {"upper_bound_at_h0": L_ - F_, "breakeven_h_bp": 1e4 * (L_ - F_) / V_,
                        "breakeven_h_bp_ci95": ci(1e4 * draw_cap / draw_vol)}

# Sensitivity 2: same swaps, a different fee on the bot wallet's swaps (a transfer, not a forecast)
fs = np.round(np.arange(0, 15.01, 0.25), 2)
fdf = pd.DataFrame({"fee_bp": fs, "lp_on_bot_wallet_swaps_usd": fs * 1e-4 * V_ - L_})
fdf["lp_minus_hold_all_usd"] = lp_minus_hold + fdf.lp_on_bot_wallet_swaps_usd - b["lp_net"]
res["fee_sensitivity"] = {"actual_fee_bp": b["fee_bp"], "breakeven_fee_bp_bot_wallet_swaps": 1e4 * L_ / V_,
                          "breakeven_fee_bp_lp_minus_hold": 1e4 * (L_ - (lp_minus_hold - b["lp_net"])) / V_}

# Reference only: how far the pool price the bot leaves is from Binance L seconds earlier
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
hdf.to_csv(a.out_prefix + "_h_sensitivity.csv", index=False)
fdf.to_csv(a.out_prefix + "_fee_sensitivity.csv", index=False)
lagdf.to_csv(a.out_prefix + "_bot_lag.csv", index=False)
# one row per swap, every input and step, for checking by hand and summing in a spreadsheet
pd.DataFrame({"utc": pd.to_datetime(sw.ts, unit="s"), "ts": sw.ts, "block": sw.block, "log_index": sw.log_index, "tx_hash": sw.tx_hash,
              "tx_from": sw.tx_from, "bot_wallet": sw.bot, "eth_to_pool": sw.amount0, "usdg_to_pool": sw.amount1,
              "binance_before": b0, "binance_12s_after": b12, "volume_usd": sw.volume, "fee_eth": sw.fee0, "fee_usdg": sw.fee1,
              "fee_usd": sw.fee, "loss_12s_usd": -sw.mk_12, "net_for_lps_usd": sw.lp_net}).to_csv(a.out_prefix + "_swaps.csv", index=False)
print(json.dumps({k_: res[k_] for k_ in ["bot", "other", "drift", "rows", "per_1000_per_30d", "ci95_per_1000_per_30d",
                                         "ci95_usd_over_period", "h_sensitivity", "fee_sensitivity", "periods"]}, indent=1))
