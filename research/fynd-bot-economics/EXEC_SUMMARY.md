# Fynd ETH/USDG: what the bot made and where LP value went (summary)

Period: bot trades 2026-10-13 to 2026-11-13; LP results Oct 2 to Nov 13, 2026. 24,199 of the bot's 24,258 transactions fully rebuilt from chain data.

1. **LPs lost $3,925 against holding** (−15.1% per 30 days on ~$18,500): fees +$2,069, impermanent loss −$5,993.
2. **The bot made $295 net** (+$739 gross, −$443 gas). Each trade is an atomic round trip: Fynd, then other on-chain pools, no inventory kept.
3. **On the bot's trades, LPs' swap side was −$4,028** (Binance, 12 s). Of that, 58% went to the pools the bot hedged on, 18% to the bot,
   19% back as Fynd fees (80% to LPs, 20% protocol), 4% to router fees.
4. **The bot aligns the pool**, in the right direction 97.9% of the time, but only to within ~5 bp, the point where its on-chain hedge (≈4 bp)
   plus fees stops paying. It was idle >1 h 32 times.
5. **Why LPs lose:** each rebalance sells LP inventory at a stale price; the bot pays 1.7 bp in fees on a loss of ~9 bp, and the hedge
   pools collect most of the difference.
6. **Against Uniswap's WETH/USDG 0.01% pool**, Fynd's LPs lost less per unit of theoretical LVR (0.63 vs 0.96) but fees covered less of it
   (0.22 vs 0.70), so net they did worse. The advantage was large before Oct 22 and nearly gone after.
7. **What would help** (historical replays, not forecasts): cheaper hedging helps LPs, the bot and alignment together; a gap-linked bot fee shifts value to
   LPs at some cost to alignment; thresholds and size caps do not help. The protocol's 20% of fees (~$521) is a transfer lever.

Caveats: native-ETH legs are inferred (they match the bot's own on-chain figures in every transaction); reverted transactions are not
listable; USDG = $1; the brief's bot address (`0x6c6a…7127`) is the pool's largest LP in the data, not the bot.
