# Fynd ETH/USDG: what LPs, Fynd and the bot made, and what to change

Oct 2 – Nov 13, 2026. All 24,258 bot trades rebuilt from chain data (24,199 completely).

**What each party made**
- **Independent LPs** (all except `0x6c6a…7127`): −$728 against holding, −6.5% per 30 days on ~$7,970. Ownership unresolved.
- **`0x6c6a…7127`** (Fynd's, per Edouard): −$3,197, −21.7% per 30 days.
- **Fynd's 20% owner fee:** ~$521 ($152 of it paid by Fynd's own bot). The LPs' $2,069 of fees is their 80% share.
- **The bot:** +$283 net after all measurable costs (+$739 gross, −$443 gas). Its USDG profits were withdrawn to its owner `0xd7c8…1c80`.

**Where the LPs' loss on bot trades went** (−$4,028 at Binance 12 s): 58% to the pools the bot hedged on (on the 21,764 trades where it can be split,
$899 is their fees; the rest is price impact, their own mispricing, basis and price moves); 18% to the bot; 19% back as Fynd fees; 4% router fees.

**Why the bot stops ~5 bp short:** it trades until the next unit stops paying. That point is set by its hedge: fees (~2.6 bp on the last unit),
its own impact on thin hedge pools (~1.8 bp) and those pools being off the market (~0.9 bp).

**The Oct 22 change** was really Oct 17. Fynd's low loss/LVR early on came from days when nobody arbitraged the pool; with the bot running, Fynd and
Uniswap look similar. No configuration change was found.

**Recommendations, ranked**
1. **Hedge on the deepest pool.** The bot never used Uniswap's WETH/USDG 0.01% pool; it would have cost 0.3 bp instead of 4.3 bp against Binance.
2. **Then raise the bot's fee to ~3–4 bp.** With hedging at 1 bp and a 4 bp fee, LPs lose $1,064 less over the month in the
   replay, with the bot's profit about unchanged.
3. **Keep the bot on and reacting fast** once 1 and 2 are in place: all three together improve LPs, the bot and price alignment in the replay.

Replays hold traders' and routers' behaviour fixed; test each step live. No conclusion is drawn on whether Fynd's design beats Uniswap's.
