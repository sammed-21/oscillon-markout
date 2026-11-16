# Checking the Fynd LP numbers by hand

Every step below uses only the chain (public RPC) and Binance's public files, not our code. Do one swap and one position
by hand first. Then open our per-row files in a spreadsheet, find the same rows, and check they match. Then do the sums
yourself.

```
R=https://rpc.mainnet.chain.robinhood.com
CORE=0x00000000000014aA86C5d3c41765bb24e11bd701      # Ekubo Core: holds every Ekubo pool on this chain
POOL=b67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546   # Fynd ETH/USDG poolId
s128() { python3 -c "x=int('$1',16); print(x-(1<<128) if x>=1<<127 else x)"; }   # signed 128-bit hex -> integer
```

Conventions:
- **Signs.** Amounts are from the pool's side: **+ = the pool received**, − = the pool paid out.
- **Decimals.** ETH has 18 decimals and USDG has 6. Divide by 1e18 and 1e6.
- **Binance price at block time T.** Take the close of the 1 s ETHUSDC candle that **opens at T−2 s**, so it closes at T−1.
- **Binance price "12 s after".** Take the close of the candle that **opens at T+11 s**.
- **Where the candles are.** Daily files are at `https://data.binance.vision/data/spot/daily/klines/ETHUSDC/1s/ETHUSDC-1s-YYYY-MM-DD.zip`. Column 1 is the open time in **microseconds**; column 5 is the close.

---

## 0. What −$3,825 is, and what it isn't

**It is not what the bot took.** It is the LPs' result on **all 28,101 swaps** (bot and everyone else), with each swap valued at Binance 12 s later and the fees added back:

| | Swaps | Fees paid to LPs | LP loss at Binance 12 s | Net for LPs |
|---|---|---|---|---|
| Bot wallet 0x4abf…84a2 | 24,258 | +$615 | −$4,037 | −$3,422 |
| Everyone else | 3,843 | +$1,470 | −$1,873 | −$403 |
| **All swaps** | 28,101 | +$2,085 | −$5,910 | **−$3,825** |
| Later price moves (12 s after each swap → position end) | | | | −$100 |
| **LP vs hold** | | | | **−$3,925** |

The "LP loss at Binance 12 s" column is the impermanent loss, measured swap by swap. **Loss at 12 s + later moves = IL**:

    −$5,910 + −$100 = −$6,010

The headline IL is −$5,993. The $17 difference is fees: the table values them when paid, the headline at each position's end.

So Fynd's point is right. This number **is IL**, and IL is a loss to LPs measured at Binance. **It is not money that arrived in the bot's wallet.** The bot pays the other side of its trade somewhere else, at that venue's price, plus gas. Step 3 shows this on a real transaction.

---

## 1. Is the data only the Fynd pool?

1. **The poolId is the hash of the pool key.** The pool key is (ETH = 0x0, USDG, config with the Fynd extension):
   ```
   cast keccak 0x0000000000000000000000000000000000000000000000000000000000000000\
   0000000000000000000000005fc5360d0400a0fd4f2af552add042d716f1d168\
   550cfe1292d0d9c0d28f232b3f42edb4439b1d09000000000000000080000400
   ```
   Expected output: `0xb67e0601…3546`.
2. **Every swap in our file carries this poolId.** In each swap log, bytes 21–52 are the poolId (step 2b).
3. **The counts match the chain.** `check_pool_scope.py` lists all 212 Ekubo pools and counts this pool's swaps on chain. That gives 28,101 swaps and 354 position updates, the same as our files.
   - It also counts 66,565 swaps on the other ETH/USDG pools. None of them are in our files.
   - This one uses our code. To check it by hand, pick any block and run `eth_getLogs` on Core for it. Every swap with poolId `b67e…` should be in `results_lp_fynd_split_swaps.csv`, and nothing else from that block.

---

## 2. One bot swap, by hand

Transaction `0x92820cc60b495c5088e44acd770888949c6674d4f91bfbf037455e54d18963da`
- Block 98,252,992, time 1793001063 = **2026-10-26 07:51:03 UTC**.
- Sent by `0x4abf…84a2` (the bot wallet) to `0x7ea0…bcc7` (its contract).

**a. Get the logs**
```
cast receipt 0x92820cc60b495c5088e44acd770888949c6674d4f91bfbf037455e54d18963da --rpc-url $R --json \
  | jq -r '.logs[] | "\(.logIndex) \(.address) \(.topics[0] // "no-topic") \(.data)"'
```
The Fynd swap is the log from **Core with no topic** (Ekubo swaps are anonymous events), log index 5. Its data is 116 bytes:
```
550cfe1292d0d9c0d28f232b3f42edb4439b1d09                           locker = the Fynd extension (20 bytes)
b67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546   poolId (32 bytes)  -> Fynd pool
000000000000000003041e2e3b851c6a                                   amount0, ETH  (signed 16 bytes)
ffffffffffffffffffffffffe1f299b7                                   amount1, USDG (signed 16 bytes)
4000c9fcf35541711b9ef2d2 fed09fab 00000000000000000070dd55d60483ad sqrt price | tick | liquidity after the swap
```

**b. Decode it**
```
s128 000000000000000003041e2e3b851c6a   ->  217331865936534634  / 1e18 = +0.217331866 ETH   (pool received ETH)
s128 ffffffffffffffffffffffffe1f299b7   ->  -504194633          / 1e6  = -504.194633 USDG  (pool paid USDG)
```
So the bot sold 0.2173 ETH to the pool for 504.19 USDG.

Cross-check with the USDG token's own Transfer log in the same transaction: log 6 moves `0x1e0d6649` = 504,194,633 = 504.194633 USDG.

**c. The Binance prices.** Open `ETHUSDC-1s-2026-10-26.zip`.
- **Before:** the candle that opens at 1793001061 (= T−2) closes at **2318.19**.
- **12 s after:** the candle that opens at 1793001074 (= T+11) closes at **2317.86**.

**d. The fee this swap paid**

The Fynd extension doesn't pay a swap's fee into the pool in the same transaction. It pays it at the pool's next interaction, as a `FeesAccumulated` log on Core (topic `0xf7e050d8…af6c`). Find the first one for this pool after the swap:
```
cast logs --address $CORE --from-block 98252993 --to-block 98253368 \
  0xf7e050d866774820d81a86ca676f3afe7bc72603ee893f82e99c08fbde39af6c --rpc-url $R
```
Keep the log whose data starts with `b67e…`. That is block 98,253,368, log 0. Its data is poolId | amount0 | amount1, with amount0 = `0x2b9b28d241c7` = 47,945,404,793,287 wei = **0.0000479454 ETH**.

Check that no other Fynd swap happened between our swap and that fee log. If one did, the fee is split between them in proportion to |USDG amount|. Here there was none, so the whole fee is this swap's.

**e. The arithmetic**
```
volume          = 0.217331866 × 2318.19                    = $503.82
fee to LPs      = 0.0000479454 × 2318.19                   = $0.111   (= 2.2 bp of volume)
LP side at 12 s = 0.217331866 × 2317.86 − 504.194633       = −$0.450  (LPs got ETH worth $503.74 for $504.19 of USDG)
net for LPs     = 0.111 − 0.450                            = −$0.339
```
**f. Match it to our file.** In `results_lp_fynd_split_swaps.csv`, the row with this tx_hash should read:

    volume_usd 503.8166, fee_usd 0.1111, loss_12s_usd 0.4498, net_for_lps_usd −0.3386

---

## 3. What the bot actually kept on that same transaction

This is the step that answers "the bot didn't take that much".

The same transaction also has a **Uniswap v3 Swap** log (topic `0xc42079f9…`) on pool `0x69bfaf19…`, the Uniswap v3 WETH/USDG 0.05% pool:
- that pool **received** 504.194633 USDG (log 9, the same amount the bot got from Fynd);
- it **paid out** `0x0304621c1fadd7ef` = **0.217406555 WETH** (log 8).

So, within one transaction:

| Bot contract | ETH / WETH | USDG |
|---|---|---|
| Sold to Fynd | −0.217331866 ETH | +504.194633 |
| Bought on Uniswap v3 0.05% | +0.217406555 WETH | −504.194633 |
| **Kept** | **+0.000074689 ETH ≈ $0.173** | 0 |

**Gas:** gasUsed `0x5ae04` × effectiveGasPrice `0x131e0b0` = 0.00000746 ETH ≈ **$0.017**.

**On this swap, LPs were −$0.34 vs Binance and the bot kept about $0.16.** The rest of the LPs' loss did not go to the bot. It is the gap between Binance 12 s later and the Uniswap price the bot actually paid.

I took a random sample of 40 bot transactions. **All 40 also swapped on another on-chain pool in the same transaction** (mostly Uniswap v4 and v3). If that holds for every bot transaction, the bot's real take is fully on chain: the bot contract's token balance change in each transaction, minus gas. That is a number you can compute exactly, with no Binance and no h. It replaces the "upper bound" (step 7).

---

## 4. A non-bot swap, the short version

Transaction `0x535cb87e90504ec0cf896025897a3989589ab0f430bc39d28edd7ed27ea9d25d`, 2026-10-26 18:06:42 UTC (ts 1793038002), from `0xf159…2a5a`.

- **Swap log:** +0.240456 ETH to the pool, −558.924744 USDG.
- **Binance:**
  - candle opening at 1793038000 closes at 2324.43;
  - candle opening at 1793038013 closes at 2325.15.
- **Next fee log for the pool:** block 98,611,109, log 6, amount1 = **0.183031 USDG**.
- **Arithmetic:**
  ```
  volume          = 0.240456 × 2324.43               = $558.92
  LP side at 12 s = 0.240456 × 2325.15 − 558.924744  = +$0.171   (ETH rose after; LPs gained)
  net for LPs     = 0.183 + 0.171                    = +$0.354
  ```
  Our file: loss_12s_usd −0.1714, net_for_lps_usd +0.3545.

---

## 5. One LP position, by hand

Position `4a70cdbf…0f7c9f19`, range ticks −19,844,096 to −19,745,792, owner `0xf94e…e85d`. It has one deposit, one fee collection and one withdrawal.

PositionUpdated logs (topic `0x704b3ab4…0a07`) carry five words: locker | poolId | position key (salt + lower tick + upper tick) | liquidity change | amounts. The last word's first 16 bytes are ETH and the next 16 are USDG. PositionFeesCollected logs (topic `0xd76ec32f…7753`) carry locker | poolId | key | ETH | USDG.

| Event | Transaction | Time (UTC) | Raw word(s) | Decoded |
|---|---|---|---|---|
| Deposit | `0xc2caaf32…d732`, log 6 | Oct 8 14:28:56 (ts 1791469736) | `057c0fc4661801b6` / `3b9aca00` | +0.395208204 ETH, +1000 USDG |
| Fees collected | `0x55254dcf…d1d9`, log 7 | Oct 8 18:25:27 (ts 1791483927) | `6858afe11063` / `26b953` | 0.000114730 ETH, 2.537811 USDG |
| Withdrawal | same transaction, log 8 | same time | `fff…f51dab82c2302001` / `fff…fdb45e4f` | −0.784282182 ETH, −38.511025 USDG |

```
cast receipt 0xc2caaf321e480fd37342d208d8ba7e61908a7419137a6c7455c27f75fd42d732 --rpc-url $R --json | jq '.logs[6].data'
cast receipt 0x55254dcfe4003acf8fabb7d9c57669adfe7f712501026b5f8ef2768c8bfde1d9 --rpc-url $R --json | jq '.logs[7,8].data'
```

**Binance prices** (`ETHUSDC-1s-2026-10-08.zip`):
- At the deposit: the candle opening at 1791469734 closes at **2532.43**.
- At the end: the candle opening at 1791483925 closes at **2437.78**.

```
cost        = 0.395208204 × 2532.43 + 1000                       = $2,000.84
hold        = 0.395208204 × 2437.78 + 1000                       = $1,963.43   (the deposited tokens, never put in)
principal   = 0.784282182 × 2437.78 + 38.511025                  = $1,950.42   (what came out, without fees)
fees        = 0.000114730 × 2437.78 + 2.537811                   = $2.82
LP          = principal + fees                                   = $1,953.24
IL          = (0.784282182 − 0.395208204) × 2437.78 + (38.511025 − 1000) = −$13.01
LP − hold   = fees + IL = 2.82 − 13.01                           = −$10.19
days        = (1791483927 − 1791469736) / 86400                  = 0.1642
capital-days = 2,000.84 × 0.1642                                 = 328.63
```
**Match it to our file.** In `results_lp_fynd_positions.csv` this position's row should read:

    fees_usd 2.82, il_usd −13.01, lp_minus_hold_usd −10.19, capital_days_usd 328.63

The ETH price fell from 2532 to 2438 while the position was open, and the position ended with more ETH and less USDG than it started with. That is IL: the pool sold ETH low and bought it high relative to just holding.

---

## 6. The sums, in a spreadsheet

Open the files and sum the columns yourself.

**`results_lp_fynd_positions.csv`** (179 rows):

| Column | Sum |
|---|---|
| fees_usd | +2,068.59 |
| il_usd | −5,993.48 |
| lp_minus_hold_usd | **−3,924.90** |
| capital_days_usd | 777,362.43 |

- The 173 closed positions sum to −3,781.74.
- The 6 still-open positions sum to −143.15 (10% of capital-days).

**`results_lp_fynd_split_swaps.csv`** (28,101 rows). Filter on bot_wallet and sum:

| bot_wallet | volume_usd | fee_usd | loss_12s_usd | net_for_lps_usd |
|---|---|---|---|---|
| TRUE | 4,484,061 | 615.27 | 4,037.28 | −3,422.01 |
| FALSE | 929,209 | 1,470.27 | 1,873.38 | −403.11 |
| all | | | | **−3,825.12** |

**Later price moves** = −3,924.90 − (−3,825.12) = **−99.77**.

---

## 7. The derived numbers, by hand

| Number | Arithmetic | Result |
|---|---|---|
| Average capital | 777,362.43 / 42.02 days | $18,500 |
| LP vs hold per $1,000 per 30 days | −3,924.90 / 777,362.43 × 30,000 | **−$151.47** (−15.1%) |
| Bot-wallet upper bound (h = 0) | 4,037.28 − 615.27 | $3,422 |
| h where that bound reaches 0 | 3,422.01 / 4,484,061 × 10,000 | **7.63 bp** |
| Fee at which LPs break even on bot swaps | 4,037.28 / 4,484,061 × 10,000 | **9.0 bp** |
| Last 15 days vs before | filter swaps from 2026-10-29 00:00 UTC, then loss_12s_usd / volume_usd | **9.28 bp** (2,132 / 2,297,252) vs **12.13 bp** (3,779 / 3,116,018) |

---

## 8. What can't be checked by hand

- **The 6 still-open positions (−$143 of the −$3,925).** Their tokens were read on chain at block 113,153,559. This RPC keeps no history, so that read can't be repeated at that block. Two checks still cover them:
  - the books close: every deposit, withdrawal, fee and swap added up equals what those 6 positions hold (4.055064 ETH, 6,399.16 USDG);
  - all fees paid in (fee logs) equal all fees in positions, to 100.000%.
- **Fee split when several swaps share one fee log.** Each swap's share is in proportion to its |USDG amount|. This is our rule; the extension doesn't log per-swap fees. Only the bot-vs-other split depends on it, and only slightly. Total fees are exact.
- **The bot's real take.** Not in these files. It needs the bot contract's token flows in every transaction (step 3).
