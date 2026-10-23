"""
Build backtest inputs from per-swap Uniswap logs (research-backtest's *_swaps_raw_*.csv: amount0, amount1, tick, timestamp)
plus Binance 1m klines and an optional Chainlink export.

Sign convention is detected, not assumed: v4 PoolManager events report the swapper's deltas, v3 pool events report the
pool's. If token0's sign moves with the tick (price of token0 up after the swap), a positive amount0 means the trader
received token0.

  python3 prepare_swaps_raw.py --raw ../../../research-backtest/data/usde_usdt/v4_swaps_raw_2025-10-02_2026-08-20.csv \
      --dec0 18 --dec1 6 --klines klines_usde \
      --oracle ../../../research-backtest/data/usde_usdt/chainlink_usde_2025-10-02_2026-08-20.csv --out-dir data_usde
"""
import argparse, glob, io, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--raw", required=True)
ap.add_argument("--dec0", type=int, required=True); ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--klines", default="", help="directory of Binance 1m kline .zip/.csv (omit for flow-only output)")
ap.add_argument("--oracle", default="")
ap.add_argument("--out-dir", required=True)
a = ap.parse_args()
os.makedirs(a.out_dir, exist_ok=True)

d = pd.read_csv(a.raw)
d["ts"] = pd.to_datetime(d["timestamp"].astype(str).str.replace(" UTC", "", regex=False), utc=True).astype("int64") // 10**9
d = d.sort_values("ts", kind="stable").reset_index(drop=True)
x0 = d["amount0"].astype(float) / 10**a.dec0
x1 = d["amount1"].astype(float) / 10**a.dec1
corr = np.corrcoef(np.sign(x0[1:]), np.sign(d["tick"].diff()[1:]))[0, 1]
trader_got0 = (x0 > 0) if corr > 0 else (x0 < 0)
swaps = pd.DataFrame({"ts": d["ts"], "dir": np.where(trader_got0, 1, -1), "a0": x0.abs(), "a1": x1.abs(),
                      "pool_px_after": 1.0001 ** d["tick"].astype(float) * 10 ** (a.dec0 - a.dec1)})
swaps = swaps[(swaps.a0 > 1e-6) & (swaps.a1 > 1e-6)]
swaps = swaps[(swaps.a1 / swaps.a0 / swaps.pool_px_after - 1).abs() < 0.005].reset_index(drop=True)

if a.klines:
    frames = []
    for f in sorted(glob.glob(os.path.join(a.klines, "*"))):
        if f.endswith(".zip"):
            with zipfile.ZipFile(f) as z:
                frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None) for n in z.namelist()]
        elif f.endswith(".csv"):
            frames.append(pd.read_csv(f, header=None))
    k = pd.concat(frames)
    k = k[pd.to_numeric(k[0], errors="coerce").notna()]
    ko = k[0].astype("int64").values
    ko = np.where(ko > 1e14, ko // 10**6, ko // 10**3)
    ref = pd.DataFrame({"ts": ko + 60, "mid": k[4].astype(float).values}).drop_duplicates("ts").sort_values("ts")
    lo, hi = max(swaps.ts.min(), ref.ts.min()), min(swaps.ts.max(), ref.ts.max())
    swaps = swaps[(swaps.ts >= lo) & (swaps.ts <= hi - 600)]
    ref[(ref.ts >= lo - 3600) & (ref.ts <= hi)].to_csv(os.path.join(a.out_dir, "ref.csv"), index=False)
swaps.to_csv(os.path.join(a.out_dir, "swaps.csv"), index=False)

if a.oracle:
    o = pd.read_csv(a.oracle)
    col = [c for c in o.columns if c.endswith("_price")][0]
    ots = pd.to_datetime(o.iloc[:, 0].astype(str).str.replace(" UTC", "", regex=False), utc=True)
    pd.DataFrame({"ts": ots.astype("int64") // 10**9, "price": o[col].astype(float)}).sort_values("ts") \
        .to_csv(os.path.join(a.out_dir, "oracle.csv"), index=False)

print(f"swaps: {len(swaps):,} (token0 bought {(swaps.dir > 0).sum():,}, sold {(swaps.dir < 0).sum():,}) | "
      f"sign/tick corr {corr:+.2f} -> positive amount0 = trader {'received' if corr > 0 else 'paid'} token0")
print(f"span {pd.to_datetime(swaps.ts.min(), unit='s')} .. {pd.to_datetime(swaps.ts.max(), unit='s')} | "
      f"volume token0 {swaps.a0.sum():,.0f} | median exec {(swaps.a1 / swaps.a0).median():.6f}")
