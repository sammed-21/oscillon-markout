"""
Whole-period LP economics per fee rule, split by trade direction: volume, fees, adverse markout, LP profit, trader profit.
Uses each rule's settings from a --sweep results JSON (fit on its train days) and replays the whole period.

Definitions (per swap, all in token1 units, priced at the reference h_eval seconds after the swap):
  markout      = LP's price P&L on the trade, fee excluded (what it received − what it paid)
  adverse      = sum of the losing markouts: what LPs gave away to trades the market then moved against them
  benign gain  = sum of the winning markouts: what LPs earned from trades the market moved back
  LP profit    = fees + adverse markout(−) + benign gain
  (Not LVR in the Milionis et al. sense: this is trade-level markout against the reference.)
  trader profit= −LP profit (the other side of every trade); "winning traders" sums only trades that made money

  python3 full_year_breakdown.py --results results_usdc_usdt_1year.json --data data_1y --fee 0.0001 \
      --out-json results_usdc_usdt_1year_breakdown.json --charts charts_1y --names USDC,USDT
"""
import argparse, json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import backtest as bt

ap = argparse.ArgumentParser()
ap.add_argument("--results", required=True); ap.add_argument("--data", required=True)
ap.add_argument("--fee", type=float, required=True)
ap.add_argument("--h-decision", type=int, default=60); ap.add_argument("--h-eval", type=int, default=300)
ap.add_argument("--out-json", required=True); ap.add_argument("--charts", required=True)
ap.add_argument("--names", default="USDC,USDT"); ap.add_argument("--prefix", default="Y")
a = ap.parse_args()
os.makedirs(a.charts, exist_ok=True)
T0, T1 = a.names.split(",")
f0 = a.fee
KIND = {"markout": "markout", "oscillon_hook": "hook", "oscillon_hook_poolfee": "hook_poolfee",
        "markout_hook": "markout_hook", "markout_hook_poolfee": "markout_hook_poolfee"}
LABEL = {"vanilla": f"Today ({f0 * 1e4:g} bp flat)", "markout": "Markout fee (linear)",
         "oscillon_hook": "Oscillon · oracle trigger, 3 bp", "oscillon_hook_poolfee": f"Oscillon · oracle trigger, {f0 * 1e4:g} bp",
         "markout_hook": "Oscillon · markout trigger, 3 bp", "markout_hook_poolfee": f"Oscillon · markout trigger, {f0 * 1e4:g} bp"}
COLOR = {"vanilla": "#8a8986", "markout": "#2a78d6", "oscillon_hook": "#eb6834", "oscillon_hook_poolfee": "#e87ba4",
         "markout_hook": "#6250d6", "markout_hook_poolfee": "#1baf7a"}
DIRS = {-1: f"{T0} → {T1} (trader sells {T0})", 1: f"{T1} → {T0} (trader buys {T0})"}

prm = json.load(open(a.results))
s, r = bt.load(os.path.join(a.data, "swaps.csv"), os.path.join(a.data, "ref.csv"))
has_oracle = os.path.exists(os.path.join(a.data, "oracle.csv"))
if has_oracle:
    s = bt.attach_oracle(s, os.path.join(a.data, "oracle.csv"))
s = bt.enrich(s, r, f0, sorted({a.h_decision, a.h_eval, 12, 60}))
first_test = None


def stats(x: pd.DataFrame, base: pd.DataFrame) -> dict:
    mk = x["markout"].values
    lp = x["lp_pnl"].values
    trader = -lp
    return {
        "volume": float(x["volume"].sum()), "volume_kept_pct": float(x["volume"].sum() / base["volume"].sum() * 100),
        "trades_kept": float(x["w"].sum()), "fees": float(x["fee_rev"].sum()),
        "lvr": float(np.minimum(mk, 0).sum()), "benign_gain": float(np.maximum(mk, 0).sum()),
        "net_markout": float(mk.sum()), "lp_profit": float(lp.sum()),
        "lp_profit_bp_of_volume": float(lp.sum() / x["volume"].sum() * 1e4) if x["volume"].sum() else np.nan,
        "lvr_pct_of_fees": float(-np.minimum(mk, 0).sum() / x["fee_rev"].sum() * 100) if x["fee_rev"].sum() else np.nan,
        "trader_profit": float(trader.sum()), "winning_trader_profit": float(np.maximum(trader, 0).sum()),
        "losing_trader_loss": float(np.minimum(trader, 0).sum()),
        "avg_fee_bps": float(bt.average_fee(x) * 1e4),
    }


out, per = {}, {}
for e, block in prm.items():
    eps = float(e); cfg = block["_config"]
    ev = lambda pol: bt.evaluate(s, bt.fees_for(pol, s, r, f0, cfg["fmin"], cfg["fmax"], a.h_decision, eps),
                                 f0, a.h_decision, a.h_eval, eps)
    rules = {"vanilla": ev(bt.Policy("vanilla", "vanilla", {"fee": f0}))}
    for name in KIND:
        if name in block and (has_oracle or KIND[name] not in ("hook", "hook_poolfee")):
            rules[name] = ev(bt.Policy(name, KIND[name], block[name]["params"]))
    per[e] = rules
    base = rules["vanilla"]
    out[e] = {}
    for name, x in rules.items():
        d = {"all": stats(x, base)}
        for dr, key in ((-1, "sell_token0"), (1, "buy_token0")):
            m, mb = x["dir"].values == dr, base["dir"].values == dr
            d[key] = stats(x[m], base[mb])
        out[e][name] = d
out["_meta"] = {"names": [T0, T1], "window": [str(pd.to_datetime(s.ts.min(), unit="s")), str(pd.to_datetime(s.ts.max(), unit="s"))],
                "swaps": int(len(s)), "fee": f0, "h_eval_s": a.h_eval, "params_from": a.results}
json.dump(out, open(a.out_json, "w"), indent=2)

# ------------------------------------------------------------------ console
for e in prm:
    print(f"\n=== elasticity {e} · whole period {out['_meta']['window'][0][:10]} – {out['_meta']['window'][1][:10]} ===")
    for key, lab in (("sell_token0", DIRS[-1]), ("buy_token0", DIRS[1]), ("all", "Both directions")):
        print(f"  {lab}")
        for name, d in out[e].items():
            t = d[key]
            print(f"    {name:22s} vol {t['volume'] / 1e6:>8,.0f}M ({t['volume_kept_pct']:5.1f}%)  fees {t['fees']:>10,.0f}  "
                  f"adverse {t['lvr']:>11,.0f}  benign {t['benign_gain']:>10,.0f}  LP {t['lp_profit']:>11,.0f}  "
                  f"traders {t['trader_profit']:>11,.0f} (winners {t['winning_trader_profit']:>10,.0f})")

# ------------------------------------------------------------------ charts
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8})
k = lambda v: (("−" if v < 0 else "") + (f"{abs(v) / 1e6:,.2f}M" if abs(v) >= 1e6 else f"{abs(v) / 1e3:,.0f}k" if abs(v) >= 1e3 else f"{abs(v):,.0f}"))
eps_list = [e for e in prm]
e_mid = eps_list[min(1, len(eps_list) - 1)]
win = f"{pd.to_datetime(s.ts.min(), unit='s'):%b %-d, %Y} – {pd.to_datetime(s.ts.max(), unit='s'):%b %-d, %Y}"
rules = list(out[e_mid].keys())


def save(fig, name):
    p = os.path.join(a.charts, f"{a.prefix}{name}")
    fig.savefig(p, dpi=160, bbox_inches="tight"); plt.close(fig); print("wrote", p)


# Y1: the full table per direction, at the middle elasticity
cols = ["Volume (kept)", "Fees", "Adverse markout\n(LP loss to\ninformed trades)", "Benign gain", "LP profit", "Trader profit\n(winners only)", "Avg fee"]
fig = plt.figure(figsize=(16, 3.2 + 1.05 * 3 * len(rules)))
fig.text(0.02, 0.985, f"{T0}/{T1}: whole-period LP economics by direction · {win} · elasticity {float(e_mid):g}", fontsize=15,
         color=INK, va="top")
fig.text(0.02, 0.955, f"Amounts in {T1}. Adverse markout = LP losses on trades the market then moved against them (priced {a.h_eval // 60} min later). "
         "LP profit = fees + adverse markout + benign gain. Trader profit = −LP profit.", fontsize=10, color=INK2, va="top")
blocks = (("sell_token0", DIRS[-1]), ("buy_token0", DIRS[1]), ("all", "Both directions"))
h = 0.86 / 3
for i, (key, lab) in enumerate(blocks):
    ax = fig.add_axes([0.02, 0.92 - (i + 1) * h + 0.02, 0.96, h - 0.04]); ax.set_axis_off()
    ax.text(0, 1.02, lab, fontsize=12, color=INK, fontweight="bold", transform=ax.transAxes)
    cells, colors = [], []
    for name in rules:
        t = out[e_mid][name][key]
        cells.append([f"{k(t['volume'])} ({t['volume_kept_pct']:.0f}%)", k(t["fees"]), k(t["lvr"]), "+" + k(t["benign_gain"]),
                      k(t["lp_profit"]), f"{k(t['trader_profit'])} ({k(t['winning_trader_profit'])})", f"{t['avg_fee_bps']:.2f} bp"])
        b = out[e_mid]["vanilla"][key]["lp_profit"]
        colors.append(["#1f7a4d" if (c == 4 and t["lp_profit"] > b and name != "vanilla") else
                       "#b5402f" if (c == 4 and t["lp_profit"] < b) else INK for c in range(len(cols))])
    tb = ax.table(cellText=cells, rowLabels=[LABEL[n] for n in rules], colLabels=cols, cellLoc="right", rowLoc="left",
                  bbox=[0.2, 0, 0.8, 0.98])
    tb.auto_set_font_size(False); tb.set_fontsize(9)
    for (ri, ci), cell in tb.get_celld().items():
        cell.set_edgecolor(GRID); cell.set_facecolor("white" if ri % 2 else SURF)
        if ri == 0:
            cell.set_text_props(color=INK2, fontweight="bold"); cell.set_height(cell.get_height() * 1.4)
        elif ci >= 0:
            cell.set_text_props(color=colors[ri - 1][ci])
save(fig, "1_whole_period_by_direction.png")

# Y2: where LP profit comes from, by direction (fees + benign − adverse = profit)
fig, axes = plt.subplots(1, 2, figsize=(15, 5.6), sharey=True)
for ax, (key, lab) in zip(axes, blocks[:2]):
    x = np.arange(len(rules))
    fees = [out[e_mid][n][key]["fees"] for n in rules]; ben = [out[e_mid][n][key]["benign_gain"] for n in rules]
    lvr = [out[e_mid][n][key]["lvr"] for n in rules]; prof = [out[e_mid][n][key]["lp_profit"] for n in rules]
    ax.set_axisbelow(True)
    ax.bar(x, fees, 0.6, color="#2a78d6", label="Fees")
    ax.bar(x, ben, 0.6, bottom=fees, color="#9cc2ef", label="Benign gain")
    ax.bar(x, lvr, 0.6, color="#e34948", label="Adverse markout (loss)")
    ax.plot(x, prof, "D", ms=9, color=INK, mec="white", mew=1.5, label="LP profit")
    for xi, p in zip(x, prof):
        ax.annotate(k(p), (xi, p), xytext=(10, 0), textcoords="offset points", va="center", fontsize=8.5, color=INK)
    ax.axhline(0, color=INK2, lw=1)
    SHORT = {"vanilla": "Today", "markout": "Markout\nlinear", "oscillon_hook": "Oracle\n3 bp", "oscillon_hook_poolfee": "Oracle\npool fee",
             "markout_hook": "Markout\ntrigger 3 bp", "markout_hook_poolfee": "Markout\ntrigger pool fee"}
    ax.set_xticks(x); ax.set_xticklabels([SHORT[n] for n in rules], fontsize=9)
    ax.yaxis.set_major_formatter(lambda v, _: k(v)); ax.set_title(lab, loc="left", fontsize=11); ax.grid(axis="x", visible=False)
axes[0].set_ylabel(f"{T1} over the whole period"); fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, loc="lower center", ncol=4, fontsize=9, bbox_to_anchor=(0.5, -0.04))
fig.suptitle(f"{T0}/{T1}: what LPs earned and lost, each direction · {win} · elasticity {float(e_mid):g}", x=0.06, ha="left",
             fontsize=14, y=1.0)
fig.subplots_adjust(top=0.88, wspace=0.05)
save(fig, "2_lp_profit_sources_by_direction.png")

# Y3: monthly adverse markout and LP profit by direction for each rule
fig, axes = plt.subplots(2, 2, figsize=(15, 8), sharex=True)
months = None
for col, (dr, key) in enumerate(((-1, "sell_token0"), (1, "buy_token0"))):
    for name in rules:
        x = per[e_mid][name]; m = x["dir"].values == dr
        g = pd.DataFrame({"m": pd.to_datetime(s.ts.values[m], unit="s"), "lvr": np.minimum(x["markout"].values[m], 0),
                          "lp": x["lp_pnl"].values[m]}).set_index("m").resample("MS").sum()
        months = g.index
        axes[0, col].plot(g.index, g.lp, color=COLOR[name], lw=2, marker="o", ms=3.5, label=LABEL[name])
        axes[1, col].plot(g.index, g.lvr, color=COLOR[name], lw=2, marker="o", ms=3.5)
    axes[0, col].set_title(DIRS[dr], loc="left", fontsize=11)
    for row in (0, 1):
        axes[row, col].axhline(0, color=INK2, lw=1); axes[row, col].yaxis.set_major_formatter(lambda v, _: k(v))
    axes[1, col].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b\n%y"))
axes[0, 0].set_ylabel(f"LP profit per month ({T1})"); axes[1, 0].set_ylabel(f"Adverse markout per month ({T1})")
fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.06))
fig.suptitle(f"{T0}/{T1}: month by month, each direction · elasticity {float(e_mid):g}", x=0.06, ha="left", fontsize=14, y=1.0)
fig.subplots_adjust(top=0.9, hspace=0.12, wspace=0.12)
save(fig, "3_monthly_by_direction.png")

# Y4: elasticity grid — LP profit, volume kept, trader profit, both directions combined
fig = plt.figure(figsize=(16, 1.6 + 0.62 * len(rules)))
fig.text(0.02, 0.97, f"{T0}/{T1}: whole period, both directions, at each elasticity · {win}", fontsize=14, color=INK, va="top")
ax = fig.add_axes([0.02, 0.03, 0.96, 0.8]); ax.set_axis_off()
cells = []
for name in rules:
    row = []
    for e in eps_list:
        t = out[e][name]["all"] if name in out[e] else None
        row.append("—" if t is None else f"LP {k(t['lp_profit'])} · adverse {k(t['lvr'])}\nvol kept {t['volume_kept_pct']:.0f}% · traders {k(t['trader_profit'])}")
    cells.append(row)
tb = ax.table(cellText=cells, rowLabels=[LABEL[n] for n in rules],
              colLabels=[{"0.5": "Elasticity 0.5 · traders stay", "2.0": "Elasticity 2 · some leave",
                          "5.0": "Elasticity 5 · cheaper pool nearby"}.get(e, e) for e in eps_list],
              cellLoc="left", rowLoc="left", bbox=[0.2, 0, 0.8, 1])
tb.auto_set_font_size(False); tb.set_fontsize(9)
for (ri, ci), cell in tb.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor("white" if ri % 2 else SURF)
    if ri == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
save(fig, "4_elasticity_grid.png")
