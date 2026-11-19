# Fynd ETH/USDG: bot profit flow and LP value-return audit

Built by `profit-flow-audit/analyze.py` from raw logs, receipts and chain-head state fetched by `fetch_flows.py` and
`fetch_contracts.py` (Robinhood Chain public RPC: **no traces, no historical state**). Coverage: blocks 84,286,819 (bot
contract deployment, 2026-10-09) to 117,293,571; balances at block
~117,311,142 (2026-11-18 09:54:17 UTC). Labels: **directly observed**, **calculated**, **inferred**, **unconfirmed**, **not observable**.

## Answers

1. **How much was withdrawn?** 7 withdrawals, all by `withdrawToken(token, amount, to)` called by owner_1 (`0xd7c8…1c80`),
   all paid to owner_1: **382.775621 USDG**, 1,424.407 AI, 175.143 PONS,
   about **$485** in all (*directly observed*; USD *calculated*, indicative for AI/PONS). Separately,
   **0.160607 native ETH** of the bot's ETH profit is no longer in the contract and left without any log (*inferred*; path and recipient
   *not observable*). ERC-20 profit reconciles exactly: profit events − withdrawals − balance = 0 for USDG, AI, PONS and NVDA.
2. **Where did it go?** Three rounds:
   - Oct 23: all three withdrawals sold on Uniswap v3 for WETH, unwrapped, and the router told to send the ETH to the **bot's gas
     wallet `0x4abf…84a2`** (0.074066 ETH).
   - Nov 11: 106.31 USDG swapped on the **Fynd ETH/USDG pool itself** for 0.051728 ETH, recipient again the bot's
     gas wallet.
   - Nov 10: 157.16 USDG, 856.44 AI and 104.84 PONS (≈$198) went into
     Ekubo Core through `0x5cec…855d`, a contract owner_1 deployed; only ~0.01% of each was swapped and the rest **was not returned to any
     audited wallet and did not become liquidity**. What Core holds it as (most likely an internal saved balance) is *not observable* without traces.
   - Retained by owner_1 at head: 1.539154 USDG, 7.6358 AI, 1.1798 PONS,
     0.005640 ETH.
   In all, about **0.1258 ETH ($285)** was routed to the bot's gas wallet (*inferred from calldata*: the
   swaps are observed, the native ETH payouts leave no log).
3. **Did any profit become liquidity in a Fynd position?** **No liquidity event was found** (*directly observed*, within coverage):
   no Ekubo PositionUpdated or Uniswap liquidity log in any owner transaction, no position NFT received by any audited wallet, and none
   of the 357 Fynd ETH/USDG liquidity events (to block 113,062,284, Nov 13) was sent, owned or minted by an
   audited wallet.
4. **Did any profit return to an existing LP position?** **No.** No transfer, liquidity addition or fee payment of that size (`LP_DEPOSIT_MATCHES.csv`).
5. **Did any go to an address linked to Fynd LP capital?** **No direct link found.** 0 token transfers between the audited wallets and
   any of the 8 LP owners (`LP_OWNER_TRANSFER_AUDIT.csv`). `0x6c6a…7127` is an EIP-7702 wallet delegating to
   `0x000000005c84f8fd50b21cac312528a64437030e`, which is not one of owner_1's contracts. Its link to Fynd rests on Edouard's Nov 12 statement (*unconfirmed* on chain).
6. **What cannot be traced?** Every native ETH movement: the 0.1606 ETH that left the bot contract, the ETH paid to the gas
   wallet, the 0.0698 ETH owner_1 sent into the Nov 10 call, and 7 owner_1 transactions that left no token log
   (nonces 1, 2, 3, 4, 14, 26, 33). Also the state of the Nov 10 tokens inside Ekubo Core (`NATIVE_ETH_FLOW_COVERAGE.md`).
7. **Is there evidence of value returning to LPs beyond their swap fees?** **No.** The only on-chain path from the bot to LPs is the fee on
   its trades. Owner_1's Nov 11 swap on the Fynd pool paid the normal pool fee like any trader; that is not a return of profit.

## 1. Roles (*directly observed* unless stated)

| address | role | evidence |
|---|---|---|
| `0xd7c8…1c80` owner_1 | EOA; deployed the bot contract (nonce 0), `0x5cec…855d` (nonce 15) and owner_2 (nonce 30); received every withdrawal | CREATE address = keccak(rlp(owner_1, nonce)); Transfer logs |
| `0x0d41…d4b2` owner_2 | **a contract** (11,673 bytes) deployed by owner_1; bot contract owner since block 111,842,342 | code at head; ownership events |
| `0x7ea0…acc7` bot contract | executes trades, holds profits; functions incl. `withdrawToken`, `setOperator`, `pause`, ownership | bytecode selectors |
| `0x4abf…84a2` bot sender | sends every trade, pays gas; **received the ETH from owner_1's swaps** | calldata recipients (*inferred*) |
| `0x6c6a…7127` | largest Fynd LP (153 positions); EIP-7702 wallet | code at head; Fynd ownership per Edouard (*unconfirmed* on chain) |

Owner_2 cannot send transactions (it is a contract); it accepted ownership through a call from owner_1. Its "nonce 1" is a
contract's default, not a transaction count (this corrects an earlier statement).

## 2. Bot profit and withdrawals

Profit events by pool (deployment to head; the bot trades four Fynd-extension pools, and its tokens are pooled in one contract,
so no withdrawal can be attributed to a pool):

| pool | profit token | trades | profit |
|---|---|---|---|
| Fynd AI/USDG | AI | 3,599 | 2,435.219984 |
| Fynd AI/USDG | USDG | 772 | 33.543501 |
| Fynd ETH/USDG | ETH | 15,280 | 0.208408 |
| Fynd ETH/USDG | USDG | 13,720 | 368.855689 |
| Fynd PONS/USDG | PONS | 2,261 | 329.250536 |
| Fynd PONS/USDG | USDG | 1,704 | 62.129668 |
| Fynd USDG/NVDA | NVDA | 2,435 | 0.280903 |
| Fynd USDG/NVDA | USDG | 2,634 | 53.367644 |

Reconciliation per token (`data/token_reconciliation.csv`; *calculated*):

| asset | profit events | withdrawn (logged) | balance at head | unexplained | trades | pools |
|---|---|---|---|---|---|---|
| USDG | 517.896502 | 382.775621 | 135.120881 | **0.000000** | 18,830 | Fynd AI/USDG, Fynd ETH/USDG, Fynd PONS/USDG, Fynd USDG/NVDA |
| AI | 2,435.219984 | 1,424.407011 | 1,010.812973 | **0.000000** | 3,599 | Fynd AI/USDG |
| PONS | 329.250536 | 175.142646 | 154.107889 | **0.000000** | 2,261 | Fynd PONS/USDG |
| NVDA | 0.280903 | 0.000000 | 0.280903 | **0.000000** | 2,435 | Fynd USDG/NVDA |
| ETH | 0.208408 | 0.000000 | 0.047801 | **0.160607** | 15,280 | Fynd ETH/USDG |

Gas is paid by the bot sender, not the contract, so these are gross trading profits. The ETH/USDG pool alone made about $739 before
gas and $295 after over Oct 13 – Nov 13 (earlier audit); the withdrawals are not that profit (they mix pools, tokens and dates).

Withdrawals (`BOT_WITHDRAWALS.csv`; calldata token, amount and recipient match the Transfer log exactly):

| UTC | tx | asset | amount | USD (indicative) | recipient |
|---|---|---|---|---|---|
| 2026-10-23 17:03 | `0x752a85c24e…` | USDG | 117.773593 | $117.77 | `0xd7c8…1c80` (owner_1) |
| 2026-10-23 17:03 | `0x750e6f12a9…` | AI | 560.285155 | $42.93 | `0xd7c8…1c80` (owner_1) |
| 2026-10-23 17:03 | `0x912526735a…` | PONS | 69.129438 | $17.56 | `0xd7c8…1c80` (owner_1) |
| 2026-11-10 13:52 | `0x0226985a92…` | USDG | 158.694006 | $158.69 | `0xd7c8…1c80` (owner_1) |
| 2026-11-10 13:52 | `0xc70ab93721…` | AI | 864.121856 | $25.23 | `0xd7c8…1c80` (owner_1) |
| 2026-11-10 13:52 | `0x23fc7b0b6a…` | PONS | 106.013208 | $16.37 | `0xd7c8…1c80` (owner_1) |
| 2026-11-11 12:52 | `0xc429c1db23…` | USDG | 106.308022 | $106.31 | `0xd7c8…1c80` (owner_1) |

## 3. Downstream (`PROFIT_DESTINATION_TRACE.csv`)

| date | tx | step | in | venue | out | output recipient | class | confidence |
|---|---|---|---|---|---|---|---|---|
| 2026-10-23 | `0xc70365c0c1…` | swap | 117.773593 USDG | Uniswap v3 WETH/USDG 0.01% | 0.048935 WETH | router 0xcaf6… (then unwrapped) | A. | directly observed |
| 2026-10-23 | `0xc70365c0c1…` | unwrap and send | 0.048935 WETH | WETH unwrap (Transfer to 0x0) + unwrapWETH9(min, recipient) | 0.048935 ETH (native) | bot sender 0x4abf…84a2 | B. | inferred (calldata names the recipient; native transfer not observable) |
| 2026-10-23 | `0xd3f84257ad…` | swap | 560.285155 AI | Uniswap v3 pool 0xd78480cafef722d75519e13b9f516e5704d0d659 | 0.017836 WETH | router 0xcaf6… (then unwrapped) | A. | directly observed |
| 2026-10-23 | `0xd3f84257ad…` | unwrap and send | 0.017836 WETH | WETH unwrap (Transfer to 0x0) + unwrapWETH9(min, recipient) | 0.017836 ETH (native) | bot sender 0x4abf…84a2 | B. | inferred (calldata names the recipient; native transfer not observable) |
| 2026-10-23 | `0x0e25ef207c…` | swap | 69.129438 PONS | Uniswap v3 pool 0xed50bdeea8adc232f159486192a4157281d722ff | 0.007295 WETH | router 0xcaf6… (then unwrapped) | A. | directly observed |
| 2026-10-23 | `0x0e25ef207c…` | unwrap and send | 0.007295 WETH | WETH unwrap (Transfer to 0x0) + unwrapWETH9(min, recipient) | 0.007295 ETH (native) | bot sender 0x4abf…84a2 | B. | inferred (calldata names the recipient; native transfer not observable) |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 1: Fynd ETH/USDG | 120.018088 USDG | Ekubo Fynd ETH/USDG through 0x5cec | 0.000006 ETH | not observable (native) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 2: Fynd ETH/USDG | 0.069062 ETH | Ekubo Fynd ETH/USDG through 0x5cec | 0.014299 USDG | owner_1 (Transfer logs) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 3: Fynd AI/USDG | 856.529325 AI | Ekubo Fynd AI/USDG through 0x5cec | 0.002501 USDG | owner_1 (Transfer logs) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 4: Fynd AI/USDG | 12.967482 USDG | Ekubo Fynd AI/USDG through 0x5cec | 0.043233 AI | owner_1 (Transfer logs) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 5: Fynd PONS/USDG | 104.847184 PONS | Ekubo Fynd PONS/USDG through 0x5cec | 0.001618 USDG | owner_1 (Transfer logs) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 6: Fynd PONS/USDG | 22.099485 USDG | Ekubo Fynd PONS/USDG through 0x5cec | 0.013794 PONS | owner_1 (Transfer logs) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-10 | `0x52c5a59510…` | 0x5cec leg 7: Fynd USDG/NVDA | 2.088215 USDG | Ekubo Fynd USDG/NVDA through 0x5cec | 0.000006 NVDA | owner_1 (Transfer logs) | F. | transfers into Core directly observed; what Core did with the unswapped balance not observable |
| 2026-11-11 | `0x493b84ee35…` | swap and send | 106.308022 USDG | Ekubo Fynd ETH/USDG (via router 0x0921…) | 0.051728 ETH (native) | bot sender 0x4abf…84a2 | A. | swap directly observed; recipient inferred from calldata |

**The Nov 10 transaction** (`0x52c5a595…`, owner_1 → its own contract `0x5cec…855d`, with 0.0698 ETH attached):

| pool | asset | 0x5cec reported in | paid into Core (logged) | swapped in Ekubo | not swapped |
|---|---|---|---|---|---|
| Fynd ETH/USDG | USDG | 120.018088 | 120.018088 | 0.01200000 | 120.006088 |
| Fynd ETH/USDG | ETH | 0.069062 | native (no log) | 0.00000691 | not observable |
| Fynd AI/USDG | AI | 856.529325 | 856.529325 | 0.08564421 | 856.443681 |
| Fynd AI/USDG | USDG | 12.967482 | 12.967482 | 0.00126300 | 12.966219 |
| Fynd PONS/USDG | PONS | 104.847184 | 104.847184 | 0.01047989 | 104.836704 |
| Fynd PONS/USDG | USDG | 22.099485 | 22.099485 | 0.00213000 | 22.097355 |
| Fynd USDG/NVDA | USDG | 2.088215 | 2.088215 | 0.00100000 | 2.087215 |

Six of the seven swaps used about 1/10,000 of the amount paid in (ratios 10,002, 10,001, 10,001, 10,267, 10,005, 10,375, 2,088); the
small NVDA-pool leg about 1/2,000. The rest stayed in Ekubo Core: no Transfer back to owner_1 or anyone else in
the transaction, no PositionUpdated, and the FeesAccumulated logs in the transaction are ordinary fee payments (Fynd ETH/USDG: 0.000000 ETH + 0.012170 USDG; Fynd AI/USDG: 0.909114 AI + 0.000000 USDG; Fynd PONS/USDG: 0.000000 PONS + 0.007775 USDG; Fynd USDG/NVDA: 0.004330 USDG + 0.000000 NVDA; Fynd ETH/USDG: 0.000001 ETH + 0.000000 USDG).
Ekubo settles all balances before a transaction ends, so the unswapped amount was booked to some internal account inside Core
(*inferred*: most likely a saved balance); which account is *not observable* with logs only. Since then, 0 transfers
larger than one token unit have left Core for owner_1, owner_2 or the bot sender (through block 117,293,571; 0 of any size),
and `0x5cec` has emitted no log before or since. Whether it was later moved to another address is
*not observable*. Owner_1's token ledgers reconcile exactly (residual USDG 0, AI 0, PONS 0, NVDA 0 raw units).

**Reported vs observed:** the earlier "≈263 USDG swapped on Ekubo" was the USDG *sent into Ekubo Core*: 106.31 was swapped
(Nov 11) and 157.16 entered Core on Nov 10 with ~0.01% swapped. The "≈118 USDG on Uniswap" is exact (117.773593).
382.78 withdrawn = 117.77 (Uniswap) + 157.17 (Nov 10, into Core) + 106.31 (Fynd pool) + 1.52 kept (net of 0.018 received back).

## 4. Liquidity search (`LP_DEPOSIT_MATCHES.csv`)

- Ekubo PositionUpdated / Uniswap v3 Mint, IncreaseLiquidity / Uniswap v4 ModifyLiquidity in any transaction involving owner_1 or owner_2: **0** (30 transactions (all owner_1 transactions with a token log, the bot contract's admin transactions, and incoming token transfers)).
- position NFTs (ERC-721 Transfer) received by the bot contract's owner_1, owner_2, or the bot sender: **0** (all ERC-721 Transfer logs to these addresses, blocks 84,286,819-117,293,571).
- Fynd ETH/USDG liquidity events sent, owned or minted by an audited wallet: **0** (all 357 position and 181 fee-collect events, blocks 78,004,833-113,062,284).
- owner_1's contract 0x5cec: any event other than its per-swap report: **0** (all 7 logs it has ever emitted).
- FeesAccumulated (fee payment to LPs) in owner_1 transactions large enough to carry the unswapped Nov 10 tokens: **0** (5 FeesAccumulated logs in owner_1 transactions).
- transfers out of Ekubo Core to owner_1, owner_2 or the bot sender after the Nov 10 transaction (> 1 token unit): **0** (blocks 110,928,730-117,293,571; 0 transfers of any size).

A swap is not a deposit, and a new position owned by the bot's owner would not compensate existing LPs; neither was found anyway.

## 5. Transfers to LP owners (`LP_OWNER_TRANSFER_AUDIT.csv`)

Direct token transfers between {bot contract, bot sender, owner_1, owner_2} and the 8 LP owners: **0**,
including `0x6c6a…7127` (also none in the earlier USDG/WETH scan). Indirect paths through shared pools or routers cannot link
owners and are not treated as links.

## 6. Keep three things apart

- **Price rebalancing.** The bot swaps against Fynd and hedges elsewhere. LPs give up the gap to the market on those trades:
  $4,037 before fees at 12 s; that is a trade, not a transfer of profit to anyone in particular.
- **LP compensation.** LPs receive 80% of the fee on every swap, the bot's included: +$615 on the bot's trades, already inside
  the net −$3,422 (do not add it again). The 80% is verified per fee-payment interval (bot only, ETH fees: 8911/8911; bot only, USDG fees: 9485/9501; mixed, ETH fees: 3/3; mixed, USDG fees: 276/276; external only, ETH fees: 0/0; external only, USDG fees: 2154/2154; all, ETH fees: 8914/8914; all, USDG fees: 11915/11931).
  The other 20% is not paid to LPs; its final recipient is not established here.
- **Bot profit distribution.** The contract keeps its trading profit; owner_1 withdrew part of it and turned most of it into ETH for the
  bot's gas wallet. None of it was observed reaching LPs.

## 7. What would settle the open points

A trace-enabled RPC (`debug_traceTransaction`) on `0x52c5a595…` (where the Nov 10 tokens were booked) and on the bot contract's
history (native ETH outflows), or Fynd's confirmation of: the 0.1606 ETH, the Nov 10 balance in Ekubo Core, and the 20% fee recipient.
