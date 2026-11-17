# Audit hand checks

Six transactions, picked by rule (`audit/write_audit.py`), traced from the raw receipt (`data/bot_txs.jsonl`) to every column of
`top_panel_transaction_reconciliation.csv`. Amounts: + = that party received. ETH = native ETH or WETH. Prices: Binance ETHUSDC
1 s, close of the candle opening at T-2 ("at execution") and at T+12 ("12 s"). U = Uniswap v3 0.01% price after its last swap
in an earlier transaction.

## H1 bot pays ETH into Fynd, one Uniswap v4 hedge

`0xb86aca46b00aeb7aa68b684116a8af082430b10ae1ccceef4bf2218350b5a5db`, block 96,287,847, 2026-10-23 22:32:10 UTC, status 1

Raw logs used:

| log | address | what | raw values |
|---|---|---|---|
| 0 | Ekubo Core | FeesAccumulated (pays LPs fees accrued before this tx) | ETH 14,800,250,540,148, USDG 0 |
| 2 | Ekubo Core | swap, pool b67e0601a036… | amount0 85,847,984,786,428,060, amount1 -204,674,212 (pool received) |
| 3 | 0x5fc5360d… | Transfer | 0x00000000… → 0x7ea0ab3b…: 204,674,212 |
| 5 | 0x5fc5360d… | Transfer | 0x7ea0ab3b… → 0x8366a39c…: 204,674,212 |
| 6 | PoolManager | Uniswap v4 Swap, pool 0x84bd4e2d8b… | amount0 85,876,709,692,086,590, amount1 -204,674,212 (swapper's side), fee 252 pips |
| 7 | 0x0bd7d308… | Transfer | 0x8366a39c… → 0x09215a47…: 85,876,709,692,086,590 |
| 8 | 0x0bd7d308… | Transfer | 0x09215a47… → 0x00000000…: 85,876,709,692,086,590 |
| 9 | router | fee event, token 0xeeeeeeee… | 0xa5503d92…: 0, 0x4abfdbac…: 0 |
| 11 | bot contract | bot event | word1 204,674,212, word2 85,861,404,736,303,984, word3 (profit) 15,304,955,782,606 |

gasUsed 387,774 × effectiveGasPrice 20,018,000 wei = 0.000007762460 ETH

| quantity | formula | value |
|---|---|---|
| Fynd pool received | Fynd swap amounts | +0.085847985 ETH, -204.674212 USDG |
| Fynd execution price | abs(USDG / ETH) | 2,384.1470 |
| Binance at execution / 12 s / U | | 2,383.02 / 2,383.86 / 2,382.4987 |
| Fynd fee | bot event: word2 - ETH received by Fynd (bot's own report) | 0.000013419950 ETH, 0.000000 USDG |
| LP swap side, 12 s | ETH × B12 + USDG | -0.024635 |
| fee credited to LPs, 12 s | 0.8 × fee | +0.025593 |
| LP net, 12 s | sum of the two | +0.000958 |
| hedge pools received | sum over hedge legs | -0.085876710 ETH, +204.674212 USDG (uniswap_v4:0x84bd4e2d) |
| hedge pools' result, 12 s | ETH × B12 + USDG | -0.043841 |
| router fee | router event, non-bot recipients | 0.000000000000 ETH, 0.000000 USDG; 12 s +0.000000 |
| Fynd 20% | 0.2 × fee | +0.006398 |
| bot change | −(pools' receipts) − fee − router | +0.000015304956 ETH, +0.000000 USDG |
| check C1: USDG from Transfer logs − bot change | | 0 raw |
| check C2: bot event profit − bot change in the token it paid | | 0 raw |
| check C3: token not paid in, left with the bot | | 0 raw |
| bot gross, at execution / 12 s | ETH × B + USDG | +0.036472 / +0.036485 |
| gas | gas ETH × B at execution | 0.018498 |
| bot net, at execution | gross − gas | +0.017974 |
| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | +2.50e-16 |

## H2 bot pays USDG into Fynd, one Uniswap v3 hedge

`0x13d93dc00f75a820a2b795394eef5a5c0fb2886cf7c46428073c232f2d6530bb`, block 112,121,048, 2026-11-12 00:31:15 UTC, status 1

Raw logs used:

| log | address | what | raw values |
|---|---|---|---|
| 33 | Ekubo Core | FeesAccumulated (pays LPs fees accrued before this tx) | ETH 0, USDG 7,616 |
| 35 | Ekubo Core | swap, pool b67e0601a036… | amount0 -72,660,371,934,616,450, amount1 149,774,035 (pool received) |
| 36 | 0x0bd7d308… | Transfer | 0x00000000… → 0x09215a47…: 72,660,371,934,616,450 |
| 37 | 0x5fc5360d… | Transfer | 0x16679e2a… → 0x09215a47…: 149,803,540 |
| 38 | 0x0bd7d308… | Transfer | 0x09215a47… → 0x16679e2a…: 72,660,371,934,616,450 |
| 39 | 0x16679e2a… | Uniswap v3 Swap | amount0 72,660,371,934,616,450, amount1 -149,803,540, sqrtPriceX96 3597487398446769503598486, L 65180880478201563 |
| 40 | router | fee event, token 0x5fc5360d… | 0xa5503d92…: 0, 0x4abfdbac…: 0 |
| 41 | 0x5fc5360d… | Transfer | 0x09215a47… → 0x7ea0ab3b…: 149,803,540 |
| 42 | 0x5fc5360d… | Transfer | 0x7ea0ab3b… → 0x00000000…: 149,782,340 |
| 43 | bot contract | bot event | word1 72,660,371,934,616,450, word2 149,782,340, word3 (profit) 21,200 |

gasUsed 500,668 × effectiveGasPrice 20,014,000 wei = 0.000010020369 ETH

| quantity | formula | value |
|---|---|---|
| Fynd pool received | Fynd swap amounts | -0.072660372 ETH, +149.774035 USDG |
| Fynd execution price | abs(USDG / ETH) | 2,061.2891 |
| Binance at execution / 12 s / U | | 2,062.53 / 2,062.75 / 2,062.2074 |
| Fynd fee | observed: USDG into Core - USDG received by Ekubo legs | 0.000000000000 ETH, 0.008305 USDG |
| LP swap side, 12 s | ETH × B12 + USDG | -0.106147 |
| fee credited to LPs, 12 s | 0.8 × fee | +0.006644 |
| LP net, 12 s | sum of the two | -0.099503 |
| hedge pools received | sum over hedge legs | +0.072660372 ETH, -149.803540 USDG (uniswap_v3:0x16679e2a) |
| hedge pools' result, 12 s | ETH × B12 + USDG | +0.076642 |
| router fee | router event, non-bot recipients | 0.000000000000 ETH, 0.000000 USDG; 12 s +0.000000 |
| Fynd 20% | 0.2 × fee | +0.001661 |
| bot change | −(pools' receipts) − fee − router | +0.000000000000 ETH, +0.021200 USDG |
| check C1: USDG from Transfer logs − bot change | | 0 raw |
| check C2: bot event profit − bot change in the token it paid | | 0 raw |
| check C3: token not paid in, left with the bot | | 0 raw |
| bot gross, at execution / 12 s | ETH × B + USDG | +0.021200 / +0.021200 |
| gas | gas ETH × B at execution | 0.020667 |
| bot net, at execution | gross − gas | +0.000533 |
| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | -3.37e-16 |

## H3 multi-hop hedge (3+ legs)

`0xc4495d64f2fc49f1e68b7dc7e0d4e6462b0ccf3e2a2ae5d8380a2bf14c70eaf5`, block 101,245,815, 2026-10-29 22:27:50 UTC, status 1

Raw logs used:

| log | address | what | raw values |
|---|---|---|---|
| 103 | Ekubo Core | swap, pool b67e0601a036… | amount0 -17,729,862,330,541,554, amount1 40,208,962 (pool received) |
| 104 | 0x0bd7d308… | Transfer | 0x00000000… → 0x09215a47…: 17,729,862,330,541,554 |
| 105 | 0xd0601ce1… | Transfer | 0x62ab521f… → 0x09215a47…: 191,521,273,976,966,021 |
| 107 | 0x0bd7d308… | Transfer | 0x09215a47… → 0x62ab521f…: 17,729,862,330,541,554 |
| 108 | 0x62ab521f… | Uniswap v3 Swap | amount0 17,729,862,330,541,554, amount1 -191,521,273,976,966,021, sqrtPriceX96 260461031972586628707410625342, L 10065218697356013166844 |
| 109 | 0x117cc213… | Transfer | 0x55942b9b… → 0x09215a47…: 52,568,089,786,656,396 |
| 111 | 0xd0601ce1… | Transfer | 0x09215a47… → 0x55942b9b…: 191,521,273,976,966,021 |
| 113 | 0x55942b9b… | Uniswap v3 Swap | amount0 -52,568,089,786,656,396, amount1 191,521,273,976,966,021, sqrtPriceX96 151338335105492411626379582345, L 50592442565909173625 |
| 114 | 0x117cc213… | Transfer | 0x09215a47… → 0x00000000…: 52,568,089,786,656,396 |
| 117 | Ekubo Core | swap, pool f4d3b239be7f… | amount0 52,568,089,786,656,396, amount1 -40,276,913 (pool received) |
| 119 | 0x5fc5360d… | Transfer | 0x00000000… → 0x09215a47…: 40,256,734 |
| 120 | router | fee event, token 0x5fc5360d… | 0xa5503d92…: 0, 0x4abfdbac…: 0 |
| 121 | 0x5fc5360d… | Transfer | 0x09215a47… → 0x7ea0ab3b…: 40,256,734 |
| 122 | 0x5fc5360d… | Transfer | 0x7ea0ab3b… → 0x00000000…: 40,238,339 |
| 123 | bot contract | bot event | word1 17,729,862,330,541,554, word2 40,238,339, word3 (profit) 18,395 |

gasUsed 639,165 × effectiveGasPrice 21,192,000 wei = 0.000013545185 ETH

| quantity | formula | value |
|---|---|---|
| Fynd pool received | Fynd swap amounts | -0.017729862 ETH, +40.208962 USDG |
| Fynd execution price | abs(USDG / ETH) | 2,267.8666 |
| Binance at execution / 12 s / U | | 2,274.95 / 2,274.30 / 2,274.8000 |
| Fynd fee | observed: USDG into Core - USDG received by Ekubo legs | 0.000000000000 ETH, 0.049556 USDG |
| LP swap side, 12 s | ETH × B12 + USDG | -0.114064 |
| fee credited to LPs, 12 s | 0.8 × fee | +0.039645 |
| LP net, 12 s | sum of the two | -0.074419 |
| hedge pools received | sum over hedge legs | +0.017729862 ETH, -40.276913 USDG (uniswap_v3:0x62ab521f+uniswap_v3:0x55942b9b+ekubo:f4d3b239be) |
| hedge pools' result, 12 s | ETH × B12 + USDG | +0.046113 |
| router fee | router event, non-bot recipients | 0.000000000000 ETH, 0.000000 USDG; 12 s +0.000000 |
| Fynd 20% | 0.2 × fee | +0.009911 |
| bot change | −(pools' receipts) − fee − router | +0.000000000000 ETH, +0.018395 USDG |
| check C1: USDG from Transfer logs − bot change | | 0 raw |
| check C2: bot event profit − bot change in the token it paid | | 0 raw |
| check C3: token not paid in, left with the bot | | 0 raw |
| bot gross, at execution / 12 s | ETH × B + USDG | +0.018395 / +0.018395 |
| gas | gas ETH × B at execution | 0.030815 |
| bot net, at execution | gross − gas | -0.012420 |
| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | -7.56e-16 |

## H4 hedge through an Ekubo stock pool whose extension keeps part of the output

`0x5a99ed06caa6e4d9611ceace7f06d961bbdec0ed2c3d7ede48a52e4b998a4c2b`, block 87,642,452, 2026-10-13 16:07:44 UTC, status 1

Raw logs used:

| log | address | what | raw values |
|---|---|---|---|
| 0 | Ekubo Core | FeesAccumulated (pays LPs fees accrued before this tx) | ETH 10,799,763,531,059, USDG 0 |
| 2 | Ekubo Core | swap, pool b67e0601a036… | amount0 70,249,392,817,251,939, amount1 -176,861,156 (pool received) |
| 3 | 0x5fc5360d… | Transfer | 0x00000000… → 0x7ea0ab3b…: 176,861,156 |
| 5 | 0x5fc5360d… | Transfer | 0x7ea0ab3b… → 0x00000000…: 176,861,156 |
| 7 | Ekubo Core | swap, pool 74044daecd99… | amount0 -1,123,714,582,228,727,539, amount1 176,861,156 (pool received) |
| 9 | 0x4a0e65a3… | Transfer | 0x00000000… → 0x09215a47…: 1,120,804,389,103,331,628 |
| 11 | 0x0bd7d308… | Transfer | 0xc3c9f017… → 0x09215a47…: 70,268,505,332,958,773 |
| 12 | 0x4a0e65a3… | Transfer | 0x09215a47… → 0xc3c9f017…: 1,120,804,389,103,331,628 |
| 14 | 0xc3c9f017… | Uniswap v3 Swap | amount0 -70,268,505,332,958,773, amount1 1,120,804,389,103,331,628, sqrtPriceX96 316349468304018666258132110993, L 5264660369342127739500 |
| 15 | 0x0bd7d308… | Transfer | 0x09215a47… → 0x00000000…: 70,268,505,332,958,773 |
| 16 | router | fee event, token 0xeeeeeeee… | 0xa5503d92…: 0, 0x4abfdbac…: 0 |
| 18 | bot contract | bot event | word1 176,861,156, word2 70,249,392,817,251,939, word3 (profit) 19,112,515,706,834 |

gasUsed 533,649 × effectiveGasPrice 20,822,000 wei = 0.000011111639 ETH

| quantity | formula | value |
|---|---|---|
| Fynd pool received | Fynd swap amounts | +0.070249393 ETH, -176.861156 USDG |
| Fynd execution price | abs(USDG / ETH) | 2,517.6183 |
| Binance at execution / 12 s / U | | 2,515.67 / 2,517.52 / 2,515.6971 |
| Fynd fee | bot event: word2 - ETH received by Fynd (bot's own report) | 0.000000000000 ETH, 0.000000 USDG |
| LP swap side, 12 s | ETH × B12 + USDG | -0.006905 |
| fee credited to LPs, 12 s | 0.8 × fee | +0.000000 |
| LP net, 12 s | sum of the two | -0.006905 |
| hedge pools received | sum over hedge legs | -0.070268505 ETH, +176.861156 USDG (ekubo:74044daecd+uniswap_v3:0xc3c9f017) |
| hedge pools' result, 12 s | ETH × B12 + USDG | -0.041212 |
| router fee | router event, non-bot recipients | 0.000000000000 ETH, 0.000000 USDG; 12 s +0.000000 |
| Fynd 20% | 0.2 × fee | +0.000000 |
| bot change | −(pools' receipts) − fee − router | +0.000019112516 ETH, +0.000000 USDG |
| check C1: USDG from Transfer logs − bot change | | 0 raw |
| check C2: bot event profit − bot change in the token it paid | | 0 raw |
| check C3: token not paid in, left with the bot | | 0 raw |
| bot gross, at execution / 12 s | ETH × B + USDG | +0.048081 / +0.048116 |
| gas | gas ETH × B at execution | 0.027953 |
| bot net, at execution | gross − gas | +0.020128 |
| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | -3.64e-14 |
| intermediate token kept by a venue (C4) | | {"0x4a0e65a3eccec6dbe60ae065f2e7bb85fae35eea": -2910193125395911} |

## H5 USDG kept by another Ekubo pool counted as Fynd fee (FeesAccumulated check fails)

`0xedbc37927446f3e9d08fbff5016071510a0fede23f9ec2fe1f0cc76966a1165d`, block 88,874,956, 2026-10-15 02:42:43 UTC, status 1

Raw logs used:

| log | address | what | raw values |
|---|---|---|---|
| 0 | Ekubo Core | FeesAccumulated (pays LPs fees accrued before this tx) | ETH 16,104,262,807,707,424, USDG 0 |
| 2 | Ekubo Core | swap, pool b67e0601a036… | amount0 -348,810,675,970,953,622, amount1 819,889,443 (pool received) |
| 3 | 0x0bd7d308… | Transfer | 0x00000000… → 0x09215a47…: 348,810,675,970,953,622 |
| 4 | 0x117cc213… | Transfer | 0xddcbba36… → 0x09215a47…: 1,076,617,440,623,889,834 |
| 6 | 0x0bd7d308… | Transfer | 0x09215a47… → 0xddcbba36…: 348,810,675,970,953,622 |
| 7 | 0xddcbba36… | Uniswap v3 Swap | amount0 348,810,675,970,953,622, amount1 -1,076,617,440,623,889,834, sqrtPriceX96 139220714244724373617922640204, L 6602954515242427068276 |
| 8 | 0x117cc213… | Transfer | 0x09215a47… → 0x8366a39c…: 1,076,617,440,623,889,834 |
| 10 | PoolManager | Uniswap v4 Swap, pool 0x6d0f670695… | amount0 -1,076,617,440,623,889,834, amount1 2,414,365,289,154,519,834 (swapper's side), fee 315 pips |
| 11 | 0x2e0847e8… | Transfer | 0x8366a39c… → 0x09215a47…: 2,414,365,289,154,519,834 |
| 13 | 0x2e0847e8… | Transfer | 0x09215a47… → 0x00000000…: 2,414,365,289,154,519,834 |
| 16 | Ekubo Core | swap, pool ca54afd48dd9… | amount0 2,414,365,289,154,519,834, amount1 -824,076,174 (pool received) |
| 18 | 0x5fc5360d… | Transfer | 0x00000000… → 0x09215a47…: 823,664,135 |
| 19 | router | fee event, token 0x5fc5360d… | 0xa5503d92…: 0, 0x4abfdbac…: 0 |
| 20 | 0x5fc5360d… | Transfer | 0x09215a47… → 0x7ea0ab3b…: 823,664,135 |
| 21 | 0x5fc5360d… | Transfer | 0x7ea0ab3b… → 0x00000000…: 823,586,159 |
| 22 | bot contract | bot event | word1 348,810,675,970,953,622, word2 823,586,159, word3 (profit) 77,976 |

gasUsed 796,031 × effectiveGasPrice 21,312,000 wei = 0.000016965013 ETH

| quantity | formula | value |
|---|---|---|
| Fynd pool received | Fynd swap amounts | -0.348810676 ETH, +819.889443 USDG |
| Fynd execution price | abs(USDG / ETH) | 2,350.5285 |
| Binance at execution / 12 s / U | | 2,372.54 / 2,370.00 / 2,371.6616 |
| Fynd fee | observed: USDG into Core - USDG received by Ekubo legs | 0.000000000000 ETH, 4.108755 USDG |
| LP swap side, 12 s | ETH × B12 + USDG | -6.791859 |
| fee credited to LPs, 12 s | 0.8 × fee | +3.287004 |
| LP net, 12 s | sum of the two | -3.504855 |
| hedge pools received | sum over hedge legs | +0.348810676 ETH, -824.076174 USDG (uniswap_v3:0xddcbba36+uniswap_v4:0x6d0f6706+ekubo:ca54afd48d) |
| hedge pools' result, 12 s | ETH × B12 + USDG | +2.605128 |
| router fee | router event, non-bot recipients | 0.000000000000 ETH, 0.000000 USDG; 12 s +0.000000 |
| Fynd 20% | 0.2 × fee | +0.821751 |
| bot change | −(pools' receipts) − fee − router | +0.000000000000 ETH, +0.077976 USDG |
| check C1: USDG from Transfer logs − bot change | | 0 raw |
| check C2: bot event profit − bot change in the token it paid | | 0 raw |
| check C3: token not paid in, left with the bot | | 0 raw |
| bot gross, at execution / 12 s | ETH × B + USDG | +0.077976 / +0.077976 |
| gas | gas ETH × B at execution | 0.040250 |
| bot net, at execution | gross − gas | +0.037726 |
| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | -8.88e-15 |
| the FeesAccumulated that pays this swap's fee | next FA after the swap | USDG 2.957372 |
| 0.8 × fee computed here | | 3.287004: the computed fee is 0.412040 USDG too high |

## H6 incomplete: a venue whose events cannot be decoded

`0x14f7ba7893739efdec879ae29df9eb44fbe1b8037ed21d8ec50e2bb201b8dde2`, block 111,066,430, 2026-11-10 17:45:44 UTC, status 1

Raw logs used:

| log | address | what | raw values |
|---|---|---|---|
| 0 | Ekubo Core | FeesAccumulated (pays LPs fees accrued before this tx) | ETH 92,313,198,395,527, USDG 0 |
| 2 | Ekubo Core | swap, pool b67e0601a036… | amount0 38,845,078,820,721,649, amount1 -78,362,819 (pool received) |
| 3 | 0x5fc5360d… | Transfer | 0x00000000… → 0x7ea0ab3b…: 78,362,819 |
| 5 | 0x117cc213… | Transfer | 0xabe817af… → 0x09215a47…: 104,955,962,254,244,303 |
| 7 | 0x5fc5360d… | Transfer | 0x7ea0ab3b… → 0xabe817af…: 78,362,819 |
| 9 | 0x0bd7d308… | Transfer | 0x3e1afde9… → 0x09215a47…: 38,857,551,255,008,366 |
| 10 | 0x117cc213… | Transfer | 0x09215a47… → 0x3e1afde9…: 104,955,962,254,244,303 |
| 12 | 0x3e1afde9… | Uniswap v3 Swap | amount0 -38,857,551,255,008,366, amount1 104,955,962,254,244,303, sqrtPriceX96 130209077723967291841945008375, L 409756952261212527919 |
| 13 | 0x0bd7d308… | Transfer | 0x09215a47… → 0x00000000…: 38,857,551,255,008,366 |
| 14 | router | fee event, token 0xeeeeeeee… | 0xa5503d92…: 0, 0x4abfdbac…: 0 |
| 16 | bot contract | bot event | word1 78,362,819, word2 38,845,096,086,345,185, word3 (profit) 12,455,168,663,181 |

gasUsed 561,285 × effectiveGasPrice 20,318,000 wei = 0.000011404189 ETH

| quantity | formula | value |
|---|---|---|
| Fynd pool received | Fynd swap amounts | +0.038845079 ETH, -78.362819 USDG |
| Fynd execution price | abs(USDG / ETH) | 2,017.3165 |
| Binance at execution / 12 s / U | | 2,017.29 / 2,016.35 / 2,016.6913 |
| Fynd fee | bot event: word2 - ETH received by Fynd (bot's own report) | 0.000000017266 ETH, 0.000000 USDG |
| LP swap side, 12 s | ETH × B12 + USDG | -0.037544 |
| fee credited to LPs, 12 s | 0.8 × fee | +0.000028 |
| LP net, 12 s | sum of the two | -0.037516 |
| hedge pools received | sum over hedge legs | -0.038857551 ETH, +0.000000 USDG (uniswap_v3:0x3e1afde9) |
| hedge pools' result, 12 s | ETH × B12 + USDG | -78.350423 |
| router fee | router event, non-bot recipients | 0.000000000000 ETH, 0.000000 USDG; 12 s +0.000000 |
| Fynd 20% | 0.2 × fee | +0.000007 |
| bot change | −(pools' receipts) − fee − router | +0.000012455169 ETH, +78.362819 USDG |
| check C1: USDG from Transfer logs − bot change | | -78362819 raw |
| check C2: bot event profit − bot change in the token it paid | | 0 raw |
| check C3: token not paid in, left with the bot | | 78362819 raw |
| bot gross, at execution / 12 s | ETH × B + USDG | +78.387945 / +78.387933 |
| gas | gas ETH × B at execution | 0.023006 |
| bot net, at execution | gross − gas | +78.364939 |
| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | +5.14e-15 |
| intermediate token kept by a venue (C4) | | {"0x117cc2133c37b721f49de2a7a74833232b3b4c0c": 104955962254244303} |
| not reconciled | | unknown events: 0xabe817af 0x19b47279 |
