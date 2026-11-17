"""
Every USDG and WETH Transfer log sent from or to a set of wallets, over a block range (this RPC allows 10M-block
queries only with an address filter, so the two tokens the bot's profits are held in are queried by address). Used to see where the bot
contract's profits went and whether any of the wallets are linked on chain. Native ETH transfers leave no log and are
not covered. Paced for the public RPC; shrinks the block range when a query hits the 10,000-log cap.

  python3 final/fetch_wallet_transfers.py --from-block 78000000 --out final/data/wallet_transfers.csv
"""
import argparse, time
import pandas as pd
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WALLETS = {
    "bot_contract": "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7",
    "bot_eoa": "0x4abfdbac0afa181338dc9c38c9c1264128c684a2",
    "bot_owner_1": "0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80",
    "bot_owner_2": "0x0d41d284672c524d14790b230afe3e287ef4d4b2",
    "lp_0x6c6a": "0x6c6a40d2d1fc442e281e1f80314fd86516e17127",
    "router_fee_recipient": "0xa5503d92ee16a78e602996ad362674dc49034a14",
    "extension_event_address": "0x4f2826f91f74c315aac59eb091c4178f913d0312",
}
ap = argparse.ArgumentParser()
ap.add_argument("--from-block", type=int, required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()


def rpc(m, p):
    for _ in range(60):
        try:
            r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=120).json()
        except requests.RequestException:
            time.sleep(10); continue
        if "result" in r:
            return r["result"]
        if "429" in str(r.get("error")) or "Too Many" in str(r.get("error")):
            time.sleep(10); continue
        raise OverflowError(str(r.get("error")))
    raise RuntimeError("rate limited")


head = int(rpc("eth_blockNumber", []), 16)
pad = lambda x: "0x" + "0" * 24 + x[2:]
rows = []
TOKENS = {"USDG": "0x5fc5360d0400a0fd4f2af552add042d716f1d168", "WETH": "0x0bd7d308f8e1639fab988df18a8011f41eacad73"}
for name, w in WALLETS.items():
  for tname, tok in TOKENS.items():
    for side, topics in [("from", [TRANSFER, pad(w)]), ("to", [TRANSFER, None, pad(w)])]:
        b, step, n = a.from_block, 10_000_000, 0
        while b <= head:
            e = min(head, b + step - 1)
            try:
                got = rpc("eth_getLogs", [{"address": tok, "topics": topics, "fromBlock": hex(b), "toBlock": hex(e)}])
            except OverflowError:
                step = max(10_000, step // 4); continue
            for l in got:
                rows.append({"wallet": name, "side": side, "block": int(l["blockNumber"], 16), "log_index": int(l["logIndex"], 16),
                             "tx_hash": l["transactionHash"], "token": l["address"].lower(), "from": "0x" + l["topics"][1][-40:],
                             "to": "0x" + l["topics"][2][-40:], "raw": int(l["data"][2:66] or "0", 16)})
            n += len(got); b = e + 1
            time.sleep(0.4)
        print(f"{name} {tname} {side}: {n:,} transfers", flush=True)
pd.DataFrame(rows).to_csv(a.out, index=False)
print("head", head, "rows", len(rows))
