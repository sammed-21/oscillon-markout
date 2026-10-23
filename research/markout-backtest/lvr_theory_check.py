"""
Measured LP adverse selection vs theoretical LVR (Milionis, Moallemi, Roughgarden, Zhang 2022) for a Uniswap v3 pool.

Theory: instantaneous LVR = (sigma^2 / 2) * S^2 * |dx/dS|, x = risky-asset reserves. Inside the active tick range of a
v3 pool with liquidity L and risky token1 (e.g. WETH) vs numeraire token0 (e.g. USDC):
    x_human = L / (10^((dec0+dec1)/2) * sqrt(S)),  so  LVR rate = sigma^2 * L * sqrt(S) / (4 * 10^((dec0+dec1)/2))
(the concentrated-liquidity form of sigma^2/8 * pool value; equal to it for a full-range pool). Computed per hour with
sigma^2 = realised variance of Binance log returns sampled every --rv-sec seconds, L = time-weighted active liquidity
from the swap events, S = mean Binance price.

Measured: sum of per-swap LP markouts (fee excluded) at 12 s and 60 s from markout_horizons.py, flagged swaps excluded.

  python3 lvr_theory_check.py --swaps data_swaps/usdc_weth_5bp.csv --markouts data_swaps/usdc_weth_5bp_markouts.csv \
      --klines klines_eth_1s --dec0 6 --dec1 18 --fee-bp 5 --png charts_flow/F2_lvr_theory_vs_measured.png \
      --out-csv results_lvr_theory_daily.csv
"""
import argparse, glob, io, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--markouts", required=True); ap.add_argument("--klines", required=True)
ap.add_argument("--dec0", type=int, required=True); ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--fee-bp", type=float, required=True); ap.add_argument("--rv-sec", type=int, default=60)
ap.add_argument("--png", required=True); ap.add_argument("--out-csv", required=True)
a = ap.parse_args()
os.makedirs(os.path.dirname(a.png), exist_ok=True)

frames = []
for p in sorted(glob.glob(os.path.join(a.klines, "*.zip"))):
    with zipfile.ZipFile(p) as z:
        frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist()]
k = pd.concat(frames); t = k[0].astype("int64").values; t = np.where(t > 1e14, t // 10**6, t // 10**3)
px = pd.Series(k[4].astype(float).values, index=pd.to_datetime(t + 1, unit="s")).sort_index()
px = px[~px.index.duplicated()]
samp = px.resample(f"{a.rv_sec}s").last().dropna()
r2 = np.log(samp).diff().pow(2)
hour = pd.DataFrame({"rv": r2.resample("1h").sum(), "S": samp.resample("1h").mean()})

sw = pd.read_csv(a.swaps, usecols=["ts", "liquidity"]).sort_values("ts")
L = pd.Series(sw.liquidity.values, index=pd.to_datetime(sw.ts, unit="s"))
L = L[~L.index.duplicated(keep="last")]
grid = pd.date_range(L.index.min().ceil("min"), L.index.max().floor("min"), freq="1min")
Lmin = L.reindex(L.index.union(grid)).ffill().reindex(grid)            # liquidity in force each minute
hour["L"] = Lmin.resample("1h").mean()
scale = 10 ** ((a.dec0 + a.dec1) / 2)
hour["lvr_theory"] = hour.rv * hour.L * np.sqrt(hour.S) / (4 * scale)

mk = pd.read_csv(a.markouts)
mk = mk[~mk.flagged.astype(bool)]
mt = pd.to_datetime(mk.ts, unit="s")
for h in (12, 60):
    hour[f"measured_{h}s"] = -pd.Series(mk[f"mk_{h}"].values, index=mt).resample("1h").sum()
hour["fees"] = pd.Series(mk.fee.values, index=mt).resample("1h").sum()
hour = hour.dropna(subset=["lvr_theory", "measured_12s"])
day = hour.resample("1D").sum(numeric_only=True)[["lvr_theory", "measured_12s", "measured_60s", "fees"]]
day = day[(day.index > day.index.min()) & (day.index < day.index.max())]   # full days only
day.to_csv(a.out_csv)

tot = day.sum()
ann = lambda col: tot[col]
print(f"{len(day)} full days, sigma from {a.rv_sec}s Binance returns, L from swap events")
print(f"  theoretical LVR        ${tot.lvr_theory / 1e6:,.2f}M")
print(f"  measured loss, 12 s    ${tot.measured_12s / 1e6:,.2f}M  = {tot.measured_12s / tot.lvr_theory:.2f}x theory")
print(f"  measured loss, 60 s    ${tot.measured_60s / 1e6:,.2f}M  = {tot.measured_60s / tot.lvr_theory:.2f}x theory")
print(f"  LP fees                ${tot.fees / 1e6:,.2f}M  = {tot.fees / tot.lvr_theory:.2f}x theory")
c = np.corrcoef(day.lvr_theory, day.measured_12s)[0, 1]
print(f"  daily correlation theory vs measured 12 s: {c:.2f}; daily ratio median {(day.measured_12s / day.lvr_theory).median():.2f}")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID})
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(15, 5.4), gridspec_kw={"width_ratios": [2.2, 1]})
ax.plot(day.index, day.lvr_theory / 1e3, color="#8a8986", lw=2, label="Theoretical LVR (σ²·L·√S / 4)")
ax.plot(day.index, day.measured_12s / 1e3, color="#e34948", lw=2, label="Measured LP loss, 12 s markout")
ax.plot(day.index, day.fees / 1e3, color="#2a78d6", lw=1.6, ls=(0, (4, 3)), label="LP fees")
ax.set_ylabel("USDC per day (thousands)"); ax.legend(frameon=False, loc="upper left", fontsize=9)
ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %-d"))
ax2.scatter(day.lvr_theory / 1e3, day.measured_12s / 1e3, s=18, color="#e34948", alpha=0.75)
lim = max(day.lvr_theory.max(), day.measured_12s.max()) / 1e3 * 1.05
ax2.plot([0, lim], [0, lim], color=INK2, lw=1, ls=(0, (4, 3))); ax2.set_xlim(0, lim); ax2.set_ylim(min(0, day.measured_12s.min() / 1e3), lim)
ax2.set_xlabel("Theoretical LVR per day ($k)"); ax2.set_ylabel("Measured loss per day ($k)")
ax2.text(0.04, 0.95, f"total: measured = {tot.measured_12s / tot.lvr_theory:.2f}× theory\ndaily corr {c:.2f}", transform=ax2.transAxes,
         va="top", fontsize=9.5, color=INK)
fig.suptitle(f"Measured LP loss vs theoretical LVR · {day.index.min():%b %-d} – {day.index.max():%b %-d, %Y}", x=0.06, ha="left", fontsize=14, y=1.0)
fig.subplots_adjust(top=0.88, wspace=0.18)
fig.savefig(a.png, dpi=160, bbox_inches="tight"); print("wrote", a.png)
