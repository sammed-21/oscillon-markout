"""
Check pool_model.py against the chain: replay every position event and every real swap (in block/log order) with the
real ETH amounts, and compare the model's USDG amount, post-swap price and active liquidity with what Ekubo logged.

  python3 validate_pool_model.py --events ../markout-backtest/data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_events.csv \
      --swaps <Fynd swap files> --out out/check_pool_model.csv
"""
import argparse, math
import numpy as np
import pandas as pd
from pool_model import Pool

ap = argparse.ArgumentParser()
ap.add_argument("--events", required=True); ap.add_argument("--swaps", nargs="+", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
E = pd.read_csv(a.events); E = E[E.event == "position"]
S = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "ts", "amount0", "amount1", "price", "liquidity"]) for f in a.swaps]) \
    .drop_duplicates(["block", "log_index"])
ev = pd.concat([E.assign(kind="pos")[["block", "log_index", "kind", "pos", "tick_lower", "tick_upper", "liquidity_delta"]],
                S.assign(kind="swap")]).sort_values(["block", "log_index"]).reset_index(drop=True)
pool = None; rows = []
for r in ev.itertuples():
    if r.kind == "pos":
        if pool is None:
            pool = Pool(math.sqrt(2700.0))
        pool.update(r.pos, r.tick_lower, r.tick_upper, r.liquidity_delta)
        continue
    if pool is None:
        continue
    s_before = pool.s
    if not rows:                                   # first swap: start from the price just before it
        pool.s = math.sqrt(r.price)
        rows.append({"block": r.block, "log_index": r.log_index, "first": True}); continue
    x, y = pool.swap_eth_in(r.amount0)
    rows.append({"block": r.block, "log_index": r.log_index, "ts": r.ts, "eth": r.amount0, "usdg_real": r.amount1, "usdg_model": y,
                 "eth_filled": x, "price_real": r.price, "price_model": pool.s ** 2,
                 "l_real": r.liquidity * 1e-12, "l_model": pool.liquidity()})
    pool.s = math.sqrt(r.price)                    # re-anchor to the real price so errors don't compound
C = pd.DataFrame(rows[1:])
C["usdg_err_bp"] = 1e4 * (C.usdg_model / C.usdg_real - 1)
C["price_err_bp"] = 1e4 * np.log(C.price_model / C.price_real)
C["l_err_pct"] = 100 * (C.l_model / C.l_real - 1)
C.to_csv(a.out, index=False)
q = lambda c: np.nanpercentile(C[c].abs(), [50, 90, 99, 100]).round(4).tolist()
print(f"{len(C):,} swaps. |error| percentiles 50/90/99/max: USDG amount {q('usdg_err_bp')} bp, post-swap price {q('price_err_bp')} bp, "
      f"active liquidity {q('l_err_pct')} %")
print("unfilled swaps:", int(((C.eth_filled - C.eth).abs() > 1e-12).sum()))
