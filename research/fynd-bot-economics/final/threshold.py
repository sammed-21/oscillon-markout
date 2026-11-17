"""
Why does the bot leave Fynd ~5 bp from Binance? Tests on the rebuilt trades (single direct hedges) and on the
second-by-second gap series.

1. Exact split of the post-trade gap. With s = +1 when the bot sells ETH into Fynd (Fynd above the market) and -1
   otherwise, and logs in bp:
     s*ln(Fynd_after / Binance) = s*ln(U / Binance)               basis: on-chain reference vs Binance
                                + s*ln(Hedge_before / U)          the hedge pool's own deviation before the trade
                                + s*ln(Hedge_after / Hedge_before) the bot's impact on the hedge pool
                                + s*ln(Fynd_after / Hedge_after)  what is left between Fynd and the hedge pool
   If the bot trades until the last unit stops paying, the last term should be close to its marginal fees
   (hedge-pool fee + Fynd fee + router fee).
2. What the bot reacts to: the chance of a bot trade in a second, by the Fynd gap to Binance and by the Fynd gap to
   the on-chain reference, in the seconds when the bot was active.
3. Marginal trades: how many trades earn less than their gas.

  python3 final/threshold.py --legs final/data/hedge_legs.csv --fynd-pool <Fynd swap files> --uni <Uniswap files> \
      --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv --klines <dirs> --out final/data/threshold.json
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--legs", required=True); ap.add_argument("--fynd-pool", nargs="+", required=True); ap.add_argument("--uni", nargs="+", required=True)
ap.add_argument("--lp-swaps", required=True); ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
H = pd.read_csv(a.legs)
S = H[H.single_direct_hedge == True].copy()
s = np.where(S.fynd_direction == "bot_sells_eth", 1.0, -1.0)
L = lambda x, y: 1e4 * np.log(x / y)
S["basis"] = s * L(S.uni_before, S.b0)
S["hedge_dev"] = s * L(S.hedge_mid_before, S.uni_before)
S["hedge_impact"] = s * L(S.hedge_mid_after, S.hedge_mid_before)
S["fynd_vs_hedge_after"] = s * L(S.pool_after, S.hedge_mid_after)
S["gap_after_signed"] = s * L(S.pool_after, S.b0)
S["check"] = S.gap_after_signed - (S.basis + S.hedge_dev + S.hedge_impact + S.fynd_vs_hedge_after)
S["router_bp"] = 1e4 * (S.router_fee_eth_wei / 1e18 * S.b0 + S.router_fee_usdg_raw / 1e6) / S.notional_usd
S["marginal_fees_bp"] = 1e4 * S.hedge_fee_total + S.fee_bp + S.router_bp
S["left_minus_fees_bp"] = S.fynd_vs_hedge_after - S.marginal_fees_bp
S["gap_before_signed"] = s * S.gap_before_bp
S["fynd_vs_hedge_before"] = s * L(S.pool_before, S.hedge_mid_before)
comp = ["gap_after_signed", "basis", "hedge_dev", "hedge_impact", "fynd_vs_hedge_after", "marginal_fees_bp", "left_minus_fees_bp",
        "gap_before_signed", "fynd_vs_hedge_before"]
res = {"trades": int(len(S)), "check_max_abs_bp": float(S.check.abs().max()),
       "median_bp": {c: float(S[c].median()) for c in comp}, "mean_bp": {c: float(S[c].mean()) for c in comp},
       "by_direction_median_bp": {d: {c: float(g[c].median()) for c in comp} for d, g in S.groupby("fynd_direction")},
       "share_left_within_1bp_of_fees": float((S.left_minus_fees_bp.abs() <= 1).mean()),
       "share_left_within_2bp_of_fees": float((S.left_minus_fees_bp.abs() <= 2).mean()),
       "mean_fee_bp_unweighted": float(H.fee_bp.mean()), "median_fee_bp": float(H.fee_bp.median()),
       "volume_weighted_fee_bp": float(1e4 * H.fee_usd.sum() / H.notional_usd.sum())}
# marginal trades
res["trades_gross_below_gas"] = int((H.bot_gross_usd < H.gas_usd).sum())
res["gross_per_trade_usd_quantiles"] = {q: float(H.bot_gross_usd.quantile(q)) for q in (0.01, 0.05, 0.25, 0.5)}

# ------------------------------------------------------------------ what the bot reacts to (second by second)
frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.Series(k[4].astype(float).values, index=np.where(t > 1e14, t // 10**6, t // 10**3) + 1)
ref = ref[~ref.index.duplicated()].sort_index()
FP = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "ts", "price"]) for f in a.fynd_pool]).drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])
U = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "ts", "sqrtPriceX96"]) for f in a.uni]).drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])
U["p"] = (U.sqrtPriceX96.astype(float) / 2**96) ** 2 * 1e12
SW = pd.read_csv(a.lp_swaps)
bt = np.sort(SW[SW.bot_wallet].ts.values)
w0, w1 = int(bt[0]), min(int(bt[-1]), int(U.ts.max()))
sec = np.arange(w0, w1 + 1)
B = ref.reindex(sec - 1, method="ffill").values
PFs = FP.groupby("ts").price.last().reindex(sec - 1, method="ffill").values       # pool price as of the previous second
Us = U.groupby("ts").p.last().reindex(sec - 1, method="ffill").values
up = np.zeros(len(sec), bool)
for t0, g in zip(bt[:-1], np.diff(bt)):
    if g <= 3600 and t0 - w0 < len(sec):
        up[t0 - w0:t0 - w0 + g + 1] = True
up = up[:len(sec)]
trade = np.isin(sec, bt)
gB, gU = np.abs(L(PFs, B)), np.abs(L(PFs, Us))
edges = [0, 2, 4, 6, 8, 10, 12, 15, 20, 1e9]
prof = {}
for nm, g in [("vs_binance", gB), ("vs_onchain", gU)]:
    df = pd.DataFrame({"b": pd.cut(g[up], edges, right=False), "t": trade[up]}).groupby("b", observed=False).t.agg(["size", "sum"])
    df["p_trade_per_s"] = df["sum"] / df["size"]
    prof[nm] = {str(i): {"seconds": int(r["size"]), "trades": int(r["sum"]), "p": float(r.p_trade_per_s)} for i, r in df.iterrows()}
res["trade_probability_by_gap_when_bot_active"] = prof
res["active_seconds"] = int(up.sum())
# when active and the gap to Binance is wide but no trade: what was the gap to the on-chain reference?
wide = up & (gB >= 8) & ~trade
res["active_wide_binance_gap_no_trade"] = {"seconds": int(wide.sum()), "median_gap_vs_onchain_bp": float(np.nanmedian(gU[wide])),
                                          "median_gap_vs_binance_bp": float(np.nanmedian(gB[wide]))}
json.dump(res, open(a.out, "w"), indent=1)
S.to_csv(a.out.replace(".json", "_trades.csv"), index=False)
print(json.dumps({k: v for k, v in res.items() if k != "trade_probability_by_gap_when_bot_active"}, indent=1))
for nm, d in prof.items():
    print(nm, {k: round(v["p"], 4) for k, v in d.items()})
