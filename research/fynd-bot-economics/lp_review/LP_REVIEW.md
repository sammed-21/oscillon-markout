# Fynd ETH/USDG: LP returns review

Oct 2 – Nov 13 2026 (42.02 days), 179 LP positions. Built by `lp_review/build_lp_review.py` from the checked LP
report, the transaction-level re-check of the bot's trades (`audit/`) and the replays (`final/`). Evidence labels: **on-chain** (read
from logs or receipts), **calculated** (arithmetic on on-chain data with a stated price reference), **model** (replay; compare rows with
each other, not with history), **unconfirmed** (needs Fynd).

All "vs holding" figures compare each position with simply holding the tokens it deposited, valued at Binance at the position's end.

## 1. Are LPs paid for the risk they take?

**No, not in this period.** Fees covered **34.5%** of impermanent loss.

| | USD | per $1,000 per 30 days |
|---|---|---|
| fees to LPs (their 80% share) — *on-chain* | +$2,069 | +$80 |
| impermanent loss — *calculated* | −$5,993 | −$231 |
| **LPs vs holding** — *calculated* | **−$3,925** | **−$151** (−15.1%) |
| 95% range (day resampling) | | −$196 to −$121 |

- Average capital $18,500 (capital-days ÷ 42.02); −21.2% vs holding over the period.
- In plain USD (not vs holding) LPs were −$6,753; holding would have been −$2,829. ETH fell over the period, so
  both lost money; LPing lost more.
- Trend (LP net on trades, per day): −$107 a day to Oct 28, −$95 a day after, with fees
  per day down from $63 to $45 and ETH volatility up (46% → 57% annualised).
  Not a clear improvement.

## 2. Who bears the loss?

**One wallet.** `0x6c6a…7127` (Fynd's, per Edouard on Nov 12) holds 153 of 179 positions and
**81%** of the shortfall.

| group | positions | avg capital | fees | IL | vs holding | per $1,000 / 30 d | fees cover | typical range width* | typical hours open* |
|---|---|---|---|---|---|---|---|---|---|
| `0x6c6a…7127` | 153 | $10,530 | +$1,878 | −$5,075 | **−$3,197** | −$217 | 37% | 2.1% | 25 |
| all other LPs | 26 | $7,970 | +$190 | −$918 | **−$728** | −$65 | 21% | 17.6% | 294 |

\* capital-weighted median: the width and duration that the typical dollar sat in.

**The clearest difference is range width.** 88% of `0x6c6a…7127`'s capital sat in 1–3% ranges (median
position open ~6 hours); that bucket is −$2,814 of its −$3,197. 95% of the
other LPs' capital sat in 10–30% ranges held ~56 hours, losing −$65 per $1,000 per 30 days
against −$217 for `0x6c6a…7127`. A narrower range earns more fees per dollar while the price is inside it but
takes proportionally more impermanent loss, and every reset locks the loss in. In this period the extra fees did not pay for it.
The other LPs' narrow-range buckets hold under 5% of their capital, too little to test this within one wallet group; timing and
size also differ between the groups. Treat it as the leading explanation, not a proven cause.

By range width (`LP_RANGE_WIDTH.csv`):

| LP | range width | positions | share of capital | median hours | fees | IL | vs holding | per $1,000 / 30 d |
|---|---|---|---|---|---|---|---|---|
| `0x6c6a…7127` | under 1% | 94 | 12% | 0 | +$332 | −$715 | **−$383** | −$224 |
| `0x6c6a…7127` | 1–3% | 58 | 88% | 6 | +$1,546 | −$4,360 | **−$2,814** | −$217 |
| `0x6c6a…7127` | over 30% / full range | 1 | 1% | 693 | +$0 | −$0 | **−$0** | −$1 |
| other LPs | under 1% | 1 | 0% | 0 | +$0 | −$0 | **−$0** | n/m |
| other LPs | 1–3% | 10 | 3% | 8 | +$26 | −$39 | **−$13** | −$39 |
| other LPs | 3–10% | 6 | 1% | 10 | +$15 | −$34 | **−$19** | −$220 |
| other LPs | 10–30% | 8 | 95% | 56 | +$145 | −$839 | **−$694** | −$65 |
| other LPs | over 30% / full range | 1 | 1% | 400 | +$5 | −$6 | **−$2** | −$12 |

By wallet (`LP_WALLET_RETURNS.csv`):

| wallet | ownership | positions | avg capital | fees | IL | vs holding | per $1,000 / 30 d | fees cover | typical width* | typical hours* | shares a tx sender with |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `0x6c6a…7127` | Fynd's, per Edouard (Nov 12) | 153 | $10,530 | +$1,878 | −$5,075 | **−$3,197** | −$217 | 37% | 2.1% | 25 |  |
| `via 0x0db5…ecd5` | unresolved | 1 | $5,562 | +$75 | −$586 | **−$511** | −$66 | 13% | 17.6% | 294 |  |
| `0xf94e…e85d` | unresolved | 3 | $1,653 | +$60 | −$218 | **−$158** | −$68 | 27% | 10.3% | 841 | 0x6572…cb3e |
| `0x6572…cb3e` | unresolved | 15 | $299 | +$40 | −$72 | **−$32** | −$76 | 56% | 2.1% | 168 | 0xf94e…e85d |
| `0xa90f…d950` | unresolved | 3 | $316 | +$10 | −$32 | **−$22** | −$51 | 30% | 14.0% | 54 |  |
| `0xed9a…8855` | unresolved | 2 | $36 | +$1 | −$3 | **−$3** | n/m | 19% | 14.0% | 119 |  |
| `0x56eb…7000` | unresolved | 1 | $103 | +$5 | −$6 | **−$2** | −$12 | 73% | 101.0% | 400 |  |
| `0x22f4…096a` | unresolved | 1 | $0 | +$0 | −$0 | **−$0** | n/m | 2% | 0.8% | 0 |  |

n/m: under $50 average capital, too small for a per-$1,000 figure.

*Unconfirmed:* whether `0x6c6a…7127` is Fynd's own liquidity (on chain it acts as an LP and sends no bot trades), and whether
wallets sharing a transaction sender are one LP.

## 3. Which trading flow does the loss come from?

**Mostly the bot's flow, because it pays LPs almost nothing for it.** The checked report splits the −$3,925
exactly into three parts (`LP_FLOW_ATTRIBUTION.csv`):

| flow | volume | fee LPs got | LPs' loss before fees (12 s) | fees cover | LP net | per $1,000 / 30 d (95% range) |
|---|---|---|---|---|---|---|
| Fynd's bot | $4.48M (83%) | 1.4 bp, +$615 | 9.0 bp, −$4,037 | 15% | **−$3,422** | −$132 (−$175 to −$109) |
| everyone else | $0.93M (17%) | 15.8 bp, +$1,470 | 20.2 bp, −$1,873 | 78% | **−$403** | −$16 (−$37 to +$6) |
| later price moves | | | | | −$100 | |
| **total** | | | | | **−$3,925** | |

- Everyone else's flow roughly pays for itself (its 95% range includes zero). The bot's flow does not: it pays 1.4 bp,
  LPs would need about **9.0 bp** to break even on it.
- *Calculated.* The transaction-level re-check of 24,199 of the bot's 24,258 trades gives −$3,423
  (12 s) and −$2,947 (at execution); the figure depends on the valuation time, the bot's profit does not.
- This is LVR: LPs lose it to whoever brings the pool back to the market. Before fees an outside arbitrageur realizes about the same
  (−$5,201 vs −$4,927 in the replay, *model*). It is **not** the bot's profit.

## 4. Is the rebalancing efficient?

**It aligns the pool, but most of what LPs give up on its trades goes to the pools it hedges on; the bot keeps about 9%.**

- Moves the pool toward Binance on **97.9%** of trades (*calculated*).
- Bot: +$739 before gas, gas −$443, **+$295 after gas** (*on-chain token flows and receipts*;
  matches the bot contract's own profit events).
- Where the $3,423 LPs gave up on the bot's trades went (12 s, *calculated*; adds up to the cent):

  | to | USD | share |
  |---|---|---|
  | pools the bot hedged on (their swap fees ~$899, price impact ~$472, price differences and moves) | $2,355 | 69% |
  | gas | $443 | 13% |
  | bot, after gas | $295 | 9% |
  | routers | $178 | 5% |
  | 20% fee share (recipient *unconfirmed*) | $151 | 4% |

  The pools' figure is not their profit: it is valued at Binance 12 s later and includes price moves.

## 5. What would improve LP returns? (*model*)

Replays of the same month; compare rows with each other. Higher fees help LPs but leave the pool further from the market:

| replay | LPs before fees | fees to LPs | LPs vs holding | gap to market | unfilled orders |
|---|---|---|---|---|---|
| real history (Fynd's bot arbitrages) | −$4,927 | +$1,487 | −$3,440 | 9 bp | 0 ETH |
| outside arbitrageur at the normal fee | −$5,201 | +$3,657 | −$1,543 | 13 bp | 17 ETH |
| no arbitrage at all (not realistic) | −$2,947 | +$837 | −$2,110 | 114 bp | 70 ETH |

Bot-policy replays (`final/MECHANISM_RECOMMENDATIONS.md`; this model's bot earns more than the real one):

| policy | LPs' trading net (12 s) | bot net | gap to market |
|---|---|---|---|
| today's rules (model baseline) | −$3,442 | +$803 | 9.2 bp |
| hedge at 1 bp instead of 3.9 bp | −$3,072 | +$1,096 | 7.8 bp |
| hedge at 1 bp, bot pays 4 bp to the pool | −$2,378 | +$836 | 8.9 bp |
| same, bot always on | −$2,349 | +$1,204 | 5.4 bp |
| bot pays the normal 19.8 bp | −$1,647 | +$389 | 16.8 bp |
| bot pays nothing | −$4,156 | +$946 | 8.3 bp |

The lever that helps everyone is **cheaper hedging** (the deepest on-chain pool costs ~0.3 bp vs ~4.3 bp today). Only then raise
the bot's fee to 3–4 bp: without cheaper hedging a higher fee makes the bot trade less and the pool staler. Two LP-side levers need
no mechanism change: **wider ranges and fewer resets** for `0x6c6a…7127` (§2; not replayed), and the protocol's 20% (giving it to LPs is a transfer, not a fix).

## Not established

- Who owns `0x6c6a…7127` and the other LP wallets (Edouard's Nov 12 statement is the only source for `0x6c6a…7127`).
- Where the 20% fee share goes.
- Gas on the bot wallet's 844 other transactions (~$13–15, estimated).
- How traders and routers would react to any change (replays hold them fixed).
