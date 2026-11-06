"""
One Aqua0 LP on one pool, vanilla vs with the Oscillon gap fee (oscillon-spec/FEE_SPEC.md), replayed on real swaps.
Works for stable pairs (USDC/USDT) and volatile pairs (USDC/WETH): any decimals, reference token on either side.

LP model, following Aqua0 SharedLiquidityPool (github.com/Aqua0-fi/aqua0-base-hook @ e260786):
  * The LP deposits capital C, half the value in each token, as free balance, and backs one range +-range_bp around
    --center (the peg, 1, for stable pairs) or the starting price.
  * Each swap, _sizeRange / _fitToBudget: liquidity L = min(target, largest L whose mint cost at the pre-swap price
    fits the current free balance of each token). Target = what C mints at the start. The budget resets every swap.
  * _principalDelta: the LP's liquidity is minted at the pre-swap price and burned at the post-swap price, so its token
    change is L x (composition(after) - composition(before)), clamped to the range. It goes to the free balance.
  * Fees: the LP earns share s = L / (L_pool + L) of the swap's fee, where L_pool is the pool's in-range liquidity
    before the swap. Fees go to earnedFees (not re-invested), after the protocol fee share.
  * --recenter: when the price leaves the range, the LP moves the range back around the price and rebalances to half
    and half at the market price, paying the pool fee on the traded amount (same rule in every variant).
Oscillon gap fee: fee_spec.gap_fees with sqrtPool = the pool's sqrtPriceX96 before the swap and the market sqrtPriceX96
  from the Binance 1-second close before the block (passed as 3 agreeing fresh sources, so the keeper is confident).
Counterfactual flow (first order, price path unchanged): arbitrage-like trades (12 s edge > base fee) pay the fee only if
  their edge beats it; ordinary trades shrink by (fee / base)^-elasticity. Fees scale with the flow that still trades. The
  price path is unchanged, so a blocked arbitrage's repricing still happens later: the LP's inventory follows the path
  regardless (conservative: a higher fee cannot make LVR vanish, only change who pays for the repricing).
Markout: the LP's token change on each swap, valued at the Binance price 12 s later (fee excluded), in USD.
Off-market price-push round trips are removed from the path (see the note in the code) and reported by count and volume.

  python3 aqua0_backtest.py --swaps data_swaps/usdc_usdt_1bp.csv --markouts data_swaps/usdc_usdt_1bp_markouts.csv \
      --ref data_usdt_swaps/ref.csv --base 0 --center 1 --fee-pips 100 --capital 1e6 --range-bp 50 --lp-fee-share 0.75 \
      --name "USDC/USDT 0.01%" --out results_aqua0_usdc_usdt_calm.json
  python3 aqua0_backtest.py --swaps data_swaps/usdc_weth_5bp.csv --markouts data_swaps/usdc_weth_5bp_markouts.csv \
      --ref klines_eth_1s --base 1 --dec1 18 --fee-pips 500 --capital 1e6 --range-bp 1000 --recenter \
      --lp-fee-share 0.75 --name "USDC/WETH 0.05%" --out results_aqua0_usdc_weth_calm.json
"""
import argparse, glob, io, json, math, os, zipfile
import numpy as np
import pandas as pd
import fee_spec as fs

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--markouts", required=True)
ap.add_argument("--ref", required=True, help="ref.csv (ts, mid) or a directory of Binance kline zips")
ap.add_argument("--kline-sec", type=int, default=1)
ap.add_argument("--base", type=int, choices=[0, 1], required=True, help="which pool token the reference prices (in the other)")
ap.add_argument("--fee-pips", type=int, default=100); ap.add_argument("--capital", type=float, default=1e6)
ap.add_argument("--range-bp", type=float, default=50); ap.add_argument("--recenter", action="store_true")
ap.add_argument("--center", type=float, default=None, help="range centre in pool terms (token1 per token0); default the starting price, 1 for a peg")
ap.add_argument("--lp-fee-share", type=float, default=0.75)
ap.add_argument("--dec0", type=int, default=6); ap.add_argument("--dec1", type=int, default=6)
ap.add_argument("--variants", default="5000:5,5000:20,8000:5,8000:20", help="alphaBps:deadband list for Oscillon")
ap.add_argument("--elasticities", default="0.5,2"); ap.add_argument("--name", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
RAW = 10 ** ((a.dec0 + a.dec1) / 2)                 # raw liquidity -> human-unit liquidity
DEC_SHIFT = a.dec0 - a.dec1                          # human price = raw price x 10^DEC_SHIFT


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
    """Market price in pool terms: human token1 per token0."""
    return mid if a.base == 0 else 1 / mid


def usd(b0, b1, mid):
    return b0 * mid + b1 if a.base == 0 else b0 + b1 * mid


sw = pd.read_csv(a.swaps).sort_values(["block", "log_index"]).reset_index(drop=True)
mk = pd.read_csv(a.markouts)
ref = load_ref(a.ref, a.kline_sec)
assert len(sw) == len(mk)
_px_all = np.array([(int(x) / fs.Q96) ** 2 for x in sw.sqrtPriceX96]) * 10.0**DEC_SHIFT
_mkt_all = pool_px(pd.merge_asof(pd.DataFrame({"ts": sw.ts - 1}), ref, on="ts", direction="backward")["mid"].values)
_end_off = np.abs(_px_all / _mkt_all - 1) > 0.01                              # swap leaves the pool >1% from market
flagged = mk.flagged.astype(bool).values | _end_off | np.r_[False, _end_off[:-1]]   # ...and the swap that starts there
# Off-market price-push round trips (bot pushes the price through an empty range, a victim trades, bot reverts) are
# removed from the path: with the LP's liquidity in that range they would not happen as recorded, and the first-order
# replay would hand the LP ~all of them. Each kept swap is linked to the previous kept swap's post-trade state.
keep_idx = np.where(~flagged)[0]
n_flagged, vol_flagged = int(flagged.sum()), float(np.nansum(mk.notional.values[flagged]))
sw, mk = sw.iloc[keep_idx].reset_index(drop=True), mk.iloc[keep_idx].reset_index(drop=True)
sq = sw.sqrtPriceX96.astype(object).map(int).values                     # exact integers
sq_pre = np.r_[[None], sq[:-1]]
px_after = np.array([(int(x) / fs.Q96) ** 2 for x in sq]) * 10.0**DEC_SHIFT   # human token1 per token0
p_pre = np.r_[np.nan, px_after[:-1]]
L_pre = np.r_[np.nan, sw.liquidity.values[:-1]].astype(float)
mid_pre = pd.merge_asof(pd.DataFrame({"ts": sw.ts - 1}), ref, on="ts", direction="backward")["mid"].values
mid12 = pd.merge_asof(pd.DataFrame({"ts": sw.ts + 12}), ref, on="ts", direction="backward")["mid"].values
mid_end = float(pd.merge_asof(pd.DataFrame({"ts": [sw.ts.max()]}), ref, on="ts", direction="backward")["mid"].iloc[0])
ok = ~np.isnan(p_pre) & ~np.isnan(mid_pre) & ~np.isnan(mid12) & (mk.notional.values > 0)
base_rate = a.fee_pips / 1e6
pool_in_is0 = (sw.amount0 > 0).values                                    # token0 in = zeroForOne
principal_in = np.where(pool_in_is0, sw.amount0, sw.amount1).astype(float) * (1 - base_rate)   # input net of the real fee
in_usd = np.where(pool_in_is0, *((mid_pre, 1.0) if a.base == 0 else (1.0, mid_pre)))          # USD per input token
notional = mk.notional.values
edge12 = np.where(notional > 0, -mk.mk_12.values / np.where(notional > 0, notional, 1) * 1e4, 0.0)
day = pd.to_datetime(sw.ts, unit="s").dt.floor("D").values
r = a.range_bp / 1e4


def comp(p, pl, pu):
    """Token amounts (human units) per unit of raw liquidity at price p, clamped to [pl, pu]."""
    sp = math.sqrt(min(max(p, pl), pu))
    return (1 / sp - 1 / math.sqrt(pu)) / RAW, (sp - math.sqrt(pl)) / RAW


_sm_cache = {}


def sqrt_mkt(mid):
    """Market sqrtPriceX96 (raw token1 per raw token0) from the reference mid, rounded to 1e-8."""
    if mid not in _sm_cache:
        m = round(mid * 10**8)
        num, den = (m, 10**8) if a.base == 0 else (10**8, m)
        num, den = (num * 10**-DEC_SHIFT, den) if DEC_SHIFT <= 0 else (num, den * 10**DEC_SHIFT)
        _sm_cache[mid] = math.isqrt(num * fs.Q96 * fs.Q96 // den)
    return _sm_cache[mid]


def oscillon_rates(alpha_bps, deadband):
    P = fs.Params(alphaBps=alpha_bps, deadband_bp=deadband, baseFee=a.fee_pips)
    f = np.full(len(sw), a.fee_pips, dtype=np.int64)
    gap = np.zeros(len(sw))
    for i in np.where(ok)[0]:
        sm = sqrt_mkt(mid_pre[i])
        f01, f10 = fs.gap_fees(int(sq_pre[i]), [{"sqrtPriceX96": sm, "updatedAt": 0}] * 3, 0, P)
        f[i] = f01 if pool_in_is0[i] else f10
        gap[i] = fs.gap_bp(int(sq_pre[i]), sm)
    return f / 1e6, gap


i0 = int(np.where(ok)[0][0])
P0, MID0 = (a.center or p_pre[i0]), mid_pre[i0]
B0 = (a.capital / 2 / usd(1, 0, MID0), a.capital / 2 / usd(0, 1, MID0))   # starting half-and-half balances


def simulate(rate, eps):
    informed = edge12 > a.fee_pips / 100.0
    w = np.where(informed, (edge12 > rate * 1e4).astype(float),
                 np.where(rate <= base_rate, 1.0, (rate / base_rate) ** (-eps)))
    pl, pu = P0 * (1 - r), P0 * (1 + r)
    b0, b1 = B0
    n0, n1 = comp(P0, pl, pu)
    L_target = min(b0 / n0, b1 / n1)
    fees = mkt = vol = vol_pool = rebal_cost = 0.0
    n_rebal = 0
    peak0, peak1, daily = b0, b1, {}
    for i in np.where(ok)[0]:
        if a.recenter and not (pl < p_pre[i] < pu):
            v = usd(b0, b1, mid_pre[i])
            traded = abs(usd(b0, 0, mid_pre[i]) - v / 2)
            v -= traded * base_rate
            rebal_cost += traded * base_rate; n_rebal += 1
            b0, b1 = v / 2 / usd(1, 0, mid_pre[i]), v / 2 / usd(0, 1, mid_pre[i])
            pl, pu = p_pre[i] * (1 - r), p_pre[i] * (1 + r)
            n0, n1 = comp(p_pre[i], pl, pu)
            L_target = min(b0 / n0, b1 / n1)
        c0, c1 = comp(p_pre[i], pl, pu)
        L = min(L_target, b0 / c0 if c0 > 0 else math.inf, b1 / c1 if c1 > 0 else math.inf)   # _fitToBudget
        d0, d1 = comp(px_after[i], pl, pu)
        D0, D1 = L * (d0 - c0), L * (d1 - c1)            # _principalDelta: the price path is fixed, so a blocked trade's
                                                          # repricing still happens (someone arbitrages later): inventory moves, fee is lost
        b0 += D0; b1 += D1
        in_range = pl < p_pre[i] < pu or pl < px_after[i] < pu
        s = L / (L_pre[i] + L) * w[i] if in_range else 0.0   # fee share scales with the flow that still trades
        fee = principal_in[i] * rate[i] * s * a.lp_fee_share * in_usd[i]
        m = usd(D0, D1, mid12[i])                                                              # markout at 12 s
        fees += fee; mkt += m; vol += notional[i] * s; vol_pool += notional[i] * w[i]
        peak0, peak1 = max(peak0, b0), max(peak1, b1)
        k = day[i]; daily[k] = daily.get(k, 0.0) + fee + m
    value = usd(b0, b1, mid_end)
    hold = usd(*B0, mid_end)
    return {"fees": fees, "markout_12s": mkt, "inventory_value_change": value - a.capital, "net": fees + value - a.capital,
            "net_vs_hold": fees + value - hold, "hold_value_change": hold - a.capital,
            "rebalances": n_rebal, "rebalance_cost": rebal_cost,
            "volume_served_by_lp": vol, "pool_volume_kept_pct": vol_pool / notional[ok].sum() * 100,
            "peak_token0": peak0, "peak_token1": peak1, "end_token0": b0, "end_token1": b1,
            "daily": {str(pd.Timestamp(d).date()): v for d, v in sorted(daily.items())}}


days = (sw.ts.max() - sw.ts.min()) / 86400
res = {"pool": a.name, "capital": a.capital, "range_bp": a.range_bp, "recenter": a.recenter, "lp_fee_share": a.lp_fee_share,
       "days": days, "swaps": int(len(sw)), "swaps_used": int(ok.sum()), "price_push_swaps_removed": n_flagged,
       "price_push_volume_removed": vol_flagged, "spec_vectors_passed": fs.N_VECTORS,
       "start_mid": MID0, "end_mid": mid_end, "runs": {}}
variants = [("vanilla", None)] + [(f"oscillon_a{x.split(':')[0]}_db{x.split(':')[1]}", tuple(map(int, x.split(":")))) for x in a.variants.split(",")]
for name, v in variants:
    rate, gap = (np.full(len(sw), base_rate), np.zeros(len(sw))) if v is None else oscillon_rates(*v)
    arb = ok & (rate > base_rate)
    for e in [float(x) for x in a.elasticities.split(",")]:
        if v is None and e != float(a.elasticities.split(",")[0]):
            res["runs"][f"{name}|eps{e:g}"] = res["runs"][f"{name}|eps{float(a.elasticities.split(',')[0]):g}"]
            continue
        rr = simulate(rate, e)
        rr["swaps_above_base_pct"] = float(arb.sum() / ok.sum() * 100)
        rr["avg_fee_bp_by_volume"] = float(np.average(rate[ok], weights=notional[ok]) * 1e4)
        rr["max_fee_bp"] = float(rate[ok].max() * 1e4)
        rr["median_gap_bp"] = float(np.median(gap[ok])) if v is not None else None
        rr["repricing_captured_pct"] = float(((rate - base_rate)[arb] * 1e4 * notional[arb]).sum() / max((gap[arb] * notional[arb]).sum(), 1e-9) * 100) if arb.any() else 0.0
        rr["net_return_annualized_pct"] = rr["net"] / a.capital * 365 / days * 100
        rr["net_vs_hold_annualized_pct"] = rr["net_vs_hold"] / a.capital * 365 / days * 100
        res["runs"][f"{name}|eps{e:g}"] = rr
        print(f"{name:22s} ε {e:<3g} fees ${rr['fees']:>9,.0f}  markout ${rr['markout_12s']:>+9,.0f}  "
              f"net ${rr['net']:>+9,.0f} ({rr['net_return_annualized_pct']:+.2f}%/yr)  vs hold ${rr['net_vs_hold']:>+9,.0f}  "
              f"LP vol ${rr['volume_served_by_lp'] / 1e6:,.1f}M  pool vol kept {rr['pool_volume_kept_pct']:.1f}%  "
              f"above base {rr['swaps_above_base_pct']:.2f}%  avg fee {rr['avg_fee_bp_by_volume']:.2f} bp", flush=True)
json.dump(res, open(a.out, "w"), indent=2, default=float)
