# Hand checks

Open each transaction at `https://robinhoodchain.blockscout.com/tx/<hash>` (Logs tab) and compare.

## HC1 a withdrawal

`0x752a85c24edc3be14ceb94204238bb3c985fc8d4fd7e5e6c766b9dc8ab2910f7`, block 96,098,879, 2026-10-23 17:03:26 UTC, from owner_1 to the bot contract.

- Calldata: selector `0x3ccdbb28` = `withdrawToken(address,uint256,address)` (keccak of the signature; present in the bot's bytecode).
  Arguments: token `0x5fc5360d0400a0fd4f2af552add042d716f1d168`, amount 117,773,593, to `0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80`.
- Its only log:

| log | address | topic0 | topics | data |
|---|---|---|---|---|
| 35 | `0x5fc5360d0400a0fd4f2af552add042d716f1d168` | `0xddf252ad` | `0x…89bcacc7`, `0x…42e61c80` | `0x0000000000000000000000000000000000000000000000000000000007051519` |

- 117,773,593 raw USDG / 10^6 = **117.773593 USDG**, from the bot contract to owner_1. Same as the calldata.

## HC2 Oct 23 sale and the ETH recipient

`0xc70365c0c1b9fe66d6b54f0b770b2efbc288e2eefd8d17a6596b2df051858702` (owner_1 → Uniswap router `0xcaf6…`, `multicall`).

| log | address | topic0 | topics | data |
|---|---|---|---|---|
| 2 | `0x0bd7d308f8e1639fab988df18a8011f41eacad73` | `0xddf252ad` | `0x…a50271ca`, `0x…959e5cb2` | `0x00000000000000000000000000000000000000000000000000add9d77171e1fd` |
| 3 | `0x5fc5360d0400a0fd4f2af552add042d716f1d168` | `0xddf252ad` | `0x…42e61c80`, `0x…a50271ca` | `0x0000000000000000000000000000000000000000000000000000000007051519` |
| 4 | `0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca` | `0xc42079f9` | `0x…959e5cb2`, `0x…959e5cb2` | `0xffffffffffffffffffffffffffffffffffffffffffffffffff5226288e8e1e0300000000…` |
| 5 | `0x0bd7d308f8e1639fab988df18a8011f41eacad73` | `0xddf252ad` | `0x…959e5cb2`, `0x…00000000` | `0x00000000000000000000000000000000000000000000000000add9d77171e1fd` |

- USDG 117.773593 from owner_1 into `0x52e6…` (WETH/USDG 0.01%); the pool pays 0.048934690 WETH to the router; the router
  burns that WETH (Transfer to 0x0 = unwrap).
- Inner call `0x49404b7c` = `unwrapWETH9(uint256 amountMinimum, address recipient)`; recipient word:
  `0000000000000000000000004abfdbac0afa181338dc9c38c9c1264128c684a2` = **bot sender `0x4abf…84a2`**. The ETH payment itself has no log.

## HC3 the Nov 10 transaction

`0x52c5a595105e8ac74f933aed5acd447eacf94f64d0d1f168d556e28c1b7b5fc7` (owner_1 → `0x5cec…855d`, value 0.069770562 ETH). Fynd ETH/USDG leg:

| log | address | topic0 | topics | data |
|---|---|---|---|---|
| 0 | `0x00000000000014aa86c5d3c41765bb24e11bd701` | `0xf7e050d8` |  | `0xb67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf8377354600000000…` |
| 1 | `0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09` | `0xd59d72ec` | `0x…83773546` | `0x4f2826f91f74c315aac59eb091c4178f913d03126af321823333333333333333` |
| 2 | `0x00000000000014aa86c5d3c41765bb24e11bd701` | `anonymous` |  | `0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09b67e0601a0363a1ad259dd848cad1c52…` |
| 3 | `0x5fc5360d0400a0fd4f2af552add042d716f1d168` | `0xddf252ad` | `0x…42e61c80`, `0x…e11bd701` | `0x00000000000000000000000000000000000000000000000000000000072754a8` |
| 4 | `0x5cec1a197e0a0213287a9750f1ba25c60ac2855d` | `0xbdb6d4ff` | `0x…83773546`, `0x…42e61c80` | `0x0000000000000000000000005fc5360d0400a0fd4f2af552add042d716f1d16800000000…` |
| 5 | `0x00000000000014aa86c5d3c41765bb24e11bd701` | `anonymous` |  | `0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09b67e0601a0363a1ad259dd848cad1c52…` |
| 6 | `0x5fc5360d0400a0fd4f2af552add042d716f1d168` | `0xddf252ad` | `0x…e11bd701`, `0x…42e61c80` | `0x00000000000000000000000000000000000000000000000000000000000037db` |
| 7 | `0x5cec1a197e0a0213287a9750f1ba25c60ac2855d` | `0xbdb6d4ff` | `0x…83773546`, `0x…42e61c80` | `0x000000000000000000000000000000000000000000000000000000000000000000000000…` |

- USDG Transfer owner_1 → Core: 120,018,088 raw = 120.018088 USDG.
- Ekubo swap (anonymous Core log, pool `b67e0601…`): amount1 = data[136:168] = +12,000 raw = **0.012 USDG** received by the pool.
- `0x5cec` event: (USDG, 120,018,088, 5,794,777,164,829) = its own report of 120.018088 in, 0.0000058 ETH out.
- 120.018088 − 0.012 = **120.006 USDG** paid into Core and not swapped, not returned in the transaction, no PositionUpdated.

## HC4 Nov 11 swap and its recipient

`0x493b84ee35ae5cdb78ed8a6b3d4cc9ee0ceecc5b463d00498b792a68b49d2edf` (owner_1 → router `0x0921…`): USDG 106.308022 into Core; Ekubo swap on `b67e0601…` with amount0 =
0.051727733 ETH paid by the pool; calldata word 6 = `0000000000000000000000004abfdbac0afa181338dc9c38c9c1264128c684a2`
= **bot sender**.

## HC5 USDG reconciliation (bot contract)

profit events 517.896502 − withdrawn 382.775621 − balance 135.120881 = 0.000000 USDG.

## HC6 owner_1 created the contracts

keccak256(rlp([owner_1, n]))[12:] for n = 0, 15, 30 gives `0x7ea0…acc7`, `0x5cec…855d`, `0x0d41…d4b2`; each has code at head
(`data/contracts.json`). Any RLP/keccak tool reproduces it.
