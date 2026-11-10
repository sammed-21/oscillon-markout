"""
Liquidity events for one Ekubo (EVM, v3 Core) pool, to rebuild its token holdings (and so TVL) over time.

  PositionUpdated(address locker, bytes32 poolId, bytes32 positionId, int128 liquidityDelta, bytes32 balanceUpdate,
                  bytes32 stateAfter)                       balanceUpdate = delta0 int128 << 128 | delta1 int128
  PositionFeesCollected(address locker, bytes32 poolId, bytes32 positionId, uint128 amount0, uint128 amount1)
  FeesAccumulated(bytes32 poolId, uint128 amount0, uint128 amount1)   fees the extension pays into the pool, all of them
                                                            (some come in transactions with no swap in this pool)
  PoolInitialized(bytes32 poolId, ...)                      to find where the pool starts

Neither is indexed by poolId, so logs are filtered by topic0 on Core and matched on poolId. Same sign convention as the
swaps file: + = pool received.

  python3 fetch_ekubo_positions.py --rpc-url https://rpc.mainnet.chain.robinhood.com \
      --core 0x00000000000014aA86C5d3c41765bb24e11bd701 \
      --pool-id 0xb67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546 --dec0 18 --dec1 6 \
      --from-block 80000000 --to-block 109623864 --out data_swaps/eth_usdg_ekubo_robinhood_positions.csv
"""
import argparse, time
import pandas as pd
import requests
from Crypto.Hash import keccak

ap = argparse.ArgumentParser()
ap.add_argument("--rpc-url", required=True); ap.add_argument("--core", required=True); ap.add_argument("--pool-id", required=True)
ap.add_argument("--dec0", type=int, required=True); ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--from-block", type=int, required=True); ap.add_argument("--to-block", type=int, required=True)
ap.add_argument("--chunk-blocks", type=int, default=2_000_000); ap.add_argument("--out", required=True)
a = ap.parse_args()
topic = lambda s: "0x" + keccak.new(digest_bits=256, data=s.encode()).hexdigest()
UPD = topic("PositionUpdated(address,bytes32,bytes32,int128,bytes32,bytes32)")
COL = topic("PositionFeesCollected(address,bytes32,bytes32,uint128,uint128)")
INIT = topic("PoolInitialized(bytes32,(address,address,bytes32),int32,uint96)")
ACC = topic("FeesAccumulated(bytes32,uint128,uint128)")
pid = a.pool_id.lower()[2:]
s128 = lambda v: v - (1 << 128) if v >= (1 << 127) else v


def logs(b, e):
    """One request per event type: this RPC caps OR-ed topic filters at 100,000 blocks, single topics much higher."""
    out = []
    for t in (UPD, COL, INIT, ACC):
        for i in range(30):
            try:
                r = requests.post(a.rpc_url, timeout=120, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [
                    {"address": a.core, "topics": [t], "fromBlock": hex(b), "toBlock": hex(e)}]}).json()
                if "result" in r:
                    out += r["result"]; break
                if any(m in str(r.get("error", "")) for m in ("exceed", "only", "too many")):
                    raise OverflowError
            except requests.RequestException:
                pass
            time.sleep(min(20, 1 + i))
        else:
            raise RuntimeError(f"getLogs {b}-{e}")
    return out


rows, b, step = [], a.from_block, a.chunk_blocks
while b <= a.to_block:
    e = min(b + step - 1, a.to_block)
    try:
        got = logs(b, e)
    except OverflowError:
        step = max(1_000, step // 2); continue
    for l in got:
        d = l["data"][2:]; t0 = l["topics"][0]
        w = [d[i:i + 64] for i in range(0, len(d), 64)]
        base = {"block": int(l["blockNumber"], 16), "log_index": int(l["logIndex"], 16), "tx_hash": l["transactionHash"]}
        if t0 == INIT and w[0] == pid:
            rows.append({**base, "event": "init", "amount0": 0.0, "amount1": 0.0, "liquidity_delta": 0.0})
        elif t0 == ACC and w[0] == pid:
            rows.append({**base, "event": "fees_accumulated", "liquidity_delta": 0.0,
                         "amount0": int(w[1], 16) / 10**a.dec0, "amount1": int(w[2], 16) / 10**a.dec1})
        elif t0 in (UPD, COL) and w[1] == pid:
            if t0 == UPD:
                bu = int(w[4], 16)
                rows.append({**base, "event": "position", "liquidity_delta": float(s128(int(w[3], 16) & ((1 << 128) - 1))),
                             "amount0": s128(bu >> 128) / 10**a.dec0, "amount1": s128(bu & ((1 << 128) - 1)) / 10**a.dec1})
            else:                                               # fees leave the pool to the position owner
                rows.append({**base, "event": "fees_collected", "liquidity_delta": 0.0,
                             "amount0": -int(w[3], 16) / 10**a.dec0, "amount1": -int(w[4], 16) / 10**a.dec1})
    print(f"  blocks {b:,}-{e:,}: {len(got):,} logs, pool events so far {len(rows):,}", flush=True)
    if len(got) < 2_000:
        step = min(a.chunk_blocks, step * 2)
    b = e + 1
out = pd.DataFrame(rows).sort_values(["block", "log_index"])
out.to_csv(a.out, index=False)
print(f"wrote {len(out):,} events -> {a.out}\n{out.event.value_counts().to_string()}")
