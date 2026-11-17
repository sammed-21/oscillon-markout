"""
Did the Fynd extension or pool configuration change during the study? And which Ekubo pools use the Fynd extension?
  - every log the extension contract emitted, counted by event type and day (a new event type = a configuration or
    admin action; the per-block event's fields are checked for changes)
  - every Ekubo PoolInitialized whose extension is the Fynd extension
Code changes cannot be seen directly (no historical state on this RPC); a proxy/upgrade would normally emit an event.

  python3 final/extension_check.py --from-block 78000000 --out final/data/extension_check.json
"""
import argparse, json, time
from collections import Counter, defaultdict
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
EXT = "0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09"
CORE = "0x00000000000014aa86c5d3c41765bb24e11bd701"
INIT = "0x5e4688b340694b7c7fd30047fd082117dc46e32acfbf81a44bb1fac0ae65154d"
ap = argparse.ArgumentParser()
ap.add_argument("--from-block", type=int, required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()


def rpc(m, p):
    for _ in range(60):
        r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=120).json()
        if "result" in r:
            return r["result"]
        if "429" in str(r.get("error")):
            time.sleep(10); continue
        raise OverflowError(str(r.get("error")))
    raise RuntimeError(m)


head = int(rpc("eth_blockNumber", []), 16)
topics, fields, first_last = Counter(), defaultdict(Counter), {}
b, step = a.from_block, 1_000_000
while b <= head:
    e = min(head, b + step - 1)
    try:
        logs = rpc("eth_getLogs", [{"address": EXT, "fromBlock": hex(b), "toBlock": hex(e)}])
    except OverflowError:
        step = max(10_000, step // 4); continue
    for l in logs:
        t0 = l["topics"][0] if l["topics"] else "anon"
        topics[t0] += 1
        blk = int(l["blockNumber"], 16)
        fl = first_last.setdefault(t0, [blk, blk]); fl[0] = min(fl[0], blk); fl[1] = max(fl[1], blk)
        if t0.startswith("0xd59d72ec"):
            d = l["data"][2:]
            fields["pool"][l["topics"][1][:18]] += 1; fields["addr"]["0x" + d[:40]] += 1; fields["share_raw"][d[48:64]] += 1
    b = e + 1; time.sleep(0.3)
pools = []
b = 0
while b <= head:
    e = min(head, b + 9_999_999)
    for l in rpc("eth_getLogs", [{"address": CORE, "topics": [INIT], "fromBlock": hex(b), "toBlock": hex(e)}]):
        w = [l["data"][2:][j:j + 64] for j in range(0, 256, 64)]
        if ("0x" + w[3][:40]).lower() == EXT:
            pools.append({"pool_id": w[0], "token0": "0x" + w[1][24:], "token1": "0x" + w[2][24:], "config": w[3], "block": int(l["blockNumber"], 16)})
    b = e + 1
res = {"from_block": a.from_block, "head": head, "event_types": dict(topics), "first_last_block": first_last,
       "per_block_event_fields": {k: dict(v) for k, v in fields.items()}, "pools_with_fynd_extension": pools}
json.dump(res, open(a.out, "w"), indent=1)
print(json.dumps(res, indent=1)[:4000])
