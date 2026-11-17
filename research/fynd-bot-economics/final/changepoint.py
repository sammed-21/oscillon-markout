"""
Daily panel for the Fynd vs Uniswap LVR comparison window, to look at what changed around Oct 22.
Everything is computed from local files; nothing new is fetched.

Per day: Fynd loss/LVR (from compare_pools' daily file), split into the bot's swaps and other swaps; Fynd depth
(liquidity per 1% move, minute average); TVL proxy; bot trades, volume, idle hours, fee bp, hedge cost bp, hedge route
mix; external volume and fee bp; trade sizes; ETH volatility; mean |gap| to Binance; active LP positions and their
capital-weighted range width.

  python3 final/changepoint.py --compare-daily ../markout-backtest/results_pool_compare_daily.csv --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv \
      --fynd-pool <Fynd swap files> --positions ../markout-backtest/results_lp_fynd_positions.csv --legs final/data/hedge_legs.csv \
      --T out/_T.pkl --klines <dirs> --split 2026-10-22 --out final/data/changepoint_daily.csv
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--compare-daily", required=True); ap.add_argument("--lp-swaps", required=True); ap.add_argument("--fynd-pool", nargs="+", required=True)
ap.add_argument("--positions", required=True); ap.add_argument("--legs", required=True); ap.add_argument("--T", required=True)
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--split", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
D = pd.read_csv(a.compare_daily, header=[0, 1], index_col=0, parse_dates=True)
days = D.index
frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.Series(k[4].astype(float).values, index=np.where(t > 1e14, t // 10**6, t // 10**3) + 1)
ref = ref[~ref.index.duplicated()].sort_index()
w0, w1 = int(days.min().timestamp()), int((days.max() + pd.Timedelta(days=1)).timestamp())
mins = np.arange(w0, w1, 60)
S = ref.reindex(mins, method="ffill")
r2 = pd.Series(np.r_[np.diff(np.log(S.values)), 0.0] ** 2, index=pd.to_datetime(mins, unit="s"))
FP = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "ts", "price", "liquidity"]) for f in a.fynd_pool]).drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])
Lm = FP.groupby("ts").liquidity.last().reindex(mins, method="ffill").values * 1e-12
Pm = FP.groupby("ts").price.last().reindex(mins, method="ffill").values
depth = pd.Series(Lm * np.sqrt(S.values) * (np.sqrt(1.01) - 1), index=r2.index)          # USDG to move the pool 1%
gapm = pd.Series(np.abs(1e4 * np.log(Pm / S.values)), index=r2.index)
SW = pd.read_csv(a.lp_swaps); SW["day"] = pd.to_datetime(SW.ts, unit="s").dt.floor("D")
T = pd.read_pickle(a.T); T = T[T.completeness.str.startswith("complete")].copy(); T["day"] = T.utc.dt.floor("D")
Hl = pd.read_csv(a.legs); Hl["day"] = pd.to_datetime(Hl.ts, unit="s").dt.floor("D")
P = pd.read_csv(a.positions, parse_dates=["start_utc", "end_utc"])
rows = []
bt = np.sort(SW[SW.bot_wallet].ts.values)
for day in days:
    d0, d1 = day, day + pd.Timedelta(days=1)
    sw = SW[SW.day == day]; b, o = sw[sw.bot_wallet], sw[~sw.bot_wallet]
    tt = T[T.day == day]; hl = Hl[(Hl.day == day) & (Hl.single_direct_hedge == True)]
    lvr = D.loc[day, ("fynd", "lvr")]
    # idle: seconds of the day inside gaps > 1 h between bot trades (or before the first bot trade)
    ts0, ts1 = int(d0.timestamp()), int(d1.timestamp())
    grid = np.r_[ts0, bt[(bt >= ts0) & (bt < ts1)], ts1]
    prev = bt[bt < ts0]
    if len(prev):
        grid[0] = prev[-1]
    g = np.diff(grid); idle_h = g[g > 3600].sum() / 3600 if len(g) else 24.0
    idle_h = min(idle_h, 24.0)
    act = P[(P.start_utc < d1) & (P.end_utc > d0)]
    width = np.log(act.range_high.where(act.range_high < 1e9) / act.range_low) * 1e4
    rows.append({"day": day.date(), "fynd_loss_over_lvr": D.loc[day, ("fynd", "loss")] / lvr,
                 "fynd_loss_bot_over_lvr": b.loss_12s_usd.sum() / lvr, "fynd_loss_external_over_lvr": o.loss_12s_usd.sum() / lvr,
                 "fynd_fees_over_lvr": D.loc[day, ("fynd", "fee")] / lvr, "uniswap_loss_over_lvr": D.loc[day, ("uniswap_v3_1bp", "loss")] / D.loc[day, ("uniswap_v3_1bp", "lvr")],
                 "fynd_lvr_usd": lvr, "fynd_loss_usd": D.loc[day, ("fynd", "loss")],
                 "eth_vol_ann_pct": float(np.sqrt(r2[d0:d1 - pd.Timedelta(seconds=1)].mean() * 525600) * 100),
                 "fynd_depth_usd_per_1pct": float(depth[d0:d1 - pd.Timedelta(seconds=1)].mean()),
                 "mean_abs_gap_bp": float(gapm[d0:d1 - pd.Timedelta(seconds=1)].mean()),
                 "bot_trades": int(len(b)), "bot_volume_usd": float(b.volume_usd.sum()), "bot_idle_hours": float(idle_h),
                 "bot_loss_bp": float(1e4 * b.loss_12s_usd.sum() / b.volume_usd.sum()) if len(b) else np.nan,
                 "bot_fee_bp": float(1e4 * tt.fee_usd.sum() / tt.notional_usd.sum()) if len(tt) else np.nan,
                 "bot_gap_before_abs_bp": float(tt.gap_before_bp.abs().median()) if len(tt) else np.nan,
                 "bot_gap_after_abs_bp": float(tt.gap_after_bp.abs().median()) if len(tt) else np.nan,
                 "hedge_cost_bp": float(hl.h_exec_vs_binance_bp.abs().median()) if len(hl) else np.nan,
                 "hedge_share_v4_eth_usdg_1bp": float((tt.venues == "uniswap_v4:0x24107d15").mean()) if len(tt) else np.nan,
                 "hedge_share_v4_weth_usdg_2bp": float((tt.venues == "uniswap_v4:0x84bd4e2d").mean()) if len(tt) else np.nan,
                 "bot_trade_size_median_usd": float(b.volume_usd.median()) if len(b) else np.nan,
                 "external_swaps": int(len(o)), "external_volume_usd": float(o.volume_usd.sum()),
                 "external_loss_bp": float(1e4 * o.loss_12s_usd.sum() / o.volume_usd.sum()) if len(o) else np.nan,
                 "external_fee_bp_lp": float(1e4 * o.fee_usd.sum() / o.volume_usd.sum()) if len(o) else np.nan,
                 "external_trade_size_median_usd": float(o.volume_usd.median()) if len(o) else np.nan,
                 "bot_share_of_volume": float(b.volume_usd.sum() / sw.volume_usd.sum()) if len(sw) else np.nan,
                 "active_positions": int(len(act)), "active_lps": int(act.owner.nunique()),
                 "range_width_bp_capital_weighted": float(np.average(width.fillna(width.max() if width.notna().any() else 0), weights=act.cost_usd)) if len(act) else np.nan})
X = pd.DataFrame(rows)
X.to_csv(a.out, index=False)
X["period"] = np.where(pd.to_datetime(X.day) < pd.Timestamp(a.split), "before", "from")
sums = X.groupby("period")[["fynd_loss_usd", "fynd_lvr_usd", "bot_volume_usd", "external_volume_usd", "bot_trades", "bot_idle_hours"]].sum()
med = X.groupby("period").median(numeric_only=True)
out = {"split": a.split, "sums": sums.to_dict(), "medians": med.to_dict()}
# the ratio recomputed on days when the bot was idle less than 2 hours
busy = X[X.bot_idle_hours < 2]
out["loss_over_lvr_on_days_bot_idle_lt_2h"] = {p: float(g.fynd_loss_usd.sum() / g.fynd_lvr_usd.sum()) for p, g in busy.groupby(np.where(pd.to_datetime(busy.day) < pd.Timestamp(a.split), "before", "from"))}
out["corr_with_loss_over_lvr"] = X.drop(columns=["day", "period"]).corr()["fynd_loss_over_lvr"].drop("fynd_loss_over_lvr").round(2).to_dict()
json.dump(out, open(a.out.replace(".csv", ".json"), "w"), indent=1, default=str)
pd.set_option("display.width", 250)
print(med.T.round(3).to_string())
print(json.dumps({k: out[k] for k in ["sums", "loss_over_lvr_on_days_bot_idle_lt_2h"]}, indent=1, default=str))
