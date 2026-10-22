"""
Build backtest inputs for a long window from per-minute pool bars (demeter-fetch format) + Binance 1m klines
+ a Chainlink oracle export. Use this when per-swap logs are not available (public RPCs refuse
archive eth_getLogs).

Minute bar columns (demeter-fetch): timestamp, netAmount0, netAmount1, closeTick, ..., inAmount0, inAmount1
  netAmountX = sum of signed amounts (pool's side, + = pool received)
  inAmountX  = sum of |amounts| (gross both ways)
So for each token:  into pool = (gross + net) / 2,  out of pool = (gross - net) / 2.
Every swap in a two-token pool pays one token in and takes the other out, so each minute splits into
two directional legs:
  USDC -> USDT (dir -1, trader sold token0):  a0 = USDC in,   a1 = USDT out
  USDT -> USDC (dir +1, trader bought token0): a0 = USDC out,  a1 = USDT in

Timing: a bar labelled t holds swaps in [t, t+60). Both legs are stamped t+60, and each kline close is
stamped at its close time (open + 60), so no reference price is used before it exists.

Example
  python3 prepare_minute_year.py \
      --bars ../../../research-backtest/data --pool 0x3416cf6c708da44db2624d63ea0aaef7113527c6 \
      --start 2025-07-01 --end 2026-06-30 --klines klines_1y \
      --oracle ../../../research-backtest/data/chainlink_usdc_2025-07_2026-06.csv --out-dir data_1y
"""
import argparse, glob, io, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--bars", required=True, help="directory with ethereum-<pool>-<date>.minute.csv files")
ap.add_argument("--pool", required=True)
ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
ap.add_argument("--klines", required=True, help="directory of Binance 1m kline .zip/.csv files")
ap.add_argument("--oracle", default="", help="Chainlink export: minute,<asset>_price")
ap.add_argument("--dec0", type=int, default=6); ap.add_argument("--dec1", type=int, default=6)
ap.add_argument("--out-dir", default="data_1y")
a = ap.parse_args()
os.makedirs(a.out_dir, exist_ok=True)

files = sorted(f for f in glob.glob(os.path.join(a.bars, f"ethereum-{a.pool}-*.minute.csv"))
               if a.start <= os.path.basename(f)[-21:-11] <= a.end)          # ...-YYYY-MM-DD.minute.csv
if not files:
    raise SystemExit("no minute bars in range")
def legs(f: str) -> pd.DataFrame:
    """inAmountX means different things across demeter-fetch versions; pick per file by which reading balances.
    'into': inAmountX = X paid into the pool.   'gross': inAmountX = |X| both ways."""
    d = pd.read_csv(f)
    n0, n1 = d["netAmount0"].astype(float) / 10**a.dec0, d["netAmount1"].astype(float) / 10**a.dec1
    g0, g1 = d["inAmount0"].astype(float) / 10**a.dec0, d["inAmount1"].astype(float) / 10**a.dec1
    err_into = ((g0 - n0) - g1).abs().sum() + ((g1 - n1) - g0).abs().sum()
    err_gross = 2 * ((g0 - n0) / 2 - (g1 + n1) / 2).abs().sum()
    if err_into < err_gross:
        d["in0"], d["out0"], d["in1"], d["out1"] = g0, g0 - n0, g1, g1 - n1
    else:
        d["in0"], d["out0"], d["in1"], d["out1"] = (g0 + n0) / 2, (g0 - n0) / 2, (g1 + n1) / 2, (g1 - n1) / 2
    d["convention"] = "into" if err_into < err_gross else "gross"
    return d


b = pd.concat([legs(f) for f in files], ignore_index=True)
t = (pd.to_datetime(b["timestamp"], utc=True).astype("int64") // 10**9).values + 60
in0, out0, in1, out1 = b["in0"], b["out0"], b["in1"], b["out1"]
px = 1.0001 ** b["closeTick"].astype(float) * 10 ** (a.dec0 - a.dec1)     # token1 per token0 after the bar
sell0 = pd.DataFrame({"ts": t, "dir": -1, "a0": in0, "a1": out1, "pool_px_after": px})
buy0 = pd.DataFrame({"ts": t, "dir": 1, "a0": out0, "a1": in1, "pool_px_after": px})
swaps = pd.concat([sell0, buy0]).sort_values(["ts", "dir"], kind="stable")
swaps = swaps[(swaps.a0 > 1e-6) & (swaps.a1 > 1e-6)]
swaps = swaps[(swaps.a1 / swaps.a0 / swaps.pool_px_after - 1).abs() < 0.005].reset_index(drop=True)  # dust legs
bad = ((in0 < -1e-6) | (out0 < -1e-6) | (in1 < -1e-6) | (out1 < -1e-6)).sum()

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
ref = ref[(ref.ts >= lo - 3600) & (ref.ts <= hi)]
swaps.to_csv(os.path.join(a.out_dir, "swaps.csv"), index=False)
ref.to_csv(os.path.join(a.out_dir, "ref.csv"), index=False)

if a.oracle:
    o = pd.read_csv(a.oracle)
    col = [c for c in o.columns if c.endswith("_price")][0]
    ots = pd.to_datetime(o.iloc[:, 0].astype(str).str.replace(" UTC", "", regex=False), utc=True)
    pd.DataFrame({"ts": ots.astype("int64") // 10**9, "price": o[col].astype(float)}) \
        .sort_values("ts").to_csv(os.path.join(a.out_dir, "oracle.csv"), index=False)

print(f"bars: {len(b):,} from {len(files)} days | legs: {len(swaps):,} "
      f"(USDC->USDT {(swaps.dir < 0).sum():,}, USDT->USDC {(swaps.dir > 0).sum():,}) | negative legs: {bad}")
print("bar conventions:", b.groupby("convention").size().to_dict())
print(f"volume: USDC->USDT {swaps[swaps.dir < 0].a0.sum():,.0f}  USDT->USDC {swaps[swaps.dir > 0].a0.sum():,.0f} (token0)")
print(f"sanity: median exec {(swaps.a1 / swaps.a0).median():.6f} vs median ref {ref.mid.median():.6f}")
