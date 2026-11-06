"""
Same capital, three ways, on two pools of the same pair (e.g. USDC/WETH 0.05% + 0.30%), replayed on real swaps:
  isolated  - a normal Uniswap LP: capital split equally, each pool backed by its own half
  shared    - Aqua0 SharedLiquidityPool: one free balance backs a position in every pool
              (_sizeRange / _fitToBudget: each swap mints L = min(target, what the current free balance affords),
              the budget resets every swap, so the same balance backs both pools)
  shared + Oscillon - the same, with the keeper's gap fee (oscillon-spec/FEE_SPEC.md) on every pool
Isolated + Oscillon is run too, so the shared and Oscillon effects can be separated.

LP mechanics, counterfactual flow, markout and price-push removal are as in aqua0_backtest.py (read its docstring).
Pools must share both tokens and one reference price; positions use one range (in human token1 per token0) for all
pools; with --recenter, the range moves back around the price when the trading pool's price leaves it, rebalancing the
free balance to half and half at the market price and paying the first pool's fee on the traded amount.

  python3 aqua0_shared.py --pools data_swaps/usdc_weth_5bp:500:0.75,data_swaps/usdc_weth_30bp:3000:0.8333 \
      --ref klines_eth_1s --base 1 --dec1 18 --range-bp 1000 --recenter --name "USDC/WETH" --out results_aqua0_shared_weth.json
"""
import argparse, glob, io, json, math, os, zipfile
import numpy as np
import pandas as pd
import fee_spec as fs

ap = argparse.ArgumentParser()
ap.add_argument("--pools", required=True, help="comma list of swaps_prefix:fee_pips:lp_fee_share (markouts at prefix_markouts.csv)")
ap.add_argument("--ref", required=True, help="ref.csv (ts, mid) or a directory of Binance kline zips")
ap.add_argument("--kline-sec", type=int, default=1)
ap.add_argument("--base", type=int, choices=[0, 1], required=True)
ap.add_argument("--capital", type=float, default=1e6)
ap.add_argument("--range-bp", type=float, default=50); ap.add_argument("--recenter", action="store_true")
ap.add_argument("--center", type=float, default=None)
ap.add_argument("--dec0", type=int, default=6); ap.add_argument("--dec1", type=int, default=6)
ap.add_argument("--variants", default="5000:20,5000:5,5000:20:500",
                help="alphaBps:deadband[:max base fee pips] list for Oscillon; with the third field, pools with a higher base fee stay vanilla")
ap.add_argument("--elasticities", default="0.5,2"); ap.add_argument("--name", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
RAW = 10 ** ((a.dec0 + a.dec1) / 2)
DEC_SHIFT = a.dec0 - a.dec1
r = a.range_bp / 1e4


def load_ref(path, sec):
    if not os.path.isdir(path):
        return pd.read_csv(path)
    frames = []
    for p in sorted(glob.glob(os.path.join(path, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                frames.append(pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]))
    k = pd.concat(frames)
    t = k[0].astype("int64").values
    t = np.where(t > 1e14, t // 10**6, t // 10**3)
    return pd.DataFrame({"ts": t + sec, "mid": k[4].astype(float).values}).drop_duplicates("ts").sort_values("ts")


def pool_px(mid):
    return mid if a.base == 0 else 1 / mid


def usd(b0, b1, mid):
    return b0 * mid + b1 if a.base == 0 else b0 + b1 * mid


def comp(p, pl, pu):
    sp = math.sqrt(min(max(p, pl), pu))
    return (1 / sp - 1 / math.sqrt(pu)) / RAW, (sp - math.sqrt(pl)) / RAW


_sm_cache = {}


def sqrt_mkt(mid):
    if mid not in _sm_cache:
        m = round(mid * 10**8)
        num, den = (m, 10**8) if a.base == 0 else (10**8, m)
        num, den = (num * 10**-DEC_SHIFT, den) if DEC_SHIFT <= 0 else (num, den * 10**DEC_SHIFT)
        _sm_cache[mid] = math.isqrt(num * fs.Q96 * fs.Q96 // den)
    return _sm_cache[mid]


ref = load_ref(a.ref, a.kline_sec)


def asof(ts):
    return pd.merge_asof(pd.DataFrame({"ts": ts}), ref, on="ts", direction="backward")["mid"].values


def prep(prefix, fee_pips, lp_share):
    sw = pd.read_csv(prefix + ".csv").sort_values(["block", "log_index"]).reset_index(drop=True)
    mk = pd.read_csv(prefix + "_markouts.csv")
    assert len(sw) == len(mk)
    px = np.array([(int(x) / fs.Q96) ** 2 for x in sw.sqrtPriceX96]) * 10.0**DEC_SHIFT
    end_off = np.abs(px / pool_px(asof(sw.ts - 1)) - 1) > 0.01
    flagged = mk.flagged.astype(bool).values | end_off | np.r_[False, end_off[:-1]]
    keep = np.where(~flagged)[0]
    removed = (int(flagged.sum()), float(np.nansum(mk.notional.values[flagged])))
    sw, mk = sw.iloc[keep].reset_index(drop=True), mk.iloc[keep].reset_index(drop=True)
    sq = sw.sqrtPriceX96.astype(object).map(int).values
    d = {"fee_pips": fee_pips, "lp_share": lp_share, "removed": removed, "block": sw.block.values, "log_index": sw.log_index.values,
         "ts": sw.ts.values, "sq_pre": np.r_[[None], sq[:-1]]}
    d["px_after"] = np.array([(int(x) / fs.Q96) ** 2 for x in sq]) * 10.0**DEC_SHIFT
    d["p_pre"] = np.r_[np.nan, d["px_after"][:-1]]
    d["L_pre"] = np.r_[np.nan, sw.liquidity.values[:-1]].astype(float)
    d["mid_pre"], d["mid12"] = asof(sw.ts - 1), asof(sw.ts + 12)
    d["notional"] = mk.notional.values
    d["ok"] = ~np.isnan(d["p_pre"]) & ~np.isnan(d["mid_pre"]) & ~np.isnan(d["mid12"]) & (d["notional"] > 0)
    d["in0"] = (sw.amount0 > 0).values
    d["principal_in"] = np.where(d["in0"], sw.amount0, sw.amount1).astype(float) * (1 - fee_pips / 1e6)
    d["in_usd"] = np.where(d["in0"], *((d["mid_pre"], 1.0) if a.base == 0 else (1.0, d["mid_pre"])))
    n = d["notional"]
    d["edge12"] = np.where(n > 0, -mk.mk_12.values / np.where(n > 0, n, 1) * 1e4, 0.0)
    d["day"] = pd.to_datetime(sw.ts, unit="s").dt.floor("D").values
    return d


def rates(d, v):
    if v is None or (len(v) > 2 and d["fee_pips"] > v[2]):
        return np.full(len(d["ts"]), d["fee_pips"] / 1e6)
    P = fs.Params(alphaBps=v[0], deadband_bp=v[1], baseFee=d["fee_pips"])
    f = np.full(len(d["ts"]), d["fee_pips"], dtype=np.int64)
    for i in np.where(d["ok"])[0]:
        f01, f10 = fs.gap_fees(int(d["sq_pre"][i]), [{"sqrtPriceX96": sqrt_mkt(d["mid_pre"][i]), "updatedAt": 0}] * 3, 0, P)
        f[i] = f01 if d["in0"][i] else f10
    return f / 1e6


pools = []
for spec in a.pools.split(","):
    prefix, fp, ls = spec.split(":")
    pools.append(prep(prefix, int(fp), float(ls)))
    print(f"loaded {prefix}: {pools[-1]['ok'].sum():,} swaps, removed {pools[-1]['removed'][0]} price-push swaps", flush=True)
# one chronological event list across pools
ev = pd.DataFrame({"pool": np.concatenate([np.full(len(p["ts"]), j) for j, p in enumerate(pools)]),
                   "i": np.concatenate([np.arange(len(p["ts"])) for p in pools]),
                   "block": np.concatenate([p["block"] for p in pools]), "log": np.concatenate([p["log_index"] for p in pools])})
ev = ev[np.concatenate([p["ok"] for p in pools])].sort_values(["block", "log"]).reset_index(drop=True)
EV = list(zip(ev.pool.values, ev.i.values))
j0, i00 = EV[0]
MID0, P0 = pools[j0]["mid_pre"][i00], (a.center or pools[j0]["p_pre"][i00])
ts_end = max(p["ts"].max() for p in pools); ts_start = min(p["ts"].min() for p in pools)
MID_END = float(asof([ts_end])[0])
days = (ts_end - ts_start) / 86400


def simulate(mode, rate, eps):
    """mode 'isolated': each pool has capital/N of its own; 'shared': one balance backs every pool."""
    N = len(pools)
    w = []
    for p, rt in zip(pools, rate):
        base = p["fee_pips"] / 1e6
        inf = p["edge12"] > p["fee_pips"] / 100.0
        w.append(np.where(inf, (p["edge12"] > rt * 1e4).astype(float), np.where(rt <= base, 1.0, (rt / base) ** (-eps))))
    cap = a.capital / N if mode == "isolated" else a.capital
    books = N if mode == "isolated" else 1
    bal = [[cap / 2 / usd(1, 0, MID0), cap / 2 / usd(0, 1, MID0)] for _ in range(books)]
    rng = [[P0 * (1 - r), P0 * (1 + r)] for _ in range(books)]
    tgt = [0.0] * books

    def retarget(k, p):
        n0, n1 = comp(p, *rng[k])
        tgt[k] = min(bal[k][0] / n0, bal[k][1] / n1)
    for k in range(books):
        retarget(k, P0)
    fees = mkt = rebal = 0.0
    fees_by_pool, vol_by_pool, daily = [0.0] * N, [0.0] * N, {}
    peak1 = 0.0
    for j, i in EV:
        p = pools[j]; k = j if mode == "isolated" else 0
        b, (pl, pu) = bal[k], rng[k]
        pp = p["p_pre"][i]
        if a.recenter and not (pl < pp < pu):
            v = usd(b[0], b[1], p["mid_pre"][i])
            traded = abs(usd(b[0], 0, p["mid_pre"][i]) - v / 2)
            cost = traded * pools[0]["fee_pips"] / 1e6
            rebal += cost; v -= cost
            b[0], b[1] = v / 2 / usd(1, 0, p["mid_pre"][i]), v / 2 / usd(0, 1, p["mid_pre"][i])
            rng[k] = [pp * (1 - r), pp * (1 + r)]; pl, pu = rng[k]
            retarget(k, pp)
        c0, c1 = comp(pp, pl, pu)
        L = min(tgt[k], b[0] / c0 if c0 > 0 else math.inf, b[1] / c1 if c1 > 0 else math.inf)   # _fitToBudget
        d0, d1 = comp(p["px_after"][i], pl, pu)
        D0, D1 = L * (d0 - c0), L * (d1 - c1)
        b[0] += D0; b[1] += D1
        in_range = pl < pp < pu or pl < p["px_after"][i] < pu
        s = L / (p["L_pre"][i] + L) * w[j][i] if in_range else 0.0
        fee = p["principal_in"][i] * rate[j][i] * s * p["lp_share"] * p["in_usd"][i]
        m = usd(D0, D1, p["mid12"][i])
        fees += fee; mkt += m; fees_by_pool[j] += fee; vol_by_pool[j] += p["notional"][i] * s
        peak1 = max(peak1, sum(x[1] for x in bal))
        dd = p["day"][i]; daily[dd] = daily.get(dd, 0.0) + fee + m
    value = sum(usd(b[0], b[1], MID_END) for b in bal)
    hold = usd(a.capital / 2 / usd(1, 0, MID0), a.capital / 2 / usd(0, 1, MID0), MID_END)
    return {"fees": fees, "fees_by_pool": fees_by_pool, "volume_by_pool": vol_by_pool, "markout_12s": mkt,
            "inventory_value_change": value - a.capital, "rebalance_cost": rebal,
            "net": fees + value - a.capital, "net_vs_hold": fees + value - hold, "hold_value_change": hold - a.capital,
            "net_annualized_pct": (fees + value - a.capital) / a.capital * 365 / days * 100,
            "fees_annualized_pct": fees / a.capital * 365 / days * 100,
            "peak_token1": peak1, "daily": {str(pd.Timestamp(x).date()): y for x, y in sorted(daily.items())}}


res = {"pair": a.name, "pools": a.pools.split(","), "capital": a.capital, "range_bp": a.range_bp, "recenter": a.recenter,
       "days": days, "start_mid": MID0, "end_mid": MID_END, "spec_vectors_passed": fs.N_VECTORS,
       "price_push_removed": [p["removed"] for p in pools], "runs": {}}
variants = [("vanilla", None)] + [("oscillon_a{}_db{}".format(*x.split(":")) + (f"_feeLE{x.split(':')[2]}" if x.count(":") > 1 else ""),
                                   tuple(map(int, x.split(":")))) for x in a.variants.split(",")]
eps_list = [float(x) for x in a.elasticities.split(",")]
for name, v in variants:
    rate = [rates(p, v) for p in pools]
    for mode in ("isolated", "shared"):
        for e in (eps_list[:1] if v is None else eps_list):
            rr = simulate(mode, rate, e)
            res["runs"][f"{mode}|{name}|eps{e:g}"] = rr
            print(f"{mode:8s} {name:20s} ε {e:<3g} fees ${rr['fees']:>9,.0f} ({rr['fees_annualized_pct']:.1f}%/yr)  markout ${rr['markout_12s']:>+10,.0f}  "
                  f"net ${rr['net']:>+9,.0f} ({rr['net_annualized_pct']:+.1f}%/yr)  vs hold ${rr['net_vs_hold']:>+9,.0f}  "
                  f"fees by pool " + " / ".join(f"${x:,.0f}" for x in rr["fees_by_pool"]), flush=True)
json.dump(res, open(a.out, "w"), indent=2, default=float)
