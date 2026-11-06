"""
Sanity checks on a fetched swaps file (Uniswap or Ekubo format, token0 = ETH, token1 = a USD stable) before backtesting:
duplicates, timestamp order, execution price vs Binance at the same second, daily volume vs GeckoTerminal, and fees.

  python3 verify_swaps.py data_swaps/eth_usdg_ekubo_robinhood.csv \
      --gecko robinhood/pools/0x00000000000014aa86c5d3c41765bb24e11bd701-0xb67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546
"""
import argparse, glob, io, os, zipfile
import numpy as np
import pandas as pd
import requests

ap = argparse.ArgumentParser(); ap.add_argument("swaps"); ap.add_argument("--klines", default="klines_eth_1s")
ap.add_argument("--gecko", default="", help="network/pools/<address> path on the GeckoTerminal API")
a = ap.parse_args()

sw = pd.read_csv(a.swaps)
print(f"{a.swaps}: {len(sw):,} swaps, blocks {sw.block.min():,}–{sw.block.max():,}, "
      f"{pd.to_datetime(sw.ts.min(), unit='s')} – {pd.to_datetime(sw.ts.max(), unit='s')}")
dup = sw.duplicated(["tx_hash", "log_index"]).sum()
s = sw.sort_values(["block", "log_index"])
back = (s.ts.diff() < 0).sum()
print(f"  duplicates {dup} | timestamps going backwards {back} | zero timestamps {(sw.ts == 0).sum()} | "
      f"zero-amount swaps {((sw.amount0 == 0) | (sw.amount1 == 0)).sum()}")
print(f"  direction: trader sells ETH {(sw.amount0 > 0).sum():,}, buys ETH {(sw.amount0 < 0).sum():,}")

frames = []
for p in sorted(glob.glob(os.path.join(a.klines, "*.zip"))):
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            frames.append(pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]))
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}).drop_duplicates("ts").sort_values("ts")
m = sw[(sw.ts <= ref.ts.max()) & (sw.amount0 != 0)].copy()
m["bn"] = pd.merge_asof(m[["ts"]].reset_index(), ref, on="ts").set_index("index")["mid"]
m["exec"] = (m.amount1 / m.amount0).abs()
dev = (m.exec / m.bn - 1) * 1e4
big = m.amount0.abs() * m.bn > 100                                 # dust swaps round badly
print(f"  exec price vs Binance (swaps > $100, n={big.sum():,}): median {dev[big].median():+.1f} bp, "
      f"|dev| p50 {dev[big].abs().median():.1f} / p95 {dev[big].abs().quantile(.95):.1f} / max {dev[big].abs().max():.0f} bp, "
      f"> 100 bp: {(dev[big].abs() > 100).sum()}")
if "price" in sw:
    pdev = (m.price / m.bn - 1) * 1e4
    print(f"  pool price after swap vs Binance: |dev| p50 {pdev.abs().median():.1f} bp, p95 {pdev.abs().quantile(.95):.1f} bp")
if "fee0" in sw:
    fee = sw.fee0 * m.bn.reindex(sw.index).fillna(m.bn.median()) + sw.fee1
    fbp = fee / (sw.amount0.abs() * m.bn.reindex(sw.index).fillna(m.bn.median())) * 1e4
    print(f"  fees: {(fee > 0).mean():.0%} of swaps carry a fee; fee bp p25/p50/p75 "
          f"{fbp[fee > 0].quantile(.25):.2f}/{fbp[fee > 0].median():.2f}/{fbp[fee > 0].quantile(.75):.2f}; total ${fee.sum():,.0f}")
    print(f"  swaps per tx: max {sw.groupby('tx_hash').size().max()}, txs with >1 pool swap {(sw.groupby('tx_hash').size() > 1).sum()}")

if a.gecko:
    usd = sw.amount1.abs().groupby(pd.to_datetime(sw.ts, unit="s").dt.floor("D")).sum()
    g = requests.get(f"https://api.geckoterminal.com/api/v2/networks/{a.gecko}/ohlcv/day", params={"limit": 100}, timeout=60).json()
    gk = pd.Series({pd.Timestamp(x[0], unit="s"): x[5] for x in g["data"]["attributes"]["ohlcv_list"]})
    j = pd.concat({"onchain": usd, "gecko": gk}, axis=1).dropna()
    j = j[(j.index > j.index.min()) & (j.index < j.index.max())]
    j["ratio"] = j.onchain / j.gecko
    print(f"  GeckoTerminal daily volume, {len(j)} full days: on-chain ${j.onchain.sum() / 1e6:,.2f}M vs Gecko ${j.gecko.sum() / 1e6:,.2f}M "
          f"({(j.onchain.sum() / j.gecko.sum() - 1) * 100:+.1f}%), daily ratio p5–p95 {j.ratio.quantile(.05):.3f}–{j.ratio.quantile(.95):.3f}")
    print(j.round(3).to_string())
