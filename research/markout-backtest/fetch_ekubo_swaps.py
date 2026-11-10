"""
Individual swaps for one Ekubo (EVM, v3 Core) pool, both directions, to CSV.

Ekubo's Core is a singleton and logs each swap as an anonymous log0 of 116 bytes:
  locker (20) | poolId (32) | balanceUpdate (32: delta0 int128 << 128 | delta1 int128) | stateAfter (32: sqrtRatio
  uint96 << 160 | tick int32 << 128 | liquidity uint128)
Anonymous logs can't be filtered by topic, so every Core log is pulled and matched on poolId = keccak(token0, token1,
config). Deltas are from the pool's side (+ = pool received), the same sign convention as the Uniswap swaps files.
sqrtRatio is Ekubo's packed float; toFixed() gives a 64.128 fixed-point sqrt(token1/token0) in raw units.

Block timestamps: some L2 RPCs return blockTimestamp 0x0 in logs, so each distinct swap block is read directly.

  python3 fetch_ekubo_swaps.py --rpc-url https://rpc.mainnet.chain.robinhood.com \
      --core 0x00000000000014aA86C5d3c41765bb24e11bd701 --token0 0x0000000000000000000000000000000000000000 \
      --token1 0x5fc5360d0400a0fd4f2af552add042d716f1d168 --dec0 18 --dec1 6 --fee 0 --tick-spacing 1024 \
      --extension 0x550CFe1292d0D9c0d28f232b3F42Edb4439B1D09 --out data_swaps/eth_usdg_ekubo_robinhood.csv
"""
import argparse, json, os, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests
from Crypto.Hash import keccak
from flow_lib import attribute_fees

ap = argparse.ArgumentParser()
ap.add_argument("--rpc-url", required=True); ap.add_argument("--core", required=True)
ap.add_argument("--token0", required=True); ap.add_argument("--token1", required=True)
ap.add_argument("--dec0", type=int, required=True); ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--fee", type=int, default=0, help="Ekubo uint64 fee (fraction of 2**64)")
ap.add_argument("--tick-spacing", type=int, required=True); ap.add_argument("--extension", required=True)
ap.add_argument("--from-block", type=int, default=0); ap.add_argument("--to-block", type=int, default=0, help="0 = head")
ap.add_argument("--chunk-blocks", type=int, default=1_000_000)
ap.add_argument("--out", required=True)
a = ap.parse_args()
os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)


def rpc(method, params, tries=10):
    for i in range(tries):
        try:
            r = requests.post(a.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=120).json()
            if "result" in r:
                return r["result"]
            err = r.get("error", {})
            if "exceeds limit" in str(err.get("message", "")):
                raise OverflowError(err["message"])
        except (requests.RequestException, ValueError) as e:
            err = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{method}: {err}")


def s128(v):
    return v - (1 << 128) if v >= (1 << 127) else v


def sqrt_fixed(r):
    """SqrtRatio.toFixed: 64.128 fixed point."""
    return (r & ~(0b11 << 94)) << (2 + ((r >> 94) & 0b11) * 32)


config = (int(a.extension, 16) << 96) | (a.fee << 32) | 0x80000000 | (a.tick_spacing & 0x7FFFFFFF)
key = int(a.token0, 16).to_bytes(32, "big") + int(a.token1, 16).to_bytes(32, "big") + config.to_bytes(32, "big")
pool_id = keccak.new(digest_bits=256, data=key).hexdigest()
print("poolId 0x" + pool_id)

# Extensions pay LPs through Core.accumulateAsFees, logged as FeesAccumulated(poolId, amount0, amount1). With a 0 Core
# fee this is the pool's whole fee income.
FEES_TOPIC = "0x" + keccak.new(digest_bits=256, data=b"FeesAccumulated(bytes32,uint128,uint128)").hexdigest()
scan_path = a.out.replace(".csv", "_scan.json")             # raw scan kept so lookups can fail without rescanning
head = a.to_block or int(rpc("eth_blockNumber", []), 16)
rows, fees, b, step = [], [], a.from_block, a.chunk_blocks
if os.path.exists(scan_path):
    saved = json.load(open(scan_path))
    if saved["from_block"] == a.from_block and saved["pool_id"] == pool_id:
        rows, fees, b = saved["rows"], saved["fees"], saved["next_block"]
        print(f"resuming scan at block {b:,} with {len(rows):,} swaps")
while b <= head:
    e = min(b + step - 1, head)
    try:
        logs = rpc("eth_getLogs", [{"address": a.core, "fromBlock": hex(b), "toBlock": hex(e)}])
    except OverflowError:                                       # > 10,000 logs: halve the span
        step = max(1_000, step // 2); continue
    n0 = len(rows)
    for l in logs:
        d = l["data"][2:]
        if l["topics"] and l["topics"][0] == FEES_TOPIC and d[0:64] == pool_id:
            fees.append({"tx_hash": l["transactionHash"], "block": int(l["blockNumber"], 16),
                         "log_index": int(l["logIndex"], 16), "fee0": int(d[64:128], 16) / 10**a.dec0, "fee1": int(d[128:192], 16) / 10**a.dec1})
        if l["topics"] or len(d) != 232 or d[40:104] != pool_id:
            continue
        bu, st = int(d[104:168], 16), int(d[168:232], 16)
        sr = sqrt_fixed(st >> 160)
        rows.append({"block": int(l["blockNumber"], 16), "tx_index": int(l["transactionIndex"], 16),
                     "log_index": int(l["logIndex"], 16), "tx_hash": l["transactionHash"], "sender": "0x" + d[0:40],
                     "amount0": s128(bu >> 128) / 10**a.dec0, "amount1": s128(bu & ((1 << 128) - 1)) / 10**a.dec1,
                     "sqrtRatioFixed": str(sr), "price": (sr / 2**128) ** 2 * 10 ** (a.dec0 - a.dec1),
                     "liquidity": float(st & ((1 << 128) - 1)),
                     "tick": (((st >> 128) & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000})
    print(f"  blocks {b:,}-{e:,}: {len(logs):,} Core logs, {len(rows) - n0:,} pool swaps (total {len(rows):,})", flush=True)
    if len(logs) < 2_000:                                       # sparse: widen again
        step = min(a.chunk_blocks, step * 2)
    b = e + 1
json.dump({"from_block": a.from_block, "pool_id": pool_id, "next_block": b, "rows": rows, "fees": fees}, open(scan_path, "w"))

sw = pd.DataFrame(rows)
if not len(sw):
    raise SystemExit("no swaps found for this poolId")


def batch(method, args, pick):
    """`method` for every arg, batched 10 per request on 2 threads (public RPCs allow ~28 reads/s)."""
    def get(chunk):
        for i in range(40):                                     # rate limits come in waves: back off up to 30 s
            try:
                r = requests.post(a.rpc_url, timeout=60, json=[{"jsonrpc": "2.0", "id": j, "method": method, "params": p}
                                                               for j, p in enumerate(chunk)]).json()
                if isinstance(r, list) and all("result" in x for x in r):
                    return [pick(x["result"]) for x in sorted(r, key=lambda x: x["id"])]
            except (requests.RequestException, ValueError):
                pass
            time.sleep(min(30, 1.5 * (i + 1)))
        raise RuntimeError(f"{method} batch starting {chunk[0]}")
    out = []
    with ThreadPoolExecutor(2) as ex:
        for res in ex.map(get, [args[i:i + 10] for i in range(0, len(args), 10)]):
            out += res
    return out


blocks = sorted(sw.block.unique().tolist())
ts = dict(zip(blocks, batch("eth_getBlockByNumber", [[hex(b), False] for b in blocks], lambda r: int(r["timestamp"], 16))))
sw.insert(0, "ts", sw.block.map(ts).astype("int64"))
hashes = sw.tx_hash.unique().tolist()
tx = dict(zip(hashes, batch("eth_getTransactionByHash", [[h] for h in hashes], lambda r: (r["from"], r.get("to")))))
sw["tx_from"] = sw.tx_hash.map(lambda h: tx[h][0]); sw["tx_to"] = sw.tx_hash.map(lambda h: tx[h][1])
sw["direction"] = (sw.amount0 > 0).map({True: "sell token0", False: "buy token0"})
sw = sw.drop_duplicates(["tx_hash", "log_index"]).sort_values(["block", "log_index"])
# Fee events carry no swap id, and the extension pays a swap's fee in at the pool's next interaction in a later block
# (logged before that interaction's own swap). So each fee event pays for the swaps since the previous one; see
# flow_lib.attribute_fees. Splitting by same transaction instead credits each swap with the previous swap's fee.
fe = pd.DataFrame(fees)
if len(fe) and "block" not in fe:
    raise SystemExit(f"{scan_path} predates fee block/log_index: delete it and rescan")
fe = fe.rename(columns={"fee0": "amount0", "fee1": "amount1"}) if len(fe) else pd.DataFrame(columns=["block", "log_index", "amount0", "amount1"])
sw = sw.reset_index(drop=True)
sw["fee0"], sw["fee1"] = attribute_fees(sw, fe) if len(fe) else (0.0, 0.0)
print(f"fee events: {len(fe):,}; swaps after the last fee event (fee not paid in yet, 0 here): "
      f"{(sw.block * 1_000_000 + sw.log_index > (fe.block * 1_000_000 + fe.log_index).max()).sum() if len(fe) else len(sw):,}")
sw.to_csv(a.out, index=False)
print(f"wrote {len(sw):,} swaps -> {a.out} | {pd.to_datetime(sw.ts.min(), unit='s')} .. {pd.to_datetime(sw.ts.max(), unit='s')}")
print(sw.groupby("direction").agg(swaps=("ts", "size"), token0=("amount0", lambda x: x.abs().sum()),
                                  token1=("amount1", lambda x: x.abs().sum())).to_string())
