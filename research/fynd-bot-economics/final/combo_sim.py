"""
Combined replays (policy_sim.py's model, same data and calibration as out/policy_simulation.csv): cheaper hedging,
a higher Fynd fee on bot trades, and the bot always on, alone and together. Historical replay: external traders,
routers and LPs keep their real behaviour.

  python3 final/combo_sim.py --lp ../markout-backtest --out final/data/combo_sim.csv
"""
import argparse, json, os, sys
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lp = os.path.relpath(os.path.abspath(a.lp), root)
src = open(os.path.join(root, "policy_sim.py")).read().split("# ------------------------------------------------------------------ fit policy A")[0]
sys.argv = ["policy_sim.py", "--out", "out", "--lp-swaps", f"{lp}/results_lp_fynd_split_swaps.csv",
            "--klines", f"{lp}/klines_eth_1s", f"{lp}/klines_eth_1s_lp", "data/klines_nov13",
            "--events", f"{lp}/data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_events.csv"]
out_abs = os.path.abspath(a.out)
os.chdir(root); sys.path.insert(0, root)
g = {"__name__": "policy_sim_lib"}
exec(compile(src, "policy_sim.py", "exec"), g)
P = pd.read_csv(os.path.join("out", "policy_simulation.csv")).set_index("policy")
m_A = json.loads(P.calibration.iloc[0])["min_profit_A_usd"]
c0, f0 = g["c_hedge"], g["f_bot"]
deep = 1.0       # hedge on the 0.01% pool: its fee; impact negligible at these sizes; basis ignored (symmetric model)
runs = [("A", "existing policy", dict(m=m_A)),
        ("H50", "hedge cost -50%", dict(m=m_A, c=c0 * 0.5)),
        ("Hdeep", "hedge at 1 bp (deepest on-chain pool)", dict(m=m_A, c=deep))]
for ff in [2.5, 3.0, 4.0, 5.0]:
    runs.append((f"H50+D{ff:g}", f"hedge cost -50% and Fynd fee on bot trades {ff:g} bp", dict(m=m_A, c=c0 * 0.5, f=ff)))
    runs.append((f"Hdeep+D{ff:g}", f"hedge at 1 bp and Fynd fee on bot trades {ff:g} bp", dict(m=m_A, c=deep, f=ff)))
runs += [("A0+Hdeep+D3", "always on, hedge at 1 bp, Fynd fee 3 bp", dict(m=m_A, c=deep, f=3.0, always_on=True)),
         ("A0+Hdeep+D4", "always on, hedge at 1 bp, Fynd fee 4 bp", dict(m=m_A, c=deep, f=4.0, always_on=True))]
rows = []
for code, desc, kw in runs:
    r = g["run"](**kw); r.update({"policy": code, "description": desc, "params": json.dumps(kw)}); rows.append(r)
    print(code, {k: round(float(v), 1) for k, v in r.items() if k in ("bot_trades", "lp_net_trading_12s_usd", "lp_fees_usd", "protocol_fees_usd", "bot_net_usd", "mean_abs_gap_bp", "share_time_gap_over_10bp")}, flush=True)
pd.DataFrame(rows).to_csv(out_abs, index=False)
print("hedge cost in A:", c0, "Fynd fee in A:", f0)
