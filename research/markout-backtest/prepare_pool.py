"""
Convert a Dune export of Uniswap v3 swaps + Binance klines into backtest inputs, for ANY pool.

The backtest prices the BASE token in the QUOTE token (mid = base price in quote).
  --base 0  : token0 is the base   (e.g. USDC/USDT pool, Binance USDCUSDT)
  --base 1  : token1 is the base   (e.g. USDC/WETH pool, Binance ETHUSDC)

Dune CSV: evt_block_time (or ts), amount0, amount1 (raw; v3 = pool's side, + = pool received),
          optional sqrtPriceX96 (exact pool price after each swap; recommended)
Klines: Binance daily .zip or .csv (col 0 open time ms or µs, col 4 close), 1s or 1m.

Examples
  USDC/USDT 0.01% (Ethereum 0x3416cf6c708da44db2624d63ea0aaef7113527c6), Binance USDCUSDT:
    python3 prepare_pool.py --dune dune.csv --klines klines/ --base 0 --dec0 6 --dec1 6
  USDC/WETH 0.05% (0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640), Binance ETHUSDC:
    python3 prepare_pool.py --dune dune.csv --klines klines/ --base 1 --dec0 6 --dec1 18
"""
import argparse, glob, io, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--dune", required=True)
ap.add_argument("--klines", required=True)
ap.add_argument("--base", type=int, choices=[0, 1], required=True)
ap.add_argument("--dec0", type=int, required=True)
ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--out-dir", default=".")
a = ap.parse_args()

d = pd.read_csv(a.dune)
if "ts" not in d.columns:
    dt = pd.to_datetime(d["evt_block_time"].astype(str).str.replace(" UTC", "", regex=False), utc=True)
    d["ts"] = ((dt - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()).astype("int64")
x0 = d["amount0"].astype(float) / 10**a.dec0
x1 = d["amount1"].astype(float) / 10**a.dec1
base, quote = (x0, x1) if a.base == 0 else (x1, x0)
swaps = pd.DataFrame({"ts": d["ts"].astype("int64"),
                      "dir": np.where(base < 0, 1, -1),     # pool paid out base → trader bought base
                      "a0": base.abs(), "a1": quote.abs()})
if "sqrtPriceX96" in d.columns:                          # exact pool price after each swap
    sp = d["sqrtPriceX96"].astype(float) / 2**96
    p1per0 = sp**2 * 10**(a.dec0 - a.dec1)               # token1 per token0, human units
    swaps["pool_px_after"] = p1per0 if a.base == 0 else 1 / p1per0
swaps = swaps[(swaps.a0 > 0) & (swaps.a1 > 0)].sort_values("ts")

frames = []
for f in sorted(glob.glob(os.path.join(a.klines, "*"))):
    if f.endswith(".zip"):
        with zipfile.ZipFile(f) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None) for n in z.namelist()]
    elif f.endswith(".csv"):
        frames.append(pd.read_csv(f, header=None))
if not frames:
    raise SystemExit("no kline files found")
k = pd.concat(frames)
k = k[pd.to_numeric(k[0], errors="coerce").notna()]
t = k[0].astype("int64").values
t = np.where(t > 1e14, t // 10**6, t // 10**3)
ref = pd.DataFrame({"ts": t, "mid": k[4].astype(float).values}).drop_duplicates("ts").sort_values("ts")

lo, hi = max(swaps.ts.min(), ref.ts.min()), min(swaps.ts.max(), ref.ts.max())
swaps = swaps[(swaps.ts >= lo) & (swaps.ts <= hi - 120)]
ref = ref[(ref.ts >= lo - 3600) & (ref.ts <= hi)]
swaps.to_csv(os.path.join(a.out_dir, "swaps.csv"), index=False)
ref.to_csv(os.path.join(a.out_dir, "ref.csv"), index=False)
print(f"swaps: {len(swaps):,} over {(swaps.ts.max()-swaps.ts.min())/86400:.1f} days | ref points: {len(ref):,}")
print(f"sanity: median exec {(swaps.a1/swaps.a0).median():.6f} vs median ref {ref.mid.median():.6f} (should be close)")
