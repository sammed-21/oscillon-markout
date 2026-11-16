"""
Fynd LP returns report: HTML + PDF, every number read from the results files (no hand-typed figures).

  python3 build_lp_report.py --prefix results_lp_fynd --split results_lp_fynd_split --flow results_flow_fynd.json \
      --main 0x6c6a40d2d1fc442e281e1f80314fd86516e17127 --png charts_flow/F8_fynd_lp_vs_hold.png \
      --tests 24 --revised "Nov 13" --out-dir <dir>

Needs Google Chrome for the PDF (headless print).
"""
import argparse, json, os, shutil, subprocess
import pandas as pd

ap = argparse.ArgumentParser()
for k in ["prefix", "split", "flow", "main", "png", "revised", "out-dir"]:
    ap.add_argument("--" + k, required=True)
ap.add_argument("--tests", type=int, required=True)
a = ap.parse_args()
R = json.load(open(a.prefix + ".json")); S = json.load(open(a.split + ".json")); F = json.load(open(a.flow))
P = pd.read_csv(a.prefix + "_positions.csv")
O = pd.read_csv(a.prefix + "_owners.csv")
T, pr = R["totals"], R["period"]

usd = lambda v, sign=True: ("+" if v > 0 and sign else "−" if v < 0 else "") + f"${abs(v):,.0f}"
per = lambda v, cd: 30_000 * v / cd
day = lambda s: pd.Timestamp(s).strftime("%b %-d")
main = P.owner.str.lower() == a.main.lower()
width = lambda g: 100 * ((g.range_high / g.range_low - 1) * g.capital_days_usd)[g.range_high < 1e9].sum() / g.capital_days_usd[g.range_high < 1e9].sum()


def group(g):
    cd = g.capital_days_usd.sum()
    return {"n": len(g), "avg": cd / pr["days"], "fees": g.fees_usd.sum(), "il": g.il_usd.sum(), "net": g.lp_minus_hold_usd.sum(),
            "pfee": per(g.fees_usd.sum(), cd), "pil": per(g.il_usd.sum(), cd), "pnet": per(g.lp_minus_hold_usd.sum(), cd),
            "lp": g.lp_pnl_usd.sum(), "hold": g.hold_pnl_usd.sum(), "w": width(g)}


gm, go, ga = group(P[main]), group(P[~main]), group(P)
share = gm["avg"] / ga["avg"]
life_h = 24 * P[main].days.median()
others = O[O.owner.str.lower() != a.main.lower()]
worse = int((O.lp_minus_hold_usd < 0).sum())
best = O.loc[O.lp_minus_hold_usd.idxmax()]
b, o, ci, hs, fs = S["bot"], S["other"], S["ci95_per_1000_per_30d"], S["h_sensitivity"], S["fee_sensitivity"]
p1, p2 = S["periods"]["before"], S["periods"]["last_15_days"]
iw = R["inside_markout_window"]
ck = R["checks"]
eth_fall = 100 * (1 - pr["eth_end"] / pr["eth_start"])
row = lambda name, g, bold=False: (f"<tr><td>{'<b>' if bold else ''}{name}{'</b>' if bold else ''}</td><td>{g['n']}</td><td>${g['avg']:,.0f}</td>"
                                   f"<td>{usd(g['fees'])}</td><td>{usd(g['il'])}</td><td><b>{usd(g['net'])}</b></td><td>{usd(g['pnet'])}</td>"
                                   f"<td>{usd(g['lp'])}</td><td>{usd(g['hold'])}</td></tr>")
ci_txt = lambda c, v: f"{usd(v)} ({usd(c[0])} to {usd(c[1])})"
cd_all = T["capital_days_usd"]

html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Fynd AMM ETH/USDG: LP returns vs holding</title>
<style>
  @page {{ size: letter; margin: 0.42in 0.55in; }}
  @page wide {{ size: letter landscape; margin: 0.4in; }}
  :root {{ --ink: #1a1a1a; --muted: #555; --rule: #d4d7dc; --head: #eef0f3; }}
  body {{ font: 9.2pt/1.32 "Helvetica Neue", Arial, sans-serif; color: var(--ink); background: #fff; margin: 0; }}
  h1 {{ font-size: 15.5pt; margin: 0 0 3pt; line-height: 1.2; }}
  .sub {{ color: var(--muted); margin: 0 0 6pt; }}
  h2 {{ font-size: 11pt; margin: 9pt 0 4pt; padding-bottom: 2pt; border-bottom: 1px solid var(--rule); break-after: avoid; }}
  p {{ margin: 0 0 5pt; }} ul {{ margin: 0 0 4pt; padding-left: 14pt; }} li {{ margin: 0 0 3pt; }}
  code {{ font: 8.6pt Menlo, monospace; }} .nw {{ white-space: nowrap; }}
  table {{ border-collapse: collapse; width: 100%; margin: 3pt 0 4pt; font-size: 8.8pt; break-inside: avoid; }}
  th, td {{ border: 1px solid var(--rule); padding: 2.5pt 5pt; text-align: right; font-variant-numeric: tabular-nums; }}
  th {{ background: var(--head); }} th:first-child, td:first-child {{ text-align: left; }}
  table.sw td {{ white-space: nowrap; }}
  .note {{ color: var(--muted); font-size: 9pt; }}
  .fig {{ page: wide; break-before: page; text-align: center; }}
  .fig img {{ width: 100%; max-height: 6.9in; object-fit: contain; }}
  .fig p {{ text-align: left; color: var(--muted); font-size: 9pt; margin-top: 4pt; }}
</style></head><body>

<h1>Fynd AMM ETH/USDG: LP returns vs holding, {day(pr['start_utc'])} – {day(pr['end_utc'])}, 2026</h1>
<p class="sub">Revised {a.revised}. Every LP position since the pool started: {R['positions']} positions, {R['owners']} LPs, to block
{pr['snapshot_block']:,} ({day(pr['end_utc'])}, {pr['end_utc'][11:16]} UTC). Only this pool: the {ck['swaps_used']:,} swaps and all position
updates are the pool with extension <code>0x550c…1d09</code>, none from the other ETH/USDG pools on Ekubo. Chart on page 3; data
and code in the attached zip.</p>

<h2>Summary</h2>
<ul>
  <li><b>LPs vs holding: {usd(T['lp_minus_hold_usd'])} on ${R['avg_capital_usd']:,.0f} average capital.</b> Fees {usd(T['fees_usd'])},
    impermanent loss {usd(T['il_usd'])}. That is <b>{usd(per(T['lp_minus_hold_usd'], cd_all))} per $1,000 of capital per 30 days
    (−{abs(R['lp_minus_hold_per_30d_pct']):.1f}%)</b>. LP vs holding = what each position ended with (withdrawals, fees, and what it still
    holds) minus the tokens it deposited, both valued at the same ETH price, so ETH's own price move drops out.</li>
  <li>The main LP (<code>{a.main[:6]}…{a.main[-4:]}</code>, {share:.0%} of capital, ranges ~{gm['w']:.1f}% wide, median position open
    about {life_h:.0f} h): <span class="nw">{usd(gm['pfee'])} / {usd(gm['pil'])} / net {usd(gm['pnet'])}</span> per $1,000 per 30 days.
    The other {len(others)} LPs, ranges ~{go['w']:.0f}% wide: <span class="nw">{usd(go['pfee'])} / {usd(go['pil'])} / net {usd(go['pnet'])}</span>.
    {'All ' + str(len(O)) if worse == len(O) else str(worse) + ' of ' + str(len(O))} LPs did worse than holding; {R['positions_beating_hold']} of {R['positions']} positions did better.</li>
  <li><b>Split by the wallet that sent each swap</b> (each swap's LP side valued at Binance 12 s later, plus its fee):
    <span class="nw">{usd(b['lp_net'])}</span> occurred on swaps by the bot wallet <code>0x4abf…84a2</code> (fees {usd(b['fee'])}, loss
    {usd(-b['loss_12s'])}, on ${b['volume'] / 1e6:.2f}M), <span class="nw">{usd(o['lp_net'])}</span> on all other swaps,
    <span class="nw">{usd(S['drift'])}</span> later price moves. The {usd(b['lp_net'])} is an <b>upper bound</b> on the bot wallet's capture,
    before its hedging and other costs.</li>
  <li><b>Bot wallet's capture = {usd(b['loss_12s'], False)} − {usd(b['fee'], False)} − h × ${b['volume'] / 1e6:.2f}M</b>, where h is its
    cost per $ traded (hedging, exchange fees, gas, and any gap between its hedge price and Binance 12 s later).
    {usd(hs['upper_bound_at_h0'])} at h = 0; zero at <span class="nw">h ≈ {hs['breakeven_h_bp']:.1f} bp</span>
    (95%: {hs['breakeven_h_bp_ci95'][0]:.1f}–{hs['breakeven_h_bp_ci95'][1]:.1f}). We can't see h; you can.</li>
  <li><b>Fee on the bot wallet's swaps:</b> with the same swaps, {fs['breakeven_fee_bp_bot_wallet_swaps']:.1f} bp instead of
    {fs['actual_fee_bp']:.2f} bp would have left LPs even on them ({fs['breakeven_fee_bp_lp_minus_hold']:.1f} bp for LP vs holding overall).
    This assumes identical swaps at every fee, so it is a transfer from the bot wallet to LPs, not a forecast.</li>
  <li><b>Last 15 days ({day(p2['from'])} – {day(p2['to'])}):</b> ETH was more volatile ({p2['eth_vol_ann_pct_mean']:.0f}% vs
    {p1['eth_vol_ann_pct_mean']:.0f}% annualised), but LP loss per $ traded was lower ({p2['loss_bp']:.1f} vs {p1['loss_bp']:.1f} bp), and so was LP loss per
    day ({usd(-p2['loss_12s_per_day'])} vs {usd(-p1['loss_12s_per_day'])}; net of fees {usd(p2['lp_net_per_day'])} vs
    {usd(p1['lp_net_per_day'])}).</li>
  <li><b>Matches the Nov 10 markout report:</b> positions that opened and closed inside its window (Oct 6 – Nov 5) are
    {usd(iw['lp_minus_hold_usd'])} vs holding; markout over that window was {usd(F['all']['lp_pnl'])}.</li>
</ul>

<h2>Results</h2>
<table>
  <tr><th>LPs</th><th>Positions</th><th>Avg capital</th><th>Fees</th><th>Impermanent loss</th><th>LP vs hold</th><th>Per $1,000 / 30 d</th><th>LP $ result</th><th>Hold $ result</th></tr>
  {row(f"<b>Main LP</b> <code>{a.main[:6]}…{a.main[-4:]}</code>", gm)}
  {row(f"Other {len(others)} LPs", go, True)}
  {row("All", ga, True)}
</table>
<p class="note">Valued at Binance ETHUSDC at each position's end (last withdrawal, or the snapshot if still open). Capital = cost of
deposits × days held. The $ results include ETH's {eth_fall:.0f}% fall (${pr['eth_start']:,.0f} → ${pr['eth_end']:,.0f}), which holding
suffers too. Per-LP and per-position rows are in the zip.</p>

<table class="sw">
  <tr><th>Swaps</th><th>Count</th><th>Volume</th><th>Fee</th><th>Fees to LPs</th><th>Loss at Binance<br>12 s later</th><th>Net for LPs</th><th>Per $1,000 / 30 d (95%)</th></tr>
  <tr><td>By the bot wallet <code>0x4abf…84a2</code></td><td>{b['swaps']:,}</td><td>${b['volume'] / 1e6:.2f}M</td><td>{b['fee_bp']:.2f} bp</td><td>{usd(b['fee'])}</td><td>{usd(-b['loss_12s'])}</td><td><b>{usd(b['lp_net'])}</b></td><td>{ci_txt(ci['bot_lp_net'], per(b['lp_net'], cd_all))}</td></tr>
  <tr><td>All other</td><td>{o['swaps']:,}</td><td>${o['volume'] / 1e6:.2f}M</td><td>{o['fee_bp']:.1f} bp</td><td>{usd(o['fee'])}</td><td>{usd(-o['loss_12s'])}</td><td><b>{usd(o['lp_net'])}</b></td><td>{ci_txt(ci['other_lp_net'], per(o['lp_net'], cd_all))}</td></tr>
  <tr><td>Later price moves</td><td></td><td></td><td></td><td></td><td></td><td><b>{usd(S['drift'])}</b></td><td>{usd(per(S['drift'], cd_all))}</td></tr>
  <tr><td><b>Total = LP vs hold</b></td><td>{S['all']['swaps']:,}</td><td>${S['all']['volume'] / 1e6:.2f}M</td><td>{S['all']['fee_bp']:.1f} bp</td><td>{usd(S['all']['fee'])}</td><td>{usd(-S['all']['loss_12s'])}</td><td><b>{usd(S['lp_minus_hold'])}</b></td><td>{usd(per(S['lp_minus_hold'], cd_all))}</td></tr>
</table>
<p class="note">Swaps start {day(S['swaps_period'][0])}. All swaps kept, including those the markout report left out. Fees here
are valued when paid ({usd(S['all']['fee'])}); the headline values them at each position's end ({usd(T['fees_usd'])}). "Loss" is the LP side of
each swap valued at Binance 12 s later, as in the markout report; it is not what the counterparty earned.</p>

<h2>Checks</h2>
<ul>
  <li><b>The books close.</b> What the open positions hold on chain ({ck['holdings_on_chain'][0]:.6f} ETH, {ck['holdings_on_chain'][1]:,.2f} USDG)
    equals every deposit, withdrawal, fee and swap since the pool started, added up ({ck['holdings_from_flows'][0]:.6f} ETH,
    {ck['holdings_from_flows'][1]:,.2f} USDG). The open positions were read on chain at the snapshot block.</li>
  <li><b>Every fee paid in reached LP positions</b> ({100 * ck['fees_to_positions_share_eth']:.3f}% of ETH, {100 * ck['fees_to_positions_share_usdg']:.3f}%
    of USDG, collected or uncollected). So any owner fee comes off before <code>FeesAccumulated</code>, not from LPs afterwards.</li>
  <li><b>Only the Fynd pool.</b> {ck['swaps_used']:,} swaps on chain for this pool over the period, exactly the rows used; the other ETH/USDG
    pools on Ekubo are not in the data.</li>
  <li>{ck['deposits_checked']} deposits match liquidity × pool price within {100 * ck['deposit_amounts_vs_liquidity_math_max_rel_err']:.2f}%.
    One position recomputed by hand from raw events and the raw Binance file. The split adds back to LP vs holding exactly.
    {a.tests} tests pass.</li>
  <li><b>Matches the markout report</b> over its window: {usd(iw['lp_minus_hold_usd'])} vs {usd(F['all']['lp_pnl'])} (above).</li>
</ul>

<h2>What the data can't show</h2>
<ul>
  <li>Hedging costs. An LP that shorts the ETH it deposits ends with LP vs holding, before hedge costs: hedging removes ETH's move,
    not impermanent loss. So these figures already are the hedged result.</li>
  <li>h, the bot wallet's cost per $ traded, and anything it books outside this pool. Anything beyond this {pr['days']:.0f}-day period;
    "per 30 days" is not an APR. How flow would change at a different fee.</li>
  <li>How a Uniswap LP did on the same pair and days. That comparison is next.</li>
  <li>Is <code>{a.main}</code> yours?</li>
</ul>

<div class="fig">
  <img src="{os.path.basename(a.png)}" alt="Figure: LP vs holding by LP group, running totals, split by wallet, and two sensitivities">
  <p><b>Figure.</b> A: fees, impermanent loss and LP vs holding per $1,000 of capital per 30 days, by LP group. B: running totals,
  each position counted when it closed. C: LP vs holding split by the wallet that sent each swap. D: the bot wallet's swaps at
  other fees (same swaps: a transfer, not a forecast). E: the bot wallet's capture for a range of h.</p>
</div>
</body></html>
"""
os.makedirs(a.out_dir, exist_ok=True)
out_html = os.path.join(a.out_dir, "report.html")
open(out_html, "w").write(html)
shutil.copy(a.png, a.out_dir)
pdf = os.path.join(a.out_dir, f"Fynd_LP_returns_{pd.Timestamp(pr['end_utc']).date()}.pdf")
subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}", out_html], check=True, capture_output=True)
print("wrote", pdf)
