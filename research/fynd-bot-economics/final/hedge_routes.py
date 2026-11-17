"""
Hedge execution: what each route cost, what the deepest single pool would have cost, netting, and replays with
cheaper hedging.

1. Route costs (historical, observed). Hedge cost to the bot, in bp of the hedge notional, signed so + = cost:
   buying ETH back: ln(p_exec / Binance); selling ETH: ln(Binance / p_exec). For single direct hedges the cost is split
   into fee, impact and the hedge pool's price vs Binance (basis + own deviation), from hedge_legs.csv.
2. Counterfactual venue (calculated, not observed): the same ETH amount on the Uniswap v3 WETH/USDG 0.01% pool, using
   its price and active liquidity just before the bot's transaction and its 0.01% fee; impact on constant liquidity
   (ignores range crossings). Assumes nobody else's trade would have changed.
3. Netting (calculated): consecutive bot trades in opposite directions within 30 s / 60 s could offset each other's
   hedges; reported as the hedge cost on the offsetting amount, and the price risk of holding it in between.
4. Replays (policy_sim.py's model, unchanged) with the hedge cost cut by 10%, 25%, 50%.

  python3 final/hedge_routes.py --legs final/data/hedge_legs.csv --T out/_T.pkl --uni <Uniswap files> --klines <dirs> \
      --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv --events <LP events> --out final
"""
import argparse, glob, io, json, os, sys, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--legs", required=True); ap.add_argument("--T", required=True); ap.add_argument("--uni", nargs="+", required=True)
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--lp-swaps", required=True); ap.add_argument("--events", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
H = pd.read_csv(a.legs)
T = pd.read_pickle(a.T); T = T[T.completeness.str.startswith("complete")].set_index("hash")
H = H.set_index("hash").join(T[["tx_index", "hedge_price", "other_eth_recv", "fynd_direction"]], rsuffix="_t")
buy_back = H.fynd_direction == "bot_sells_eth"                       # bot buys ETH on the hedge venue
H["hedge_notional_usd"] = H.other_eth_recv.abs() * H.b0
H["hedge_cost_bp"] = np.where(buy_back, 1e4 * np.log(H.hedge_price / H.b0), 1e4 * np.log(H.b0 / H.hedge_price))
H["hedge_cost_usd"] = H.hedge_cost_bp / 1e4 * H.hedge_notional_usd
S = H.single_direct_hedge == True
# for single direct hedges, the bot's cost = -(what the hedge pool gained), split into parts (bp of hedge notional)
for c in ["h_fee_usd", "h_impact_usd", "h_own_dev_usd", "h_basis_usd"]:
    H[c.replace("h_", "cost_").replace("_usd", "_bp")] = (1e4 * H[c] / H.hedge_notional_usd).where(S)

# ---------------------------------------------------------------- counterfactual: the Uniswap v3 0.01% pool
U = pd.concat([pd.read_csv(f, usecols=["block", "tx_index", "log_index", "sqrtPriceX96", "liquidity"]) for f in a.uni]) \
    .drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])
U["key"] = U.block * 100_000.0 + U.tx_index
key = pd.DataFrame({"key": H.block * 100_000.0 + H.tx_index - 0.5}).reset_index()
m = pd.merge_asof(key.sort_values("key"), U[["key", "sqrtPriceX96", "liquidity"]], on="key").set_index("hash")
H = H.join(m[["sqrtPriceX96", "liquidity"]])
H.loc[H.block > U.block.max(), ["sqrtPriceX96", "liquidity"]] = np.nan
sp0 = H.sqrtPriceX96.astype(float) / 2**96; Lr = H.liquidity.astype(float); f = 1e-4
q = H.other_eth_recv.abs() * 1e18                                    # raw ETH amount hedged
# buying ETH (token0 out): 1/sqrtP rises... price up: 1/sp1 = 1/sp0 - q/L ; USDG in (net) = L*(sp1 - sp0); gross = net/(1-f)
sp1_buy = 1 / (1 / sp0 - q / Lr)
usdg_in = Lr * (sp1_buy - sp0) / (1 - f) / 1e6
# selling ETH: net in q(1-f); 1/sp1 = 1/sp0 + q(1-f)/L ; USDG out = L*(sp0 - sp1)
sp1_sell = 1 / (1 / sp0 + q * (1 - f) / Lr)
usdg_out = Lr * (sp0 - sp1_sell) / 1e6
p_cf = np.where(buy_back, usdg_in / (q / 1e18), usdg_out / (q / 1e18))
H["cf_uni1bp_cost_bp"] = np.where(buy_back, 1e4 * np.log(p_cf / H.b0), 1e4 * np.log(H.b0 / p_cf))
H["cf_uni1bp_mid_vs_binance_bp"] = 1e4 * np.log(sp0 ** 2 * 1e12 / H.b0)
H["cf_uni1bp_cost_usd"] = H.cf_uni1bp_cost_bp / 1e4 * H.hedge_notional_usd

R = H.groupby("route").agg(trades=("b0", "size"), hedge_notional_usd=("hedge_notional_usd", "sum"),
                           median_trade_usd=("hedge_notional_usd", "median"), hedge_cost_usd=("hedge_cost_usd", "sum"),
                           cost_fee_bp_mean=("cost_fee_bp", "mean"), cost_impact_bp_mean=("cost_impact_bp", "mean"),
                           cost_own_dev_bp_mean=("cost_own_dev_bp", "mean"), cost_basis_bp_mean=("cost_basis_bp", "mean"),
                           cf_trades=("cf_uni1bp_cost_usd", "count"), cf_uni1bp_cost_usd=("cf_uni1bp_cost_usd", "sum"))
R["hedge_cost_bp_vw"] = 1e4 * R.hedge_cost_usd / R.hedge_notional_usd
cfn = H[H.cf_uni1bp_cost_usd.notna()].groupby("route").hedge_notional_usd.sum()
cfa = H[H.cf_uni1bp_cost_usd.notna()].groupby("route").hedge_cost_usd.sum()
R["actual_cost_bp_vw_on_cf_trades"] = 1e4 * cfa / cfn
R["cf_uni1bp_cost_bp_vw"] = 1e4 * R.cf_uni1bp_cost_usd / cfn
R = R.sort_values("hedge_notional_usd", ascending=False)
R.reset_index().to_csv(os.path.join(a.out, "HEDGE_ROUTE_COSTS.csv"), index=False)
cf = H[H.cf_uni1bp_cost_usd.notna()]
res = {"trades": int(len(H)), "hedge_notional_usd": float(H.hedge_notional_usd.sum()), "hedge_cost_usd": float(H.hedge_cost_usd.sum()),
       "hedge_cost_bp_vw": float(1e4 * H.hedge_cost_usd.sum() / H.hedge_notional_usd.sum()),
       "single_direct": {"trades": int(S.sum()), "cost_bp_mean": {c: float(H.loc[S, c].mean()) for c in ["cost_fee_bp", "cost_impact_bp", "cost_own_dev_bp", "cost_basis_bp"]},
                         "cost_usd": {c: float(-H.loc[S, c.replace("cost_", "h_").replace("_bp", "_usd")].sum()) for c in ["cost_fee_bp", "cost_impact_bp", "cost_own_dev_bp", "cost_basis_bp"]}},
       "counterfactual_uni1bp": {"trades": int(len(cf)), "actual_cost_usd": float(cf.hedge_cost_usd.sum()), "cf_cost_usd": float(cf.cf_uni1bp_cost_usd.sum()),
                                 "actual_bp_vw": float(1e4 * cf.hedge_cost_usd.sum() / cf.hedge_notional_usd.sum()),
                                 "cf_bp_vw": float(1e4 * cf.cf_uni1bp_cost_usd.sum() / cf.hedge_notional_usd.sum()),
                                 "share_trades_cf_cheaper": float((cf.cf_uni1bp_cost_bp < cf.hedge_cost_bp).mean()),
                                 "best_of_both_cost_usd": float(np.minimum(cf.cf_uni1bp_cost_usd, cf.hedge_cost_usd).sum()),
                                 "by_direction_bp": {d: {"actual": float(1e4 * g.hedge_cost_usd.sum() / g.hedge_notional_usd.sum()),
                                                         "cf": float(1e4 * g.cf_uni1bp_cost_usd.sum() / g.hedge_notional_usd.sum()),
                                                         "uni1bp_mid_vs_binance_bp_median": float(g.cf_uni1bp_mid_vs_binance_bp.median())}
                                                     for d, g in cf.groupby("fynd_direction")}}}
# splitting: impact share and a rough saving from halving the size on each of two equally deep pools
res["splitting_rough"] = {"impact_cost_usd_single_direct": float(-H.loc[S, "h_impact_usd"].sum()),
                          "saving_if_impact_halved_usd": float(-H.loc[S, "h_impact_usd"].sum() / 2),
                          "note": "impact is linear in size on constant liquidity; two pools of equal depth halve it; extra hop gas not deducted"}
# ---------------------------------------------------------------- netting
Ts = H.reset_index().sort_values("ts")
net = {}
for win in [30, 60]:
    t, d, n, c = Ts.ts.values, np.where(Ts.fynd_direction == "bot_sells_eth", 1, -1), Ts.hedge_notional_usd.values, Ts.hedge_cost_bp.values
    used = np.zeros(len(t), bool); saved = 0.0; amt = 0.0; pairs = 0; risk = []
    b0 = Ts.b0.values
    for i in range(len(t) - 1):
        if used[i]:
            continue
        j = i + 1
        if j < len(t) and t[j] - t[i] <= win and d[j] != d[i] and not used[j]:
            o = min(n[i], n[j]); amt += o; pairs += 1; used[i] = used[j] = True
            saved += o * (c[i] + c[j]) / 1e4
            risk.append(o / b0[i] * (b0[j] - b0[i]) * d[i])        # P&L of holding the ETH instead of hedging (sign aside)
    net[f"{win}s"] = {"pairs": pairs, "netted_notional_usd": amt, "hedge_cost_saved_usd": saved,
                      "inventory_pnl_mean_usd": float(np.mean(risk)) if risk else 0.0, "inventory_pnl_std_usd": float(np.std(risk)) if risk else 0.0}
res["netting"] = net
H.reset_index().to_csv(os.path.join(a.out, "data", "hedge_costs_per_trade.csv"), index=False)

# ---------------------------------------------------------------- replays with cheaper hedging (policy_sim.py's model)
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
src = open(os.path.join(root, "policy_sim.py")).read().split("# ------------------------------------------------------------------ fit policy A")[0]
kl = [os.path.relpath(k, root) for k in a.klines]
sys.argv = ["policy_sim.py", "--out", "out", "--lp-swaps", os.path.relpath(a.lp_swaps, root), "--klines", *kl, "--events", os.path.relpath(a.events, root)]
cwd = os.getcwd(); os.chdir(root); sys.path.insert(0, root)
g = {"__name__": "policy_sim_lib"}
exec(compile(src, "policy_sim.py", "exec"), g)                         # same data, same model as policy_simulation.csv
os.chdir(cwd)
c0 = g["c_hedge"]
P = pd.read_csv(os.path.join(root, "out", "policy_simulation.csv")).set_index("policy")
m_A = json.loads(P.calibration.iloc[0])["min_profit_A_usd"]
sens = []
for cut in [0.0, 0.10, 0.25, 0.50]:
    r = g["run"](m=m_A, c=c0 * (1 - cut)); r.update({"hedge_cost_cut": cut, "hedge_cost_bp": c0 * (1 - cut)}); sens.append(r)
    print("cut", cut, {k: round(float(v), 1) for k, v in r.items() if k in ("bot_trades", "lp_net_trading_12s_usd", "lp_fees_usd", "bot_net_usd", "mean_abs_gap_bp", "protocol_fees_usd")}, flush=True)
SE = pd.DataFrame(sens)
SE.to_csv(os.path.join(a.out, "data", "hedge_cost_sensitivity.csv"), index=False)
res["sensitivity"] = SE.to_dict(orient="records")
json.dump(res, open(os.path.join(a.out, "data", "hedge_routes.json"), "w"), indent=1, default=float)
print(json.dumps({k: v for k, v in res.items() if k != "sensitivity"}, indent=1, default=float))
