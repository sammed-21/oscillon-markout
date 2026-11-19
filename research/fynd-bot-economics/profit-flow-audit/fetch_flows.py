"""
Raw on-chain data for the bot profit-flow audit (Robinhood Chain public RPC: no traces, no historical state, logs without an
address filter limited to 30,000 blocks per query).

  1. Every Transfer / Approval / WETH Deposit / WETH Withdrawal log, on ANY token or NFT contract, whose first indexed
     address is one of the audited wallets (outgoing transfers, approvals given, wraps/unwraps), and every Transfer into
     the owner wallets and the bot sender (incoming). Scanned in 30,000-block windows from the bot contract's deployment.
  2. The bot contract's own logs (trade events, ownership events) from the deployment block to the head.
  3. Receipts and transactions for every transaction found in 1 that involves the owner wallets.
  4. Chain-head snapshot: nonces, native balances, ERC-20 balances of the audited wallets.

  python3 profit-flow-audit/fetch_flows.py --out profit-flow-audit/data
"""
import argparse, json, os, time
from concurrent.futures import ThreadPoolExecutor
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
DEPLOY = 84_286_819                       # bot contract deployment (OwnershipTransferred from 0x0)
W = {"bot_contract": "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7", "bot_sender": "0x4abfdbac0afa181338dc9c38c9c1264128c684a2",
     "owner_1": "0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80", "owner_2": "0x0d41d284672c524d14790b230afe3e287ef4d4b2",
     "lp_0x6c6a": "0x6c6a40d2d1fc442e281e1f80314fd86516e17127"}
TR = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
APPR = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
DEP = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"   # WETH Deposit(address indexed dst, uint wad)
WD = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"    # WETH Withdrawal(address indexed src, uint wad)
TOKENS = {"USDG": "0x5fc5360d0400a0fd4f2af552add042d716f1d168", "WETH": "0x0bd7d308f8e1639fab988df18a8011f41eacad73",
          "AI": "0x2e8c31162b855a2ffa90f6f8634643ad6f111e18", "PONS": "0x39dbed3a2bd333467115de45665cc57f813c4571",
          "NVDA": "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"}           # the bot's profit tokens (its trade events)
pad = lambda a: "0x" + "0" * 24 + a[2:].lower()
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--threads", type=int, default=4)
ap.add_argument("--snapshot-only", action="store_true", help="redo only step 4 (head snapshot)")
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
S = requests.Session()


def rpc(method, params):
    for i in range(40):
        try:
            r = S.post(RPC, timeout=120, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).json()
            if "result" in r:
                return r["result"]
            if "10000" in str(r.get("error", "")) or "too many" in str(r.get("error", "")).lower():
                raise OverflowError(r["error"])
        except requests.RequestException:
            pass
        time.sleep(min(30, 1 + i))
    raise RuntimeError(f"{method} {params} failed")


def logs(flt, b, e):
    try:
        return rpc("eth_getLogs", [{**flt, "fromBlock": hex(b), "toBlock": hex(e)}])
    except OverflowError:
        m = (b + e) // 2
        return logs(flt, b, m) + logs(flt, m + 1, e)


head = int(rpc("eth_blockNumber", []), 16)


def snapshot():
    """State at the chain head. This RPC keeps no history, so every call uses "latest"; the block is read before and after."""
    bal = lambda tok, w: int(rpc("eth_call", [{"to": tok, "data": "0x70a08231" + pad(w)[2:]}, "latest"]), 16)
    b0 = int(rpc("eth_blockNumber", []), 16); snap = {"wallets": {}}
    for k, w in W.items():
        snap["wallets"][k] = {"address": w, "nonce": int(rpc("eth_getTransactionCount", [w, "latest"]), 16),
                              "native_wei": int(rpc("eth_getBalance", [w, "latest"]), 16),
                              **{f"{t}_raw": bal(addr, w) for t, addr in TOKENS.items()}}
    b1 = int(rpc("eth_blockNumber", []), 16)
    snap.update(block_from=b0, block_to=b1, timestamp=int(rpc("eth_getBlockByNumber", [hex(b1), False])["timestamp"], 16))
    json.dump(snap, open(os.path.join(a.out, "head_snapshot.json"), "w"), indent=1)
    print("snapshot", json.dumps(snap), flush=True)


if a.snapshot_only:
    snapshot(); raise SystemExit
out_w = [pad(W[k]) for k in ("bot_contract", "bot_sender", "owner_1", "owner_2")]
in_w = [pad(W[k]) for k in ("bot_sender", "owner_1", "owner_2")]
wins = [(b, min(b + 29_999, head)) for b in range(DEPLOY, head + 1, 30_000)]


def window(be):
    b, e = be
    return logs({"topics": [[TR, APPR, DEP, WD], out_w]}, b, e) + logs({"topics": [TR, None, in_w]}, b, e)


t0 = time.time(); found = []
with ThreadPoolExecutor(a.threads) as ex:
    for i, got in enumerate(ex.map(window, wins)):
        found += got
        if i % 100 == 0:
            print(f"window {i}/{len(wins)} logs {len(found)} {time.time() - t0:.0f}s", flush=True)
uniq = {(l["transactionHash"], l["logIndex"]): l for l in found}
json.dump({"from_block": DEPLOY, "to_block": head, "logs": sorted(uniq.values(), key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))},
          open(os.path.join(a.out, "wallet_logs.json"), "w"))
print("wallet logs", len(uniq), flush=True)

bot_logs = []
for b in range(DEPLOY, head + 1, 2_000_000):
    bot_logs += logs({"address": W["bot_contract"]}, b, min(b + 1_999_999, head))
json.dump({"from_block": DEPLOY, "to_block": head, "logs": bot_logs}, open(os.path.join(a.out, "bot_contract_logs.json"), "w"))
print("bot contract logs", len(bot_logs), flush=True)

owners = {pad(W["owner_1"]), pad(W["owner_2"])}
txs = {l["transactionHash"] for l in uniq.values() if set(l["topics"][1:3]) & owners}          # any token log naming an owner
txs |= {l["transactionHash"] for l in bot_logs if not l["topics"][0].startswith("0xed370fed")}  # bot contract admin events
txs = sorted(txs)
with ThreadPoolExecutor(a.threads) as ex:
    rec = list(ex.map(lambda h: {"tx": rpc("eth_getTransactionByHash", [h]), "receipt": rpc("eth_getTransactionReceipt", [h])}, txs))
for r in rec:
    blk = rpc("eth_getBlockByNumber", [r["receipt"]["blockNumber"], False]); r["timestamp"] = int(blk["timestamp"], 16)
with open(os.path.join(a.out, "owner_txs.jsonl"), "w") as f:
    for r in rec:
        f.write(json.dumps(r) + "\n")
print("owner txs", len(rec), flush=True)

snapshot()
