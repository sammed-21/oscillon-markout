"""
Write final/IL_VS_BOT_CAPTURE.md: the LPs' loss against holding, where it went, and how much of it the bot kept.
Every number is read from final/data/il_attribution.json, final/data/reconcile.json and the checked LP split.

  python3 final/write_il_note.py --root . --lp ../markout-backtest
"""
import argparse, json, os

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True)
a = ap.parse_args()
F = lambda *p: os.path.join(a.root, "final", *p)
IA = json.load(open(F("data", "il_attribution.json")))
RC = json.load(open(F("data", "reconcile.json")))
SP = json.load(open(os.path.join(a.lp, "results_lp_fynd_split.json")))
C = {r["section"] + "|" + r["item"]: r["usd"] for r in __import__("csv").DictReader(open(F("VALUE_FLOW_RECONCILIATION.csv")))}


def usd(v, sign=True):
    s = f"${abs(v):,.0f}"
    return ("−" if v < 0 else ("+" if sign else "")) + s if sign or v < 0 else s


def cval(part):
    k = [k for k in C if part in k]
    assert len(k) == 1, (part, k)
    return float(C[k[0]])


hz = IA["horizons"]; R = IA["replays"]; P = IA["params"]
bot_g, bot_n, gas = hz["bot_gross_realized_usd"], hz["bot_net_realized_usd"], hz["bot_gas_usd"]
wf = {w["step"][:2]: w["usd"] for w in RC["waterfall"]}
net_all = wf["9."]
b = SP["bot"]; o = SP["other"]
lp_net_bot = b["lp_net"]                                      # LPs' swap side at 12 s + their fees, on the bot's swaps
hedge12 = cval("pools the bot hedged on (Binance 12 s later)")
bot12 = cval("bot, gross (Binance 12 s later)")
fee12 = cval("Fynd fee (Binance 12 s later)")
router12 = cval("router fees (Binance 12 s later)")
lp_fee_bot = b["fee"]
proto_bot = -wf["2."] * 0.2                                   # Fynd's 20% of the bot's fee (exact per swap, rebuild)
resid = lp_net_bot + hedge12 + bot12 + router12 + proto_bot
h_match = (b["loss_12s"] - b["fee"] - bot_g) / b["volume"] * 1e4
hs = RC["hedge_split"]
hedge_fees = sum(v for k, v in hs.items() if k.startswith("fees charged"))
Rr, Rn, Ro = R["REAL"], R["NO_BOT"], R["OUTSIDE"]
grp = lambda r, g: r["lp_vs_hold_ex_fees_by_group_usd"][g]
fees = lambda r: r["lp_fees_usd"]["bot"] + r["lp_fees_usd"]["external"]
pct = lambda v: f"{100 * v / -lp_net_bot:.0f}%"

md = f"""# Fynd ETH/USDG: the LPs' loss against holding is not the bot's profit

Audience: Fynd's founders. Question raised by Fynd: *the bot did not capture that much; is the LPs' impermanent loss (made larger by
the bot's trades) being counted as the bot's gain?* Short answer: **it should not be, and in the rebuild it is not.** The bot kept
**{usd(bot_g)}** before gas and **{usd(bot_n)}** after gas ({usd(net_all)} after every measurable cost), measured from its own token
flows and equal to its contract's own profit events ({RC['bot_event_vs_reconstruction']['eth_event']:.4f} ETH +
{RC['bot_event_vs_reconstruction']['usdg_event']:,.2f} USDG). The Nov 13 LP report gave the LPs' {usd(-lp_net_bot, False)} net loss on the bot's swaps as an
*upper bound* on the bot's capture. It is about {-lp_net_bot / bot_g:.1f}× what the bot actually kept and should not be read as its profit.

## 1. The LPs' result against holding (Oct 2 – Nov 13, checked report)

| part | USD |
|---|---|
| on the bot's swaps: swap side at Binance 12 s | {usd(-b['loss_12s'])} |
| on the bot's swaps: fees to LPs | {usd(b['fee'])} |
| on everyone else's swaps: swap side | {usd(-o['loss_12s'])} |
| on everyone else's swaps: fees to LPs | {usd(o['fee'])} |
| price moves after the 12 s marks, until each position's exit | {usd(SP['drift'])} |
| **LPs vs holding** | **{usd(SP['lp_minus_hold'])}** |

Almost all of the loss against holding is realized at the moment of a swap (the "price moves after" line is {usd(SP['drift'])}).
That is how an AMM loses to holding: someone trades the pool to the market price, and the LPs sell low or buy high to them.

## 2. Where the LPs' {usd(-lp_net_bot, False)} net loss on the bot's swaps went

Every bot transaction is an atomic round trip (sell to Fynd, buy back on another pool, or the reverse), so tokens are conserved and the LPs'
loss splits exactly between the parties to the transaction (Binance 12 s after, as above):

| who | USD | share of the LPs' net loss on the bot's swaps |
|---|---|---|
| the other on-chain pools the bot hedged on | {usd(hedge12, False)} | {pct(hedge12)} |
| the bot, gross | {usd(bot12, False)} | {pct(bot12)} |
| of which paid as gas | {usd(gas, False)} | {pct(gas)} |
| of which the bot kept (net) | {usd(bot_n, False)} | {pct(bot_n)} |
| router fees | {usd(router12, False)} | {pct(router12)} |
| Fynd's 20% of the bot's fee | {usd(proto_bot, False)} | {pct(proto_bot)} |
| valuation residual (LPs' fee share as in the checked report vs the rebuild) | {usd(resid)} | |

The hedge pools' part is not profit kept by anyone in particular. Where it can be split (single direct hedges, Binance at execution)
about {usd(hedge_fees, False)} is their swap fees; the rest is the bot's price impact on thin pools, those pools already sitting away from the
on-chain market, the on-chain/Binance basis and the market move over the next 12 s (`VALUE_FLOW_RECONCILIATION.csv`, section D).

The Nov 13 report's formula, capture = {usd(b['loss_12s'], False)} − {usd(b['fee'], False)} − h × ${b['volume'] / 1e6:.2f}M, matches the bot's actual
gross at **h = {h_match:.1f} bp**: the bot's real cost of hedging, routing and Fynd's share per dollar traded. The upper bound assumed h = 0.

## 3. Did the bot's trades make the LPs' loss larger?

**Not by trading on noise.** If the bot traded on short-lived Binance jitter, the LPs' loss on its swaps would shrink as prices came back.
It does not shrink:

| LPs' swap side on the bot's {hz['n_bot_swaps']:,} swaps, valued at Binance | USD |
|---|---|
""" + "\n".join(f"| {k} | {usd(v)} |" for k, v in hz["lp_swap_side_on_bot_swaps_usd"].items()) + f"""

The loss stays between {usd(-max(hz['lp_swap_side_on_bot_swaps_usd'].values()), False)} and {usd(-min(hz['lp_swap_side_on_bot_swaps_usd'].values()), False)} from execution to an hour later. The bot traded when Fynd's price was behind a market move that then persisted.

**Compared with no arbitrage, yes; compared with another arbitrageur, no.** Replay of Oct 13 – Nov 13 with the pool's real liquidity
(`final/il_attribution.py`, same pool model as the policy replays). LP vs holding is measured per position, fees added:

| | real history | no bot, no other arbitrage | outside arbitrageur paying the normal fee |
|---|---|---|---|
| LPs vs holding, before fees | {usd(Rr['lp_vs_hold_ex_fees_usd'])} | {usd(Rn['lp_vs_hold_ex_fees_usd'])} | {usd(Ro['lp_vs_hold_ex_fees_usd'])} |
| of which `0x6c6a…7127` (Fynd) | {usd(grp(Rr, '0x6c6a...7127'))} | {usd(grp(Rn, '0x6c6a...7127'))} | {usd(grp(Ro, '0x6c6a...7127'))} |
| of which all other LPs | {usd(grp(Rr, 'all other LPs'))} | {usd(grp(Rn, 'all other LPs'))} | {usd(grp(Ro, 'all other LPs'))} |
| fees to LPs (80%) | {usd(fees(Rr))} | {usd(fees(Rn))} | {usd(fees(Ro))} |
| **LPs vs holding** | **{usd(Rr['lp_vs_hold_usd'])}** | **{usd(Rn['lp_vs_hold_usd'])}** | **{usd(Ro['lp_vs_hold_usd'])}** |
| mean gap to Binance | {Rr['mean_abs_gap_bp']:.1f} bp | {Rn['mean_abs_gap_bp']:.0f} bp | {Ro['mean_abs_gap_bp']:.1f} bp |
| external orders that could not fill (2% limit) | {Rr['external_eth_unfilled']:.0f} ETH | {Rn['external_eth_unfilled']:.0f} ETH | {Ro['external_eth_unfilled']:.0f} ETH |
| arbitrageur's net | {usd(bot_n)} (real) | – | {usd(Ro['arbitrageur_net_usd'])} (model, upper bound) |

- **Against a pool nobody arbitrages**, the bot's trading realized about {usd(Rn['lp_vs_hold_ex_fees_usd'] - Rr['lp_vs_hold_ex_fees_usd'], False)} more
  loss before fees over the month ({usd(Rn['lp_vs_hold_usd'] - Rr['lp_vs_hold_usd'], False)} after the fees it paid), almost all on `0x6c6a…7127`'s positions. Independent LPs' result before fees is about the same in all three
  cases. A pool nobody arbitrages is not a better outcome. It sat {Rn['mean_abs_gap_bp']:.0f} bp from the market on average and could not fill
  {Rn['external_eth_unfilled']:.0f} ETH of orders. Its loss is postponed and goes to whichever trader arrives first.
- **Against another arbitrageur**, the loss before fees is similar ({usd(Ro['lp_vs_hold_ex_fees_usd'])} vs {usd(Rr['lp_vs_hold_ex_fees_usd'])}). Moving
  the pool to the market costs LPs about the same whoever does it. The difference is the fee: an outside arbitrageur paying the normal
  {P['outside_fee_bp']:.1f} bp would have paid LPs {usd(Ro['lp_fees_usd']['bot'], False)} on its swaps; the bot's swaps paid LPs
  {usd(Rr['lp_fees_usd']['bot'], False)} (it is charged ~1.7 bp).

So the bot's trades are when the LPs' loss is realized, as any arbitrage's would be. The bot keeps a small part of it. The LPs' cost
of the bot, compared with another arbitrageur, is the low fee the bot pays, not a large profit it makes.

## What this changes

- Describe the bot's capture as **{usd(bot_g)} gross, {usd(bot_n)} after gas**. Do not use the Nov 13 upper bound ({usd(-lp_net_bot, False)}).
- Describe the LPs' loss on the bot's swaps as the cost of keeping the pool at the market price. Most of it went to the other pools
  the bot hedged on, through fees, price impact and their own mispricing.
- The recommendations (`MECHANISM_RECOMMENDATIONS.md`) still hold: cheaper hedging helps LPs and the bot together. A higher bot fee
  helps LPs once hedging is cheaper.

## Limits

The replays hold external traders' sizes and timing fixed, and the no-bot case assumes no one else would arbitrage. Both are
simplifications, not forecasts. The outside arbitrageur's profit comes from the replay's bot model, which overstates the real bot's
profit, so read it as an upper bound. In the replay, LP vs holding resets at each position's own deposit or withdrawal, and the window
starts on Oct 13, so it differs from the checked full-period −$3,925. Fees are not split by owner in the replay.
Window: {P['window_utc'][0]} – {P['window_utc'][1]} UTC.
"""
open(F("IL_VS_BOT_CAPTURE.md"), "w").write(md)
print(md)
