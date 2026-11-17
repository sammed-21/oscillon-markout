"""
One chart: where the LPs' swap-side loss on the bot's trades went (Binance 12 s after each trade).
Every bar is a row of out/bot_value_reconciliation.csv.

  python3 chart_value_split.py --out out --png out/value_split.png
"""
import argparse, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
r = pd.read_csv(os.path.join(a.out, "bot_value_reconciliation.csv")).set_index("item").usd
g = lambda pre: float(r[[i for i in r.index if i.startswith(pre) and "12 s later" in i][0]])
lp = -g("Fynd LPs, swap side")
fee = g("  Fynd fee paid")
parts = [("Pools the bot hedged on", g("  other venues")), ("Bot, before gas", g("  bot, gross")),
         ("Fynd fee: back to LPs (80%)", 0.8 * fee), ("Fynd fee: protocol (20%)", 0.2 * fee), ("Router fees", g("  router fee"))]
BG, TEXT, TEXT2, MUTED, GRID, BAR = "#ffffff", "#1f1f1e", "#4a4a47", "#7a7a75", "#e6e5e0", "#d95926"
fig = plt.figure(figsize=(10, 4.6), dpi=150, facecolor=BG)
ax = fig.add_axes([0.30, 0.14, 0.58, 0.62], facecolor=BG)
names = [p[0] for p in parts][::-1]; vals = [p[1] for p in parts][::-1]
ax.barh(names, vals, color=BAR, height=0.56)
for y, v in enumerate(vals):
    ax.text(v + lp * 0.01, y, f"${v:,.0f}  ({v / lp:.0%})", va="center", color=TEXT2, fontsize=10)
for s in ax.spines.values():
    s.set_visible(False)
ax.tick_params(colors=TEXT2, length=0, labelsize=10)
ax.xaxis.set_major_formatter(lambda v, _: f"${v:,.0f}")
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
ax.set_xlim(0, max(vals) * 1.3)
fig.text(0.03, 0.91, f"Most of what LPs gave up on bot trades went to the pools it hedged on", color=TEXT, fontsize=14, fontweight="bold")
fig.text(0.03, 0.85, f"LPs' swap-side loss on the bot's Fynd trades: ${lp:,.0f} at Binance 12 s later, split by where the tokens went "
         "inside each transaction", color=MUTED, fontsize=9.5)
fig.text(0.03, 0.04, "Tokens are conserved in each transaction, so the bars add up to the loss. This is an accounting of flows, not a "
         "statement of cause.", color=MUTED, fontsize=8.5)
fig.savefig(a.png, facecolor=BG)
print("wrote", a.png)
