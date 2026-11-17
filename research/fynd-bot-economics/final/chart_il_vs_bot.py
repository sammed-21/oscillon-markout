"""
One PNG, two panels, from final/data/il_attribution.json and final/data/reconcile.json (same numbers as IL_VS_BOT_CAPTURE.md):
  top:    where the LPs' net loss on the bot's swaps went; what the bot kept
  bottom: LPs vs holding in three replays: real history, no arbitrage, an outside arbitrageur paying the normal fee

  python3 final/chart_il_vs_bot.py --root . --lp ../markout-backtest --png final/il_vs_bot_capture.png
"""
import argparse, csv, json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
F = lambda *p: os.path.join(a.root, "final", *p)
IA = json.load(open(F("data", "il_attribution.json"))); RC = json.load(open(F("data", "reconcile.json")))
SP = json.load(open(os.path.join(a.lp, "results_lp_fynd_split.json")))
C = {r["item"].strip(): float(r["usd"]) for r in csv.DictReader(open(F("VALUE_FLOW_RECONCILIATION.csv"))) if r["usd"]}
g = lambda s: [v for k, v in C.items() if k.startswith(s) and "12 s later" in k][0]
wf = {w["step"][:2]: w["usd"] for w in RC["waterfall"]}
lp_net = -SP["bot"]["lp_net"]
gas, kept = IA["horizons"]["bot_gas_usd"], IA["horizons"]["bot_net_realized_usd"]
parts = [("Pools the bot hedged on", g("pools the bot hedged on")), ("Gas (paid to the chain)", gas),
         ("Bot kept, after gas", kept), ("Router fees", g("router fees")), ("Fynd's 20% of the bot's fee", -wf["2."] * 0.2)]
R = IA["replays"]

BG, TEXT, TEXT2, MUTED, GRID = "#fcfcfb", "#1f1f1e", "#4a4a47", "#7a7a75", "#e6e5e0"
ACC, NEUT, LOSS, FEE = "#d95926", "#b9b8b2", "#d95926", "#2a7ab0"
plt.rcParams.update({"font.size": 10})
fig = plt.figure(figsize=(11, 9.4), dpi=150, facecolor=BG)


def style(ax):
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=TEXT2, length=0, labelsize=10)
    ax.xaxis.set_major_formatter(lambda v, _: f"−${-v:,.0f}" if v < 0 else f"${v:,.0f}")
    ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)


# ---------------------------------------------------------------- top panel
ax = fig.add_axes([0.27, 0.585, 0.62, 0.27], facecolor=BG)
names = ["LPs' net loss on bot trades\n(Nov 13 report's upper bound)"] + [p[0] for p in parts]
vals = [lp_net] + [p[1] for p in parts]
cols = ["none"] + [ACC if p[0].startswith("Bot kept") else NEUT for p in parts]
y = list(range(len(vals)))[::-1]
for yy, v, c in zip(y, vals, cols):
    ax.barh(yy, v, color=c, height=0.6, edgecolor=TEXT2 if c == "none" else BG, lw=1.2 if c == "none" else 2)
    lab = f"${v:,.0f}" + ("" if c == "none" else f"  ({v / lp_net:.0%})")
    ax.text(v + lp_net * 0.012, yy, lab, va="center", color=TEXT if c == ACC else TEXT2, fontsize=10,
            fontweight="bold" if c == ACC else "normal")
ax.set_yticks(y); ax.set_yticklabels(names)
ax.get_yticklabels()[3].set_color(ACC); ax.get_yticklabels()[3].set_fontweight("bold")
style(ax); ax.set_xlim(0, lp_net * 1.22)
fig.text(0.03, 0.955, f"The bot kept ${kept:,.0f} of the ${lp_net:,.0f} LPs lost on its trades", color=TEXT, fontsize=14.5, fontweight="bold", parse_math=False)
fig.text(0.03, 0.925, "Fynd ETH/USDG, Oct 13 – Nov 13 2026. LPs' loss net of their fees, at Binance 12 s after each trade, split by where the tokens went.", color=MUTED, fontsize=9.5, parse_math=False)
fig.text(0.03, 0.902, f"Bot figures are its own token flows (they match its contract's profit events). Before gas it made ${IA['horizons']['bot_gross_realized_usd']:,.0f}.",
         color=MUTED, fontsize=9.5, parse_math=False)

# ---------------------------------------------------------------- bottom panel
ax2 = fig.add_axes([0.27, 0.11, 0.48, 0.30], facecolor=BG)
sc = [("Real history\n(Fynd's bot)", R["REAL"]), ("No bot,\nno other arbitrage", R["NO_BOT"]),
      ("Outside arbitrageur\npaying the normal fee", R["OUTSIDE"])]
yy = [2, 1, 0]
for y0, (nm, r) in zip(yy, sc):
    ex = r["lp_vs_hold_ex_fees_usd"]; fe = sum(r["lp_fees_usd"].values()); net = r["lp_vs_hold_usd"]
    ax2.barh(y0 + 0.17, ex, color=LOSS, height=0.32, edgecolor=BG, lw=1.5)
    ax2.barh(y0 - 0.17, fe, color=FEE, height=0.32, edgecolor=BG, lw=1.5)
    ax2.text(ex - 120, y0 + 0.17, f"−${-ex:,.0f}", va="center", ha="right", color=TEXT2, fontsize=9.5, parse_math=False)
    ax2.text(fe + 120, y0 - 0.17, f"+${fe:,.0f}", va="center", ha="left", color=TEXT2, fontsize=9.5, parse_math=False)
    tr = ax2.get_yaxis_transform()
    ax2.text(1.03, y0 + 0.2, f"net −${-net:,.0f}", transform=tr, va="center", ha="left", color=TEXT, fontsize=11, fontweight="bold", parse_math=False)
    ax2.text(1.03, y0 - 0.2, f"gap to market {r['mean_abs_gap_bp']:.0f} bp\nunfilled orders {r['external_eth_unfilled']:.0f} ETH", transform=tr,
             va="center", ha="left", color=MUTED, fontsize=8.5, linespacing=1.4)
ax2.axvline(0, color=TEXT2, lw=0.8)
ax2.set_yticks(yy); ax2.set_yticklabels([s[0] for s in sc])
style(ax2); ax2.set_xlim(-6900, 5000); ax2.set_ylim(-0.6, 2.6)
ax2.set_xticks([-6000, -4000, -2000, 0, 2000, 4000])
fig.text(0.03, 0.475, "Before fees, any arbitrage costs LPs about the same; the bot's low fee is the difference",
         color=TEXT, fontsize=14.5, fontweight="bold")
fig.text(0.03, 0.447, "Replay of the same month with the pool's real liquidity: LPs vs holding, per position.", color=MUTED, fontsize=9.5)
lx = 0.03
for col, lab in [(LOSS, "loss before fees"), (FEE, "fees paid to LPs (80% share)")]:
    fig.patches.append(matplotlib.patches.Rectangle((lx, 0.418), 0.012, 0.012, color=col, transform=fig.transFigure))
    fig.text(lx + 0.017, 0.418, lab, color=TEXT2, fontsize=9.5, va="bottom"); lx += 0.2
fig.text(0.03, 0.035, "Replays hold external traders' sizes and timing fixed, and the no-bot case assumes nobody else arbitrages: simplifications, "
         "not forecasts.\nA pool nobody arbitrages loses less on paper only by staying off the market (114 bp) and failing orders. "
         "Source: final/il_attribution.py, IL_VS_BOT_CAPTURE.md.", color=MUTED, fontsize=8.3, linespacing=1.5)
fig.savefig(a.png, facecolor=BG)
print("wrote", a.png)
