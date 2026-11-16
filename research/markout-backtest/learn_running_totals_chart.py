"""
A running-totals line chart, built one layer at a time: fees vs loss to price moves for Fynd's LPs.

Each numbered block adds one layer of the picture. Comment a block out and re-run to see what it does.

  python3 learn_running_totals_chart.py --daily results_lp_fynd_split_daily.csv --split results_lp_fynd_split.json --png charts_flow/F9_fynd_running_totals.png
"""
import argparse, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--daily", required=True); ap.add_argument("--split", required=True, help="results JSON from lp_split.py")
ap.add_argument("--png", required=True)
a = ap.parse_args()

# ---- 1. DATA: daily amounts -> running totals ------------------------------------------------------------------
# A running total is just the cumulative sum of the daily numbers. That is the whole trick behind this chart type.
d = pd.read_csv(a.daily, parse_dates=["day"]).set_index("day")
fees = d.fees.cumsum()                 # fees paid to LPs, added up day by day
loss = -d.loss_12s.cumsum()            # LP loss on each swap at Binance 12 s later (negative = lost)
net = fees + loss                      # the two together

# ---- 2. COLOURS: decide them once, by role ----------------------------------------------------------------------
# Surfaces and text are neutral. Only the two series get a hue (checked for colour-blind separation and contrast).
# Net gets the text colour: it is the total, not a third category.
BG, GRID = "#1a1a19", "#2e2e2b"
TEXT, TEXT2, MUTED = "#f0efec", "#c3c2b7", "#8f8e88"
C_FEES, C_LOSS = "#3987e5", "#d95926"
MONO = "DejaVu Sans Mono"              # numbers in a monospace font line up

# ---- 3. CANVAS: figure, one plot area, room for titles above and labels on the right -----------------------------
fig = plt.figure(figsize=(12, 6.6), dpi=150, facecolor=BG)
ax = fig.add_axes([0.07, 0.17, 0.72, 0.60], facecolor=BG)    # [left, bottom, width, height] as fractions of the figure

# ---- 4. THE LINES: thin (2 px), net slightly heavier because it is the answer -------------------------------------
ax.plot(fees.index, fees.values, color=C_FEES, lw=2, solid_capstyle="round")
ax.plot(loss.index, loss.values, color=C_LOSS, lw=2, solid_capstyle="round")
ax.plot(net.index, net.values, color=TEXT, lw=2.6, solid_capstyle="round")

# ---- 5. ZERO LINE AND GRID: recessive, so the data stays in front -----------------------------------------------------
ax.axhline(0, color=MUTED, lw=1, zorder=0)
ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
for s in ax.spines.values():           # no box around the plot
    s.set_visible(False)
ax.tick_params(colors=MUTED, length=0, labelsize=10, pad=8)
ax.yaxis.set_major_formatter(lambda v, _: "$0" if v == 0 else f"{'+' if v > 0 else '−'}${abs(v) / 1000:,.0f}k")
ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.TU))
ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
for t in ax.get_yticklabels() + ax.get_xticklabels():
    t.set_fontfamily(MONO)
ax.set_xlim(fees.index[0], fees.index[-1])

# ---- 6. DIRECT LABELS at the end of each line, instead of making the reader look up a legend -----------------------
# The text stays in text colours; a short coloured dash beside it says which line it is.
# If two ends are too close, push the lower label down so they don't overlap.
ends = sorted([(fees.iloc[-1], "Fees paid to LPs", C_FEES), (net.iloc[-1], "Net result", TEXT),
               (loss.iloc[-1], "Loss to price moves", C_LOSS)], key=lambda e: -e[0])
span = ax.get_ylim()[1] - ax.get_ylim()[0]
y_prev = None
for v, name, c in ends:
    y = v if y_prev is None else min(v, y_prev - 0.09 * span)
    y_prev = y
    x0 = ax.get_xlim()[1]
    ax.annotate("", xy=(x0, y), xytext=(14, 0), textcoords="offset points", annotation_clip=False,
                arrowprops=dict(arrowstyle="-", color=c, lw=3))
    sign = "+" if v > 0 else "−"
    ax.annotate(name, xy=(x0, y), xytext=(22, 6), textcoords="offset points", va="bottom", color=TEXT,
                fontsize=11, fontweight="bold", annotation_clip=False)
    ax.annotate(f"{sign}${abs(v):,.0f}", xy=(x0, y), xytext=(22, -2), textcoords="offset points", va="top",
                color=TEXT2, fontsize=11, fontfamily=MONO, annotation_clip=False)

# ---- 7. HEADER: a title that states the finding, a subtitle that says what is plotted, a compact legend --------------
fig.text(0.07, 0.92, "Fees came in every day. Price moves took more.", color=TEXT, fontsize=17, fontweight="bold")
d0, d1 = fees.index[0], fees.index[-1]
fig.text(0.07, 0.875, f"RUNNING TOTALS FOR FYND ETH/USDG LIQUIDITY PROVIDERS, {d0:%d %B} TO {d1:%d %B %Y}".upper(),
         color=MUTED, fontsize=9.5, fontfamily=MONO)
x = 0.07
for name, c in [("Fees paid to LPs", C_FEES), ("Loss to price moves", C_LOSS), ("Net result", TEXT)]:
    fig.add_artist(plt.Line2D([x, x + 0.02], [0.825, 0.825], color=c, lw=3, transform=fig.transFigure))
    fig.text(x + 0.026, 0.825, name, color=TEXT2, fontsize=10, va="center")
    x += 0.026 + 0.0075 * len(name) + 0.03

# ---- 8. CAPTION: one or two plain sentences on how to read it ----------------------------------------------------------
drift = json.load(open(a.split))["drift"]
fig.text(0.07, 0.065, "Each line adds up one part of what LPs earned or lost, day by day. \"Loss to price moves\" values the "
         "tokens each swap left LPs with at Binance 12 seconds later.", color=MUTED, fontsize=9.5)
fig.text(0.07, 0.035, f"Add the price moves after those 12 seconds (−${abs(drift):,.0f}, not drawn) and you get the impermanent loss.",
         color=MUTED, fontsize=9.5)

# ---- 9. SAVE ---------------------------------------------------------------------------------------------------------
fig.savefig(a.png, facecolor=BG)
print("wrote", a.png)
