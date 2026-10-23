"""
Stress test: replay a window (e.g. the Mar 2023 USDC depeg) with every policy's parameters frozen from an earlier
--sweep run. Nothing is refit on the stress window. Writes a results JSON and PNG charts.

  python3 run_stress.py --params results_usdc_usdt_1year.json --data data_2023_03 --fee 0.0001 \
      --out results_usdc_usdt_2023_03.json --charts charts_2023_03 --names USDC,USDT
"""
import argparse, json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import backtest as bt

ap = argparse.ArgumentParser()
ap.add_argument("--params", required=True); ap.add_argument("--data", required=True)
ap.add_argument("--fee", type=float, default=0.0001)
ap.add_argument("--h-decision", type=int, default=60); ap.add_argument("--h-eval", type=int, default=300)
ap.add_argument("--out", required=True); ap.add_argument("--charts", required=True)
ap.add_argument("--names", default="USDC,USDT")
a = ap.parse_args()
os.makedirs(a.charts, exist_ok=True)
T0, T1 = a.names.split(",")
f0 = a.fee
KIND = {"markout": "markout", "oscillon_hook": "hook", "oscillon_hook_poolfee": "hook_poolfee",
        "markout_hook": "markout_hook", "markout_hook_poolfee": "markout_hook_poolfee", "dynamic_vol": "vol",
        "oscillon_depeg": "depeg"}

prm = json.load(open(a.params))
s, r = bt.load(os.path.join(a.data, "swaps.csv"), os.path.join(a.data, "ref.csv"))
if os.path.exists(os.path.join(a.data, "oracle.csv")):
    s = bt.attach_oracle(s, os.path.join(a.data, "oracle.csv"))
s = bt.enrich(s, r, f0, sorted({a.h_decision, a.h_eval, 12, 60}))

results, per_swap = {}, {}
for e, block in prm.items():
    eps = float(e)
    cfg = block["_config"]
    ev = lambda pol: bt.evaluate(s, bt.fees_for(pol, s, r, f0, cfg["fmin"], cfg["fmax"], a.h_decision, eps),
                                 f0, a.h_decision, a.h_eval, eps)
    base = ev(bt.Policy("vanilla", "vanilla", {"fee": f0}))
    results[e] = {"vanilla": {"params": {"fee": f0}, "stress": bt.summarize(base, base)}}
    per_swap[e] = {"vanilla": base}
    for name, v in block.items():
        if name.startswith("_") or name == "vanilla" or name not in KIND:
            continue
        x = ev(bt.Policy(name, KIND[name], v["params"]))
        results[e][name] = {"params": v["params"], "stress": bt.summarize(x, base)}
        per_swap[e][name] = x
        fl = bt.average_fee(x)                       # control: flat fee at this rule's own average fee in the window
        xf = ev(bt.Policy("flat", "vanilla", {"fee": fl}))
        results[e][f"flat_{name}"] = {"params": {"fee": fl}, "stress": bt.summarize(xf, base)}
        per_swap[e][f"flat_{name}"] = xf
    results[e]["_config"] = {**cfg, "window": [str(pd.to_datetime(s.ts.min(), unit="s")), str(pd.to_datetime(s.ts.max(), unit="s"))],
                             "swaps": int(len(s)), "params_from": a.params}
with open(a.out, "w") as fh:
    json.dump(results, fh, indent=2, default=str)
for e in per_swap:                                   # per-leg fees, for replicate_old_2023.py
    fees = pd.DataFrame({"ts": s.ts.values, "dir": s.dir.values,
                         **{n: x["fee"].values for n, x in per_swap[e].items()}})
    fees.to_csv(os.path.join(a.data, f"fees_eps{e}.csv"), index=False)

# ------------------------------------------------------------------ table to stdout
for e in results:
    print(f"\n=== elasticity {e} · stress window, params frozen from {a.params} ===")
    for name, v in results[e].items():
        if name.startswith("_"):
            continue
        t = v["stress"]
        lo, hi = t["edge_vs_vanilla_ci90"]
        print(f"{name:22s} LP {t['lp_pnl']:>12,.0f}  fees {t['fee_revenue']:>11,.0f}  markout {t['markout_loss']:>12,.0f}  "
              f"kept {t['volume_kept_pct']:5.1f}%  avg fee {t['avg_fee_bps']:6.2f} bp  vs vanilla {t['edge_vs_vanilla']:>11,.0f} "
              f"[{lo:,.0f}, {hi:,.0f}]")

# ------------------------------------------------------------------ charts
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8986", "#e6e5e1", "#fcfcfb"
POL = {"vanilla": ("Vanilla 1 bp (today)", MUTED), "markout": ("Markout fee (linear)", "#2a78d6"),
       "oscillon_hook": ("Oscillon hook · oracle trigger, 3 bp base", "#eb6834"),
       "oscillon_hook_poolfee": ("Oscillon surcharge · oracle trigger, 1 bp base", "#e87ba4"),
       "markout_hook": ("Oscillon curve · markout trigger, 3 bp base", "#6250d6"),
       "markout_hook_poolfee": ("Oscillon curve · markout trigger, 1 bp base", "#1baf7a")}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8})
k_fmt = lambda v, _=None: f"{v / 1e6:,.1f}M" if abs(v) >= 1e6 else f"{v / 1000:,.0f}k" if abs(v) >= 1000 else f"{v:,.0f}"
sgn = lambda v: ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):,.0f}"
eps_list = list(results)
pols = [p for p in POL if p in results[eps_list[0]]]
t_ = pd.to_datetime(s.ts, unit="s")
win = f"{t_.min():%b %-d %H:%M} – {t_.max():%b %-d, %Y} UTC"


def save(fig, name):
    fig.savefig(os.path.join(a.charts, name), dpi=160, bbox_inches="tight"); plt.close(fig)
    print("wrote", os.path.join(a.charts, name))


# S1: what each fee rule charged USDC sellers as the price moved
e_mid = eps_list[min(1, len(eps_list) - 1)]
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7.5), sharex=True, gridspec_kw={"height_ratios": [1, 1.3]})
rr = r[(r.ts >= s.ts.min() - 3600) & (r.ts <= s.ts.max())]
ax1.plot(pd.to_datetime(rr.ts, unit="s"), rr.mid, color="#2a78d6", lw=1.4, label=f"Binance {T0}/{T1}")
if "oracle" in s.columns:
    ax1.plot(t_, s.oracle, color="#eb6834", lw=1.4, label=f"Chainlink {T0}/USD")
ax1.set_ylabel("Price"); ax1.legend(frameon=False, loc="lower right")
sell = s.dir.values < 0
for name in ("oscillon_hook", "markout_hook", "markout_hook_poolfee", "markout"):
    if name in per_swap[e_mid]:
        f = per_swap[e_mid][name]["fee"].values * 1e4
        ser = pd.Series(np.where(sell, f, np.nan), index=t_).resample("15min").max()
        ax2.plot(ser.index, ser.values, color=POL[name][1], lw=1.6, label=POL[name][0], drawstyle="steps-post")
ax2.set_ylabel(f"Fee on {T0} → {T1} swaps (bp)\n15-min max"); ax2.legend(frameon=False, loc="upper right", fontsize=9)
ax2.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %-d"))
fig.suptitle(f"{T0} depeg: what each fee rule charged {T0} sellers", x=0.06, ha="left", fontsize=14, y=0.99)
fig.text(0.06, 0.935, f"{win}. Oracle trigger reads Chainlink's distance from $1. Markout trigger reads how much LPs actually lost "
         f"on recent swaps, settled 1–5 min later.", fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.88, hspace=0.08)
save(fig, "S1_fee_charged_during_depeg.png")

# S2: cumulative LP profit through the depeg
fig, axes = plt.subplots(1, len(eps_list), figsize=(15, 5.4), sharey=True)
for ax, e in zip(np.atleast_1d(axes), eps_list):
    ends = []
    for p in pols:
        x = per_swap[e][p]
        c = pd.Series(x["lp_pnl"].values, index=t_).resample("1h").sum().cumsum()
        ax.plot(c.index, c.values, color=POL[p][1], lw=2)
        ends.append((c.iloc[-1], p))
    ax.axhline(0, color=INK2, lw=1)
    ax.set_title({"0.5": "Elasticity 0.5 · traders stay", "2.0": "Elasticity 2 · some flow leaves",
                  "5.0": "Elasticity 5 · cheaper pool nearby"}.get(e, e), loc="left", fontsize=11)
    ax.yaxis.set_major_formatter(k_fmt); ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %-d"))
    ax.xaxis.set_major_locator(matplotlib.dates.DayLocator(interval=4))
for ax, e in zip(np.atleast_1d(axes), eps_list):
    lo, hi = ax.get_ylim(); gap = (hi - lo) * 0.05; placed = []
    for v, p in sorted((per_swap[e][p]["lp_pnl"].sum(), p) for p in pols):
        y = v if not placed else max(v, placed[-1] + gap); placed.append(y)
        ax.annotate(k_fmt(v), (t_.max(), y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.5,
                    color=INK, annotation_clip=False)
np.atleast_1d(axes)[0].set_ylabel(f"Cumulative LP profit ({T1})")
fig.legend([plt.Line2D([], [], color=POL[p][1], lw=2.5) for p in pols], [POL[p][0] for p in pols],
           loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.1))
fig.suptitle(f"Cumulative LP profit through the {T0} depeg ({win})", x=0.06, ha="left", fontsize=14, y=1.0)
fig.text(0.06, 0.925, "Every rule uses the settings fitted on Jul 2025 – Jan 2026 data. Nothing was refit on the depeg.",
         fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.82, wspace=0.1)
save(fig, "S2_cumulative_lp_profit_depeg.png")

# S3: one-page results table
fig = plt.figure(figsize=(15, 9.5))
fig.text(0.03, 0.96, f"{T0} depeg stress test · {win}", fontsize=17, color=INK, va="top")
fig.text(0.03, 0.9, f"{len(s):,} directional legs · settings frozen from the 1-year fit · LP profit in {T1}; "
         "change vs today's 1 bp with 90% range, and vs a flat fee at the rule's own average", fontsize=10.5, color=INK2, va="top")
ax = fig.add_axes([0.03, 0.03, 0.94, 0.82]); ax.set_axis_off()
cells, cols = [], []
for p in pols:
    row, crow = [], []
    for e in eps_list:
        t = results[e][p]["stress"]
        if p == "vanilla":
            row.append(f"{t['lp_pnl']:,.0f}".replace("-", "−") + f"\nfees {k_fmt(t['fee_revenue'])} · markout {k_fmt(t['markout_loss'])}")
            crow.append(INK)
        else:
            lo, hi = t["edge_vs_vanilla_ci90"]
            fl = results[e].get(f"flat_{p}", {}).get("stress")
            fline = "" if fl is None else (f"\nvs flat {results[e]['flat_' + p]['params']['fee'] * 1e4:.2f} bp: "
                                           f"{sgn(t['lp_pnl'] - fl['lp_pnl'])}")
            row.append(f"{t['lp_pnl']:,.0f}".replace("-", "−") + f"   {sgn(t['edge_vs_vanilla'])} vs today\n[{sgn(lo)} to {sgn(hi)}]\n"
                       f"avg fee {t['avg_fee_bps']:.1f} bp · kept {t['volume_kept_pct']:.0f}%" + fline)
            crow.append("#1f7a4d" if lo > 0 else "#b5402f" if hi < 0 else INK2)
    cells.append(row); cols.append(crow)
tb = ax.table(cellText=cells, rowLabels=[POL[p][0] for p in pols],
              colLabels=[{"0.5": "Elasticity 0.5 · traders stay", "2.0": "Elasticity 2 · some leave",
                          "5.0": "Elasticity 5 · cheaper pool nearby"}.get(e, e) for e in eps_list],
              cellLoc="left", rowLoc="left", bbox=[0.22, 0, 0.78, 1])
tb.auto_set_font_size(False); tb.set_fontsize(9)
for (ri, ci), cell in tb.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor("white" if ri % 2 else SURF)
    if ri == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
    elif ci >= 0:
        cell.set_text_props(color=cols[ri - 1][ci])
save(fig, "S3_depeg_results_summary.png")
