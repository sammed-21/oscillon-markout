"""
Fynd AMM ETH/USDG vs Uniswap v3 WETH/USDG 0.01% on Robinhood Chain: LP loss to informed flow, on the same days.

Per pool, per swap (LP side, Binance ETHUSDC 1 s close, timing as in flow_classify.py / lp_split.py):
  volume    = |ETH amount| x Binance 1 s before
  fee       = what the swap paid LPs (Fynd: FeesAccumulated split per swap, from lp_split.py; Uniswap: 1 bp of the input,
              which v3 includes in the input amount, less the protocol's share: SetFeeProtocol(4, 4) at block 20,579,075,
              long before the window, so 1/4 of every fee goes to the protocol and LPs get 0.75 bp)
  loss_12s  = -(ETH to pool x Binance 12 s after + USDG to pool), fee excluded
  net       = fee - loss_12s

Yardstick: theoretical LVR (Milionis et al. 2022) for the depth each pool actually had, minute by minute:
  LVR = sum over minutes of (dln S)^2 x L x sqrt(S) / (4 x 1e12)       (USD; 1e12 = 10^((18+6)/2))
  L = the pool's active liquidity (from the last swap before the minute), S = Binance price, dln S over that minute.
It is what a pool with that depth would lose to arbitrage at zero fee, so dividing by it puts pools of any size and
any range width on one scale:
  loss_12s / LVR   share of theoretical LVR the pool actually lost (lower = better protected)
  fees / LVR       how much of it fees paid back
  net / LVR        LP result per $ of theoretical LVR
L between swaps ignores deposits and withdrawals that happen between two swaps (both pools trade every few seconds).
95% intervals from resampling days (5,000 draws).

  python3 compare_pools.py --fynd-swaps results_lp_fynd_split_swaps.csv \
      --fynd-pool data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv data_swaps/eth_usdg_ekubo_robinhood_nov11_13.csv \
      --uni data_swaps/weth_usdg_1bp_robinhood_oct02_15.csv data_swaps/weth_usdg_1bp_robinhood.csv data_swaps/weth_usdg_1bp_robinhood_oct22_nov12.csv \
      --klines klines_eth_1s klines_eth_1s_lp --out-prefix results_pool_compare
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--fynd-swaps", required=True, help="per-swap file from lp_split.py")
ap.add_argument("--fynd-pool", nargs="+", required=True, help="Fynd swap files (liquidity column)")
ap.add_argument("--uni", nargs="+", required=True); ap.add_argument("--uni-fee-bp", type=float, default=1.0)
ap.add_argument("--uni-protocol-share", type=float, default=0.25, help="share of each fee kept by the protocol (feeProtocol 4 = 1/4)")
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--out-prefix", required=True)
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
    .drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
at = lambda ts: pd.merge_asof(pd.DataFrame({"ts": np.asarray(ts, dtype="int64")}), ref, on="ts")["mid"].values

# Fynd: per-swap values straight from lp_split.py
F = pd.read_csv(a.fynd_swaps)
F = pd.DataFrame({"ts": F.ts, "volume": F.volume_usd, "fee": F.fee_usd, "loss": F.loss_12s_usd})
FL = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "ts", "liquidity"]) for f in a.fynd_pool]) \
    .drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])

# Uniswap v3: amounts include the fee on the input side
U = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "ts", "amount0", "amount1", "liquidity"]) for f in a.uni]) \
    .drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"]).reset_index(drop=True)
b0, b12 = at(U.ts - 1), at(U.ts + 12)
x, y = U.amount0.values, U.amount1.values
fee_in = np.where(x > 0, x * b0, y) * a.uni_fee_bp / 1e4            # input side x fee rate (input includes the fee)
UU = pd.DataFrame({"ts": U.ts, "volume": np.abs(x) * b0, "fee": fee_in * (1 - a.uni_protocol_share), "loss": -(x * b12 + y) + fee_in})
UL = U[["block", "log_index", "ts", "liquidity"]]

t0 = int(max(F.ts.min(), UU.ts.min())); t1 = int(min(F.ts.max(), UU.ts.max()))
day0 = pd.Timestamp(t0, unit="s").ceil("D"); day1 = pd.Timestamp(t1, unit="s").floor("D")   # whole days only
w0, w1 = int(day0.timestamp()), int(day1.timestamp())

# minute grid: Binance close at each minute, log-return over the minute, active L at the minute's start
mins = np.arange(w0, w1 + 1, 60)
S = at(mins)
r2 = np.r_[np.diff(np.log(S)), 0.0] ** 2                                # return over [m, m+60)


def lvr(L):
    Lm = pd.merge_asof(pd.DataFrame({"ts": mins}), L[["ts", "liquidity"]].sort_values("ts"), on="ts")["liquidity"].values
    return pd.Series(r2 * Lm * np.sqrt(S) / 4e12, index=pd.to_datetime(mins, unit="s")).resample("D").sum()


res, daily = {"window_utc": [str(day0), str(day1)], "eth_vol_ann_pct": float(np.sqrt(r2[:-1].mean() * 525_600) * 100)}, {}
for name, sw, L in [("fynd", F, FL), ("uniswap_v3_1bp", UU, UL)]:
    sw = sw[(sw.ts >= w0) & (sw.ts < w1)]
    d = sw.assign(day=pd.to_datetime(sw.ts, unit="s").dt.floor("D")).groupby("day")[["volume", "fee", "loss"]].sum()
    d["lvr"] = lvr(L).reindex(d.index)
    d["net"] = d.fee - d.loss
    daily[name] = d
    tot = d.sum()
    rng = np.random.default_rng(0); idx = rng.integers(0, len(d), size=(5000, len(d)))
    ci = lambda num: [float(np.percentile(d[num].values[idx].sum(1) / d.lvr.values[idx].sum(1), q)) for q in (2.5, 97.5)]
    res[name] = {"swaps": int(len(sw)), "days": int(len(d)), "volume": float(tot.volume), "fees": float(tot.fee),
                 "loss_12s": float(tot.loss), "net": float(tot.net), "lvr_theory": float(tot.lvr),
                 "fee_bp": float(1e4 * tot.fee / tot.volume), "loss_bp": float(1e4 * tot.loss / tot.volume),
                 "net_bp": float(1e4 * tot.net / tot.volume),
                 "loss_over_lvr": float(tot.loss / tot.lvr), "loss_over_lvr_ci95": ci("loss"),
                 "fees_over_lvr": float(tot.fee / tot.lvr), "net_over_lvr": float(tot.net / tot.lvr), "net_over_lvr_ci95": ci("net")}
json.dump(res, open(a.out_prefix + ".json", "w"), indent=1)
pd.concat(daily, axis=1).to_csv(a.out_prefix + "_daily.csv")
print(json.dumps(res, indent=1))
