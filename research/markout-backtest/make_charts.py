"""
PNG charts for a backtest run: results JSON (--sweep output) + the --daily-out CSV + the prepared inputs.

  python3 make_charts.py --results results_usdc_usdt_1year.json --daily data_1y/daily_results.csv \
      --data data_1y --out charts_1y --names USDC,USDT
"""
import argparse, json, os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ap = argparse.ArgumentParser()
ap.add_argument("--results", required=True); ap.add_argument("--daily", required=True)
ap.add_argument("--data", required=True); ap.add_argument("--out", default="charts")
ap.add_argument("--names", default="USDC,USDT")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
T0, T1 = a.names.split(",")

INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8986", "#e6e5e1", "#fcfcfb"
POL = {  # name -> (label, color); slots 1-3 of the validated categorical palette, vanilla as neutral
    "vanilla": ("Vanilla 1 bp (today)", MUTED),
    "markout": ("Markout fee (linear)", "#2a78d6"),
    "oscillon_hook": ("Oscillon · oracle trigger, 3 bp", "#eb6834"),
    "oscillon_hook_poolfee": ("Oscillon · oracle trigger, 1 bp", "#e87ba4"),
    "markout_hook": ("Oscillon · markout trigger, 3 bp", "#6250d6"),
    "markout_hook_poolfee": ("Oscillon · markout trigger, 1 bp", "#1baf7a"),
}
DIRS = {-1: f"{T0} → {T1}  (trader sells {T0})", 1: f"{T1} → {T0}  (trader buys {T0})"}
DKEY = {-1: "sell_token0", 1: "buy_token0"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK, "figure.facecolor": SURF,
                     "axes.facecolor": SURF, "savefig.facecolor": SURF, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8})
res = json.load(open(a.results))
eps_list = [e for e in res]
pols = [p for p in POL if p in res[eps_list[0]]]
daily = pd.read_csv(a.daily, parse_dates=["day"])
daily["elasticity"] = daily["elasticity"].astype(float).map(lambda x: str(x))
cfg = res[eps_list[0]]["_config"]
k_fmt = lambda v, _=None: f"{v/1000:,.0f}k" if abs(v) >= 1000 else f"{v:,.0f}"
sgn = lambda v: ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):,.0f}"
eps_name = {"0.5": "Elasticity 0.5 · traders stay", "2.0": "Elasticity 2 · some flow leaves",
            "5.0": "Elasticity 5 · cheaper pool nearby"}


def save(fig, name):
    fig.savefig(os.path.join(a.out, name), dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("wrote", os.path.join(a.out, name))


# ------------------------------------------------------------------ 0. one-page results summary
van_all = daily[(daily.elasticity == eps_list[0]) & (daily.policy == "vanilla")]


def edge_vs_flat(p: str, e: str, period: str = "test", n_boot: int = 500):
    """Rule minus its flat-fee control (same average fee), summed over days, with a 90% bootstrap range by day."""
    d = daily[(daily.elasticity == e) & (daily.period == period)]
    a_ = d[d.policy == p].groupby("day").lp_pnl.sum()
    b_ = d[d.policy == f"flat_{p}"].groupby("day").lp_pnl.sum()
    if b_.empty:
        return None
    diff = (a_ - b_).dropna().values
    boots = np.random.default_rng(0).choice(diff, size=(n_boot, len(diff)), replace=True).sum(axis=1)
    return diff.sum(), np.percentile(boots, 5), np.percentile(boots, 95)


fig = plt.figure(figsize=(15, 14.5))
fig.text(0.04, 0.965, f"{T0}/{T1} 1 bp pool · fee rule backtest results", fontsize=19, color=INK, va="top")
fig.text(0.04, 0.925, f"{daily.day.min():%b %-d, %Y} – {daily.day.max():%b %-d, %Y} · {van_all.volume.sum() / 1e9:,.2f}B traded · "
         f"fitted on {cfg['train_days']} days, scored on the last {cfg['test_days']} days (out of sample) · amounts in {T1}",
         fontsize=10.5, color=INK2, va="top")

tiles = [(f"{van_all.fee_rev.sum():,.0f}", "LP fees at 1 bp, full year"),
         (sgn(van_all.markout.sum()), "LP markout at 1 bp, full year"),
         (f"{(res[eps_list[0]]['vanilla']['test']['lp_pnl']):,.0f}", f"LP profit at 1 bp, test {cfg['test_days']} days")]
for i, (v, lab) in enumerate(tiles):
    x = 0.04 + i * 0.31
    fig.text(x, 0.87, v, fontsize=24, color=INK, va="top", family="DejaVu Serif")
    fig.text(x, 0.825, lab, fontsize=10, color=INK2, va="top")

ax = fig.add_axes([0.03, 0.40, 0.94, 0.39]); ax.set_axis_off()
ax.text(0, 1.0, f"LP profit by fee rule, test period ({cfg['test_days']} days). Line 1–2: vs today's 1 bp with 90% range. "
        "Line 3: vs a flat fee at the rule's own average fee.", fontsize=11.5, color=INK, va="bottom", transform=ax.transAxes)
cols = [eps_name.get(e, e) for e in eps_list]
cells, colors = [], []
for p in pols:
    row, crow = [], []
    for e in eps_list:
        t = res[e][p]["test"]
        if p == "vanilla":
            row.append(f"{t['lp_pnl']:,.0f}"); crow.append(INK)
        else:
            lo, hi = t["edge_vs_vanilla_ci90"]
            fv = edge_vs_flat(p, e)
            fline = "" if fv is None else (f"\nvs flat {res[e]['flat_' + p]['params']['fee_test'] * 1e4:.2f} bp: {sgn(fv[0])} "
                                           f"[{sgn(fv[1])} to {sgn(fv[2])}]")
            row.append(f"{t['lp_pnl']:,.0f}".replace("-", "−") + f"   {sgn(t['edge_vs_vanilla'])} vs today\n[{sgn(lo)} to {sgn(hi)}]\n"
                       f"avg fee {t['avg_fee_bps']:.2f} bp · kept {t['volume_kept_pct']:.0f}% of volume" + fline)
            crow.append("#1f7a4d" if lo > 0 else "#b5402f" if hi < 0 else INK2)
    cells.append(row); colors.append(crow)
tb = ax.table(cellText=cells, rowLabels=[POL[p][0] for p in pols], colLabels=cols, cellLoc="left", rowLoc="left",
              bbox=[0.17, 0, 0.83, 0.95])
tb.auto_set_font_size(False); tb.set_fontsize(8.6)
for (r, c), cell in tb.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor(SURF if r % 2 else "white")
    if r == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
    elif c >= 0:
        cell.set_text_props(color=colors[r - 1][c])
    else:
        cell.set_text_props(color=INK)

ax2 = fig.add_axes([0.04, 0.22, 0.92, 0.13]); ax2.set_axis_off()
ax2.text(0, 1.0, f"Both directions at today's 1 bp: fees, markout and LP profit ({T1})", fontsize=12, color=INK,
         va="bottom", transform=ax2.transAxes)
drows = []
for dr in (-1, 1):
    r = []
    for per in ("train", "test"):
        b = res[eps_list[0]]["vanilla"][per]["by_direction"][DKEY[dr]]
        r += [f"{b['fee_revenue']:,.0f}", sgn(b["markout_loss"]), f"{b['lp_pnl']:,.0f}"]
    drows.append(r)
tb2 = ax2.table(cellText=drows, rowLabels=[DIRS[d] for d in (-1, 1)],
                colLabels=["Fit: fees", "Fit: markout", "Fit: LP profit", "Test: fees", "Test: markout", "Test: LP profit"],
                cellLoc="right", rowLoc="left", bbox=[0.27, 0, 0.73, 0.88])
tb2.auto_set_font_size(False); tb2.set_fontsize(10)
for (r, c), cell in tb2.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor("white")
    if r == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
    elif c in (1, 4):
        cell.set_text_props(color="#1f7a4d" if not cell.get_text().get_text().startswith("−") else "#b5402f")

e2 = eps_list[min(1, len(eps_list) - 1)]
hook2, mk2 = res[e2]["oscillon_hook"]["test"], res[e2]["markout"]["test"]
fv_mk, fv_mh = edge_vs_flat("markout", e2), edge_vs_flat("markout_hook_poolfee", e2)
notes = ["What it means",
         f"• At 1 bp, LPs lost almost nothing to price moves over the year (markout {sgn(van_all.markout.sum())}): little toxic flow to defend against.",
         f"• A 3 bp base only pays if traders stay, whichever trigger it uses. At elasticity {float(e2):g} the oracle-triggered hook "
         f"costs LPs {sgn(hook2['edge_vs_vanilla'])}: arbitrage stays at 3 bp, ordinary flow leaves.",
         f"• Flat-fee control: the linear markout fee beats a flat fee at its own average by {sgn(fv_mk[0])} [{sgn(fv_mk[1])} to {sgn(fv_mk[2])}],"
         " so its gain comes from when and on which side it charges, not from charging more.",
         f"• The Oscillon curve with a markout trigger on a 1 bp base beats its flat control by {sgn(fv_mh[0])}, but is not clearly better"
         " than today: its 3 bp dead band rarely opens in calm months.",
         "Elasticity = how much ordinary flow leaves when the fee rises (assumed, not measured). Per-minute pool data; markout priced "
         "on Binance 5 min after each trade; hook fees use on-chain whole-bp rounding."]
for i, n in enumerate(notes):
    fig.text(0.04, 0.175 - i * 0.028, n, fontsize=12 if i == 0 else 10.5, color=INK if i < len(notes) - 1 else INK2,
             fontweight="bold" if i == 0 else "normal", va="top")
save(fig, "00_results_summary.png")

# ------------------------------------------------------------------ 1. how one swap is scored
fig, ax = plt.subplots(figsize=(13, 7.4)); ax.set_axis_off(); ax.set_xlim(0, 13); ax.set_ylim(0, 7.4)
fig.suptitle("How the backtest scores one swap for LPs, in each direction", x=0.06, ha="left", fontsize=15, color=INK)
ax.text(0, 7.05, "LP result = value of what the pool received − value of what it paid out, both priced on Binance 5 minutes later. "
        "The fee is included in what it received.", fontsize=10, color=INK2)


def box(x, y, w, h, title, lines, edge):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc="white", ec=edge, lw=1.4))
    ax.text(x + 0.15, y + h - 0.32, title, fontsize=10.5, fontweight="bold", color=INK)
    for i, ln in enumerate(lines):
        ax.text(x + 0.15, y + h - 0.68 - i * 0.33, ln, fontsize=9.5, color=INK2)


def arrow(x0, x1, y):
    ax.annotate("", xy=(x1, y), xytext=(x0, y), arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.4))


rows = [
    (4.25, DIRS[-1], "#e34948",
     [f"Sells 1,000,000 {T0}", f"Receives 999,800 {T1}", "(price 0.9999, fee 1 bp ≈ 100)"],
     [f"Gets 1,000,000 {T0}", f"Pays 999,800 {T1}"],
     [f"{T0} slips to 0.9995 {T1}", f"Pool's {T0} now worth 999,500"],
     ["999,500 − 999,800 = −300", "fee +100, markout −400", "Toxic: price fell after the sale"]),
    (1.15, DIRS[1], "#1baf7a",
     [f"Pays 1,000,200 {T1}", f"Receives 1,000,000 {T0}", "(price 1.0001, fee 1 bp ≈ 100)"],
     [f"Gets 1,000,200 {T1}", f"Pays 1,000,000 {T0}"],
     [f"{T0} still 1.0001 {T1}", f"{T0} paid out worth 1,000,100"],
     ["1,000,200 − 1,000,100 = +100", "fee +100, markout 0", "Benign: LP simply earns the fee"]),
]
for y, title, edge, trader, pool, later, result in rows:
    ax.text(0, y + 2.05, title, fontsize=12, fontweight="bold", color=INK)
    box(0.0, y, 2.9, 1.75, "1 · Trader", trader, GRID)
    arrow(2.95, 3.35, y + 0.9)
    box(3.4, y, 2.9, 1.75, "2 · Pool (LPs)", pool, GRID)
    arrow(6.35, 6.75, y + 0.9)
    box(6.8, y, 2.9, 1.75, "3 · Binance, 5 min later", later, GRID)
    arrow(9.75, 10.15, y + 0.9)
    box(10.2, y, 2.8, 1.75, "4 · LP result (USDT)", result, edge)
ax.text(0, 0.55, "Fee rules compared:  Vanilla = 1 bp on every swap.   Markout fee = 1 bp, raised for one direction while recent "
        "swaps that way lost LPs money.", fontsize=9.5, color=INK2)
ax.text(0, 0.2, f"Oscillon hook = 3 bp on every swap, plus a surcharge on {T0} sellers when Chainlink shows {T0} ≥ 3 bp below $1.   "
        "Surcharge on 1 bp = the same surcharge on top of today's 1 bp.", fontsize=9.5, color=INK2)
save(fig, "01_how_a_swap_is_scored.png")

# ------------------------------------------------------------------ 2. cumulative LP profit
fig, axes = plt.subplots(1, len(eps_list), figsize=(15, 5.2), sharey=True)
split_day = daily[daily.period == "test"].day.min()
for ax, e in zip(np.atleast_1d(axes), eps_list):
    d = daily[daily.elasticity == e].groupby(["policy", "day"]).lp_pnl.sum().reset_index()
    ends = []
    for p in pols:
        s = d[d.policy == p].sort_values("day")
        c = s.lp_pnl.cumsum()
        ax.plot(s.day, c, color=POL[p][1], lw=2, solid_capstyle="round")
        ends.append((c.iloc[-1], p))
    ax.axvline(split_day, color=INK2, ls=(0, (4, 4)), lw=1)
    ax.set_title(eps_name.get(e, f"Elasticity {e}"), loc="left", fontsize=11)
    ax.yaxis.set_major_formatter(k_fmt); ax.tick_params(axis="x", labelrotation=0)
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b\n%Y")); ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(interval=3))
for ax, e in zip(np.atleast_1d(axes), eps_list):        # end labels, pushed apart once the shared y-range is known
    lo, hi = ax.get_ylim(); gap = (hi - lo) * 0.045
    d = daily[daily.elasticity == e].groupby(["policy", "day"]).lp_pnl.sum().reset_index()
    ends = sorted((d[d.policy == p].lp_pnl.sum(), p) for p in pols)
    placed = []
    for v, p in ends:
        y = v if not placed else max(v, placed[-1] + gap)
        placed.append(y)
        ax.annotate(k_fmt(v), (d.day.max(), y), xytext=(4, 0), textcoords="offset points", va="center",
                    fontsize=8.5, color=INK, annotation_clip=False)
for ax in np.atleast_1d(axes):
    lo, hi = ax.get_ylim()
    ax.text(split_day, hi, "  test →", va="top", fontsize=8.5, color=INK2)
    ax.text(split_day, hi, "← fit  ", va="top", ha="right", fontsize=8.5, color=INK2)
np.atleast_1d(axes)[0].set_ylabel("Cumulative LP profit (USDT)")
handles = [plt.Line2D([], [], color=POL[p][1], lw=2.5) for p in pols]
fig.legend(handles, [POL[p][0] for p in pols], loc="lower center", ncol=len(pols), frameon=False, bbox_to_anchor=(0.5, -0.06))
fig.suptitle(f"Cumulative LP profit, {daily.day.min():%b %Y} – {daily.day.max():%b %Y}", x=0.06, y=1.0, ha="left", fontsize=14)
fig.text(0.06, 0.92, "Markout fee was fitted on the first 60% of days (left of the dashed line) and frozen. The Oscillon hook "
         "uses its on-chain formula as coded, with no fitting.", fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.82, wspace=0.12)
save(fig, "02_cumulative_lp_profit.png")

# ------------------------------------------------------------------ 3. test-period LP profit split by direction
fig, axes = plt.subplots(2, len(eps_list), figsize=(15, 7), sharex="col")
for j, e in enumerate(eps_list):
    for i, dr in enumerate((-1, 1)):
        ax = axes[i, j]
        vals = [res[e][p]["test"]["by_direction"][DKEY[dr]] for p in pols]
        y = np.arange(len(pols))[::-1]
        net = [v["lp_pnl"] for v in vals]
        ax.set_axisbelow(True)
        ax.barh(y, net, color=[POL[p][1] for p in pols], height=0.6)
        ax.axvline(0, color=INK2, lw=1)
        ax.set_yticks(y); ax.set_yticklabels([POL[p][0] for p in pols] if j == 0 else [])
        ax.xaxis.set_major_formatter(k_fmt); ax.grid(axis="y", visible=False)
        for yy, v in zip(y, vals):
            ax.annotate(f"{k_fmt(v['lp_pnl'])}  (fees {k_fmt(v['fee_revenue'])}, markout {k_fmt(v['markout_loss'])})",
                        (max(v["lp_pnl"], 0), yy), xytext=(4, 0), textcoords="offset points", va="center", fontsize=7.8, color=INK)
        lo, hi = ax.get_xlim(); ax.set_xlim(min(lo, 0), hi + (hi - min(lo, 0)) * 0.9)
        if i == 0:
            ax.set_title(eps_name.get(e, e), loc="left", fontsize=11)
        if j == 0:
            ax.set_ylabel(DIRS[dr].split("  ")[0], fontsize=11, color=INK, labelpad=10)
fig.suptitle(f"Where LP profit comes from: test period ({cfg['test_days']} days), split by trade direction",
             x=0.06, ha="left", fontsize=14)
fig.text(0.06, 0.93, "Bar = net LP profit in USDT. Markout below zero means traders in that direction moved the price against LPs "
         "within 5 minutes.", fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.85, hspace=0.25, wspace=0.05)
save(fig, "03_profit_by_direction.png")

# ------------------------------------------------------------------ 4. edge vs vanilla with 90% CI
others = [p for p in pols if p != "vanilla"]
fig, ax = plt.subplots(figsize=(11, 4.8))
yt, yl = [], []
for gi, e in enumerate(eps_list):
    for pi, p in enumerate(others):
        t = res[e][p]["test"]; y = -(gi * (len(others) + 1) + pi)
        lo, hi = t["edge_vs_vanilla_ci90"]
        ax.plot([lo, hi], [y, y], color=POL[p][1], lw=2.5, solid_capstyle="round")
        ax.plot(t["edge_vs_vanilla"], y, "o", ms=8, color=POL[p][1], mec="white", mew=1.5)
        verdict = "better" if lo > 0 else "worse" if hi < 0 else "not clear"
        ax.annotate(f"{sgn(t['edge_vs_vanilla'])}  ({verdict})", (hi, y), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8.5, color=INK)
        yt.append(y); yl.append(f"{eps_name.get(e, e).split(' · ')[0]} · {POL[p][0]}")
ax.axvline(0, color=INK, lw=1)
ax.set_yticks(yt); ax.set_yticklabels(yl, fontsize=9); ax.grid(axis="y", visible=False)
ax.xaxis.set_major_formatter(k_fmt); ax.set_xlabel("Extra LP profit vs vanilla over the test period (USDT); line = 90% interval")
lo, hi = ax.get_xlim(); ax.set_xlim(lo, hi + (hi - lo) * 0.18)
ax.set_title(f"Is each rule better than today's 1 bp? Test period, {cfg['test_days']} days", loc="left", fontsize=13)
save(fig, "04_edge_vs_vanilla.png")

# ------------------------------------------------------------------ 5. market context: Binance vs Chainlink, hook trigger
ref = pd.read_csv(os.path.join(a.data, "ref.csv")); ref["day"] = pd.to_datetime(ref.ts, unit="s").dt.floor("D")
orc = pd.read_csv(os.path.join(a.data, "oracle.csv")) if os.path.exists(os.path.join(a.data, "oracle.csv")) else None
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 6.4), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
rd = ref.groupby("day").mid.agg(["mean", "min", "max"])
ax1.fill_between(rd.index, (rd["min"] - 1) * 1e4, (rd["max"] - 1) * 1e4, color="#2a78d6", alpha=0.15, lw=0)
ax1.plot(rd.index, (rd["mean"] - 1) * 1e4, color="#2a78d6", lw=1.8, label=f"Binance {T0}/{T1} (daily mean, band = min–max)")
if orc is not None:
    orc["day"] = pd.to_datetime(orc.ts, unit="s").dt.floor("D")
    od = orc.groupby("day").price.mean()
    ax1.plot(od.index, (od - 1) * 1e4, color="#eb6834", lw=1.8, label=f"Chainlink {T0}/USD (daily mean)")
    ax1.axhline(-3, color="#eb6834", ls=(0, (4, 4)), lw=1, label="Hook surcharge starts (Chainlink −3 bp)")
ax1.axhline(0, color=INK2, lw=1)
ax1.set_ylabel("bp away from 1.0000"); ax1.legend(frameon=False, loc="lower left", fontsize=9)
sw = pd.read_csv(os.path.join(a.data, "swaps.csv")); sw["day"] = pd.to_datetime(sw.ts, unit="s").dt.floor("D")
if orc is not None:
    sw["oracle"] = pd.merge_asof(pd.DataFrame({"ts": sw.ts - 1}), orc[["ts", "price"]], on="ts")["price"].values
    sw["notional"] = sw.a0
    drain = (sw.dir < 0) & ((1 - sw.oracle) * 1e4 >= 3)
    share = sw.assign(dn=np.where(drain, sw.notional, 0)).groupby("day").agg(dn=("dn", "sum"), n=("notional", "sum"))
    ax2.bar(share.index, share.dn / share.n * 100, color="#eb6834", width=1.0)
    ax2.set_ylabel(f"% of volume\nsurcharged")
ax2.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %Y"))
fig.suptitle(f"What the market did: {T0} vs {T1}, and when the Oscillon hook would charge extra", x=0.06, ha="left", fontsize=14)
dmin = ref.loc[ref.mid.idxmin()]
fig.text(0.06, 0.92, f"No lasting depeg. Binance swung about ±10 bp (low {(dmin.mid - 1) * 1e4:+.0f} bp on "
         f"{pd.to_datetime(dmin.ts, unit='s'):%b %-d, %Y}). Chainlink sat 0–5 bp under $1, "
         "a level the hook reads as drain pressure.", fontsize=9.5, color=INK2)
fig.subplots_adjust(top=0.86, hspace=0.12)
save(fig, "05_market_and_hook_trigger.png")

# ------------------------------------------------------------------ 6. monthly LP markout by direction, vanilla
e0 = eps_list[0]
v = daily[(daily.elasticity == e0) & (daily.policy == "vanilla")].copy()
v["month"] = v.day.dt.to_period("M").dt.to_timestamp()
m = v.groupby(["month", "dir"])[["fee_rev", "markout", "lp_pnl"]].sum().reset_index()
fig, ax = plt.subplots(figsize=(13, 5))
months = sorted(m.month.unique()); x = np.arange(len(months)); wbar = 0.38
for k, (dr, col) in enumerate(((-1, "#e34948"), (1, "#1baf7a"))):
    mm = m[m.dir == dr].set_index("month").reindex(months).fillna(0)
    ax.bar(x + (k - 0.5) * wbar, mm.markout, width=wbar - 0.03, color=col, label=f"Markout · {DIRS[dr].split('  ')[0]}")
    ax.plot(x + (k - 0.5) * wbar, mm.fee_rev, "_", ms=14, mew=2.5, color=INK)
ax.plot([], [], "_", ms=14, mew=2.5, color=INK, label="Fees earned (same direction)")
ax.axhline(0, color=INK2, lw=1)
ax.set_xticks(x); ax.set_xticklabels([pd.Timestamp(t).strftime("%b\n%y") for t in months])
ax.yaxis.set_major_formatter(k_fmt); ax.set_ylabel("USDT per month"); ax.grid(axis="x", visible=False)
ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.14), fontsize=9)
ax.set_title("Which direction hurts LPs? Monthly markout at today's 1 bp fee, by trade direction", loc="left", fontsize=13,
             pad=26)
ax.text(0, 1.025, "Below zero = traders that way left LPs worse off 5 min later. The losing side flips from month to month.",
        transform=ax.transAxes, fontsize=9.5, color=INK2)
save(fig, "06_monthly_markout_by_direction.png")

# ------------------------------------------------------------------ 7. Oscillon hook fee by depeg
import backtest as _bt


def _onchain_fee_bps(dev: float, k: int = 45) -> float:
    """Integer path of OscillonFeePolicy.sol (select_fee_pips / 100): truncates depeg and each surcharge leg."""
    d = int(dev)
    if d < 3:
        return 3.0
    ex = d - 3
    piece = 1 if d <= 3 else (10_000 + 204 * ex * ex) // 10_000 if d <= 20 else min((10_000 + 204 * 289 + 1100 * (d - 20)) // 10_000, 100)
    quad = min(1 + (k * ex * ex) // 10_000, 100)
    return float(min(3 + max(piece, quad), 100))


devs = np.linspace(0, 100, 1001)
float_fee = np.where(devs >= 3, 3 + _bt._hybrid_surcharge_bps(devs, 45), 3.0)
chain_fee = np.array([_onchain_fee_bps(d) for d in devs])
fig, (ax, axt) = plt.subplots(1, 2, figsize=(14, 5.6), gridspec_kw={"width_ratios": [1.6, 1]})
ax.plot(devs, float_fee, color="#eb6834", lw=2, label="Backtest fee (float, select_fee_bps)")
ax.step(devs, chain_fee, where="post", color=INK, lw=1.2, ls=(0, (4, 3)), label="On-chain fee (integer, select_fee_pips)")
if orc is not None:
    seen = np.maximum(0, (1 - orc.price) * 1e4).max()
    ax.axvspan(0, seen, color="#2a78d6", alpha=0.12, lw=0)
    ax.text(seen + 1, 30, f"Depeg Chainlink showed\n{daily.day.min():%b %Y}–{daily.day.max():%b %Y}: 0–{seen:.1f} bp",
            fontsize=9, color=INK2, va="center")
for d in (10, 20, 50):
    f = 3 + float(_bt._hybrid_surcharge_bps(np.array([d]), 45)[0])
    ax.plot(d, f, "o", ms=7, color="#eb6834", mec="white", mew=1.5)
    ax.annotate(f"{d} bp depeg → {f:.2f} bp fee", (d, f), xytext=(8, -14), textcoords="offset points", fontsize=9, color=INK)
ax.set_xlabel(f"{T0} depeg on the oracle (bp below $1)"); ax.set_ylabel("Fee on a drain swap (bp)")
ax.set_xlim(0, 100); ax.set_ylim(0, 50); ax.legend(frameon=False, loc="upper left", fontsize=9)
axt.set_axis_off()
rows = [[f"{d:g}", f"{3 + float(_bt._hybrid_surcharge_bps(np.array([d]), 45)[0]) if d >= 3 else 3:.2f}", f"{_onchain_fee_bps(d):.0f}"]
        for d in (0, 3, 5, 7, 10, 15, 20, 25, 30, 50, 100)]
t = axt.table(cellText=rows, colLabels=["Depeg", "Backtest fee", "On-chain fee"], cellLoc="right",
              bbox=[0.05, 0.02, 0.95, 0.9])
t.auto_set_font_size(False); t.set_fontsize(10)
for (r, c), cell in t.get_celld().items():
    cell.set_edgecolor(GRID); cell.set_facecolor("white" if r % 2 else SURF)
    if r == 0:
        cell.set_text_props(color=INK2, fontweight="bold")
axt.text(0.05, 0.96, "All values in bp. Drain swaps only; every other swap pays 3 bp.", fontsize=9.5, color=INK2, transform=axt.transAxes)
fig.suptitle("Oscillon hook fee by depeg: 3 bp base + hybrid surcharge (k = 45, max 100 bp)", x=0.06, ha="left", fontsize=14)
fig.subplots_adjust(top=0.88, wspace=0.08)
save(fig, "07_hook_fee_by_depeg.png")
