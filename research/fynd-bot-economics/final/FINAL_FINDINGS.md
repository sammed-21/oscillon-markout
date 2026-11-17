# Fynd ETH/USDG: final findings

Audience: Fynd's founders. Scope: Fynd's ETH/USDG pool on Robinhood Chain; LP results Oct 2 – Nov 13, 2026; bot trades Oct 13 – Nov 13.
Builds on `BOT_ECONOMICS_REPORT.md` (unchanged). Labels: **observed** (read from chain logs), **calculated**, **inferred**, **assumed**, **unresolved**.

## Answers

1. **Independent LPs vs holding.** Independent LPs (every LP other than `0x6c6a…7127`) lost **$728** against holding: fees +$190, impermanent loss −$918, on an average $7,970 of capital, i.e. −9.1% over the 42 days, −6.5% per 30 days. Their ownership is *unresolved* (no on-chain link to Fynd found). `0x6c6a…7127` (Fynd, per Edouard, Nov 12) lost $3,197 (−21.7% per 30 days). All LPs: −$3,925.
2. **Fynd's owner fee.** About **$521** over Oct 2 – Nov 13: 20% of $2,607 of fees. The bot paid $760 of those fees (so $152 of the owner fee came from Fynd's own bot); everyone else $1,847. The 80/20 split is observed on 22,186 of 22,202 checkable fee payments, including all 2,426 that include external traders' fees.
3. **Bot net profit.** **$283** after every measurable cost (+$739 gross trading P&L, −$443 gas, −$13 estimated gas on non-trade transactions, +$0.08 on the 59 incomplete ones). Marked to the Nov 13 ETH price: $218.
4. **Why ~5 bp short.** It trades until the next unit stops paying. After a trade the median gap to Binance is 5.1 bp, made of: 2.5 bp between Fynd and the hedge pool (≈ the 2.6 bp of fees on the next unit), 1.8 bp of the bot's own impact on the hedge pool, 0.9 bp because the hedge pool already sat away from the on-chain market, and −1.1 bp of on-chain/Binance basis.
5. **Why the LVR advantage narrowed.** The ratio is low only while the pool had no active arbitrage: the bot started on Oct 13 and paused for 54 h on Oct 15–17. On days with the bot idle under 2 hours the ratio is 0.86 before Oct 22 and 0.94 after, close to Uniswap's ~0.95 both times. The shift is at Oct 17, not Oct 22; it coincides with the bot running continuously, LP ranges widening and depth halving. These moved together, so the data cannot separate them.
6. **Most promising change.** **Hedge on the deepest pool, then charge the bot more.** The bot never used Uniswap's WETH/USDG 0.01% pool; on 95% of its trades that pool was cheaper (0.3 bp vs 4.3 bp against Binance). In the replay, hedging at 1 bp and charging the bot 4 bp gives LPs −$2,378 instead of −$3,442 while the bot still nets +$836 (+$803 under today's rules in the same model).

## 1. The accounting, reconciled

Bot P&L (`BOT_PNL_WATERFALL.csv`; 24,199 complete transactions, Binance at execution unless stated):

| step | USD | type |
|---|---|---|
| Price edge captured (Fynd vs hedge price, before fees) | +$1,676 | gross, realized |
| − Fynd fee paid by the bot | −$760 | cost (80% to LPs, 20% to Fynd) |
| − router fees | −$178 | cost |
| **= Gross trading P&L** | **+$739** | gross, realized |
| − gas on these trades | −$443 | cost, observed |
| **= Net realized (the reported $295)** | **+$295** | net, realized |
| + the 59 incomplete transactions | +$0.08 | net, realized |
| − gas on 844 non-trade transactions | −$13 | estimate (assumed) |
| **= Net after all measurable costs** | **+$283** | net, realized |
| ETH profits revalued to the Nov 13 price | −$65 | unrealized |
| = Net, marked to Nov 13 | +$218 | realized + unrealized |

How the other bot figures relate:
- **$739** in the replay table is the same gross trading P&L (step 4).
- **$725** in the earlier value split is the same gross without the Nov 13 trades, which have no on-chain reference price
  ($724.95; those trades made $13.60), and with ETH valued at the on-chain price instead of Binance ($724.84). Fewer trades and a
  different price, not a different result.
- At Binance 12 s later the gross is +$739 (the bot holds only its tiny profit, so the move barely matters).
- The bot contract's own on-chain profit figures add up to exactly the rebuilt amounts: 0.180656 ETH and
  325.50 USDG.

Fees:
- **The $2,069 LP fee income is the LPs' 80% share**, not gross fees. Every FeesAccumulated payment (the LP share) reached positions
  (checked report, 100.000%). Valued when paid it is $2,086; the $17 difference is valuation timing.
- Gross fees = $2,607; Fynd's 20% = **$521** (*calculated*, using the share read from the extension's events).
- The split holds for external traders too (*observed*). The extension charges them on their **output**: a trader receiving USDG gets less
  than the pool paid out, while the bot is charged on its input. That made 2,434 external fees directly observable
  ($893, 20.5 bp volume-weighted), and every one of the 2,426 LP fee payments that include them
  equals exactly 80% (all checkable payments: 22,186 of 22,202). Fees on external swaps that receive ETH are native ETH and cannot be observed.
- The "~1.4 bp bot fee" is the LPs' share of the bot's fee: the bot pays 1.70 bp volume-weighted (0.50 bp median,
  1.01 bp simple mean); 80% of 1.70 = 1.36 bp reaches LPs.

## 2. Who is who

| role | address | evidence | label |
|---|---|---|---|
| Fynd's bot, per Edouard (Nov 12) | `0x6c6a…7127` | Fynd's statement; on chain this wallet is the largest LP (153 positions) and an EIP-7702 wallet; it sent 11 multi-pool swaps and no bot trade | confirmed by Fynd (as relayed); role on chain: LP |
| Fynd's bot, per the user (Nov 11) | `0x4abf…84a2` | sends every one of the 24,258 bot trades; registered in the bot contract at deployment | confirmed by the user |
| Transaction sender | `0x4abf…84a2` | sender of every trade; pays all gas | observed |
| Execution contract | `0x7ea0…acc7` | target of every trade; emits a profit event per trade; trades only pools that use Fynd's extension | observed |
| Owner / controller | `0xd7c8…1c80` until block 111,842,342, then `0x0d41…d4b2` | OwnershipTransferred events | observed |
| Economic beneficiary | `0xd7c8…1c80` | received the bot contract's USDG profits: 3 withdrawals, 382.78 USDG in total; it then traded them on Fynd's pools | observed (USDG); ETH withdrawals unobservable |
| LP position owners | `0x6c6a…7127` and 2 other groups | position NFTs | observed |

The bot contract trades only pools whose swaps are locked through Fynd's extension (`0x550cfe12…`): ETH/USDG and three tokenized-stock pools
(6 pools use the extension). Together with Edouard's confirmation that Fynd runs a bot, this makes Fynd the likely operator of
`0x4abf…`/`0x7ea0…` too (*inferred*). No USDG or WETH transfer links `0x6c6a…7127` to the bot's wallets (native ETH cannot be checked).

LP results by owner group (*calculated* from the checked positions file):

| group | positions | avg capital | LP vs hold | per 30 days | ownership |
|---|---|---|---|---|---|
| 0x6c6a...7127 (Fynd, confirmed by Edouard Nov 12) | 153 | $10,530 | −$3,197 | −21.7% | confirmed (Fynd) |
| held through contract 0x0db596af (owner unresolved) | 1 | $5,562 | −$511 | −6.6% | unresolved |
| other EOAs (ownership unresolved) | 25 | $2,408 | −$217 | −6.4% | unresolved |
| **all except 0x6c6a** | | $7,970 | **−$728** | **−6.5%** | unresolved |

If `0x6c6a` is Fynd's, $3,197 of the $3,925 LP loss is Fynd's own, and much of the bot's trading is
between two Fynd wallets.

## 3. What the 58% to hedge pools is

On the bot's swaps, Fynd LPs' swap side was −$4,028 at Binance 12 s. Exact shares: hedge pools 58.39%, bot 18.33%,
Fynd fee 18.87%, router fees 4.41% (sum 100.00%: the parts add up; the residual is $0.05, the fee being valued at the 12 s
price). The earlier "58 + 18 + 19 + 4 = 99" was rounding.

For hedges that are one direct ETH/USDG swap and have an on-chain reference price, the hedge pools' result splits exactly (`VALUE_FLOW_RECONCILIATION.csv`, section D):

| part | USD | what it is | kept by the hedge pool? |
|---|---|---|---|
| fees to their LPs | +$662 | the pools' swap fee | yes |
| fees to their protocols | +$189 | protocol cut of the fee | yes (protocol) |
| fees, split unknown | +$47 | non-standard pools | yes |
| price impact | +$472 | the bot moving thin pools | only if not reversed later |
| pool price vs on-chain market | +$406 | the hedge pool was already off | only if not reversed later |
| on-chain/Binance basis | −$299 | valuation at Binance | no: a measurement effect |
| **= at execution** | **+$1,477** | | |
| Binance move in the next 12 s | +$425 | market movement | no: valuation |
| other bot trades (multi-hop, or Nov 13), 12 s, not split | +$450 | | unknown |

So the 58% is not profit kept by other pools. About $899 is fee income; impact and the pools' own
deviation are gains marked to Binance that the next arbitrage may take back; the rest is basis and 12-second price movement.
From the bot's side this is its **execution shortfall**: 4.2 bp of hedge notional against Binance.

The Fynd side splits the same way: Fynd's price vs the on-chain market before the trade −$4,669, basis +$316,
Fynd's own curve +$852; total −$3,501 at execution.

## 4. The ~5 bp stop

Exact split of the post-trade gap (22,413 single-hedge trades; medians, bp; signed so + = Fynd still on the side it started):

| | all | bot sells ETH into Fynd | bot buys ETH from Fynd |
|---|---|---|---|
| gap to Binance after the trade | 5.1 | 5.0 | 5.1 |
| = basis (on-chain vs Binance) | −1.1 | −2.8 | 1.6 |
| + hedge pool vs on-chain market, before | 0.9 | 1.8 | 0.6 |
| + bot's impact on the hedge pool | 1.8 | 2.9 | 1.6 |
| + Fynd vs hedge pool, after | 2.5 | 2.5 | 1.3 |
| marginal fees (hedge + Fynd + router) | 2.6 | 3.2 | 1.9 |

(Medians of parts need not add to the median of the whole; for each trade they add exactly, max error 5e-12 bp.)

- **Fees explain the last leg.** What is left between Fynd and the hedge pool is within 1 bp of the marginal fees on 69% of
  trades and within 2 bp on 88%. The bot trades until the next unit no longer pays (*inferred* from this match; its code is not visible).
- **The rest is hedge quality and basis.** The bot's own impact on thin hedge pools (~1.8 bp) and those pools sitting off the market
  (~0.9 bp) make up most of the remaining gap. Against the on-chain market rather than Binance, Fynd is left
  7.8 bp off when it was above and 3.5 bp when it was below: the 2.6 bp basis shifts the band, it is not misalignment.
- **Reaction speed.** While the bot was active, the chance it traded in a given second was about
  7% even with Fynd 10–12 bp off Binance. Active seconds with a gap of 8 bp or more and no trade:
  267,331 (median gap to the on-chain market then 11.3 bp). Whether that is polling, competition for
  block space or the hedge pools being off too cannot be seen.
- **Failed attempts.** 844 of the EOA's 36,024 transactions were not successful trades; their content cannot be
  read on this RPC, so they say nothing about the decision rule (*not measurable*).
- 792 trades earned less than their gas; the median trade grossed $0.031.

## 5. The LVR ratio over time

See `LVR_CHANGEPOINT_ANALYSIS.md`. In short: loss/LVR is 0.48 before Oct 22 and 0.88 after; split at Oct 17 it is
0.42 and 0.88. The low early figure comes from days with no bot (it started Oct 13) or a paused one. A pool nobody arbitrages
is stale and books less loss than the theory, which assumes continuous arbitrage; that is not protection. No extension or configuration change
was found (0xd59d72ec: 52,903 events from the extension; the per-block event's fields never changed).

## 6. Hedge execution

`HEDGE_ROUTE_COSTS.csv` has every route. Totals: hedge notional $4,477,209, hedge cost $1,876 = 4.19 bp against
Binance. For single direct hedges the cost is fee 2.09 bp + impact 1.19 bp + hedge pool off the
on-chain market 1.04 bp + basis −0.86 bp (means).

| route | trades | hedge cost bp (vw) | same trades on the 0.01% pool, bp |
|---|---|---|---|
| `uniswap_v4:0x24107d15` | 8,576 | 4.15 | 2.39 |
| `uniswap_v4:0x84bd4e2d` | 7,335 | 3.61 | -1.49 |
| `uniswap_v3:0x69bfaf19` | 2,610 | 4.77 | -1.55 |
| `uniswap_v3:0x16679e2a` | 2,305 | 0.52 | -0.33 |
| `uniswap_v4:0xa5d2fa75+uniswap_v4:0xf399bd15` | 650 | 5.82 | 3.03 |
| `uniswap_v3:0x76159260` | 784 | 0.92 | 0.45 |
| `uniswap_v3:0xfae65eaa` | 400 | 0.93 | -1.15 |
| `uniswap_v4:0xe1ae6a4c+uniswap_v3:0xddcbba36` | 215 | 5.34 | -1.57 |

- **The deepest pool was never used.** The bot hedged 23,543 trades on other pools; the Uniswap v3 WETH/USDG 0.01% pool, at its price and
  liquidity just before each trade, would have cost 0.31 bp instead of 4.26 bp ($137 vs $1,864), cheaper on
  95% of trades. *Calculated counterfactual*: assumes the pool's state is still available inside the same block and ignores other
  traders' reaction. Why the router skipped it is not visible on chain.
- **Cheap routes already exist in the bot's set.** Three non-standard 0.01% pools (`0x16679e2a`, `0x76159260`, `0xfae65eaa`) cost
  0.68 bp on the
  3,489 trades routed there; the two main v4 pools cost 3.6–4.2 bp. The router's choice, not the pool menu, drives the cost.
- **Splitting.** Impact on the hedge pools cost $486; two equally deep venues would roughly halve it
  ($243), before the extra hop's gas. On the 0.01% pool impact is close to zero at these sizes, so splitting matters less.
- **Netting.** Opposite trades within 60 s: 1,435 pairs, $199,788 that could offset, saving
  $102 of hedge cost, at a price risk of about $0.11 per pair (std). Small.
- **Batching** would save gas ($443 in all) but trades later; not tested.

Replays with cheaper hedging (policy_sim.py's model, historical replay; external flow fixed):

| hedge cost | bot trades | LPs' trading-side net, 12 s | LP fees | Fynd's 20% | bot net (upper bound) | mean gap (bp) |
|---|---|---|---|---|---|---|
| −0% (3.89 bp) | 23,657 | −$3,442 | $1,479 | $370 | +$803 | 9.2 |
| −10% (3.50 bp) | 24,950 | −$3,408 | $1,516 | $379 | +$825 | 9.0 |
| −25% (2.92 bp) | 27,038 | −$3,349 | $1,591 | $398 | +$870 | 8.4 |
| −50% (1.95 bp) | 31,565 | −$3,241 | $1,716 | $429 | +$969 | 8.1 |
| 1 bp (the 0.01% pool) | 37,548 | −$3,072 | $1,883 | $471 | +$1,096 | 7.8 |

Cheaper hedging lets the bot trade more often at smaller gaps: LPs lose less per rebalance, earn more fees, the pool tracks the market better,
and the bot earns more. The replay's bot earns more than the real one at every setting (its hedge cost does not grow with size), so read bot
figures as upper bounds and compare rows with each other.

## 7. Recommendations

See `MECHANISM_RECOMMENDATIONS.md`. Ranked:
1. Route hedges to the deepest on-chain pool (and quote it on every trade).
2. Use the bot's new margin to raise its Fynd fee to about 3–4 bp.
3. Keep the bot running and reacting, once 1 and 2 are in place.

Not concluded: whether Fynd's design is better or worse than Uniswap's. The comparison metrics move with arbitrage activity, depth and range width,
and the two pools serve different flow.

## Limits

Native ETH legs are inferred (they match the bot's own on-chain figures in every transaction). Reverted transactions cannot be read. Uniswap v3
protocol fee shares are read at the current block. The replays keep external traders, routers and LPs as they were. USDG = $1.
