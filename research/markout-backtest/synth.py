"""Synthetic data ONLY to check the pipeline runs. Never present these numbers as results."""
import argparse
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=20)
ap.add_argument("--seed", type=int, default=1)
a = ap.parse_args()
rng = np.random.default_rng(a.seed)

T = a.days * 86400
ts = np.arange(0, T, 1)
vol = np.where((ts // 3600) % 24 < 3, 4e-4, 1.2e-4)          # calm hours and a few volatile hours a day
ret = rng.normal(0, vol)
jumps = rng.random(T) < 2e-5
ret[jumps] += rng.normal(0, 4e-3, jumps.sum())
mid = 3000 * np.exp(np.cumsum(ret))
start = 1_760_000_000
pd.DataFrame({"ts": ts + start, "mid": mid}).to_csv("ref.csv", index=False)

rows = []
t = 0
while t < T - 120:
    t += int(rng.exponential(6)) + 1
    informed = rng.random() < (0.35 if vol[t] > 2e-4 else 0.15)
    if informed:
        d = 1 if mid[min(t + 12, T - 1)] > mid[t] else -1          # sees the next 12s
        size = rng.lognormal(1.2, 0.8)
    else:
        d = 1 if rng.random() < 0.5 else -1
        size = rng.lognormal(0.0, 1.0)
    px = mid[t] * (1 + d * rng.normal(1e-4, 1e-4))                  # small slippage
    a0 = size
    a1 = a0 * px / (1 - 0.0005) if d > 0 else a0 * px * (1 - 0.0005)
    rows.append((t + start, d, a0, a1))
pd.DataFrame(rows, columns=["ts", "dir", "a0", "a1"]).to_csv("swaps.csv", index=False)
print(f"wrote {len(rows)} swaps over {a.days} days (SYNTHETIC)")
