"""
Write hand_checks/HAND_CHECKS.md: for a few chosen bot transactions, every raw log value used, how it becomes each
number in bot_transaction_economics.csv, and the cast command to fetch the same receipt yourself.

  python3 hand_checks.py --txs data/bot_txs.jsonl --meta data/meta.json --out out
"""
import argparse, json, os
import pandas as pd
from decode import decode, economics, s128, s256, CORE, PM, FYND_POOL, NATIVE, USDG, WETH, BOT_CONTRACT, ROUTER, T_BOT, T_ROUTER

ap = argparse.ArgumentParser()
ap.add_argument("--txs", required=True); ap.add_argument("--meta", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
meta = json.load(open(a.meta))
E = pd.read_csv(os.path.join(a.out, "bot_transaction_economics.csv"))
C = E[E.completeness.str.startswith("complete")]
pick = [
    ("A normal profitable trade (the bot EOA's first, nonce 0)", "0x21baf60f981b95f5b96b15efdcdb04d12cf4b7e0a45be61e494a87fd4c59542e"),
    ("Bot buys ETH from Fynd: the Fynd fee is visible as a USDG transfer", "0x6863b1c049e427d51edf2586814a252208b6a18a3b514a42fe905bf7191d0b4e"),
    ("Negative after gas: the most negative net result", C.sort_values("bot_net_usd").tx_hash.iloc[0]),
    ("Several routing legs, an intermediate token that must net to zero", "0x02404683855a01c6dd8553a8f84c4bd034adfd006c6590a2f70cef62f4539f23"),
    ("A route through a tokenized-stock pool whose extension keeps part of the output", "0x5dc6a7ad7f0bca7dbbd22c1c8f3c075192baf9b1a6dbf20b3c4bffbcf46c514d"),
    ("Ambiguous flow: a router fee paid in native ETH, recorded only in the router's own event", "0x91a789f6b2532e953a37d268b4c1d5916cbba35b16bf8f463129a8135b077dae"),
]
inc = E[~E.completeness.str.startswith("complete")]
if len(inc):
    pick.append(("An incomplete transaction", inc.tx_hash.iloc[0]))
want = {h for _, h in pick}
raw = {}
for line in open(a.txs):
    x = json.loads(line)
    h = x["receipt"]["transactionHash"]
    if h in want:
        raw[h] = x
sym = lambda t: "ETH" if t == NATIVE else (meta["tokens"].get(t, {}).get("symbol") or t[:10])
dec = lambda t: 18 if t == NATIVE else (meta["tokens"].get(t, {}).get("decimals") or 18)
md = ["# Hand checks: bot transactions\n",
      "Each check uses only the transaction receipt and the conversions shown. To fetch a receipt yourself:\n",
      "```\ncast receipt <tx_hash> --rpc-url https://rpc.mainnet.chain.robinhood.com --json\n```\n",
      "Conventions. Amounts are from the receiving side: + = that pool or wallet received. Ekubo's swap log is anonymous, "
      "116 bytes: locker (20) | poolId (32) | amount0 int128 (16) | amount1 int128 (16) | price and liquidity (32). "
      "Uniswap v4's Swap event reports the swapper's side, so its signs are flipped. ETH has 18 decimals, USDG 6. "
      "The bot contract's own event (topic 0xed370fed) has words: poolId | amount out of Fynd | amount paid into Fynd "
      "including the Fynd fee | profit, in the token the bot paid in.\n"]
for title, h in pick:
    if h not in raw:
        md.append(f"## {title}\n\n`{h}`: receipt not in the fetched data.\n"); continue
    x = raw[h]; d = decode(x["tx"], x["receipt"], meta); e = economics(d)
    row = E[E.tx_hash == h].iloc[0]
    md.append(f"## {title}\n\n`{h}`, block {d['block']:,}, {pd.Timestamp(d['ts'], unit='s')} UTC, completeness: **{row.completeness}**\n")
    md.append("Raw values from the receipt:\n")
    md.append("| log | what | raw | = |\n|---|---|---|---|")
    for l in x["receipt"]["logs"]:
        ad, t, dd, li = l["address"].lower(), l["topics"], l["data"][2:], int(l["logIndex"], 16)
        if ad == CORE and not t and dd[40:104] == FYND_POOL:
            md.append(f"| {li} | Fynd swap, amount0 (ETH to pool) | `{dd[104:136]}` | {s128(dd[104:136]) / 1e18:+.18f} ETH |")
            md.append(f"| {li} | Fynd swap, amount1 (USDG to pool) | `{dd[136:168]}` | {s128(dd[136:168]) / 1e6:+.6f} USDG |")
        elif t and t[0].startswith("0xddf252ad") and len(t) == 3:
            md.append(f"| {li} | Transfer {sym(ad)} {t[1][-40:][:8]}… → {t[2][-40:][:8]}… | `{dd[-32:]}` | {int(dd, 16) / 10 ** dec(ad):.{min(dec(ad), 18)}f} |")
        elif t and t[0].startswith("0x40e9cecb"):
            p = meta["v4"][t[1]]
            md.append(f"| {li} | Uniswap v4 swap {sym(p['currency0'])}/{sym(p['currency1'])}, swapper side | `{dd[32:64]}`, `{dd[96:128]}` | "
                      f"{s128(dd[32:64]) / 10 ** dec(p['currency0']):+.18g} {sym(p['currency0'])}, {s128(dd[96:128]) / 10 ** dec(p['currency1']):+.10g} {sym(p['currency1'])} |")
        elif t and t[0].startswith("0xc42079f9"):
            p = meta["v3"][ad]
            md.append(f"| {li} | Uniswap v3 swap {sym(p['token0'])}/{sym(p['token1'])} {ad[:10]}, pool side | `{dd[0:64][-32:]}`, `{dd[64:128][-32:]}` | "
                      f"{s256(dd[0:64]) / 10 ** dec(p['token0']):+.18g} {sym(p['token0'])}, {s256(dd[64:128]) / 10 ** dec(p['token1']):+.10g} {sym(p['token1'])} |")
        elif ad == CORE and not t:
            md.append(f"| {li} | other Ekubo pool swap {dd[40:50]}…, pool side | `{dd[104:136]}`, `{dd[136:168]}` | see legs |")
        elif ad == BOT_CONTRACT and t and t[0] == T_BOT:
            w = [dd[i:i + 64] for i in range(0, 256, 64)]
            md.append(f"| {li} | bot event: out of Fynd, paid into Fynd, profit | `{w[1][-20:]}`, `{w[2][-20:]}`, `{w[3][-20:]}` | "
                      f"{int(w[1], 16)}, {int(w[2], 16)}, {int(w[3], 16)} (raw units) |")
        elif ad == ROUTER and t and t[0] == T_ROUTER:
            items = [(dd[128 + 128 * k + 24:192 + 128 * k][:8], int(dd[192 + 128 * k:256 + 128 * k], 16)) for k in range(int(dd[64:128], 16))]
            md.append(f"| {li} | router fee event, token {t[1][-40:][:6]}…, (recipient, amount) | | {items} |")
        elif t and t[0].startswith("0xf7e050d8") and dd[:64] == FYND_POOL:
            md.append(f"| {li} | Fynd FeesAccumulated (pays LPs for earlier swaps) | | {int(dd[64:128], 16) / 1e18:.18f} ETH, {int(dd[128:192], 16) / 1e6:.6f} USDG |")
    md.append("")
    gas = f"{d['gas_used']:,} gas x {d['gas_price']:,} wei = {d['gas_eth']:.12f} ETH"
    steps = [f"Direction: {e['fynd_direction'].replace('_', ' ')}.",
             f"Fynd fee: {row.fynd_fee_amount:.12g} {row.fynd_fee_token} ({row.fynd_fee_source}) = ${row.fynd_fee_usd:.6f}, "
             f"{row.fynd_fee_bp:.3f} bp of ${row.notional_usd:,.2f}. LPs get {1 - 0.2:.0%} = ${row.fynd_fee_to_lps_usd:.6f}, protocol ${row.fynd_fee_to_protocol_usd:.6f}.",
             f"Router fee: {row.router_fee_eth:.12g} ETH + {row.router_fee_usdg:.6f} USDG = ${row.router_fee_usd:.6f}.",
             f"Bot keeps {row.bot_eth_change:+.18f} ETH and {row.bot_usdg_change:+.6f} USDG; the bot's own event says {row.bot_event_profit:.18g} "
             f"(difference {row.bot_event_check_gap:.3g}).",
             f"At Binance {row.binance_at_exec:,.2f}: gross ${row.bot_gross_usd:.6f}; gas {gas} = ${row.gas_usd:.6f}; net ${row.bot_net_usd:.6f}.",
             f"LPs' swap side at execution ${row.lp_swap_side_exec_usd:.6f}, other venues ${row.other_venues_exec_usd:.6f}; "
             f"fee + router fee + bot + LPs + other venues = ${row.identity_check_usd:.2e}.",
             f"Issues recorded: {row.issues if isinstance(row.issues, str) and row.issues else 'none'}."]
    md += [f"{i + 1}. {s}" for i, s in enumerate(steps)] + [""]
n_res = int((E.completeness == "complete, residual inventory").sum())
md.append(f"## Residual inventory\n\nNo transaction left the bot holding anything but its profit token: {n_res} of {len(E):,} are classed "
          "'complete, residual inventory'. The check is in decode.py (bot's change in the non-profit token, and intermediate tokens "
          "left with the bot or the router).\n")
os.makedirs("hand_checks", exist_ok=True)
open("hand_checks/HAND_CHECKS.md", "w").write("\n".join(md))
print("wrote hand_checks/HAND_CHECKS.md with", len(pick), "transactions")
