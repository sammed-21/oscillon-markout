"""
Every log the bot contract ever emitted (any event), from block 0 to head, chunked to the RPC's 10M-block limit.
This is a census of the bot's successful trades on any pool, independent of the Fynd swap files.

  python3 fetch_contract_logs.py --address 0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7 --out data/bot_contract_logs.json
"""
import argparse, json, time
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
ap = argparse.ArgumentParser()
ap.add_argument("--address", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--from-block", type=int, default=0)
a = ap.parse_args()


def rpc(m, p):
    for i in range(40):
        try:
            r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=180).json()
            if "result" in r:
                return r["result"]
            if any(s in str(r.get("error")).lower() for s in ("exceed", "too many results", "limit")) and "429" not in str(r.get("error")):
                raise OverflowError(str(r["error"]))
        except requests.RequestException:
            pass
        time.sleep(10)
    raise RuntimeError(m)


head = int(rpc("eth_blockNumber", []), 16)
logs, b, step = [], a.from_block, 10_000_000
while b <= head:
    e = min(head, b + step - 1)
    try:
        got = rpc("eth_getLogs", [{"address": a.address, "fromBlock": hex(b), "toBlock": hex(e)}])
    except OverflowError:
        step = max(10_000, step // 4); continue
    logs += got; print(f"blocks {b:,}-{e:,}: {len(got):,} logs", flush=True); b = e + 1
json.dump({"address": a.address, "head": head, "logs": logs}, open(a.out, "w"))
print("total", len(logs), "head", head)
