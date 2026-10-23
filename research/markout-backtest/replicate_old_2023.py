"""
Like-for-like check against research-backtest's published Mar 2023 result (LP capture 14.8% static -> 33.2% hybrid).

Step 1 runs research-backtest's own engine on its own file (prepared_swaps_2023-03.csv) to reproduce the old numbers.
Step 2 keeps that exact file, accounting and "LVR proxy" definition (spread = Chainlink depeg on drain flow) and only swaps
the fee per minute for: the hook with on-chain whole-bp rounding, the markout-triggered curve, and flat controls.
Markout-trigger fees come from run_stress.py's per-leg fee file (same minutes, settings frozen from the 1-year fit).

  python3 replicate_old_2023.py --repo ../../../research-backtest --fees data_2023_03/fees_eps2.0.csv \
      --out results_old_2023_capture.json --png charts_2023_03/S4_capture_vs_old_result.png
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--repo", required=True); ap.add_argument("--fees", required=True)
ap.add_argument("--out", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.repo))
from src.backtest_engine import run_prepared_backtest, static_fee_fn, hybrid_fee_fn, summarize_backtest  # noqa: E402
from src.oscillon_fee import select_fee_pips, FeeContext  # noqa: E402

old = pd.read_csv(os.path.join(a.repo, "data", "prepared_swaps_2023-03.csv"))
days = (pd.to_datetime(old.timestamp).max() - pd.to_datetime(old.timestamp).min()).total_seconds() / 86400
summ = lambda df: summarize_backtest(df, tvl=1, period_days=days)

out = {"file": "prepared_swaps_2023-03.csv", "rows": len(old), "window": [old.timestamp.min(), old.timestamp.max()]}
rows = []
for name, fn in (("Static 3 bp (old)", static_fee_fn), ("Oscillon hybrid, float (old)", hybrid_fee_fn),
                 ("Oscillon hybrid, on-chain rounding",
                  lambda d, dr: select_fee_pips(FeeContext(depeg_bps=int(d), is_drain=dr, k_override=45)) / 100)):
    r = summ(run_prepared_backtest(old, fn))
    rows.append((name, r["lp_income_usd"], r["lvr_usd"], r["lp_capture_pct"]))

# ---- per-minute fees from the markout-triggered rules (keeper legs are stamped at bar time + 60 s)
fees = pd.read_csv(a.fees)
fees["minute"] = pd.to_datetime(fees.ts - 60, unit="s")
sell = fees[fees.dir < 0].set_index("minute"); buy = fees[fees.dir > 0].set_index("minute")
old["minute"] = pd.to_datetime(old.timestamp)
covered = old.minute.isin(sell.index.union(buy.index))
out["minutes_with_keeper_fee"] = int(covered.sum())


def capture(fee_drain_bps: np.ndarray, fee_other_bps: np.ndarray) -> tuple[float, float, float]:
    """research-backtest accounting (simulate_swap_row, apply_routing=False) with a per-minute fee."""
    drain = old.is_drain.astype(bool).values
    dev = old.dev_bps.fillna(0).values
    dsz = old.drain_size_usd.fillna(old.swap_size_usd).values
    rsz = old.restore_size_usd.fillna(0).values
    lp = np.where(drain, dsz * fee_drain_bps / 1e4 + rsz * fee_other_bps / 1e4, (dsz + rsz) * fee_other_bps / 1e4)
    lvr = np.where(drain & (dev > 0), np.maximum(0, dsz * (dev - fee_drain_bps) / 1e4), 0.0)
    return lp.sum(), lvr.sum(), lp.sum() / (lp.sum() + lvr.sum()) * 100


net_sell = old.netAmount0.values > 0                  # this minute's net flow sold USDC into the pool
for col, label in (("markout_hook", "Markout-triggered curve, 3 bp base"),
                   ("markout_hook_poolfee", "Markout-triggered curve, 1 bp base"),
                   ("oscillon_hook", "Oracle-triggered hook, 3 bp (keeper run)")):
    if col not in fees.columns:
        continue
    fs = sell[col].reindex(old.minute).values * 1e4
    fb = buy[col].reindex(old.minute).values * 1e4
    base = 3.0 if "poolfee" not in col else 1.0
    f_net = np.where(net_sell, fs, fb)                 # fee on the side the minute's net flow went
    f_drain = np.nan_to_num(fs, nan=base); f_other = np.nan_to_num(np.where(np.isnan(f_net), base, f_net), nan=base)
    lp, lvr, cap = capture(f_drain, f_other)
    rows.append((label, lp, lvr, cap))
    sz = (old.drain_size_usd.fillna(0) + old.restore_size_usd.fillna(0)).values
    flat = float(np.average(np.where(old.is_drain, f_drain, f_other), weights=np.maximum(sz, 1e-9)))
    lp, lvr, cap = capture(np.full(len(old), flat), np.full(len(old), flat))
    rows.append((f"  flat {flat:.2f} bp (same average fee)", lp, lvr, cap))

hyb = rows[1]
sz = (old.drain_size_usd.fillna(0) + old.restore_size_usd.fillna(0)).values
fl = float(np.average(np.where(old.is_drain, [hybrid_fee_fn(d, True) for d in old.dev_bps.fillna(0)], 3.0),
                      weights=np.maximum(sz, 1e-9)))
lp, lvr, cap = capture(np.full(len(old), fl), np.full(len(old), fl))
rows.insert(2, (f"  flat {fl:.2f} bp (hybrid's average fee)", lp, lvr, cap))

out["results"] = [{"rule": n, "lp_income_usd": lp, "lvr_usd": lvr, "lp_capture_pct": c} for n, lp, lvr, c in rows]
json.dump(out, open(a.out, "w"), indent=2)
for n, lp, lvr, c in rows:
    print(f"{n:45s} LP income {lp:>12,.0f}  LVR proxy {lvr:>12,.0f}  capture {c:5.1f}%")

# ---- PNG
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": GRID, "axes.spines.top": False,
                     "axes.spines.right": False, "xtick.color": INK2, "ytick.color": INK2})
fig, ax = plt.subplots(figsize=(13, 0.55 * len(rows) + 1.8))
y = np.arange(len(rows))[::-1]
col = ["#8a8986" if n.startswith("Static") else "#c9c8c4" if n.startswith("  flat") else
       "#eb6834" if "hybrid" in n.lower() or "oracle" in n.lower() else "#6250d6" if "3 bp base" in n else "#1baf7a"
       for n, *_ in rows]
ax.barh(y, [c for *_, c in rows], color=col, height=0.62)
for yy, (n, lp, lvr, c) in zip(y, rows):
    ax.text(c + 0.6, yy, f"{c:.1f}%   LP \\${lp:,.0f} · LVR proxy \\${lvr:,.0f}", va="center", fontsize=9, color=INK)
ax.set_yticks(y); ax.set_yticklabels([n for n, *_ in rows]); ax.set_xlim(0, max(c for *_, c in rows) * 1.6)
ax.set_xlabel("LP capture % = fees ÷ (fees + LVR proxy), research-backtest metric. Published 33.2% = on-chain rounding with the old 50 bp cap"); ax.grid(axis="x", color=GRID); ax.set_axisbelow(True)
ax.set_title(f"Same file, same accounting as the published 14.8% → 33.2%: {out['window'][0][:10]} – {out['window'][1][:10]}, "
             f"{len(old):,} minute rows", loc="left", fontsize=12, color=INK)
fig.savefig(a.png, dpi=160, bbox_inches="tight")
print("wrote", a.png)
