"""
Is the LPs' loss against holding the same thing as what the bot captured? Did the bot's trades add to that loss?

Two tests, nothing in out/ or the checked reports is changed:

1. Horizons. For every real bot trade: the Fynd LPs' result on the swap valued at Binance at execution and 12 s, 60 s, 5 min,
   30 min and 1 h later, next to the bot's own realized gross (from its token flows). If the bot traded on noise, the LPs'
   loss would shrink at longer horizons (prices come back); if it traded on real price moves, it would not.

2. Counterfactual replay, LP vs hold per position (same pool model as policy_sim.py, pool_model.py; Oct 13 - Nov 13 window):
     REAL      history: every real swap in on-chain order, the price re-anchored to the logged post-swap price after each
               (as validate_pool_model.py does), so this mode checks the method against the checked LP results
     NO_BOT    external swaps only: nobody else arbitrages the pool (a lower bound on arbitrage, not a forecast)
     OUTSIDE   no Fynd bot; an outside arbitrageur that pays what external traders pay (19.8 bp gross), hedges at the real
               bot's cost and is always on
   LP vs hold is measured per position: between two of its own events (deposit, withdrawal, window end) a position's token
   change is valued at Binance at the later event: (x2 - x1) * P2 + (y2 - y1). Fees are added separately (LPs' 80%).

  python3 final/il_attribution.py --root . --lp ../markout-backtest --out final/data/il_attribution.json
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--modes", default="REAL,NO_BOT,OUTSIDE")
a = ap.parse_args()
sys.path.insert(0, a.root)
from pool_model import Pool  # noqa: E402

O = os.path.join(a.root, "out")
T = pd.read_pickle(os.path.join(O, "_T.pkl")); T = T[T.completeness.str.startswith("complete")]
FP = pd.read_pickle(os.path.join(O, "_FP.pkl"))
PROTO = json.load(open(os.path.join(O, "_build_meta.json")))["protocol_share"]
SW = pd.read_csv(os.path.join(a.lp, "results_lp_fynd_split_swaps.csv"))
EVF = pd.read_csv(os.path.join(a.lp, "data_swaps", "eth_usdg_ekubo_robinhood_lp_to1113_events.csv"))
frames = []
for d in [os.path.join(a.lp, "klines_eth_1s"), os.path.join(a.lp, "klines_eth_1s_lp"), os.path.join(a.root, "data", "klines_nov13")]:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.Series(k[4].astype(float).values, index=np.where(t > 1e14, t // 10**6, t // 10**3) + 1)
ref = ref[~ref.index.duplicated()].sort_index()
res = {}

# ================================================================== 1. horizons, real bot trades
bot = SW[SW.bot_wallet].copy()
H = {"execution": -1, "12 s": 12, "60 s": 60, "5 min": 300, "30 min": 1800, "1 h": 3600}
hz = {}
for nm, h in H.items():
    p = ref.reindex(bot.ts.values + h, method="ffill").values
    hz[nm] = float(np.nansum(bot.eth_to_pool.values * p + bot.usdg_to_pool.values))
res["horizons"] = {"lp_swap_side_on_bot_swaps_usd": hz, "lp_fees_on_bot_swaps_usd": float(bot.fee_usd.sum()),
                   "bot_gross_realized_usd": float(T.bot_gross_usd.sum()), "bot_net_realized_usd": float(T.bot_net_usd.sum()),
                   "bot_gas_usd": float(T.gas_usd.sum()), "n_bot_swaps": int(len(bot))}
print(json.dumps(res["horizons"], indent=1), flush=True)

# ================================================================== 2. replays
c_hedge = float(T.hedge_vs_binance_bp.abs().median())
rho = float(1e4 * (T.router_fee_eth_wei / 1e18 * T.b0 + T.router_fee_usdg_raw / 1e6).sum() / T.notional_usd.sum())
gas = float(T.gas_usd.mean())
f_ext = float(1e4 * SW[~SW.bot_wallet].fee_usd.sum() / (1 - PROTO) / SW[~SW.bot_wallet].volume_usd.sum())
bot_ts = np.sort(bot.ts.values); w0, w1 = int(bot_ts[0]), int(bot_ts[-1])
sec = np.arange(w0, w1 + 1)
B = ref.reindex(sec - 1, method="ffill").values
B12 = ref.reindex(sec + 12, method="ffill").values
P0 = float(FP[FP.ts < w0].price.iloc[-1])
EV = EVF[EVF.event == "position"].sort_values(["block", "log_index"])
owner = EV.groupby("pos").owner.first().str.lower()
ev_pre = EV[EV.ts < w0]; ev_in = EV[(EV.ts >= w0) & (EV.ts <= w1)]
ev_i = (ev_in.ts.values - w0).astype(int)
ev_rows = list(ev_in[["pos", "tick_lower", "tick_upper", "liquidity_delta"]].itertuples(index=False))
ev_s = np.searchsorted(ev_i, np.arange(len(sec)), side="left"); ev_e = np.searchsorted(ev_i, np.arange(len(sec)), side="right")
win = SW[(SW.ts >= w0) & (SW.ts <= w1)].sort_values(["block", "log_index"])
sw_i = (win.ts.values - w0).astype(int); sw_x = win.eth_to_pool.values; sw_bot = win.bot_wallet.values
sw_rate = np.where(sw_bot, 0.0, (win.fee_usd / (1 - PROTO) / win.volume_usd).replace([np.inf, -np.inf], np.nan).fillna(0).values)   # externals: gross rate
sw_fee_lp_real = win.fee_usd.values
_fp = FP.drop_duplicates(["block", "log_index"]).set_index(["block", "log_index"]).price
sw_price = _fp.reindex(pd.MultiIndex.from_arrays([win.block.values, win.log_index.values])).values   # real post-swap price
assert not np.isnan(sw_price).any(), "a swap without a logged post-swap price"                                                               # LP share, as paid
s_s = np.searchsorted(sw_i, np.arange(len(sec)), side="left"); s_e = np.searchsorted(sw_i, np.arange(len(sec)), side="right")
# one stream of position events (kind 0) and swaps (kind 1) in on-chain order (block, log index)
ST = pd.concat([pd.DataFrame({"block": ev_in.block.values, "li": ev_in.log_index.values, "kind": 0, "j": np.arange(len(ev_in)), "i": ev_i}),
                pd.DataFrame({"block": win.block.values, "li": win.log_index.values, "kind": 1, "j": np.arange(len(win)), "i": sw_i})]
               ).sort_values(["block", "li"], kind="stable")
st_kind, st_j, st_i = ST.kind.values, ST.j.values, ST.i.values
q_s = np.searchsorted(st_i, np.arange(len(sec)), side="left"); q_e = np.searchsorted(st_i, np.arange(len(sec)), side="right")


def tokens(p, s):
    lo, hi, l = p
    if s <= lo:
        return l * (1 / lo - 1 / hi), 0.0
    if s >= hi:
        return 0.0, l * (hi - lo)
    return l * (1 / s - 1 / hi), l * (s - lo)


def replay(mode):
    """mode: REAL, NO_BOT, OUTSIDE. Returns totals and LP vs hold per owner group."""
    pool = Pool(np.sqrt(P0))
    for e in ev_pre[["pos", "tick_lower", "tick_upper", "liquidity_delta"]].itertuples(index=False):
        pool.update(*e)
    mark = {key: tokens(p, pool.s) for key, p in pool.pos.items()}
    acc = {}                                                       # pos -> LP vs hold (USD), ex fees

    def close(key, P):
        if key in pool.pos and key in mark:
            x2, y2 = tokens(pool.pos[key], pool.s); x1, y1 = mark[key]
            acc[key] = acc.get(key, 0.0) + (x2 - x1) * P + (y2 - y1)

    fees_lp = {"bot": 0.0, "external": 0.0}
    mk12 = {"bot": 0.0, "external": 0.0}; mk0 = {"bot": 0.0, "external": 0.0}
    vol = {"bot": 0.0, "external": 0.0}; n = {"bot": 0, "external": 0}
    arb_gross = arb_gas = 0.0; gap_sum = 0.0; unfilled = 0.0
    s_stop = (c_hedge + f_ext + rho) / 1e4
    for i in range(len(sec)):
        b = B[i]
        for q in range(q_s[i], q_e[i]):
            j = st_j[q]
            if st_kind[q] == 0:                                    # deposit / withdrawal
                key = ev_rows[j][0]
                close(key, b)
                pool.update(*ev_rows[j])
                if key in pool.pos:
                    mark[key] = tokens(pool.pos[key], pool.s)
                else:
                    mark.pop(key, None)
                continue
            who = "bot" if sw_bot[j] else "external"
            if who == "bot" and mode != "REAL":
                continue
            # REAL replays history: no limit. Otherwise the trader's limit is 2% from Binance.
            lim = None if mode == "REAL" else np.sqrt(b * (0.98 if sw_x[j] > 0 else 1.02))
            x, y = pool.swap_eth_in(sw_x[j], lim)
            if mode == "REAL":
                pool.s = np.sqrt(sw_price[j])                      # re-anchor to the logged price (errors don't compound)
            unfilled += abs(sw_x[j] - x)
            mk12[who] += x * B12[i] + y; mk0[who] += x * b + y
            vol[who] += abs(x) * b; n[who] += 1
            fees_lp[who] += sw_fee_lp_real[j] if who == "bot" else sw_rate[j] * abs(x) * b * (1 - PROTO)
        g = 2 * np.log(pool.s) - np.log(b)
        gap_sum += abs(g)
        if mode == "OUTSIDE" and abs(g) > s_stop:
            s_before = pool.s
            x, y = pool.move_to(np.sqrt(b * np.exp(np.sign(g) * s_stop)))
            notional = abs(x) * b
            gross = -y - x * b * (1 + np.sign(x) * c_hedge / 1e4) - (f_ext + rho) / 1e4 * notional
            if gross - gas < 0 or x == 0.0:
                pool.s = s_before; continue
            arb_gross += gross; arb_gas += gas
            mk12["bot"] += x * B12[i] + y; mk0["bot"] += x * b + y
            vol["bot"] += notional; n["bot"] += 1
            fees_lp["bot"] += f_ext / 1e4 * notional * (1 - PROTO)
    for key in list(pool.pos):
        close(key, B[-1])
    lvh = pd.Series(acc)
    grp = lvh.groupby(lambda key: "0x6c6a...7127" if owner.get(key, "") == "0x6c6a40d2d1fc442e281e1f80314fd86516e17127" else "all other LPs").sum()
    fee_total = fees_lp["bot"] + fees_lp["external"]
    return {"mode": mode, "swaps": n, "volume_usd": vol, "lp_swap_side_at_execution_usd": mk0, "lp_swap_side_12s_usd": mk12,
            "lp_fees_usd": fees_lp, "lp_vs_hold_ex_fees_usd": float(lvh.sum()), "lp_vs_hold_usd": float(lvh.sum() + fee_total),
            "lp_vs_hold_ex_fees_by_group_usd": grp.to_dict(), "mean_abs_gap_bp": 1e4 * gap_sum / len(sec),
            "arbitrageur_gross_usd": arb_gross, "arbitrageur_net_usd": arb_gross - arb_gas, "external_eth_unfilled": unfilled}


res["params"] = {"hedge_cost_bp": c_hedge, "router_bp": rho, "gas_usd": gas, "outside_fee_bp": f_ext, "protocol_share": PROTO,
                 "window_utc": [str(pd.Timestamp(w0, unit="s")), str(pd.Timestamp(w1, unit="s"))]}
res["replays"] = {}
for mode in a.modes.split(","):
    r = replay(mode); res["replays"][mode] = r
    print(json.dumps(r, indent=1, default=float), flush=True)
json.dump(res, open(a.out, "w"), indent=1, default=float)
