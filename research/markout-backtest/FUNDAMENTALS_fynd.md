# Fynd LP research from first principles

For you, not for sending. Every number is from this pool. If you understand sections 1–6, you can derive every answer
in the reports yourself.

## 1. What an LP actually owns

An LP lends the pool two tokens, ETH and USDG. The pool will trade with anyone at its formula price. So the LP's
position is a portfolio that **rebalances itself**: as ETH falls, traders sell ETH into the pool, so the LP ends up
holding more ETH; as ETH rises, the LP ends up holding more USDG.

That rebalancing always goes the wrong way. You keep buying the thing that is falling and selling the thing that is
rising. That cost is **impermanent loss (IL)**. Fees are what the LP is paid for taking it.

## 2. The one equation

    LP − hold = fees + impermanent loss

- **hold** = the tokens you deposited, kept in your wallet.
- **LP** = what you got back (withdrawals + fees) plus what is still in the pool.
- Value both at the **same** ETH price. ETH's own move (which hits both sides equally) cancels. What's left is only what
  the pool did to you.

Real example, the position held via `0x0db596af` (tested by hand in `test_lp.py`):

| | ETH | USDG | at ETH $2,189.88 |
|---|---|---|---|
| Deposited (= hold) | 3.983 | 10,596 | $19,318 |
| Got back (principal) | 8.554 | 0 | $18,732 |
| Fees | 0.014 | 44 | $75 |
| **LP** | | | **$18,807** |

LP − hold = −$511 = fees +$75 + IL −$586. ETH fell through the range, so the pool sold all the LP's USDG for ETH on
the way down. In dollars the LP lost $1,419, but $908 of that is just ETH falling, which holding would also have lost.

## 3. Why IL happens: the pool's price is always late

The pool doesn't know the market price. Binance moves first, and for a moment the pool's price is stale. Someone trades
the gap: buys from the pool below the market, or sells to it above. Each such trade, the LP sells at the stale price
and loses the gap. The fee gets back part of it.

That's what the **markout** report measured swap by swap: LP gain or loss = what the pool got vs. what it gave,
valued at Binance 12 s later. **Markout and LP-vs-hold are two lenses on the same money.** Every token that leaves or
enters the pool between deposit and withdrawal is a swap, so adding up the swaps (marked to price) plus the fees gives
LP − hold. That's why they match:

- Markout, Oct 6 – Nov 5: **−$3,196**
- LP vs hold, positions opened and closed inside that window: **−$3,108**

92% of the markout loss is already there at trade time (0 s). The pool was behind Binance *before* the swap. This is
LVR (loss-versus-rebalancing): the cost of quoting a price that is always slightly behind.

## 4. Concentration is leverage

A range 1.6% wide puts all of your money into that 1.6%. Per dollar, it's much more liquidity than a wide range, so
per dollar it earns **more fees and loses more IL**, in proportion. What decides the sign is the ratio:

| | fees per $1k / 30 d | IL per $1k / 30 d | fees ÷ IL | net |
|---|---|---|---|---|
| Main LP, ~1.6% ranges | +$126 | −$342 | 0.37 | **−$217** |
| Other LPs, ~16% ranges | +$17 | −$76 | 0.22 | **−$59** |

If fees ÷ IL is below 1, concentrating only makes you lose faster. The fix is never "pick a better range". It's
"make fees bigger relative to IL": higher fees on the flow that causes IL, or a pool price that lags less.

The main LP re-centres its range about once an hour (median position life ~1 hour, 150 positions). Each re-centre
locks in the IL so far.

## 5. Who gets the LPs' loss: capture vs lag (revised after Edouard's pushback, Nov 11)

My first version said "86% of the loss went to your bot". Edouard said the bot didn't capture that much. He was
right, and the reason is worth understanding.

A swap's loss to LPs, valued at Binance, has separate parts. Example: the pool says $2,010, Binance says $2,000.
The bot sells ETH into the pool and moves it to $2,005, not all the way to $2,000.

- **Capture.** Along the curve, the bot's average price is ~$2,007.5. Valued at $2,005, where it left the pool, it
  gained $2.5 per ETH. That's all the bot "sees", if it thinks its own target price is fair.
- **Lag.** The pool is still $5 above Binance after the trade. LPs just bought ETH at a price that's stale by $5.
  Nobody books that, unless the trader hedges at Binance.
- **After.** Whatever Binance does in the next 12 s.

Measured, Oct 6 – Nov 11 (`lp_split.py`, F8 panels C and D):

| | Fees | Capture | Pool lag | After 12 s |
|---|---|---|---|---|
| Fynd's bot (1.38 bp fee, $3.9M) | +$539 | −$757 (1.94 bp) | −$2,558 | −$396 |
| Other traders (16.3 bp fee, $0.87M) | +$1,422 | −$659 | −$1,094 | −$32 |

Plus drift −$155 (later moves). All of it adds up to LP − hold, −$3,690.

- **The bot nets +$218 in its own terms** ($757 capture − $539 fees) over 35 days, before its costs elsewhere.
- **The big number is the pool lag, −$3,652.** After a bot trade, the pool is still a median 5.4 bp off Binance, on
  the same side 99% of the time. Its price best matches Binance from **~15 s earlier**. The bot moves the pool toward a
  price that's about 15 s old.
- Ruled out: Binance noise (smoothing the price barely changes it) and a wrong chain clock (within ~1.5 s of real time).

So the lever isn't the bot's fee. It's **how stale the bot's target price is**. A pool that trails the market by 15 s
makes every trader, bot or not, trade against LPs at stale prices. That's what LPs pay for.

What I don't know: what price the bot targets and how it hedges. If it hedges at Binance-like prices, it books part of
the lag. If not, the lag is a pure cost of the pool trailing the market.

**The lesson:** "what LPs lost to a trader" (valued at Binance) and "what the trader captured" (valued at its own
prices) are different numbers. Never call the first one the second.

## 5b. Hedging doesn't make the loss go away

The objection you'll hear: "our LP hedges, so this isn't our P&L." Work it through:

- LP's dollar result = LP − cost. Holding's dollar result = hold − cost.
- An LP that shorts, at deposit, the ETH it deposits makes −(hold − cost) on the short.
- Add them: (LP − cost) − (hold − cost) = **LP − hold**.

So a hedged LP's result *is* LP − hold, minus the hedge's own costs (fees, funding). Hedging removes ETH's move, which
LP − hold already removes. It can't remove impermanent loss, because impermanent loss is the pool selling to arbs at
stale prices. Re-hedging during a position changes this a little; for 1-hour positions, not much.

## 5c. Is it real or noise? Error bars

One number from one period can be luck. To check, resample: draw 37 days at random, with replacement, from the 37
real days, add them up, and repeat 5,000 times. The middle 95% of those totals is the interval.

- Pool lag: −$200 to −$124 per $1,000 per 30 days. Entirely below zero, so it's real.
- The bot's own net (+$218): +$5 to +$14 per $1,000 per 30 days. Small but real.
- In the first version, other traders' total was −$36 to +$10. It crossed zero, so you couldn't say they cost LPs anything.

Rule: never say "X loses money" unless the interval excludes zero. This is what separates research from a dashboard.

## 5d. Internal vs external money

When two wallets belong to the same company, money between them is a **transfer**, not a profit or loss for the
company. Always ask, for every flow: who is on each side?

Money flows from LPs to whoever trades against them:

- LP → bot, both Fynd's: the bot's capture (+$218 net) is an internal transfer.
- Outside LPs → bot (Fynd): outside LPs pay for Fynd's rebalancing. A fairness question.
- LPs → nobody: the pool-lag part isn't anyone's revenue unless a trader hedges at Binance. It's a cost of the design.
  This is the biggest bucket here.

So "is 0x6c6a yours?" matters less than it did. "What price does the bot target?" matters more.

## 6. Units and why they're chosen

- **bp of volume** (markout report): loss per dollar traded. Good for comparing flows and fees.
- **$ per $1,000 of capital per 30 days** (LP report): what an LP actually cares about. Capital-days = money in the pool ×
  days it was there, so a position open 1 hour counts much less than one open 2 weeks.
- **−14.8% per 30 days is not "−180% APR".** It's one 40-day period in which ETH fell 24%; IL grows with how much the
  price moves. Never annualise it.

## 7. Why the numbers can be trusted (say these if challenged)

- **The books close.** The open positions hold, on chain, exactly what every deposit, withdrawal, fee and swap since
  launch adds up to: 2.841752 ETH and 9,103.62 USDG. Nothing is missing or double-counted.
- **Every fee paid in reached LPs**: 100.000%. So no owner cut is taken from LPs after `FeesAccumulated`.
- **Liquidity math** matches all 176 deposits within 0.05%.
- **One position by hand**, and the swap in the markout report's panel D, which you checked on Blockscout.
- **Volume** within 0.2% of GeckoTerminal. 22 tests pass.

## 8. Questions you might get

**Why compare with holding and not just "did LPs make money in USD"?**
ETH fell 24%, so almost anyone holding ETH lost money. LP − hold isolates what the *pool* did, which is what Fynd
controls.

**Why 12 seconds for markout?**
About how long it takes the market to "settle" after a swap. 0 s, 12 s and 60 s give −$4.3k, −$4.7k and −$4.7k, so the
choice barely matters.

**Why does fee timing matter (the bug you fixed)?**
The extension pays a swap's fee into the pool at the *next* interaction. Attributing it to the same transaction gave
each swap its neighbour's fee and mixed up who paid what. The totals barely moved; the split between bot and external
did.

**Why did 42 positions beat holding if the LPs lost overall?**
Short positions that happened to close when the price came back, or that earned a burst of fees. They're mostly the
main LP's 1-hour positions. Over many positions the loss shows up.

**Why is your TVL different from GeckoTerminal?**
Ours is exact: it's what the positions hold on chain. GeckoTerminal is ~15% lower on both days checked. Leaving out
the one position that is out of range (all ETH) gets within 4%, so they probably count only in-range liquidity. Not
confirmed.

**Is the Binance price the right reference?**
It's the deepest ETH market and the pool tracks CEX prices. A 1-second timing error is about 0.9 bp at 50% annual
volatility, small next to the −11 bp loss per swap.

**What would you recommend?**
Look at the bot's target price first. The pool trails Binance by ~15 s after the bot trades, and that lag is ~$3.65k
of the $3.69k LP loss. A fresher reference (or one that leads with the fastest venue) should cut it. How much needs a
simulation, which I haven't done. Fees don't fix lag; they only move money between the bot and LPs. And narrow ranges
lose faster per dollar under this flow, so a wider default range limits LP losses.

**"Our bot didn't capture that much."**
Correct: +$218 net in its own terms. The LP loss is mostly the pool trailing the market (see 5).

**"Our LP hedges."**
Then its result is LP − hold minus hedge costs; see 5b. Hedging removes ETH's move, not impermanent loss.

**"Is this just Binance being noisy?"**
No. Smoothing Binance over 5 s only changes the bot's lag term from −$2,558 to −$2,104, and the pool matches Binance
best ~15 s back, which noise wouldn't produce.

**What's not covered?**
Hedge costs, the bot's costs outside the pool, who controls the main LP, any period other than this one, how flow
would react to different fees, and a Uniswap comparison.

## 9. What to learn from this project

The lessons that carry over to any AMM, in the order they bit here:

1. **Reconcile before you interpret.** Two fee bugs shipped because nothing forced the numbers to add up. "The books
   close to the token" is now the first check, before any chart. Always build one identity that must hold exactly
   (holdings = sum of flows; fees out = fees in) and assert it in code.
2. **Read the raw logs before assuming the mechanism.** Fees are paid one interaction late. No doc said so; the log
   order and a correlation test did. Look at five raw transactions by hand before writing the classifier.
3. **Choose the benchmark before the metric.** "LPs lost $6k" is mostly ETH falling. LP − hold is the question a pool
   designer controls. Markout is the same money seen per swap. Know which lens answers which question.
4. **Ask who is on both sides of every flow, and at whose price.** "LPs lost $3.2k on the bot's trades" (at Binance)
   is not "the bot made $3.2k" (at its own prices: $218). Edouard caught this; check it yourself next time.
5. **Put error bars on anything you'll say out loud.** The outsider number looked like a loss; it isn't significant.
6. **Turn findings into a lever.** "LPs lose $148 per $1,000 a month" is a finding. "The bot's target price is ~15 s
   stale, and that lag is most of the loss" is something a team can act on.
7. **State what you assumed, next to the number.** Binance as truth; per 30 days isn't an APR.
8. **When the client pushes back, test their claim, don't defend yours.** Edouard's "the bot didn't capture that much"
   was testable in an hour, and testing it found the real story.

Theory worth reading, in this order: impermanent loss for concentrated liquidity (Uniswap v3 whitepaper, section 6);
LVR (Milionis, Moallemi, Roughgarden, Zhang, "Automated Market Making and Loss-Versus-Rebalancing", 2022); markout
as used in market-making (any "adverse selection / markout" note from a market-making desk); the bootstrap
(Efron & Tibshirani, chapter 1–2).
