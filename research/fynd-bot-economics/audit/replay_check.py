"""
Validate the pool model behind the bottom-panel replays (pool_model.py) against history, swap by swap and position by position.

  A. every real Fynd swap (28,100) and position event in on-chain order, from the first position event:
       per swap, BEFORE re-anchoring: model USDG amount vs logged amount1, model post-swap price vs logged price,
       model active liquidity vs logged liquidity; then the price is re-anchored to the logged one (as in REAL)
  B. open loop (no re-anchoring): how far the model drifts from history when errors are allowed to compound
  C. LP vs holding per position, reset at the position's own events, valued at Binance (price "at T"), compared with the
     checked LP report's il_usd for positions with one deposit and one withdrawal (where the two definitions coincide)
  D. token conservation: sum over positions of token changes vs sum of the swaps' amounts (pool received)

  python3 audit/replay_check.py --root . --lp ../markout-backtest --out audit
"""
import argparse, json, math, os, sys
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
sys.path.insert(0, a.root)
from pool_model import Pool  # noqa: E402

D = os.path.join(a.lp, "data_swaps")
E = pd.read_csv(os.path.join(D, "eth_usdg_ekubo_robinhood_lp_to1113_events.csv")); E = E[E.event == "position"]
S = pd.concat([pd.read_csv(os.path.join(D, f), usecols=["block", "log_index", "ts", "tx_hash", "amount0", "amount1", "price", "liquidity"])
               for f in ["eth_usdg_ekubo_robinhood_to1108.csv", "eth_usdg_ekubo_robinhood_nov9_11.csv", "eth_usdg_ekubo_robinhood_nov11_13.csv"]]) \
    .drop_duplicates(["block", "log_index"])
ev = pd.concat([E.assign(kind="pos")[["block", "log_index", "ts", "kind", "pos", "tick_lower", "tick_upper", "liquidity_delta"]],
                S.assign(kind="swap")]).sort_values(["block", "log_index"]).reset_index(drop=True)
ref = pd.read_pickle(os.path.join(a.out, "data", "_binance.pkl")).close
ev["B"] = ref.reindex(ev.ts.astype("int64") - 1, method="ffill").values


def tokens(p, s):
    lo, hi, l = p
    if s <= lo:
        return l * (1 / lo - 1 / hi), 0.0
    if s >= hi:
        return 0.0, l * (hi - lo)
    return l * (1 / s - 1 / hi), l * (s - lo)


def run(anchor):
    pool = None; mark = {}; acc = {}; tok = {}; rows = []
    started = False
    for r in ev.itertuples():
        if r.kind == "pos":
            if pool is None:
                pool = Pool(math.sqrt(2700.0))
            k = r.pos
            if k in pool.pos and k in mark:
                x2, y2 = tokens(pool.pos[k], pool.s); x1, y1 = mark[k]
                acc[k] = acc.get(k, 0.0) + (x2 - x1) * r.B + (y2 - y1)
                tok[k] = (tok.get(k, (0, 0))[0] + x2 - x1, tok.get(k, (0, 0))[1] + y2 - y1)
            pool.update(k, r.tick_lower, r.tick_upper, r.liquidity_delta)
            if k in pool.pos:
                mark[k] = tokens(pool.pos[k], pool.s)
            else:
                mark.pop(k, None)
            continue
        if pool is None:
            continue
        if not started:                                   # first swap: start from the logged price before it
            pool.s = math.sqrt(r.price); started = True
            for k in pool.pos:
                mark[k] = tokens(pool.pos[k], pool.s)
            continue
        x, y = pool.swap_eth_in(r.amount0)
        rows.append({"block": r.block, "log_index": r.log_index, "ts": r.ts, "tx_hash": r.tx_hash, "eth": r.amount0, "usdg_real": r.amount1,
                     "usdg_model": y, "eth_filled": x, "price_real": r.price, "price_model": pool.s ** 2,
                     "l_real": r.liquidity * 1e-12, "l_model": pool.liquidity()})
        if anchor:
            pool.s = math.sqrt(r.price)
    for k in list(pool.pos):
        if k in mark:
            x2, y2 = tokens(pool.pos[k], pool.s); x1, y1 = mark[k]
            acc[k] = acc.get(k, 0.0) + (x2 - x1) * ev.B.iloc[-1] + (y2 - y1)
            tok[k] = (tok.get(k, (0, 0))[0] + x2 - x1, tok.get(k, (0, 0))[1] + y2 - y1)
    return pd.DataFrame(rows), acc, tok


res = {}
for anchor in (True, False):
    C, acc, tok = run(anchor)
    C["usdg_err_bp"] = 1e4 * (C.usdg_model / C.usdg_real - 1)
    C["price_err_bp"] = 1e4 * np.log(C.price_model / C.price_real)
    C["l_err_pct"] = 100 * (C.l_model / C.l_real - 1)
    C["usdg_err_usd"] = C.usdg_model - C.usdg_real
    tag = "anchored" if anchor else "open_loop"
    q = lambda c: [float(np.nanpercentile(C[c].abs(), p)) for p in (50, 90, 99, 100)]
    res[tag] = {"swaps": len(C), "usdg_err_bp_p50_p90_p99_max": q("usdg_err_bp"), "price_err_bp_p50_p90_p99_max": q("price_err_bp"),
                "liquidity_err_pct_p50_p90_p99_max": q("l_err_pct"), "cum_usdg_err_usd": float(C.usdg_err_usd.sum()),
                "cum_abs_usdg_err_usd": float(C.usdg_err_usd.abs().sum()),
                "max_abs_usdg_err_usd": float(C.usdg_err_usd.abs().max()),
                "unfilled_swaps": int(((C.eth_filled - C.eth).abs() > 1e-12).sum()),
                "swaps_price_err_over_1bp": int((C.price_err_bp.abs() > 1).sum()),
                "swaps_liquidity_err_over_1pct": int((C.l_err_pct.abs() > 1).sum())}
    if anchor:
        C.to_csv(os.path.join(a.out, "data", "replay_per_swap_anchored.csv"), index=False)
        A, TOK = acc, tok
        sw_eth, sw_usdg = float(C.eth.sum()), float(C.usdg_real.sum())
        res["conservation"] = {"positions_token_change_eth": float(sum(v[0] for v in TOK.values())),
                               "positions_token_change_usdg": float(sum(v[1] for v in TOK.values())),
                               "swaps_eth_to_pool": sw_eth, "swaps_usdg_to_pool": sw_usdg}
    else:
        C.to_csv(os.path.join(a.out, "data", "replay_per_swap_open_loop.csv"), index=False)
# position-level comparison with the checked LP report
P = pd.read_csv(os.path.join(a.lp, "results_lp_fynd_positions.csv"))
nev = E.groupby("pos").liquidity_delta.agg(n="size", adds=lambda s: int((s > 0).sum()), rems=lambda s: int((s < 0).sum()))
P = P.merge(nev, left_on="pos", right_index=True, how="left")
P["replay_il_usd"] = P.pos.map(A)
simple = P[(P.adds == 1) & (P.rems <= 1)].copy()
simple["diff_usd"] = simple.replay_il_usd - simple.il_usd
res["positions"] = {"positions": len(P), "simple_positions": len(simple),
                    "checked_il_usd_all": float(P.il_usd.sum()), "replay_il_usd_all": float(P.replay_il_usd.sum()),
                    "checked_il_usd_simple": float(simple.il_usd.sum()), "replay_il_usd_simple": float(simple.replay_il_usd.sum()),
                    "simple_max_abs_diff_usd": float(simple.diff_usd.abs().max()), "simple_median_abs_diff_usd": float(simple.diff_usd.abs().median()),
                    "simple_sum_abs_diff_usd": float(simple.diff_usd.abs().sum())}
P[["pos", "owner", "start_utc", "end_utc", "adds", "rems", "il_usd", "replay_il_usd"]].to_csv(os.path.join(a.out, "data", "replay_positions.csv"), index=False)
json.dump(res, open(os.path.join(a.out, "data", "replay_check.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
