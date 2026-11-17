"""
Mint and Burn events of the Uniswap v3 WETH/USDG 0.01% pool over a block range (for auditing compare_pools.py's
assumption that liquidity only changes at swaps). Paced to stay under the public RPC's rate limit.

  python3 fetch_uni_mint_burn.py --pool 0x52e65b17... --from-block 77787161 --to-block 112925842 --out data/uni_1bp_mint_burn.csv
"""
import argparse, time
import pandas as pd
import requests

RPC = "https://rpc.mainnet.chain.robinhood.com"
MINT = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
BURN = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
ap = argparse.ArgumentParser()
ap.add_argument("--pool", required=True); ap.add_argument("--from-block", type=int, required=True)
ap.add_argument("--to-block", type=int, required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()


def logs(b, e):
    for i in range(60):
        r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs",
                                     "params": [{"address": a.pool, "topics": [[MINT, BURN]], "fromBlock": hex(b), "toBlock": hex(e)}]}, timeout=120).json()
        if "result" in r:
            return r["result"]
        if "429" not in str(r.get("error")):
            raise OverflowError(str(r.get("error")))
        time.sleep(10)
    raise RuntimeError("rate limited")


rows, b, step = [], a.from_block, 90_000            # a list in a topic position allows <= 100k blocks per query
while b <= a.to_block:
    e = min(a.to_block, b + step - 1)
    try:
        got = logs(b, e)
    except OverflowError as err:
        step = max(1000, step // 4); print("shrink", step, str(err)[:80], flush=True); continue
    for l in got:
        d = l["data"][2:]
        mint = l["topics"][0] == MINT
        amt = int(d[64:128], 16) if mint else int(d[0:64], 16)   # Mint: sender, amount, a0, a1; Burn: amount, a0, a1
        tl = int(l["topics"][2], 16); tu = int(l["topics"][3], 16)
        tl -= (1 << 256) if tl >= 1 << 255 else 0; tu -= (1 << 256) if tu >= 1 << 255 else 0
        rows.append({"block": int(l["blockNumber"], 16), "log_index": int(l["logIndex"], 16), "event": "mint" if mint else "burn",
                     "tick_lower": tl, "tick_upper": tu, "liquidity": amt})
    b = e + 1
    time.sleep(1.0)
pd.DataFrame(rows).to_csv(a.out, index=False)
print("events", len(rows))
