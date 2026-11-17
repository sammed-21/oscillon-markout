# Fynd ETH/USDG: the LPs' loss against holding is not the bot's profit

Audience: Fynd's founders. Question raised by Fynd: *the bot did not capture that much; is the LPs' impermanent loss (made larger by
the bot's trades) being counted as the bot's gain?* Short answer: **it should not be, and in the rebuild it is not.** The bot kept
**+$739** before gas and **+$295** after gas (+$283 after every measurable cost), measured from its own token
flows and equal to its contract's own profit events (0.1807 ETH +
325.50 USDG). The Nov 13 LP report gave the LPs' $3,422 net loss on the bot's swaps as an
*upper bound* on the bot's capture. It is about 4.6× what the bot actually kept and should not be read as its profit.

## 1. The LPs' result against holding (Oct 2 – Nov 13, checked report)

| part | USD |
|---|---|
| on the bot's swaps: swap side at Binance 12 s | −$4,037 |
| on the bot's swaps: fees to LPs | +$615 |
| on everyone else's swaps: swap side | −$1,873 |
| on everyone else's swaps: fees to LPs | +$1,470 |
| price moves after the 12 s marks, until each position's exit | −$100 |
| **LPs vs holding** | **−$3,925** |

Almost all of the loss against holding is realized at the moment of a swap (the "price moves after" line is −$100).
That is how an AMM loses to holding: someone trades the pool to the market price, and the LPs sell low or buy high to them.

## 2. Where the LPs' $3,422 net loss on the bot's swaps went

Every bot transaction is an atomic round trip (sell to Fynd, buy back on another pool, or the reverse), so tokens are conserved and the LPs'
loss splits exactly between the parties to the transaction (Binance 12 s after, as above):

| who | USD | share of the LPs' net loss on the bot's swaps |
|---|---|---|
| the other on-chain pools the bot hedged on | $2,352 | 69% |
| the bot, gross | $739 | 22% |
| of which paid as gas | $443 | 13% |
| of which the bot kept (net) | $295 | 9% |
| router fees | $178 | 5% |
| Fynd's 20% of the bot's fee | $152 | 4% |
| valuation residual (LPs' fee share as in the checked report vs the rebuild) | −$2 | |

The hedge pools' part is not profit kept by anyone in particular. Where it can be split (single direct hedges, Binance at execution)
about $899 is their swap fees; the rest is the bot's price impact on thin pools, those pools already sitting away from the
on-chain market, the on-chain/Binance basis and the market move over the next 12 s (`VALUE_FLOW_RECONCILIATION.csv`, section D).

The Nov 13 report's formula, capture = $4,037 − $615 − h × $4.48M, matches the bot's actual
gross at **h = 6.0 bp**: the bot's real cost of hedging, routing and Fynd's share per dollar traded. The upper bound assumed h = 0.

## 3. Did the bot's trades make the LPs' loss larger?

**Not by trading on noise.** If the bot traded on short-lived Binance jitter, the LPs' loss on its swaps would shrink as prices came back.
It does not shrink:

| LPs' swap side on the bot's 24,258 swaps, valued at Binance | USD |
|---|---|
| execution | −$3,561 |
| 12 s | −$4,037 |
| 60 s | −$4,031 |
| 5 min | −$3,731 |
| 30 min | −$3,834 |
| 1 h | −$3,583 |

The loss stays between $3,561 and $4,037 from execution to an hour later. The bot traded when Fynd's price was behind a market move that then persisted.

**Compared with no arbitrage, yes; compared with another arbitrageur, no.** Replay of Oct 13 – Nov 13 with the pool's real liquidity
(`final/il_attribution.py`, same pool model as the policy replays). LP vs holding is measured per position, fees added:

| | real history | no bot, no other arbitrage | outside arbitrageur paying the normal fee |
|---|---|---|---|
| LPs vs holding, before fees | −$4,927 | −$2,947 | −$5,201 |
| of which `0x6c6a…7127` (Fynd) | −$4,173 | −$2,277 | −$4,443 |
| of which all other LPs | −$754 | −$670 | −$758 |
| fees to LPs (80%) | +$1,487 | +$837 | +$3,657 |
| **LPs vs holding** | **−$3,440** | **−$2,110** | **−$1,543** |
| mean gap to Binance | 9.1 bp | 114 bp | 13.2 bp |
| external orders that could not fill (2% limit) | 0 ETH | 70 ETH | 17 ETH |
| arbitrageur's net | +$295 (real) | – | +$505 (model, upper bound) |

- **Against a pool nobody arbitrages**, the bot's trading realized about $1,980 more
  loss before fees over the month ($1,330 after the fees it paid), almost all on `0x6c6a…7127`'s positions. Independent LPs' result before fees is about the same in all three
  cases. A pool nobody arbitrages is not a better outcome. It sat 114 bp from the market on average and could not fill
  70 ETH of orders. Its loss is postponed and goes to whichever trader arrives first.
- **Against another arbitrageur**, the loss before fees is similar (−$5,201 vs −$4,927). Moving
  the pool to the market costs LPs about the same whoever does it. The difference is the fee: an outside arbitrageur paying the normal
  19.8 bp would have paid LPs $2,927 on its swaps; the bot's swaps paid LPs
  $615 (it is charged ~1.7 bp).

So the bot's trades are when the LPs' loss is realized, as any arbitrage's would be. The bot keeps a small part of it. The LPs' cost
of the bot, compared with another arbitrageur, is the low fee the bot pays, not a large profit it makes.

## What this changes

- Describe the bot's capture as **+$739 gross, +$295 after gas**. Do not use the Nov 13 upper bound ($3,422).
- Describe the LPs' loss on the bot's swaps as the cost of keeping the pool at the market price. Most of it went to the other pools
  the bot hedged on, through fees, price impact and their own mispricing.
- The recommendations (`MECHANISM_RECOMMENDATIONS.md`) still hold: cheaper hedging helps LPs and the bot together. A higher bot fee
  helps LPs once hedging is cheaper.

## Limits

The replays hold external traders' sizes and timing fixed, and the no-bot case assumes no one else would arbitrage. Both are
simplifications, not forecasts. The outside arbitrageur's profit comes from the replay's bot model, which overstates the real bot's
profit, so read it as an upper bound. In the replay, LP vs holding resets at each position's own deposit or withdrawal, and the window
starts on Oct 13, so it differs from the checked full-period −$3,925. Fees are not split by owner in the replay.
Window: 2026-10-13 11:47:37 – 2026-11-13 06:35:33 UTC.
