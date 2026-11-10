"""
Who trades against LPs, and what it costs them, for one ETH/stable pool: arbitrage vs other flow, per swap and per wallet.

Per swap (token0 = ETH in both Robinhood pools; reference = Binance ETH/USDC 1 s, stable taken as $1):
  gap_bp      pool price just before the swap vs Binance at the block (pre-swap price = previous swap's post price)
  arbitrage   the swap moves the pool toward Binance AND |gap| exceeds the fee it paid: decided from the state the
              trader saw, not from how the trade turned out
  markout_h   LP value change, fee excluded, valued at Binance h seconds later (negative = trade hurt LPs)
  lp_pnl      fee + markout_12
Per wallet (tx signer when the file has it, else the contract that called the pool):
  arbitrage bot  >= 50% of its swaps are arbitrage and >= 20 swaps
  toxic          not a bot, and markout_12 per $ worse than minus the fee it paid (LPs lose on it after fees)
  genuine        the rest: fees cover what it took
Wallet classes use the whole window (after the fact); --persistence also labels wallets on the first half and scores
them on the second, which is the honest test of whether a class could be priced in advance.
Internal flow: wallets in INTERNAL_WALLETS (plus --internal) are treated as the pool operator's own; see the comment there.
Every metric is reported twice: all flow, and external only.

Also written (see README_flow_fynd.md for assumptions):
  <prefix>_groups.csv      volume, fees, markout 0/12/60 s, LP net, each also in bp of volume, per group and scope
  <prefix>_excluded.csv    every swap dropped, with the reason
  <prefix>_tvl_daily.csv   pool holdings rebuilt from position, swap and fee events (--positions), valued at Binance
  <prefix>_fee_sweep.csv   external arbitrage swaps under a flat fee f = 0..30 bp, assuming a swap happens only if gap > f
  <prefix>_lvr_weekly.csv  theoretical LVR vs measured loss per week, with sigma and the active liquidity used

  python3 flow_classify.py --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv --fee-mode events \
      --name "Fynd AMM ETH/USDG (Ekubo, Robinhood)" --tvl 10490 --end 2026-11-06 --persistence \
      --positions data_swaps/eth_usdg_ekubo_robinhood_positions.csv --out-prefix results_flow_fynd
  python3 flow_classify.py --swaps data_swaps/weth_usdg_1bp_robinhood.csv --fee-mode fixed --fee-bp 1 --lp-fee-share 0.75 \
      --name "Uniswap v3 USDG/WETH 0.01%" --tvl 12818600 --out-prefix results_flow_uni_usdg
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd
from flow_lib import markout, toward_binance, is_arbitrage, attribute_fees

# Wallets treated as the pool operator's own. 0x4abfdbac is listed by us, not by Fynd: every one of its swaps goes
# through 0x7ea0ab3b. Not confirmed by the Fynd team. Their flow is labelled "internal", never inferred here.
INTERNAL_WALLETS = {"0x4abfdbac0afa181338dc9c38c9c1264128c684a2"}

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--klines", default="klines_eth_1s")
ap.add_argument("--fee-mode", choices=["fixed", "columns", "events"], required=True,
                help="fixed: pool fee taken from the input amount (Uniswap); columns: fee0/fee1 per swap; events: each "
                     "FeesAccumulated event in --positions pays for the swaps since the previous one (Ekubo extension)")
ap.add_argument("--fee-bp", type=float, default=0.0); ap.add_argument("--lp-fee-share", type=float, default=1.0)
ap.add_argument("--dec0", type=int, default=18); ap.add_argument("--dec1", type=int, default=6)
ap.add_argument("--name", required=True); ap.add_argument("--tvl", type=float, default=0.0, help="USD, today's (no history)")
ap.add_argument("--start", default=""); ap.add_argument("--end", default="", help="exclusive, UTC date")
ap.add_argument("--max-dev-bp", type=float, default=100.0); ap.add_argument("--persistence", action="store_true")
ap.add_argument("--internal", nargs="*", default=[], help="wallets to add to INTERNAL_WALLETS")
ap.add_argument("--positions", default="", help="fetch_ekubo_positions.py output, for daily TVL")
ap.add_argument("--max-sweep-bp", type=int, default=30)
ap.add_argument("--out-prefix", required=True)
a = ap.parse_args()
internal = {w.lower() for w in INTERNAL_WALLETS | set(a.internal)}
H = [0, 12, 60, 300]

frames = []
for p in sorted(glob.glob(os.path.join(a.klines, "*.zip"))):
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            frames.append(pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]))
k = pd.concat(frames)
t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}) \
    .drop_duplicates("ts").sort_values("ts")

sw = pd.read_csv(a.swaps).sort_values(["block", "log_index"]).reset_index(drop=True)
if "price" not in sw:                                           # Uniswap: sqrtPriceX96 after the swap
    sw["price"] = (sw.sqrtPriceX96.astype(float) / 2**96) ** 2 * 10 ** (a.dec0 - a.dec1)
sw["pre"] = sw.price.shift(1)
if a.fee_mode == "events":
    pe = pd.read_csv(a.positions)
    sw["fee0"], sw["fee1"] = attribute_fees(sw, pe[pe.event == "fees_accumulated"])
wallet =sw.tx_from if "tx_from" in sw else sw.sender
sw["wallet"] = wallet.str.lower()
every = sw.copy()                                               # whole file, for pool holdings (TVL)
t0 = pd.Timestamp(a.start, tz="UTC").timestamp() if a.start else 0
t1 = pd.Timestamp(a.end, tz="UTC").timestamp() if a.end else ref.ts.max() - 3600
inw = (sw.ts >= t0) & (sw.ts < t1)
nopre = sw[inw & sw.pre.isna()].assign(reason="no earlier swap to give the pre-swap price")
sw = sw[inw & sw.pre.notna()].reset_index(drop=True)
sw["internal"] = sw.wallet.isin(internal)

b, q = sw.amount0.values, sw.amount1.values
p0 = pd.merge_asof(pd.DataFrame({"ts": sw.ts - 1}), ref, on="ts")["mid"].values
if a.fee_mode == "fixed":
    f = a.fee_bp / 1e4
    b_net, q_net = np.where(b > 0, b * (1 - f), b), np.where(q > 0, q * (1 - f), q)
    fee = np.abs(np.where(b > 0, b * p0 * f, q * f)) * a.lp_fee_share
else:                                                           # Core deltas exclude the extension's fee
    b_net, q_net = b, q
    fee = sw.fee0.values * p0 + sw.fee1.values
notional = np.abs(b) * p0
sw["notional"], sw["fee"], sw["fee_bp"] = notional, fee, fee / notional * 1e4
for h in H:
    ph = p0 if h == 0 else pd.merge_asof(pd.DataFrame({"ts": sw.ts + h}), ref, on="ts")["mid"].values
    sw[f"mk_{h}"] = markout(b_net, q_net, ph)
sw["p_binance"] = p0
sw["gap_bp"] = (sw.pre / p0 - 1) * 1e4
sw["toward"] = toward_binance(b, sw.gap_bp)
sw["arb"] = is_arbitrage(b, sw.gap_bp, sw.fee_bp)
sw["dev_bp"] = (np.abs(q / b) / p0 - 1) * 1e4
sw["flagged"] = sw.dev_bp.abs() > a.max_dev_bp
sw["lp_pnl"] = sw.fee + sw.mk_12
d = sw[~sw.flagged]
days = (d.ts.max() - d.ts.min()) / 86400
excl = pd.concat([nopre, sw[sw.flagged].assign(reason=f"execution price more than {a.max_dev_bp:g} bp from Binance")])
excl.reindex(columns=["ts", "block", "tx_hash", "wallet", "amount0", "amount1", "p_binance", "dev_bp", "reason"]) \
    .to_csv(a.out_prefix + "_excluded.csv", index=False)


def summary(x):
    v = x.notional.sum()
    bp = lambda y: float(y / v * 1e4) if v else 0.0
    return {"swaps": int(len(x)), "volume": float(v), "fees": float(x.fee.sum()), "fee_bp": bp(x.fee.sum()),
            **{f"markout_{h}": float(x[f"mk_{h}"].sum()) for h in H}, **{f"markout_{h}_bp": bp(x[f"mk_{h}"].sum()) for h in H},
            "lp_pnl": float(x.lp_pnl.sum()), "lp_pnl_bp": bp(x.lp_pnl.sum())}


def wallets(x):
    g = x.groupby("wallet").agg(swaps=("ts", "size"), volume=("notional", "sum"), fees=("fee", "sum"), mk12=("mk_12", "sum"),
                                mk60=("mk_60", "sum"), arb_share=("arb", "mean"), first=("ts", "min"), last=("ts", "max"))
    g["lp_pnl"] = g.fees + g.mk12
    g["mk12_bp"] = g.mk12 / g.volume * 1e4
    g["fee_bp"] = g.fees / g.volume * 1e4
    g["cls"] = np.where((g.arb_share >= 0.5) & (g.swaps >= 20), "arbitrage bot",
                        np.where(g.mk12_bp < -g.fee_bp, "toxic", "genuine"))
    return g.sort_values("lp_pnl")


CLASSES = ("arbitrage bot", "toxic", "genuine")


def check_sums(total, parts, what):
    """Groups must add back to the total they split."""
    for k in ("swaps", "volume", "fees", "markout_0", "markout_12", "markout_60", "lp_pnl"):
        s = sum(p[k] for p in parts)
        assert np.isclose(s, total[k], rtol=1e-9, atol=1e-6), f"{what}: {k} groups sum {s} != total {total[k]}"


def report(x):
    """Every metric for one scope of flow (all, or external only)."""
    g = wallets(x)
    r = {"all": summary(x), "by_flow": {"internal": summary(x[x.internal]), "external": summary(x[~x.internal])},
         "by_swap": {"arbitrage": summary(x[x.arb]), "other": summary(x[~x.arb])},
         "by_wallet_class": {c: {**summary(x[x.wallet.isin(g.index[g.cls == c])]), "wallets": int((g.cls == c).sum())}
                             for c in CLASSES},
         "share_of_loss_at_trade_time": float(x.mk_0.sum() / x.mk_12.sum()) if x.mk_12.sum() else None,
         # fees / (fees + what arbitrage took): the share of arbitrage loss the fee gave back to LPs
         "lp_capture_rate": float(x.fee[x.arb].sum() / (x.fee[x.arb].sum() - x.mk_12[x.arb].sum()))}
    for k in ("by_flow", "by_swap", "by_wallet_class"):
        check_sums(r["all"], list(r[k].values()), k)
    if a.persistence:
        mid = x.ts.min() + (x.ts.max() - x.ts.min()) / 2
        g1 = wallets(x[x.ts < mid])
        later = x[x.ts >= mid]
        r["persistence"] = {c: {**summary(later[later.wallet.isin(g1.index[g1.cls == c])]), "wallets": int((g1.cls == c).sum())}
                            for c in CLASSES}
        r["persistence"]["new wallets"] = summary(later[~later.wallet.isin(g1.index)])
    return r, g


r_all, g = report(d)
r_ext, g_ext = report(d[~d.internal])

# Theoretical LVR (Milionis et al.) for concentrated liquidity, per minute: sigma^2 * L * sqrt(S) / (4 * 10^((dec0+dec1)/2)),
# sigma^2 = squared 60 s Binance log return, L = active liquidity in force (from the swap events), S = Binance price.
# Same form whichever token is the risky one; see lvr_theory_check.py.
grid = pd.date_range(pd.to_datetime(d.ts.min(), unit="s").ceil("min"), pd.to_datetime(d.ts.max(), unit="s").floor("min"), freq="min")
S = ref.set_index(pd.to_datetime(ref.ts, unit="s")).mid.reindex(grid, method="ffill")
Ls = pd.Series(sw.liquidity.values, index=pd.to_datetime(sw.ts, unit="s")).groupby(level=0).last()
L = Ls.reindex(Ls.index.union(grid)).ffill().reindex(grid)
r2 = np.log(S).diff() ** 2
lvr_min = r2 * L * np.sqrt(S) / (4 * 10 ** ((a.dec0 + a.dec1) / 2))
lvr_theory = float(lvr_min.sum())

# Same LVR per week, next to the measured loss, so the gap between them can be seen rather than explained away
wk = lambda ts: ts.dt.to_period("W-SUN").dt.start_time
mt = pd.DataFrame({"r2": r2, "L": L / 10 ** ((a.dec0 + a.dec1) / 2), "S": S, "lvr": lvr_min}, index=grid)
dt = pd.to_datetime(d.ts, unit="s")
lw = mt.groupby(wk(mt.index.to_series())).agg(minutes=("r2", "count"), r2=("r2", "mean"), L=("L", "mean"), S=("S", "mean"),
                                               lvr_theory=("lvr", "sum"))
lw["sigma_annual"] = np.sqrt(lw.pop("r2") * 525_600)
lw["measured_loss_all"] = -d.groupby(wk(dt)).mk_12.sum()
lw["measured_loss_external"] = -d[~d.internal].groupby(wk(dt[~d.internal])).mk_12.sum()
lw["ratio_all"] = lw.measured_loss_all / lw.lvr_theory
lw["ratio_external"] = lw.measured_loss_external / lw.lvr_theory
lw = lw.rename(columns={"L": "active_liquidity_L", "S": "eth_price"})

# Daily TVL: the pool's token holdings rebuilt from every event that moves them, valued at Binance at the end of the day
tvl = None
if a.positions:
    pe = pd.read_csv(a.positions)
    pe["ts"] = np.interp(pe.block, every.block, every.ts)          # block -> time from the swaps around it
    own = "fees_accumulated" in set(pe.event)                     # events file has every fee paid in: don't add them twice
    fee0 = every.fee0 if "fee0" in every and not own else 0.0
    fee1 = every.fee1 if "fee1" in every and not own else 0.0
    fl = pd.concat([pe[["block", "log_index", "ts", "amount0", "amount1"]],
                    every.assign(amount0=every.amount0 + fee0, amount1=every.amount1 + fee1)[["block", "log_index", "ts", "amount0", "amount1"]]])
    fl = fl.sort_values(["block", "log_index"])
    fl[["h0", "h1"]] = fl[["amount0", "amount1"]].cumsum().values
    assert fl.h0.min() > -1e-9 and fl.h1.min() > -1e-6, "pool holdings went negative: an event type is missing or mis-signed"
    days_idx = pd.date_range(pd.to_datetime(fl.ts.min(), unit="s").normalize(), pd.to_datetime(fl.ts.max(), unit="s").normalize(), freq="D")
    h = fl.groupby(pd.to_datetime(fl.ts, unit="s").dt.normalize())[["h0", "h1"]].last().reindex(days_idx).ffill()
    close = ref.set_index(pd.to_datetime(ref.ts, unit="s")).mid.resample("D").last().reindex(days_idx).ffill()
    tvl = h.assign(eth_close=close, tvl_usd=h.h0 * close + h.h1)
    inwin = tvl[(tvl.index >= pd.to_datetime(d.ts.min(), unit="s").normalize()) & (tvl.index < pd.to_datetime(t1, unit="s"))]
    avg_tvl = float(inwin.tvl_usd.mean())

res = {"pool": a.name, "window": [str(pd.to_datetime(d.ts.min(), unit="s")), str(pd.to_datetime(d.ts.max(), unit="s"))],
       "days": days, "tvl_today": a.tvl, "flagged_swaps": int(sw.flagged.sum()), "internal_wallets": sorted(internal),
       **r_all, "external_only": r_ext, "lvr_theory": lvr_theory}
if tvl is not None:
    res["tvl"] = {"average_in_window": avg_tvl, "last_rebuilt": float(tvl.tvl_usd.iloc[-1]), "last_day": str(tvl.index[-1].date())}
    base, basis = avg_tvl, "average daily TVL in the window"
else:
    base, basis = a.tvl, "today's TVL (no history)"
if base:
    # A 30-day result scaled to a year: an extrapolation, not a forecast
    res["apr_extrapolated"] = {"basis": basis, "tvl": base, **{
        s: {"fees": r["all"]["fees"] / base * 365 / days, "markout_12": r["all"]["markout_12"] / base * 365 / days,
            "lp_net": r["all"]["lp_pnl"] / base * 365 / days} for s, r in (("all_flow", r_all), ("external_only", r_ext))}}

# Fee sweep on external arbitrage swaps only. Assumes an arbitrage swap happens only while its gap > f, at the same
# size and with the same markout; says nothing about retail demand or how arbitrageurs would resize.
xa = d[~d.internal & d.arb]
sweep = []
for f in range(a.max_sweep_bp + 1):
    k_ = xa[xa.gap_bp.abs() > f]
    fees_f = k_.notional.sum() * f / 1e4 * (a.lp_fee_share if a.fee_mode == "fixed" else 1.0)
    sweep.append({"fee_bp": f, "swaps": len(k_), "volume": k_.notional.sum(), "volume_retained": k_.notional.sum() / xa.notional.sum(),
                  "fees": fees_f, "markout_12": k_.mk_12.sum(), "lp_net": fees_f + k_.mk_12.sum()})
sweep = pd.DataFrame(sweep)
res["fee_sweep_actual"] = summary(xa)

groups = []
for scope, r in (("all flow", r_all), ("external only", r_ext)):
    groups.append({"scope": scope, "group": "total", **r["all"]})
    for k in ("by_flow", "by_swap", "by_wallet_class"):
        for n, s in r[k].items():
            groups.append({"scope": scope, "group": f"{k[3:]}: {n}", **s})
pd.DataFrame(groups).drop(columns=["markout_300", "markout_300_bp"]).to_csv(a.out_prefix + "_groups.csv", index=False)
json.dump(res, open(a.out_prefix + ".json", "w"), indent=2, default=float)
g.to_csv(a.out_prefix + "_wallets.csv")
d.assign(cls=d.wallet.map(g.cls))[
    ["ts", "block", "tx_hash", "wallet", "internal", "cls", "amount0", "amount1", "pre", "price", "p_binance", "gap_bp", "arb",
     "notional", "fee", "fee_bp"] + [f"mk_{h}" for h in H] + ["lp_pnl"]].to_csv(a.out_prefix + "_swaps.csv", index=False)
pd.DataFrame({"t": grid, "lvr_theory": lvr_min.values}).to_csv(a.out_prefix + "_lvr_minute.csv", index=False)
lw.to_csv(a.out_prefix + "_lvr_weekly.csv", index_label="week_start")
sweep.to_csv(a.out_prefix + "_fee_sweep.csv", index=False)
if tvl is not None:
    tvl.to_csv(a.out_prefix + "_tvl_daily.csv", index_label="day")


def line(k, s):
    return (f"  {k:22s} swaps {s['swaps']:>7,} vol ${s['volume'] / 1e6:>6,.2f}M fees ${s['fees']:>7,.0f} ({s['fee_bp']:5.2f} bp) "
            f"mk0 {s['markout_0_bp']:+6.2f} mk12 ${s['markout_12']:>+7,.0f} ({s['markout_12_bp']:+6.2f} bp) mk60 {s['markout_60_bp']:+6.2f} bp "
            f" LP ${s['lp_pnl']:>+7,.0f} ({s['lp_pnl_bp']:+6.2f} bp)")


print(f"{a.name}: {res['window'][0][:16]} – {res['window'][1][:16]} ({days:.1f} d), excluded {len(excl)} swaps "
      f"(-> {a.out_prefix}_excluded.csv) | internal wallets: {', '.join(w[:10] + '…' for w in sorted(internal))}")
for scope, r in (("ALL FLOW", r_all), ("EXTERNAL ONLY", r_ext)):
    A = r["all"]
    print(f"\n== {scope} ==")
    print(line("total", A))
    print(f"  at trade time = {r['share_of_loss_at_trade_time']:.0%} of the 12 s loss | measured loss = {-A['markout_12'] / lvr_theory:.2f}x "
          f"theoretical LVR (${lvr_theory:,.0f}) | capture rate on arbitrage {r['lp_capture_rate']:.0%}")
    for k in ("by_flow", "by_swap", "by_wallet_class"):
        for n, s in r[k].items():
            print(line(f"{n} ({s['wallets']})" if "wallets" in s else n, s))
    if "persistence" in r:
        print("  persistence (labelled on first half, scored on second):")
        for n, s in r["persistence"].items():
            print(line(f"{n} ({s.get('wallets', '-')})", s))
    if base:
        x = res["apr_extrapolated"]["all_flow" if scope == "ALL FLOW" else "external_only"]
        print(f"  EXTRAPOLATION to a year on {basis} ${base:,.0f}: fees {x['fees']:+.0%}, loss at 12 s {x['markout_12']:+.0%}, LP net {x['lp_net']:+.0%}")
if tvl is not None:
    print(f"\nTVL rebuilt from events: average in window ${avg_tvl:,.0f}; on {tvl.index[-1].date()} ${tvl.tvl_usd.iloc[-1]:,.0f} "
          f"(GeckoTerminal today: ${a.tvl:,.0f})")
print("\nLVR, theory vs measured, by week (theory = sum over minutes of sigma^2 * L * sqrt(S) / 4, L = in-range liquidity "
      "from the swap events, scaled by 10^((dec0+dec1)/2)):")
print(lw.round({"sigma_annual": 3, "active_liquidity_L": 1, "eth_price": 0, "lvr_theory": 0, "measured_loss_all": 0,
                "measured_loss_external": 0, "ratio_all": 2, "ratio_external": 2}).to_string())
print(f"\nFee sweep, external arbitrage swaps only ({len(xa):,} swaps, ${xa.notional.sum():,.0f}; actual fees ${xa.fee.sum():,.0f}, "
      f"LP ${xa.lp_pnl.sum():+,.0f}). Assumes a swap happens only if its gap > f, same size; says nothing about retail demand:")
print(sweep.iloc[::5].round({"volume": 0, "volume_retained": 3, "fees": 0, "markout_12": 0, "lp_net": 0}).to_string(index=False))
print(" top wallets by LP loss:")
for w, r in g.head(8).iterrows():
    print(f"  {w[:12]}… {'internal' if w in internal else r.cls:13s} swaps {r.swaps:>7,} vol ${r.volume / 1e6:>8,.2f}M arb {r.arb_share:>4.0%} "
          f"markout {r.mk12_bp:+6.2f} bp fee {r.fee_bp:.2f} bp LP ${r.lp_pnl:+,.0f}")
