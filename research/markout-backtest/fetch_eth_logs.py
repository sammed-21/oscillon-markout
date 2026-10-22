"""
Fetch real Uniswap v3 Swap events for one pool, one month, via public eth_getLogs
(no Dune, no API key). Writes dune.csv with columns: ts, amount0, amount1, sqrtPriceX96
-- the exact schema prepare_pool.py expects from a "Dune export".

Topic0 for Swap(address,address,int256,int256,uint160,uint128,int24) is computed at
runtime from the event signature (keccak256), never hardcoded from memory.
"""
import argparse
import os
import sys
import time

import pandas as pd
import requests
from Crypto.Hash import keccak

RPC = os.environ.get("ETH_RPC_URL", "https://ethereum-rpc.publicnode.com")
SWAP_SIG = "Swap(address,address,int256,int256,uint160,uint128,int24)"


def topic0() -> str:
    k = keccak.new(digest_bits=256)
    k.update(SWAP_SIG.encode())
    return "0x" + k.hexdigest()


def rpc(method: str, params: list, retries: int = 5):
    for attempt in range(retries):
        r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60)
        d = r.json()
        if "result" in d:
            return d["result"]
        err = d.get("error", {})
        if attempt == retries - 1:
            raise RuntimeError(f"{method} failed: {err}")
        time.sleep(2 * (attempt + 1))


def block_at_or_before(ts: int, lo: int, hi: int) -> int:
    """Binary search for the highest block whose timestamp <= ts."""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        bt = int(rpc("eth_getBlockByNumber", [hex(mid), False])["timestamp"], 16)
        if bt <= ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def decode_swap(log: dict) -> dict:
    data = log["data"][2:]
    words = [data[i:i + 64] for i in range(0, len(data), 64)]

    def s256(h: str) -> int:
        v = int(h, 16)
        return v - (1 << 256) if v >= (1 << 255) else v

    amount0 = s256(words[0])
    amount1 = s256(words[1])
    sqrt_price_x96 = int(words[2], 16)  # uint160, fits in the low bits of the 32-byte word
    return {
        "ts": int(log["blockTimestamp"], 16),
        "amount0": amount0,
        "amount1": amount1,
        "sqrtPriceX96": sqrt_price_x96,
        "block": int(log["blockNumber"], 16),
        "logIndex": int(log["logIndex"], 16),
    }


def fetch(address: str, from_block: int, to_block: int, chunk: int) -> pd.DataFrame:
    t0 = topic0()
    rows = []
    b = from_block
    n_chunks = (to_block - from_block) // chunk + 1
    i = 0
    while b <= to_block:
        end = min(b + chunk - 1, to_block)
        i += 1
        logs = rpc("eth_getLogs", [{
            "address": address, "topics": [t0],
            "fromBlock": hex(b), "toBlock": hex(end),
        }])
        print(f"  chunk {i}/{n_chunks} blocks {b}-{end}: {len(logs)} swaps", flush=True)
        rows.extend(decode_swap(l) for l in logs)
        b = end + 1
    df = pd.DataFrame(rows).sort_values(["block", "logIndex"]).reset_index(drop=True)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--chunk-blocks", type=int, default=5000)
    ap.add_argument("--out", default="dune.csv")
    a = ap.parse_args()

    latest = int(rpc("eth_blockNumber", []), 16)
    now_ts = int(rpc("eth_getBlockByNumber", [hex(latest), False])["timestamp"], 16)
    start_ts = now_ts - a.days * 86400
    print(f"Finding start block for ts={start_ts} ({a.days} days back)...")
    start_block = block_at_or_before(start_ts, latest - a.days * 7500, latest)
    print(f"from_block={start_block} to_block={latest}")

    df = fetch(a.pool, start_block, latest, a.chunk_blocks)
    df[["ts", "amount0", "amount1", "sqrtPriceX96"]].to_csv(a.out, index=False)
    print(f"\nwrote {len(df):,} real swaps -> {a.out}")
    print(f"span: {pd.to_datetime(df.ts.min(), unit='s')} .. {pd.to_datetime(df.ts.max(), unit='s')}")


if __name__ == "__main__":
    main()
