"""
Historical replay of the Fynd ETH/USDG pool under alternative bot policies.

What is replayed, second by second from the bot's first trade to its last before the Nov 13 snapshot:
  - Binance ETHUSDC 1 s (reference, price "at T" = close of the candle opening at T-2, as everywhere else)
  - every non-bot swap, with the ETH amount it actually traded (its USDG side is recomputed on the simulated pool)
    and the fee rate it actually paid
  - every LP deposit and withdrawal (position events), so the pool has its real liquidity profile over price at every
    second; swaps are walked across range boundaries (pool_model.py, which reproduces all 28,100 real swaps to
    within 0.77 bp in USDG amount, out/check_pool_model.csv)
  - the bot, which may trade once per second while it is "up". Up = inside the real bot's activity: any stretch
    where its real trades are less than an hour apart (the real bot went quiet for >1 h 32 times, 136 h in all).

The bot model (fitted to the rebuilt transactions, see calibration block in policy_simulation.csv):
  - it hedges each Fynd trade on other on-chain pools at Binance x (1 + c) when buying ETH back and x (1 - c) when
    selling it; c = median |hedge price vs Binance| of the real trades
  - it pays the Fynd fee f, a router fee rho and gas G per trade (means of the real trades)
  - a profit-maximising bot moves Fynd until its marginal price equals the hedge price after fees, i.e. to a gap of
    s = c + f + rho from Binance, and trades only if the expected net profit >= m. Policy A fits m to the real
    number of trades. The fitted s is checked against the real post-trade gap.


What it cannot show: traders, routers and LPs reacting to a different pool (volume, routing, deposits). A different
bot fee is shown with the bot re-optimising its own trades, everything else fixed. This is a replay, not a forecast.

  python3 policy_sim.py --out out --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv \
      --klines ../markout-backtest/klines_eth_1s ../markout-backtest/klines_eth_1s_lp data/klines_nov13
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd
from pool_model import Pool

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True); ap.add_argument("--lp-swaps", required=True)
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--events", required=True)
a = ap.parse_args()

T = pd.read_pickle(os.path.join(a.out, "_T.pkl"))
T = T[T.completeness.str.startswith("complete")]
FP = pd.read_pickle(os.path.join(a.out, "_FP.pkl"))
BM = json.load(open(os.path.join(a.out, "_build_meta.json")))
PROTO = BM["protocol_share"]
SW = pd.read_csv(a.lp_swaps)

frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.Series(k[4].astype(float).values, index=np.where(t > 1e14, t // 10**6, t // 10**3) + 1)
ref = ref[~ref.index.duplicated()].sort_index()

# ------------------------------------------------------------------ calibration from the real bot trades
c_hedge = float(T.hedge_vs_binance_bp.abs().median())
f_bot = float(1e4 * T.fee_usd.sum() / T.notional_usd.sum())
rho = float(1e4 * (T.router_fee_eth_wei / 1e18 * T.b0 + T.router_fee_usdg_raw / 1e6).sum() / T.notional_usd.sum())
gas = float(T.gas_usd.mean())
real_gap_after = float(T.gap_after_bp.abs().median())
real_gap_before = float(T.gap_before_bp.abs().median())

# ------------------------------------------------------------------ the replay grid
bot_ts = np.sort(SW[SW.bot_wallet].ts.values)
w0, w1 = int(bot_ts[0]), int(bot_ts[-1])
sec = np.arange(w0, w1 + 1)
B = ref.reindex(sec - 1, method="ffill").values                 # price "at T"
B12 = ref.reindex(sec + 12, method="ffill").values
P_END = float(B[-1])
gaps = np.diff(bot_ts)
up = np.zeros(len(sec), bool)
for t0, g in zip(bot_ts[:-1], gaps):
    if g <= 3600:
        up[t0 - w0:t0 - w0 + g + 1] = True
P0 = float(FP[FP.ts < w0].price.iloc[-1])
EV = pd.read_csv(a.events); EV = EV[EV.event == "position"].sort_values(["block", "log_index"])
ev_pre = EV[EV.ts < w0]; ev_in = EV[(EV.ts >= w0) & (EV.ts <= w1)]
ev_i = (ev_in.ts.values - w0).astype(int)
ev_rows = list(ev_in[["pos", "tick_lower", "tick_upper", "liquidity_delta"]].itertuples(index=False))
ev_s = np.searchsorted(ev_i, np.arange(len(sec)), side="left"); ev_e = np.searchsorted(ev_i, np.arange(len(sec)), side="right")
ext = SW[(~SW.bot_wallet) & (SW.ts >= w0) & (SW.ts <= w1)].sort_values(["block", "log_index"])
ext_rate = (ext.fee_usd / (1 - PROTO) / ext.volume_usd).fillna(0).values
ext_i = (ext.ts.values - w0).astype(int)
ext_x = ext.eth_to_pool.values
# per-second list of external swaps
starts = np.searchsorted(ext_i, np.arange(len(sec)), side="left")
ends = np.searchsorted(ext_i, np.arange(len(sec)), side="right")


def run(m=0.0, theta=0.0, f=f_bot, cap=None, always_on=False, kappa=0.0, c=c_hedge):
    """Replay one policy. Returns totals. m: min expected net profit (USD); theta: min |gap| (bp) to trade;
    f: Fynd fee charged to the bot (bp); cap: max price move per trade (bp); kappa: inventory awareness."""
    s_stop = (c + f + rho) / 1e4                                   # profit-maximising stop, as a log-gap
    pool = Pool(np.sqrt(P0))
    for e in ev_pre[["pos", "tick_lower", "tick_upper", "liquidity_delta"]].itertuples(index=False):
        pool.update(*e)
    unfilled = 0.0
    lp_mk_bot = lp_mk_ext = fees_bot = fees_ext = 0.0
    end_x = end_y = 0.0                                            # LP token changes, for the end-marked result
    bot_gross = bot_gas = bot_router = vol_bot = vol_ext = 0.0
    n_bot = 0; missed = 0
    inv = 0.0; inv_ref = 5.0                                       # ETH the bot has pushed into the pool (for F)
    abs_gap_sum = 0.0; over10 = 0
    on = np.ones(len(sec), bool) if always_on else up
    theta_l = theta / 1e4; real_thr = real_gap_before / 1e4
    cap_l = cap / 1e4 if cap else None
    for i in range(len(sec)):
        b = B[i]
        for j in range(ev_s[i], ev_e[i]):                           # LP deposits / withdrawals this second
            pool.update(*ev_rows[j])
        for j in range(starts[i], ends[i]):                         # external swaps this second
            lim = np.sqrt(b * (0.98 if ext_x[j] > 0 else 1.02))     # trader's limit: 2% from Binance
            x, y = pool.swap_eth_in(ext_x[j], lim)                 # same ETH amount, USDG from the simulated pool
            unfilled += abs(ext_x[j] - x)
            lp_mk_ext += x * B12[i] + y
            fees_ext += ext_rate[j] * abs(x) * b
            vol_ext += abs(x) * b
            end_x += x; end_y += y
        g = 2 * np.log(pool.s) - np.log(b)                         # log(P / B)
        ag = abs(g)
        abs_gap_sum += ag
        if ag > 10e-4:
            over10 += 1
        if not on[i] or ag <= s_stop:
            if on[i] and ag >= real_thr:
                missed += 1
            continue
        tgt = np.sign(g) * s_stop
        if cap_l is not None and ag - s_stop > cap_l:
            tgt = g - np.sign(g) * cap_l
        s_before = pool.s
        x, y = pool.move_to(np.sqrt(b * np.exp(tgt)))             # ETH, USDG to pool (+ ETH = bot sells ETH into Fynd)
        notional = abs(x) * b
        hedge = x * b * (1 + np.sign(x) * c / 1e4)                 # USDG the bot pays to buy x ETH back (or receives)
        gross = -y - hedge - (f + rho) / 1e4 * notional
        net = gross - gas
        need = m
        if kappa and np.sign(x) == np.sign(inv) and inv != 0:      # F: pushing the pool further the same way costs more
            need = m + kappa * gas * abs(inv) / inv_ref
        if ag < theta_l or net < need or x == 0.0:
            pool.s = s_before                                      # undo: the trade is not made (curve unchanged)
            if ag >= real_thr:
                missed += 1
            continue
        lp_mk_bot += x * B12[i] + y
        fees_bot += f / 1e4 * notional
        bot_gross += gross; bot_gas += gas; bot_router += rho / 1e4 * notional
        vol_bot += notional; n_bot += 1; inv += x
        end_x += x; end_y += y
    fees_all = fees_bot + fees_ext
    return {"bot_trades": n_bot, "bot_volume_usd": vol_bot, "external_volume_usd": vol_ext,
            "lp_markout_12s_bot_usd": lp_mk_bot, "lp_markout_12s_external_usd": lp_mk_ext,
            "lp_fees_usd": fees_all * (1 - PROTO), "protocol_fees_usd": fees_all * PROTO,
            "lp_net_trading_12s_usd": lp_mk_bot + lp_mk_ext + fees_all * (1 - PROTO),
            "lp_il_proxy_at_end_usd": end_x * P_END + end_y,
            "lp_vs_hold_proxy_usd": end_x * P_END + end_y + fees_all * (1 - PROTO),
            "bot_gross_usd": bot_gross, "bot_gas_usd": bot_gas, "bot_router_fees_usd": bot_router, "bot_net_usd": bot_gross - bot_gas,
            "mean_abs_gap_bp": 1e4 * abs_gap_sum / len(sec), "share_time_gap_over_10bp": over10 / len(sec),
            "unexecuted_opportunities_s": missed, "external_eth_unfilled": unfilled}


# ------------------------------------------------------------------ fit policy A's min profit to the real trade count
real_n = int(len(bot_ts))
fits = []
for m in [0.0, 0.002, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12]:
    r = run(m=m); fits.append((m, r["bot_trades"])); print("fit m", m, r["bot_trades"], flush=True)
    if r["bot_trades"] < real_n:
        break
m_A = min(fits, key=lambda z: abs(z[1] - real_n))[0]
print(f"policy A: min net profit ${m_A}, stop at {c_hedge + f_bot + rho:.2f} bp (real median post-trade gap {real_gap_after:.2f} bp)")

pols = [("A", "existing policy, reconstructed", dict(m=m_A)),
        ("A0", "A with the bot always on (no >1 h pauses)", dict(m=m_A, always_on=True))]
for th in [8, 10, 15]:
    pols.append((f"B{th}", f"A + minimum gap {th} bp before trading", dict(m=m_A, theta=th)))
for mm in [0.05, 0.25, 1.0]:
    pols.append((f"C{mm}", f"minimum expected net profit ${mm} after fees and gas", dict(m=mm)))
f_ext = float(1e4 * SW[~SW.bot_wallet].fee_usd.sum() / (1 - PROTO) / SW[~SW.bot_wallet].volume_usd.sum())
for ff in [0.0, 3.0, 5.0, 10.0, round(f_ext, 1)]:
    lab = f"Fynd fee on bot trades {ff:g} bp (bot re-optimises)" + (" = what other traders pay: a one-fee passive pool" if ff == round(f_ext, 1) else "")
    pols.append((f"D{ff:g}", lab, dict(m=m_A, f=ff)))
for cp in [1.0, 2.0]:
    pols.append((f"E{cp:g}", f"A + max price move {cp:g} bp per trade", dict(m=m_A, cap=cp)))
for kp in [1.0, 5.0]:
    pols.append((f"F{kp:g}", f"A + inventory-aware threshold (kappa {kp:g})", dict(m=m_A, kappa=kp)))
for cc in [1.0, 2.0]:
    pols.append((f"H{cc:g}", f"A with cheaper hedging: {cc:g} bp instead of {c_hedge:.1f} bp (needs an off-chain or better venue)", dict(m=m_A, c=cc)))
res = []
for code, desc, kw in pols:
    r = run(**kw); r.update({"policy": code, "description": desc, "params": json.dumps(kw)}); res.append(r)
    print(code, {k: round(v, 1) if isinstance(v, float) else v for k, v in r.items() if k not in ("description", "params")}, flush=True)
out = pd.DataFrame(res)
out["lp_fee_share_100pct_usd"] = out.lp_fees_usd / (1 - PROTO)          # D: fee-sharing variants, same trades
out["lp_net_trading_12s_if_lps_got_100pct"] = out.lp_net_trading_12s_usd + out.protocol_fees_usd
# real history over the same window, for the calibration check
real = SW[(SW.ts >= w0) & (SW.ts <= w1)]
cal = {"policy": "REAL", "description": "what happened (same window, same measures)", "bot_trades": real_n,
       "bot_volume_usd": float(real[real.bot_wallet].volume_usd.sum()), "external_volume_usd": float(real[~real.bot_wallet].volume_usd.sum()),
       "lp_markout_12s_bot_usd": -float(real[real.bot_wallet].loss_12s_usd.sum()), "lp_markout_12s_external_usd": -float(real[~real.bot_wallet].loss_12s_usd.sum()),
       "lp_fees_usd": float(real.fee_usd.sum()), "protocol_fees_usd": float(real.fee_usd.sum() / (1 - PROTO) * PROTO),
       "lp_net_trading_12s_usd": float(real.net_for_lps_usd.sum()),
       "lp_il_proxy_at_end_usd": float((real.eth_to_pool * P_END + real.usdg_to_pool).sum()),
       "lp_vs_hold_proxy_usd": float((real.eth_to_pool * P_END + real.usdg_to_pool).sum() + real.fee_usd.sum()),
       "bot_gross_usd": float(T.bot_gross_usd.sum()), "bot_gas_usd": float(T.gas_usd.sum()),
       "bot_router_fees_usd": float((T.router_fee_eth_wei / 1e18 * T.b0 + T.router_fee_usdg_raw / 1e6).sum()),
       "bot_net_usd": float(T.bot_net_usd.sum())}
gp = 1e4 * np.log(pd.Series(FP.groupby("ts").price.last()).reindex(sec, method="ffill").values / B)
cal.update({"mean_abs_gap_bp": float(np.nanmean(np.abs(gp))), "share_time_gap_over_10bp": float(np.nanmean(np.abs(gp) > 10))})
out = pd.concat([pd.DataFrame([cal]), out], ignore_index=True)
out["calibration"] = json.dumps({"hedge_cost_bp": c_hedge, "bot_fee_bp": f_bot, "router_fee_bp": rho, "gas_usd_per_trade": gas,
                                 "stop_gap_bp": c_hedge + f_bot + rho, "real_median_abs_gap_after_bp": real_gap_after,
                                 "real_median_abs_gap_before_bp": real_gap_before, "min_profit_A_usd": m_A,
                                 "window_utc": [str(pd.Timestamp(w0, unit='s')), str(pd.Timestamp(w1, unit='s'))],
                                 "eth_end": P_END, "bot_up_share_of_time": float(up.mean())})
out.to_csv(os.path.join(a.out, "policy_simulation.csv"), index=False)
print(out.drop(columns=["calibration", "params", "description"]).round(1).to_string())
