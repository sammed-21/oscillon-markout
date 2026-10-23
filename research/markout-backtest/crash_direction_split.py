"""
Which side hurt LPs during the Mar 2023 USDC crash and recovery, and which side the oracle-triggered hook charged.
Vanilla 1 bp flow (no counterfactual), 6-hour buckets: net markout per direction next to the hook's average fee per side.

  python3 crash_direction_split.py --data data_2023_03 --start 2023-03-10T18:00 --end 2023-03-14 \
      --png charts_2023_03/S5_crash_direction_split.png --out-csv results_crash_direction_split.csv
"""
import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import backtest as bt

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
ap.add_argument("--fee", type=float, default=0.0001); ap.add_argument("--h-eval", type=int, default=300)
ap.add_argument("--bucket", default="6h"); ap.add_argument("--png", required=True); ap.add_argument("--out-csv", required=True)
a = ap.parse_args()

s, r = bt.load(f"{a.data}/swaps.csv", f"{a.data}/ref.csv")
s = bt.attach_oracle(s, f"{a.data}/oracle.csv")
s = bt.enrich(s, r, a.fee, sorted({a.h_eval, 12, 60}))
hook = bt._hook_fees({"base": 0.0003, "k": 45}, s) * 1e4                     # oracle trigger, 3 bp base, on-chain rounding
t = pd.to_datetime(s.ts, unit="s")
m = (t >= a.start) & (t < a.end)
df = pd.DataFrame({"t": t[m], "dir": s.dir[m], "markout": s[f"mark_{a.h_eval}"][m], "fees": a.fee * s.notional[m],
                   "volume": s.notional[m], "hook_fee": hook[m.values], "ref": s.ref_t[m]})
rows = []
for b, g in df.groupby(pd.Grouper(key="t", freq=a.bucket)):
    row = {"bucket_start": b, "ref_mid": g.ref.mean()}
    for d, lab in ((-1, "usdc_sellers"), (1, "usdc_buyers")):
        x = g[g.dir == d]
        row[f"{lab}_volume"] = x.volume.sum()
        row[f"{lab}_net_markout"] = x.markout.sum()
        row[f"{lab}_lp_profit_1bp"] = x.markout.sum() + x.fees.sum()
        row[f"{lab}_hook_fee_bp"] = np.average(x.hook_fee, weights=x.volume) if len(x) else np.nan
    rows.append(row)
out = pd.DataFrame(rows)
out.to_csv(a.out_csv, index=False)
pd.set_option("display.width", 200)
print(out[["bucket_start", "ref_mid", "usdc_sellers_net_markout", "usdc_sellers_hook_fee_bp",
           "usdc_buyers_net_markout", "usdc_buyers_hook_fee_bp"]].round(3).to_string(index=False))
tot = df.groupby("dir").markout.sum()
print(f"\nTotal net markout {a.start} – {a.end}: USDC sellers {tot.get(-1, 0):,.0f} · USDC buyers {tot.get(1, 0):,.0f}")

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID})
fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [1, 1.5, 1]})
x = np.arange(len(out)); w = 0.38
ax0.plot(x, out.ref_mid, color="#2a78d6", lw=2, marker="o", ms=4); ax0.set_ylabel("USDC/USDT\n(market)")
ax1.bar(x - w / 2, out.usdc_sellers_net_markout, w, color="#e34948", label="USDC sellers (USDC → USDT)")
ax1.bar(x + w / 2, out.usdc_buyers_net_markout, w, color="#1baf7a", label="USDC buyers (USDT → USDC)")
ax1.axhline(0, color=INK2, lw=1); ax1.set_ylabel("LP net markout (USDT)\nbelow 0 = side hurt LPs")
ax1.yaxis.set_major_formatter(lambda v, _: f"{v / 1e3:,.0f}k"); ax1.legend(frameon=False, loc="lower right", fontsize=9)
ax2.bar(x - w / 2, out.usdc_sellers_hook_fee_bp, w, color="#e34948")
ax2.bar(x + w / 2, out.usdc_buyers_hook_fee_bp, w, color="#1baf7a")
ax2.set_ylabel("Oracle hook fee (bp)\nvolume-weighted"); ax2.set_ylim(0, 105)
ax2.set_xticks(x); ax2.set_xticklabels([pd.Timestamp(b).strftime("%b %-d\n%H:%M") for b in out.bucket_start], fontsize=8.5)
fig.suptitle("Mar 2023 USDC crash: which side hurt LPs, and which side the oracle hook charged", x=0.06, ha="left", fontsize=14, y=0.995)
fig.text(0.06, 0.95, f"{a.bucket} buckets, today's 1 bp flow. Markout priced on the market (Kraken fill before Mar 11 14:00 UTC, Binance after) "
         f"{a.h_eval // 60} min after each trade.", fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.91, hspace=0.08)
fig.savefig(a.png, dpi=160, bbox_inches="tight"); print("wrote", a.png)
