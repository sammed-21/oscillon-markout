"""
Audit of compare_pools.py's Uniswap side (read-only use of its inputs and outputs).

1. Liquidity between swaps. compare_pools.py takes each minute's active liquidity from the last swap before it, so
   a deposit or withdrawal between two swaps is missed. Here the 0.01% pool's Mint/Burn events are added back when
   their range covers the current tick, and the theoretical LVR is recomputed both ways on the same minutes.
2. Like-for-like facts that the comparison depends on: trade sizes, depth, fee rates, sampling interval.

  python3 uni_audit.py --uni ../markout-backtest/data_swaps/weth_usdg_1bp_robinhood_oct22_nov12.csv \
      --mint-burn data/uni_1bp_mint_burn_oct22_nov12.csv --compare-daily ../markout-backtest/results_pool_compare_daily.csv \
      --compare ../markout-backtest/results_pool_compare.json --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv \
      --klines ../markout-backtest/klines_eth_1s ../markout-backtest/klines_eth_1s_lp --out out/uniswap_comparison_audit.json
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--uni", required=True); ap.add_argument("--mint-burn", required=True)
ap.add_argument("--compare-daily", required=True); ap.add_argument("--compare", required=True)
ap.add_argument("--lp-swaps", required=True); ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()

frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}) \
    .drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
at = lambda ts: pd.merge_asof(pd.DataFrame({"ts": np.asarray(ts, dtype="int64")}), ref, on="ts")["mid"].values

U = pd.read_csv(a.uni, usecols=["ts", "block", "log_index", "amount0", "amount1", "liquidity", "tick"]).sort_values(["block", "log_index"])
MB = pd.read_csv(a.mint_burn).sort_values(["block", "log_index"])
MB["delta"] = np.where(MB.event == "mint", MB.liquidity.astype(float), -MB.liquidity.astype(float))
MB["ts"] = np.interp(MB.block, U.block, U.ts)                       # block -> time from the swaps around it
seq = pd.concat([U.assign(kind=0), MB.assign(kind=1)]).sort_values(["block", "log_index"]).reset_index(drop=True)
L = np.empty(len(seq)); cur_l = np.nan; cur_tick = None
kind, liq, tick, tl, tu, dl = (seq[c].values for c in ["kind", "liquidity", "tick", "tick_lower", "tick_upper", "delta"])
for i in range(len(seq)):
    if kind[i] == 0:
        cur_l = float(liq[i]); cur_tick = tick[i]
    elif cur_tick is not None and tl[i] <= cur_tick < tu[i]:
        cur_l += dl[i]
    L[i] = cur_l
seq["L_adj"] = L
w0 = int(pd.Timestamp(U.ts.min(), unit="s").ceil("D").timestamp()); w1 = int(pd.Timestamp(U.ts.max(), unit="s").floor("D").timestamp())
mins = np.arange(w0, w1, 60)
S = at(mins); r2 = np.r_[np.diff(np.log(S)), 0.0] ** 2
grid = pd.DataFrame({"ts": mins})
base = pd.merge_asof(grid, U[["ts", "liquidity"]].sort_values("ts"), on="ts")["liquidity"].values.astype(float)
sq = pd.DataFrame({"ts": np.floor(seq.ts.values).astype("int64"), "L_adj": seq.L_adj.values})   # already in block order
assert (np.diff(sq.ts.values) >= 0).all()
adj = pd.merge_asof(grid, sq, on="ts")["L_adj"].values
lvr_base = float(np.nansum(r2 * base * np.sqrt(S) / 4e12)); lvr_adj = float(np.nansum(r2 * adj * np.sqrt(S) / 4e12))
D = pd.read_csv(a.compare_daily, header=[0, 1], index_col=0, parse_dates=True)
days = (D.index >= pd.Timestamp(w0, unit="s")) & (D.index < pd.Timestamp(w1, unit="s"))
u = D["uniswap_v3_1bp"][days]; f = D["fynd"][days]
res = {"window_utc": [str(pd.Timestamp(w0, unit="s")), str(pd.Timestamp(w1, unit="s"))],
       "mint_burn_events": int(len(MB)), "mint_burn_in_range_share": float(np.mean([(r.tick_lower <= c < r.tick_upper) for r, c in
                                                                                    zip(MB.itertuples(), pd.merge_asof(MB[["block"]], U[["block", "tick"]], on="block")["tick"].values)])),
       "lvr_last_swap_L": lvr_base, "lvr_with_mint_burn": lvr_adj, "lvr_change_pct": 100 * (lvr_adj / lvr_base - 1),
       "compare_pools_uniswap_lvr_same_days": float(u.lvr.sum()),
       "uniswap_loss_over_lvr_as_reported": float(u.loss.sum() / u.lvr.sum()),
       "uniswap_loss_over_lvr_with_mint_burn": float(u.loss.sum() / u.lvr.sum() * lvr_base / lvr_adj),
       "uniswap_net_over_lvr_with_mint_burn": float(u.net.sum() / u.lvr.sum() * lvr_base / lvr_adj),
       "fynd_loss_over_lvr_same_days": float(f.loss.sum() / f.lvr.sum())}
# the comparison split in two: before and from the start of this window
split = pd.Timestamp(w0, unit="s")
for nm, m in [("before_" + str(split.date()), D.index < split), ("from_" + str(split.date()), D.index >= split)]:
    uu_, ff_ = D["uniswap_v3_1bp"][m], D["fynd"][m]
    res.setdefault("by_period", {})[nm] = {"days": int(m.sum()),
        "fynd": {"loss_over_lvr": float(ff_.loss.sum() / ff_.lvr.sum()), "fees_over_lvr": float(ff_.fee.sum() / ff_.lvr.sum()), "net_over_lvr": float(ff_.net.sum() / ff_.lvr.sum())},
        "uniswap": {"loss_over_lvr": float(uu_.loss.sum() / uu_.lvr.sum()), "fees_over_lvr": float(uu_.fee.sum() / uu_.lvr.sum()), "net_over_lvr": float(uu_.net.sum() / uu_.lvr.sum())}}
# like-for-like facts
C = json.load(open(a.compare))
SW = pd.read_csv(a.lp_swaps)
fy = SW[(SW.ts >= w0) & (SW.ts < w1)]
uu = U[(U.ts >= w0) & (U.ts < w1)]
vol_u = np.abs(uu.amount0.values) * at(uu.ts.values - 1)
res["trade_size_usd_median"] = {"fynd_all": float(fy.volume_usd.median()), "fynd_bot": float(fy[fy.bot_wallet].volume_usd.median()),
                                "fynd_other": float(fy[~fy.bot_wallet].volume_usd.median()), "uniswap": float(np.median(vol_u))}
res["swaps_per_day"] = {"fynd": float(len(fy) / ((w1 - w0) / 86400)), "uniswap": float(len(uu) / ((w1 - w0) / 86400))}
res["fynd_volume_share_bot"] = float(fy[fy.bot_wallet].volume_usd.sum() / fy.volume_usd.sum())
res["fee_bp_to_lps"] = {"fynd": C["fynd"]["fee_bp"], "uniswap": C["uniswap_v3_1bp"]["fee_bp"]}
res["active_liquidity_usd_per_1pct_median"] = {
    "uniswap": float(np.nanmedian(base * 1e-12 * np.sqrt(S) * (np.sqrt(1.01) - 1))),
}
json.dump(res, open(a.out, "w"), indent=1)
print(json.dumps(res, indent=1))
