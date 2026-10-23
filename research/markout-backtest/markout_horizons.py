"""
When do LPs lose money? LP markout per swap at several horizons, split by side, from individual swaps
(fetch_swaps_onchain.py output) and Binance klines.

For a swap, with the pool's signed amounts (+ = pool received) in base and quote tokens, the LP's value change
measured at the reference price P(t+h) is
    markout_h = base_received_net * P(t+h) + quote_received_net        (fee excluded: input side net of the pool fee)
h = 0 uses the last reference price before the block: it is the trader's instant edge against the market.
A negative markout means the trade hurt LPs. Summed over a side it is that side's adverse selection at horizon h.

  python3 markout_horizons.py --swaps data_swaps/usdc_weth_5bp.csv --klines klines_eth_1s --kline-sec 1 \
      --base 1 --fee-bp 5 --name "USDC/WETH 0.05%" --base-name ETH --quote-name USDC --out-json results_markout_weth.json
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--klines", required=True)
ap.add_argument("--kline-sec", type=int, required=True, help="kline interval in seconds (1 or 60)")
ap.add_argument("--base", type=int, choices=[0, 1], required=True, help="which pool token the reference prices")
ap.add_argument("--fee-bp", type=float, required=True)
ap.add_argument("--horizons", default="0,12,60,300,3600")
ap.add_argument("--name", required=True); ap.add_argument("--base-name", required=True); ap.add_argument("--quote-name", required=True)
ap.add_argument("--max-dev-bp", type=float, default=100.0,
                help="swaps executing further than this from the reference at trade time are flagged (sandwiches around "
                     "liquidity pulls, broken quotes) and reported separately, not in the side totals")
ap.add_argument("--out-json", required=True); ap.add_argument("--out-swaps", default="", help="also save per-swap markouts (parquet/csv)")
a = ap.parse_args()
H = [int(x) for x in a.horizons.split(",")]
f = a.fee_bp / 1e4


def load_klines(d: str, sec: int) -> pd.DataFrame:
    frames = []
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                frames.append(pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]))
    k = pd.concat(frames)
    t = k[0].astype("int64").values
    t = np.where(t > 1e14, t // 10**6, t // 10**3)               # µs or ms -> s
    return pd.DataFrame({"ts": t + sec, "mid": k[4].astype(float).values}).drop_duplicates("ts").sort_values("ts")


ref = load_klines(a.klines, a.kline_sec)
sw = pd.read_csv(a.swaps).sort_values(["block", "log_index"]).reset_index(drop=True)
base = sw["amount0" if a.base == 0 else "amount1"].values
quote = sw["amount1" if a.base == 0 else "amount0"].values
base_net = np.where(base > 0, base * (1 - f), base)                # fee was taken on the input side
quote_net = np.where(quote > 0, quote * (1 - f), quote)
trader_buys_base = base < 0
p0 = pd.merge_asof(pd.DataFrame({"ts": sw.ts - 1}), ref, on="ts", direction="backward")["mid"].values
notional = np.abs(base) * p0
fees = np.abs(np.where(base > 0, base * p0 * f, quote * f))          # fee in quote units, on the input side
exec_px = np.abs(quote / base)
flagged = np.abs(exec_px / p0 - 1) * 1e4 > a.max_dev_bp

res = {"flagged": {"max_dev_bp": a.max_dev_bp, "swaps": int(flagged.sum()), "txs": int(sw.tx_hash[flagged].nunique()),
                   "volume": float(np.nansum(notional[flagged]))}, "pool": a.name, "base": a.base_name, "quote": a.quote_name, "fee_bp": a.fee_bp, "swaps": int(len(sw)),
       "window": [str(pd.to_datetime(sw.ts.min(), unit="s")), str(pd.to_datetime(sw.ts.max(), unit="s"))],
       "volume": float(np.nansum(notional)), "fees": float(np.nansum(fees)), "horizons": H, "sides": {}}
per = {"ts": sw.ts.values, "buy_base": trader_buys_base, "notional": notional, "fee": fees, "flagged": flagged}
for h in H:
    ph = p0 if h == 0 else pd.merge_asof(pd.DataFrame({"ts": sw.ts + h}), ref, on="ts", direction="backward")["mid"].values
    per[f"mk_{h}"] = base_net * ph + quote_net
res["flagged"]["net_markout_0"] = float(np.nansum(per["mk_0"][flagged]))
for side, m in ((f"trader buys {a.base_name}", trader_buys_base & ~flagged), (f"trader sells {a.base_name}", ~trader_buys_base & ~flagged)):
    d = {"swaps": int(m.sum()), "volume": float(np.nansum(notional[m])), "fees": float(np.nansum(fees[m])), "markout": {}}
    for h in H:
        mk = per[f"mk_{h}"][m]
        d["markout"][str(h)] = {"net": float(np.nansum(mk)), "adverse": float(np.nansum(np.minimum(mk, 0))),
                                "net_bp": float(np.nansum(mk) / np.nansum(notional[m]) * 1e4),
                                "share_of_swaps_hurting_lps": float(np.mean(mk < 0))}
    res["sides"][side] = d
json.dump(res, open(a.out_json, "w"), indent=2)
if a.out_swaps:
    pd.DataFrame(per).to_csv(a.out_swaps, index=False)

print(f"{a.name}: {len(sw):,} swaps, ${res['volume'] / 1e9:,.2f}B, fees ${res['fees'] / 1e3:,.0f}k ({res['window'][0][:10]} – {res['window'][1][:10]})")
fl = res["flagged"]
print(f"  flagged (exec > {a.max_dev_bp:g} bp from market): {fl['swaps']} swaps in {fl['txs']} txs, ${fl['volume'] / 1e6:,.1f}M, "
      f"net LP markout {fl['net_markout_0'] / 1e3:+,.0f}k — excluded below")
print("  net LP markout ($, fee excluded) by horizon:  " + "  ".join(f"{h:>6}s" for h in H))
for side, d in res["sides"].items():
    print(f"  {side:22s} fees {d['fees'] / 1e3:>7,.0f}k   " + "  ".join(f"{d['markout'][str(h)]['net'] / 1e3:>+6,.0f}k" for h in H))
    print(f"  {'':22s} in bp of volume        " + "  ".join(f"{d['markout'][str(h)]['net_bp']:>+7.2f}" for h in H))
