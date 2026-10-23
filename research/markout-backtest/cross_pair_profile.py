"""
Two-way flow profile for every stable pair in research-backtest, on one common yardstick, to judge which asset categories
a dynamic LP fee is worth building for.

Per pair and direction: swaps, volume, fees at the pool's real fee tier, and LP markout measured against the pool's OWN
price 5 minutes later (no outside price needed, so thin pairs can be compared too). That pool-relative markout catches
losses that arbitrage later corrects in the pool; it misses losses while the pool stays stale, so it is a lower bound.

  python3 cross_pair_profile.py --out-json results_cross_pair_profile.json --png charts_cross_pair/C1_two_way_profile.png
"""
import argparse, json, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default="../../../research-backtest")
ap.add_argument("--h", type=int, default=300)
ap.add_argument("--out-json", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
os.makedirs(os.path.dirname(a.png), exist_ok=True)
D = os.path.join(a.repo, "data")

# name, category, raw file (or prepared legs), dec0, dec1, LP fee (bp), token names, fee source
PAIRS = [
    ("USDC/USDT", "Fiat-backed majors", "legs:data_1y/swaps.csv", 6, 6, 1.0, ("USDC", "USDT"), "v3 0.01% tier"),
    ("USDe/USDT", "Synthetic / yield-bearing", f"{D}/usde_usdt/v4_swaps_raw_2025-10-02_2026-08-20.csv", 18, 6, 0.45, ("USDe", "USDT"), "StateView lpFee 45"),
    ("USDe/USDC", "Synthetic / yield-bearing", f"{D}/usde_usdc/v4_swaps_raw_2026-07-17_2026-08-20.csv", 18, 6, 0.25, ("USDe", "USDC"), "StateView lpFee 25"),
    ("USDS/USDT", "Decentralised (CDP)", f"{D}/usds_usdt/v4_swaps_raw_2026-01-24_2026-08-24.csv", 6, 18, 0.05, ("USDT", "USDS"), "StateView lpFee 5"),
    ("PYUSD/USDS", "Fiat-backed minor", f"{D}/pyusd_usds/v4_swaps_raw_2026-02-19_2026-08-25.csv", 6, 18, 0.05, ("PYUSD", "USDS"), "StateView lpFee 5"),
    ("FRAX/USDC", "Fractional / algorithmic", f"{D}/frax_usdc/v3_swaps_raw_2026-01-24_2026-08-25.csv", 18, 6, 5.0, ("FRAX", "USDC"), "v3 fee() 500"),
    ("AUSD/USDC", "Fiat-backed, Monad", f"{D}/ausd_usdc_monad/v4_swaps_raw_2026-01-24_2026-08-25.csv", 6, 6, 0.5, ("AUSD", "USDC"), "pool_config tier 50"),
]


def load(src: str, dec0: int, dec1: int) -> pd.DataFrame:
    if src.startswith("legs:"):
        s = pd.read_csv(src[5:])
        return s[["ts", "dir", "a0", "a1", "pool_px_after"]]
    d = pd.read_csv(src)
    d["ts"] = pd.to_datetime(d["timestamp"].astype(str).str.replace(" UTC", "", regex=False), utc=True).astype("int64") // 10**9
    d = d.sort_values("ts", kind="stable").reset_index(drop=True)
    x0, x1 = d["amount0"].astype(float) / 10**dec0, d["amount1"].astype(float) / 10**dec1
    corr = np.corrcoef(np.sign(x0[1:]), np.sign(d["tick"].diff()[1:]))[0, 1]
    got0 = (x0 > 0) if corr > 0 else (x0 < 0)
    s = pd.DataFrame({"ts": d["ts"], "dir": np.where(got0, 1, -1), "a0": x0.abs(), "a1": x1.abs(),
                      "pool_px_after": 1.0001 ** d["tick"].astype(float) * 10 ** (dec0 - dec1)})
    s = s[(s.a0 > 1e-6) & (s.a1 > 1e-6)]
    return s[(s.a1 / s.a0 / s.pool_px_after - 1).abs() < 0.005].reset_index(drop=True)


out = []
for name, cat, src, dec0, dec1, fee_bp, (t0, t1), fee_src in PAIRS:
    s = load(src, dec0, dec1)
    px = s[["ts", "pool_px_after"]].groupby("ts").last().reset_index()
    fut = pd.merge_asof(pd.DataFrame({"ts": s.ts + a.h}), px, on="ts", direction="backward")["pool_px_after"].values
    f = fee_bp / 1e4
    buy = s.dir.values > 0
    a0, a1 = s.a0.values, s.a1.values
    a1n, a0n = np.where(buy, a1 * (1 - f), a1), np.where(buy, a0, a0 * (1 - f))
    mark = np.where(buy, a1n - a0 * fut, a0n * fut - a1)            # token1, fee excluded
    notional = a0 * s.pool_px_after.values
    feerev = f * notional
    days = (s.ts.max() - s.ts.min()) / 86400
    dev = (s.pool_px_after - 1).abs() * 1e4
    row = {"pair": name, "category": cat, "fee_bp": fee_bp, "fee_source": fee_src, "days": round(days, 1),
           "window": [str(pd.to_datetime(s.ts.min(), unit="s"))[:10], str(pd.to_datetime(s.ts.max(), unit="s"))[:10]],
           "swaps": int(len(s)), "volume": float(notional.sum()), "volume_per_day": float(notional.sum() / days),
           "pool_price_dev_bp_median": float(dev.median()), "pool_price_dev_bp_p99": float(dev.quantile(.99)),
           "pool_price_dev_bp_max": float(dev.max()), "dirs": {}}
    for dr, lab in ((-1, f"{t0} → {t1}"), (1, f"{t1} → {t0}")):
        m = s.dir.values == dr
        mk = mark[m]
        row["dirs"][lab] = {"swaps": int(m.sum()), "volume": float(notional[m].sum()), "median_size": float(np.median(notional[m])),
                            "fees": float(feerev[m].sum()), "lvr_pool_relative": float(np.nansum(np.minimum(mk, 0))),
                            "net_markout_pool_relative": float(np.nansum(mk)),
                            "lp_profit_pool_relative": float(feerev[m].sum() + np.nansum(mk)),
                            "lvr_bp_of_volume": float(-np.nansum(np.minimum(mk, 0)) / notional[m].sum() * 1e4)}
    row["lvr_bp_of_volume"] = float(-np.nansum(np.minimum(mark, 0)) / notional.sum() * 1e4)
    row["net_markout_bp_of_volume"] = float(np.nansum(mark) / notional.sum() * 1e4)
    row["lvr_to_fee_ratio"] = float(-np.nansum(np.minimum(mark, 0)) / feerev.sum()) if feerev.sum() else np.nan
    out.append(row)
    print(f"{name:11s} {cat:28s} fee {fee_bp:>4} bp | {len(s):>7,} swaps {notional.sum() / 1e6:>8,.0f}M over {days:5.0f} d | "
          f"dev p99 {row['pool_price_dev_bp_p99']:6.1f} bp | adverse markout {row['lvr_bp_of_volume']:.2f} bp of vol, "
          f"net markout {row['net_markout_bp_of_volume']:+.2f} bp")
    for lab, v in row["dirs"].items():
        print(f"    {lab:14s} {v['swaps']:>7,} swaps {v['volume'] / 1e6:>8,.0f}M  fees {v['fees']:>9,.0f}  adverse {v['lvr_pool_relative']:>10,.0f}"
              f"  net {v['net_markout_pool_relative']:>+10,.0f}  LP {v['lp_profit_pool_relative']:>+10,.0f}")
json.dump(out, open(a.out_json, "w"), indent=2)

# ------------------------------------------------------------------ PNG
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID})
k = lambda v: ("−" if v < 0 else "") + (f"{abs(v) / 1e6:,.2f}M" if abs(v) >= 1e6 else f"{abs(v) / 1e3:,.0f}k" if abs(v) >= 1e3 else f"{abs(v):,.0f}")
fig = plt.figure(figsize=(17, 2.2 + 0.95 * len(out)))
fig.text(0.02, 0.975, "Two-way flow by stablecoin pair: where LPs lose to informed trades", fontsize=16, color=INK, va="top")
fig.text(0.02, 0.94, f"Adverse markout = LP losses on trades the pool itself re-priced against within {a.h // 60} min (pool-relative, a lower bound). "
         "Fees at each pool's real on-chain fee tier. Windows differ by pair.", fontsize=10, color=INK2, va="top")
ax = fig.add_axes([0.02, 0.03, 0.96, 0.86]); ax.set_axis_off()
cols = ["Category", "Window · fee", "Volume / day", "Price dev p99", "Side A\nfees · adverse · LP profit", "Side B\nfees · adverse · LP profit",
        "Adverse markout\nbp of volume", "Net markout\nbp of volume"]
cells = []
for r_ in out:
    (la, va), (lb, vb) = list(r_["dirs"].items())
    cells.append([r_["category"], f"{r_['window'][0]} → {r_['window'][1]}\n{r_['fee_bp']:g} bp", k(r_["volume_per_day"]),
                  f"{r_['pool_price_dev_bp_p99']:.1f} bp",
                  f"{la}\n{k(va['fees'])} · {k(va['lvr_pool_relative'])} · {k(va['lp_profit_pool_relative'])}",
                  f"{lb}\n{k(vb['fees'])} · {k(vb['lvr_pool_relative'])} · {k(vb['lp_profit_pool_relative'])}",
                  f"{r_['lvr_bp_of_volume']:.2f}", f"{r_['net_markout_bp_of_volume']:+.2f}"])
tb = ax.table(cellText=cells, rowLabels=[r_["pair"] for r_ in out], colLabels=cols, cellLoc="left", rowLoc="left", bbox=[0.07, 0, 0.93, 1])
tb.auto_set_font_size(False); tb.set_fontsize(9)
for (ri, ci), cell in tb.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor("white" if ri % 2 else SURF)
    if ri == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
    elif ci == 7:
        v = out[ri - 1]["net_markout_bp_of_volume"]
        cell.set_text_props(color="#b5402f" if v < 0 else INK)
fig.savefig(a.png, dpi=160, bbox_inches="tight"); print("wrote", a.png)
