"""
Fetch the transaction and receipt for every hash in a list, from the Robinhood Chain public RPC, in batches.
Resumable: hashes already in the output are skipped. One JSON object per line: {"tx": {...}, "receipt": {...}}.

  python3 fetch_txs.py --hashes data/bot_tx_hashes.txt --out data/bot_txs.jsonl
"""
import argparse, json, os, time
from concurrent.futures import ThreadPoolExecutor
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
ap = argparse.ArgumentParser()
ap.add_argument("--hashes", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--batch", type=int, default=25); ap.add_argument("--threads", type=int, default=1)
ap.add_argument("--calls-per-s", type=float, default=6, help="sustained rate the public RPC accepts without 429s")
ap.add_argument("--receipts-only", action="store_true", help="skip eth_getTransactionByHash (nonce/value/input not stored)")
a = ap.parse_args()

want = [h.strip().lower() for h in open(a.hashes) if h.strip()]
have = set()
if os.path.exists(a.out):
    for l in open(a.out):
        x = json.loads(l)
        have.add((x["tx"] or {}).get("hash", x["receipt"]["transactionHash"]).lower())
todo = [h for h in dict.fromkeys(want) if h not in have]
print(f"{len(want)} hashes, {len(have)} already fetched, {len(todo)} to go", flush=True)


def call(batch):
    methods = ["eth_getTransactionReceipt"] if a.receipts_only else ["eth_getTransactionByHash", "eth_getTransactionReceipt"]
    for attempt in range(30):
        try:
            req = [{"jsonrpc": "2.0", "id": len(methods) * i + k, "method": m, "params": [h]}
                   for i, h in enumerate(batch) for k, m in enumerate(methods)]
            t0 = time.time()
            r = requests.post(RPC, json=req, timeout=180).json()
            if not isinstance(r, list):
                raise RuntimeError(str(r)[:200])
            by = {x["id"]: x for x in r}
            out = []
            for i, h in enumerate(batch):
                n = len(methods)
                tx = None if a.receipts_only else by.get(n * i, {}).get("result")
                rc = by.get(n * i + n - 1, {}).get("result")
                if not rc or (not a.receipts_only and not tx):
                    raise RuntimeError(f"missing result for {h}")
                out.append({"tx": tx, "receipt": rc})
            time.sleep(max(0.0, len(req) / a.calls_per_s - (time.time() - t0)))   # pace including the request's own time
            return out
        except Exception as e:
            print("retry:", str(e)[:80], flush=True)
            time.sleep(15)                                  # 429: wait for the limit window to pass
            err = e
    raise err


chunks = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
done = 0
with open(a.out, "a") as f, ThreadPoolExecutor(a.threads) as ex:
    for res in ex.map(call, chunks):
        for x in res:
            f.write(json.dumps(x) + "\n")
        done += len(res)
        if done % 2000 < a.batch:
            print(f"{done}/{len(todo)}", flush=True)
print("done", done)
