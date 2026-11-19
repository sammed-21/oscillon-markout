# Native ETH flow coverage

Robinhood Chain's public RPC exposes no `debug_trace*`/`trace_*` methods and no historical state (`eth_getBalance` at a past block
fails), and Blockscout's API is behind a browser challenge. Native ETH moves without logs, so this audit can see native ETH only where
a log or calldata describes it.

| flow | what is visible | status |
|---|---|---|
| bot trade profit in ETH (Fynd ETH/USDG pool, native ETH) | the bot contract's trade event (profit word) | *directly observed*: 0.208408 ETH over 15,280 trades |
| bot contract native balance | `eth_getBalance` at head only | *directly observed*: 0.047801 ETH |
| ETH that left the bot contract | nothing: no WETH transfer, no event | **0.160607 ETH *inferred* (profit − balance), path and recipient *not observable*** |
| Oct 23 swap proceeds to the bot sender | WETH burn log + `unwrapWETH9(min, recipient)` calldata | *inferred* recipient: 0.074066 ETH |
| Nov 11 swap proceeds to the bot sender | Ekubo swap log (ETH paid by the pool) + recipient word in calldata | *inferred* recipient: 0.051728 ETH |
| ETH attached to the Nov 10 call | tx value 0.069771; Ekubo swap consumed 0.000006905 | remainder *not observable* (refund or kept in Core) |
| owner_1 transactions without token logs | nonce count vs transactions seen: 34 sent, 25 seen, 2 contract creations identified by address | 7 (nonces 1, 2, 3, 4, 14, 26, 33) *not observable*; could include native ETH withdrawals via `withdrawToken` |
| owner_1 native balance | head only | 0.005640 ETH |
| bot sender funding and gas | gas per receipt (earlier audit); funding transfers are native | inflows *not observable* |

What this means: the ETH-side profit trail cannot be closed. The most economical reading (*inferred, unconfirmed*) is that the
0.1606 ETH also went to pay the bot's gas, as the observed USDG/AI/PONS proceeds did; nothing on chain contradicts or confirms it.
Missing logs are not proof that no transfer happened.
