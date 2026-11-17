# Hand checks: bot transactions

Each check uses only the transaction receipt and the conversions shown. To fetch a receipt yourself:

```
cast receipt <tx_hash> --rpc-url https://rpc.mainnet.chain.robinhood.com --json
```

Conventions. Amounts are from the receiving side: + = that pool or wallet received. Ekubo's swap log is anonymous, 116 bytes: locker (20) | poolId (32) | amount0 int128 (16) | amount1 int128 (16) | price and liquidity (32). Uniswap v4's Swap event reports the swapper's side, so its signs are flipped. ETH has 18 decimals, USDG 6. The bot contract's own event (topic 0xed370fed) has words: poolId | amount out of Fynd | amount paid into Fynd including the Fynd fee | profit, in the token the bot paid in.

## A normal profitable trade (the bot EOA's first, nonce 0)

`0x21baf60f981b95f5b96b15efdcdb04d12cf4b7e0a45be61e494a87fd4c59542e`, block 87,487,456, 2026-10-13 11:47:37 UTC, completeness: **complete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 17 | Fynd FeesAccumulated (pays LPs for earlier swaps) | | 0.000637592503444074 ETH, 0.000000 USDG |
| 19 | Fynd swap, amount0 (ETH to pool) | `000000000000000002add01d6d350d62` | +0.193039183851621721 ETH |
| 19 | Fynd swap, amount1 (USDG to pool) | `ffffffffffffffffffffffffe323b7a1` | -484.198495 USDG |
| 20 | Transfer USDG 00000000… → 7ea0ab3b… | `0000000000000000000000001cdc485f` | 484.198495 |
| 22 | Transfer USDG 7ea0ab3b… → 8366a39c… | `0000000000000000000000001cdc485f` | 484.198495 |
| 23 | Uniswap v4 swap WETH/USDG, swapper side | `000000000000000002ae565aaa0681c9`, `ffffffffffffffffffffffffe323b7a1` | +0.19318678142310855 WETH, -484.198495 USDG |
| 24 | Transfer WETH 8366a39c… → 09215a47… | `000000000000000002ae565aaa0681c9` | 0.193186781423108550 |
| 25 | Transfer WETH 09215a47… → 00000000… | `000000000000000002ae565aaa0681c9` | 0.193186781423108550 |
| 26 | router fee event, token eeeeee…, (recipient, amount) | | [('a5503d92', 0), ('4abfdbac', 0)] |
| 28 | bot event: out of Fynd, paid into Fynd, profit | `0000000000001cdc485f`, `000002ae47d45a75918c`, `000000000e864f90f03d` | 484198495, 193170811399803276, 15970023305277 (raw units) |

1. Direction: bot sells eth.
2. Fynd fee: 0.000131627548181 ETH (bot event (inferred)) = $0.329449, 6.819 bp of $483.16. LPs get 80% = $0.263559, protocol $0.065890.
3. Router fee: 0 ETH + 0.000000 USDG = $0.000000.
4. Bot keeps +0.000015970023305277 ETH and +0.000000 USDG; the bot's own event says 1.59700233052770007e-05 (difference 0).
5. At Binance 2,502.89: gross $0.039971; gas 387,949 gas x 20,020,000 wei = 0.000007766739 ETH = $0.019439; net $0.020532.
6. LPs' swap side at execution $-1.042652, other venues $0.673232; fee + router fee + bot + LPs + other venues = $1.41e-14.
7. Issues recorded: none.

## Bot buys ETH from Fynd: the Fynd fee is visible as a USDG transfer

`0x6863b1c049e427d51edf2586814a252208b6a18a3b514a42fe905bf7191d0b4e`, block 87,491,525, 2026-10-13 11:54:29 UTC, completeness: **complete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 1 | Fynd swap, amount0 (ETH to pool) | `fffffffffffffffffe474009f652d385` | -0.124060053197892733 ETH |
| 1 | Fynd swap, amount1 (USDG to pool) | `000000000000000000000000127859bc` | +309.877180 USDG |
| 2 | Uniswap v4 swap ETH/USDG, swapper side | `fffffffffffffffffe474009f652d385`, `0000000000000000000000001279472a` | -0.124060053197892733 ETH, +309.937962 USDG |
| 3 | Transfer USDG 8366a39c… → 09215a47… | `0000000000000000000000001279472a` | 309.937962 |
| 4 | router fee event, token 5fc536…, (recipient, amount) | | [('a5503d92', 0), ('4abfdbac', 0)] |
| 5 | Transfer USDG 09215a47… → 7ea0ab3b… | `0000000000000000000000001279472a` | 309.937962 |
| 6 | Transfer USDG 7ea0ab3b… → 00000000… | `0000000000000000000000001278ce07` | 309.906951 |
| 7 | bot event: out of Fynd, paid into Fynd, profit | `000001b8bff609ad2c7b`, `0000000000001278ce07`, `00000000000000007923` | 124060053197892731, 309906951, 31011 (raw units) |

1. Direction: bot buys eth.
2. Fynd fee: 0.029771 USDG (USDG transfer to Core minus swap amount (observed)) = $0.029771, 0.960 bp of $309.96. LPs get 80% = $0.023817, protocol $0.005954.
3. Router fee: 0 ETH + 0.000000 USDG = $0.000000.
4. Bot keeps +0.000000000000000000 ETH and +0.031011 USDG; the bot's own event says 0.0310110000000000004 (difference 0).
5. At Binance 2,498.45: gross $0.031011; gas 330,120 gas x 20,328,000 wei = 0.000006710679 ETH = $0.016766; net $0.014245.
6. LPs' swap side at execution $-0.080660, other venues $0.019878; fee + router fee + bot + LPs + other venues = $-1.74e-14.
7. Issues recorded: none.

## Negative after gas: the most negative net result

`0x98533b3059bea48476fe9ebd52ad98ba6cce1e3afb4d63a4f4206b2453b3b6d7`, block 94,336,703, 2026-10-21 14:02:09 UTC, completeness: **complete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 26 | Fynd FeesAccumulated (pays LPs for earlier swaps) | | 0.000009817040588783 ETH, 0.000000 USDG |
| 28 | Fynd swap, amount0 (ETH to pool) | `000000000000000000157972bab0f340` | +0.006044508176315200 ETH |
| 28 | Fynd swap, amount1 (USDG to pool) | `ffffffffffffffffffffffffff1c5c40` | -14.918592 USDG |
| 29 | Transfer USDG 00000000… → 7ea0ab3b… | `00000000000000000000000000e3a3c0` | 14.918592 |
| 31 | Transfer TSLA c4f0172d… → 09215a47… | `00000000000000000088b57349c9c83e` | 0.038480103596476481 |
| 33 | Transfer USDG 7ea0ab3b… → c4f0172d… | `00000000000000000000000000e3a3c0` | 14.918592 |
| 34 | Uniswap v3 swap TSLA/USDG 0xc4f0172d, pool side | `ffffffffffffffffff774a8cb63637c2`, `00000000000000000000000000e3a3c0` | -0.0384801035964764809 TSLA, +14.918592 USDG |
| 35 | Transfer TSLA 09215a47… → 00000000… | `00000000000000000088b57349c9c83e` | 0.038480103596476481 |
| 38 | other Ekubo pool swap 29c15f10aa…, pool side | `00000000000000000088b57349c9c83e`, `fffffffffffffffffebdd3b79952c667` | see legs |
| 39 | Transfer SPCX 00000000… → 09215a47… | `00000000000000000141810b0ea886a2` | 0.090495352014669475 |
| 41 | Transfer WETH c3c9f017… → 09215a47… | `000000000000000000157a8362141881` | 0.006045679215712385 |
| 42 | Transfer SPCX 09215a47… → c3c9f017… | `00000000000000000141810b0ea886a2` | 0.090495352014669475 |
| 44 | Uniswap v3 swap WETH/SPCX 0xc3c9f017, pool side | `ffffffffffffffffffea857c9debe77f`, `00000000000000000141810b0ea886a2` | -0.00604567921571238457 WETH, +0.09049535201 SPCX |
| 45 | Transfer WETH 09215a47… → 00000000… | `000000000000000000157a8362141881` | 0.006045679215712385 |
| 46 | router fee event, token eeeeee…, (recipient, amount) | | [('a5503d92', 0), ('4abfdbac', 0)] |
| 48 | bot event: out of Fynd, paid into Fynd, profit | `00000000000000e3a3c0`, `000000157999f12a6658`, `0000000000e970e9b229` | 14918592, 6044676593968728, 1002621743657 (raw units) |

1. Direction: bot sells eth.
2. Fynd fee: 1.68417653528e-07 ETH (bot event (inferred)) = $0.000415, 0.279 bp of $14.91. LPs get 80% = $0.000332, protocol $0.000083.
3. Router fee: 0 ETH + 0.000000 USDG = $0.000000.
4. Bot keeps +0.000001002621743657 ETH and +0.000000 USDG; the bot's own event says 1.00262174365699998e-06 (difference 0).
5. At Binance 2,466.83: gross $0.002473; gas 652,418 gas x 20,386,000 wei = 0.000013300193 ETH = $0.032809; net $-0.030336.
6. LPs' swap side at execution $-0.007818, other venues $0.004929; fee + router fee + bot + LPs + other venues = $1.16e-15.
7. Issues recorded: none.

## Several routing legs, an intermediate token that must net to zero

`0x02404683855a01c6dd8553a8f84c4bd034adfd006c6590a2f70cef62f4539f23`, block 87,496,225, 2026-10-13 12:02:25 UTC, completeness: **complete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 0 | Fynd FeesAccumulated (pays LPs for earlier swaps) | | 0.000007647423032337 ETH, 0.000000 USDG |
| 2 | Fynd swap, amount0 (ETH to pool) | `00000000000000000028f0deea58689e` | +0.011523839273494686 ETH |
| 2 | Fynd swap, amount1 (USDG to pool) | `fffffffffffffffffffffffffe4908c5` | -28.768059 USDG |
| 3 | Transfer USDG 00000000… → 7ea0ab3b… | `00000000000000000000000001b6f73b` | 28.768059 |
| 5 | Transfer USDG 7ea0ab3b… → 8366a39c… | `00000000000000000000000001b6f73b` | 28.768059 |
| 6 | Uniswap v4 swap SPY/USDG, swapper side | `000000000000000000833b6b317c9a60`, `fffffffffffffffffffffffffe4908c5` | +0.0369385535268849582 SPY, -28.768059 USDG |
| 7 | Uniswap v4 swap SPY/PAIR, swapper side | `ffffffffffffffffff7cc494ce8365a0`, `00000000000005264fe2f693756fd26d` | -0.0369385535268849582 SPY, +24318.56512 PAIR |
| 8 | Transfer PAIR 8366a39c… → 09215a47… | `00000000000005264fe2f693756fd26d` | 24318.565123536111059366 |
| 9 | Transfer WETH c54c8ba6… → 09215a47… | `00000000000000000029eed545cce862` | 0.011803073811638370 |
| 10 | Transfer PAIR 09215a47… → c54c8ba6… | `00000000000005264fe2f693756fd26d` | 24318.565123536111059366 |
| 11 | Uniswap v3 swap WETH/PAIR 0xc54c8ba6, pool side | `ffffffffffffffffffd6112aba33179e`, `00000000000005264fe2f693756fd26d` | -0.0118030738116383701 WETH, +24318.56512 PAIR |
| 12 | Transfer WETH 09215a47… → 00000000… | `00000000000000000029eed545cce862` | 0.011803073811638370 |
| 13 | router fee event, token eeeeee…, (recipient, amount) | | [('a5503d92', 0), ('4abfdbac', 0)] |
| 15 | bot event: out of Fynd, paid into Fynd, profit | `00000000000001b6f73b`, `00000029e9ef23f3f497`, `0000000004e621d8f3cb` | 28768059, 11797687354782871, 5386456855499 (raw units) |

1. Direction: bot sells eth.
2. Fynd fee: 0.000273848081288 ETH (bot event (inferred)) = $0.683218, 237.636 bp of $28.75. LPs get 80% = $0.546574, protocol $0.136644.
3. Router fee: 0 ETH + 0.000000 USDG = $0.000000.
4. Bot keeps +0.000005386456855499 ETH and +0.000000 USDG; the bot's own event says 5.3864568554989997e-06 (difference 0).
5. At Binance 2,494.88: gross $0.013439; gas 572,436 gas x 20,536,000 wei = 0.000011755546 ETH = $0.029329; net $-0.015890.
6. LPs' swap side at execution $-0.017463, other venues $-0.679194; fee + router fee + bot + LPs + other venues = $2.31e-16.
7. Issues recorded: none.

## A route through a tokenized-stock pool whose extension keeps part of the output

`0x5dc6a7ad7f0bca7dbbd22c1c8f3c075192baf9b1a6dbf20b3c4bffbcf46c514d`, block 88,373,865, 2026-10-14 12:40:28 UTC, completeness: **complete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 2 | Fynd FeesAccumulated (pays LPs for earlier swaps) | | 0.000006652476253200 ETH, 0.000000 USDG |
| 4 | Fynd swap, amount0 (ETH to pool) | `000000000000000000872ca4f831c1b7` | +0.038048208906207671 ETH |
| 4 | Fynd swap, amount1 (USDG to pool) | `fffffffffffffffffffffffffa5e086e` | -94.500754 USDG |
| 5 | Transfer USDG 00000000… → 7ea0ab3b… | `00000000000000000000000005a1f792` | 94.500754 |
| 7 | Transfer USDG 7ea0ab3b… → 00000000… | `00000000000000000000000005a1f792` | 94.500754 |
| 9 | other Ekubo pool swap d22599ab7e…, pool side | `00000000000000000000000005a1f792`, `fffffffffffffffffc305579c06e7463` | see legs |
| 11 | Transfer AAPL 00000000… → 09215a47… | `000000000000000003ceb01a11f3c6e6` | 0.274350253333006056 |
| 13 | Transfer WETH 8bb3514e… → 09215a47… | `00000000000000000087438b8b1879a4` | 0.038073388469090724 |
| 14 | Transfer AAPL 09215a47… → 8bb3514e… | `000000000000000003ceb01a11f3c6e6` | 0.274350253333006056 |
| 16 | Uniswap v3 swap WETH/AAPL 0x8bb3514e, pool side | `ffffffffffffffffff78bc7474e7865c`, `000000000000000003ceb01a11f3c6e6` | -0.0380733884690907243 WETH, +0.2743502533 AAPL |
| 17 | Transfer WETH 09215a47… → 00000000… | `00000000000000000087438b8b1879a4` | 0.038073388469090724 |
| 18 | router fee event, token eeeeee…, (recipient, amount) | | [('a5503d92', 2734963731341), ('4abfdbac', 0)] |
| 20 | bot event: out of Fynd, paid into Fynd, profit | `00000000000005a1f792`, `000000872cbb64e5781c`, `0000000014535da855fb` | 94500754, 38048305219205148, 22348286154235 (raw units) |

1. Direction: bot sells eth.
2. Fynd fee: 9.6312997477e-08 ETH (bot event (inferred)) = $0.000239, 0.025 bp of $94.38. LPs get 80% = $0.000191, protocol $0.000048.
3. Router fee: 2.73496373134e-06 ETH + 0.000000 USDG = $0.006784.
4. Bot keeps +0.000022348286154235 ETH and +0.000000 USDG; the bot's own event says 2.23482861542349986e-05 (difference 0).
5. At Binance 2,480.64: gross $0.055438; gas 536,537 gas x 20,142,000 wei = 0.000010806928 ETH = $0.026808; net $0.028630.
6. LPs' swap side at execution $-0.116845, other venues $0.054384; fee + router fee + bot + LPs + other venues = $-1.26e-14.
7. Issues recorded: none.

## Ambiguous flow: a router fee paid in native ETH, recorded only in the router's own event

`0x91a789f6b2532e953a37d268b4c1d5916cbba35b16bf8f463129a8135b077dae`, block 87,487,774, 2026-10-13 11:48:08 UTC, completeness: **complete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 57 | Fynd FeesAccumulated (pays LPs for earlier swaps) | | 0.000000722622290348 ETH, 0.000000 USDG |
| 59 | Fynd swap, amount0 (ETH to pool) | `000000000000000001c862a4e2c542ac` | +0.128461049698796209 ETH |
| 59 | Fynd swap, amount1 (USDG to pool) | `ffffffffffffffffffffffffecd4c5bd` | -321.600067 USDG |
| 60 | Transfer USDG 00000000… → 7ea0ab3b… | `000000000000000000000000132b3a43` | 321.600067 |
| 62 | Transfer USDG 7ea0ab3b… → 8366a39c… | `000000000000000000000000132b3a43` | 321.600067 |
| 63 | Uniswap v4 swap WETH/USDG, swapper side | `000000000000000001c890b57300e660`, `ffffffffffffffffffffffffecd4c5bd` | +0.128511698372978267 WETH, -321.600067 USDG |
| 64 | Transfer WETH 8366a39c… → 09215a47… | `000000000000000001c890b57300e660` | 0.128511698372978267 |
| 65 | Transfer WETH 09215a47… → 00000000… | `000000000000000001c890b57300e660` | 0.128511698372978267 |
| 66 | router fee event, token eeeeee…, (recipient, amount) | | [('a5503d92', 13367926209924), ('4abfdbac', 0)] |
| 68 | bot event: out of Fynd, paid into Fynd, profit | `000000000000132b3a43`, `000001c8760fffa13054`, `000000000e7cfce17888` | 321600067, 128482400465399892, 15929981368456 (raw units) |

1. Direction: bot sells eth.
2. Fynd fee: 2.13507666037e-05 ETH (bot event (inferred)) = $0.053419, 1.662 bp of $321.41. LPs get 80% = $0.042735, protocol $0.010684.
3. Router fee: 1.33679262099e-05 ETH + 0.000000 USDG = $0.033446.
4. Bot keeps +0.000015929981368456 ETH and +0.000000 USDG; the bot's own event says 1.59299813684560012e-05 (difference 0).
5. At Binance 2,501.97: gross $0.039856; gas 394,816 gas x 20,498,000 wei = 0.000008092938 ETH = $0.020248; net $0.019608.
6. LPs' swap side at execution $-0.194374, other venues $0.067653; fee + router fee + bot + LPs + other venues = $7.29e-15.
7. Issues recorded: none.

## An incomplete transaction

`0x14f7ba7893739efdec879ae29df9eb44fbe1b8037ed21d8ec50e2bb201b8dde2`, block 111,066,430, 2026-11-10 17:45:44 UTC, completeness: **incomplete**

Raw values from the receipt:

| log | what | raw | = |
|---|---|---|---|
| 0 | Fynd FeesAccumulated (pays LPs for earlier swaps) | | 0.000092313198395527 ETH, 0.000000 USDG |
| 2 | Fynd swap, amount0 (ETH to pool) | `0000000000000000008a0164b46193f1` | +0.038845078820721649 ETH |
| 2 | Fynd swap, amount1 (USDG to pool) | `fffffffffffffffffffffffffb54473d` | -78.362819 USDG |
| 3 | Transfer USDG 00000000… → 7ea0ab3b… | `00000000000000000000000004abb8c3` | 78.362819 |
| 5 | Transfer SPY abe817af… → 09215a47… | `00000000000000000174e0e43f3939cf` | 0.104955962254244306 |
| 7 | Transfer USDG 7ea0ab3b… → abe817af… | `00000000000000000000000004abb8c3` | 78.362819 |
| 9 | Transfer WETH 3e1afde9… → 09215a47… | `0000000000000000008a0cbcab65746e` | 0.038857551255008366 |
| 10 | Transfer SPY 09215a47… → 3e1afde9… | `00000000000000000174e0e43f3939cf` | 0.104955962254244306 |
| 12 | Uniswap v3 swap WETH/SPY 0x3e1afde9, pool side | `ffffffffffffffffff75f343549a8b92`, `00000000000000000174e0e43f3939cf` | -0.0388575512550083657 WETH, +0.1049559623 SPY |
| 13 | Transfer WETH 09215a47… → 00000000… | `0000000000000000008a0cbcab65746e` | 0.038857551255008366 |
| 14 | router fee event, token eeeeee…, (recipient, amount) | | [('a5503d92', 0), ('4abfdbac', 0)] |
| 16 | bot event: out of Fynd, paid into Fynd, profit | `00000000000004abb8c3`, `0000008a0168b97e15e1`, `000000000b53f1e75e8d` | 78362819, 38845096086345185, 12455168663181 (raw units) |

1. Direction: bot sells eth.
2. Fynd fee: 1.7265623536e-08 ETH (bot event (inferred)) = $0.000035, 0.004 bp of $78.36. LPs get 80% = $0.000028, protocol $0.000007.
3. Router fee: 0 ETH + 0.000000 USDG = $0.000000.
4. Bot keeps +0.000012455168663181 ETH and +0.000000 USDG; the bot's own event says 1.24551686631810001e-05 (difference 0).
5. At Binance 2,017.29: gross $0.025126; gas 561,285 gas x 20,318,000 wei = 0.000011404189 ETH = $0.023006; net $0.002120.
6. LPs' swap side at execution $-0.001030, other venues $-78.386950; fee + router fee + bot + LPs + other venues = $-7.84e+01.
7. Issues recorded: unknown events: 0xabe817af 0x19b47279256b2a23.

## Residual inventory

No transaction left the bot holding anything but its profit token: 0 of 24,258 are classed 'complete, residual inventory'. The check is in decode.py (bot's change in the non-profit token, and intermediate tokens left with the bot or the router).
