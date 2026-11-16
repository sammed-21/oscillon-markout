"""
Check that the Fynd data covers exactly one pool and nothing from the other ETH/USDG pools on Ekubo Core.

  1. Lists every pool ever created on Core (PoolInitialized) and keeps those with the same two tokens.
  2. Checks the target poolId is keccak(token0, token1, config) of the Fynd pool key, and that no other pool on the
     pair uses the same extension.
  3. Counts every swap and PositionUpdated on Core over the swaps file's block range, per pool on the pair, and checks
     the target pool's on-chain counts equal the rows in our files.

  python3 check_pool_scope.py --rpc-url https://rpc.mainnet.chain.robinhood.com \
      --pool-key 0x0000000000000000000000000000000000000000,0x5fc5360d0400a0fd4f2af552add042d716f1d168,0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09000000000000000080000400 \
      --swaps data_swaps/eth_usdg_ekubo_robinhood_to1108.csv data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv \
      --events data_swaps/eth_usdg_ekubo_robinhood_lp_events.csv --to-block 111478410
"""
import argparse, time
import pandas as pd
import requests
from Crypto.Hash import keccak

ap = argparse.ArgumentParser()
ap.add_argument("--rpc-url", required=True); ap.add_argument("--pool-key", required=True)
ap.add_argument("--core", default="0x00000000000014aa86c5d3c41765bb24e11bd701")
ap.add_argument("--swaps", nargs="+", required=True); ap.add_argument("--events", required=True)
ap.add_argument("--to-block", type=int, required=True)
a = ap.parse_args()
k256 = lambda b: keccak.new(digest_bits=256, data=b).hexdigest()
INIT = "0x" + k256(b"PoolInitialized(bytes32,(address,address,bytes32),int32,uint96)")
UPD = "0x" + k256(b"PositionUpdated(address,bytes32,bytes32,int128,bytes32,bytes32)")


def rpc(m, p):
    for i in range(20):
        try:
            r = requests.post(a.rpc_url, timeout=120, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).json()
            if "result" in r:
                return r["result"]
            if any(s in str(r.get("error")) for s in ("exceed", "too many", "spans", "range")):
                raise OverflowError
        except requests.RequestException:
            pass
        time.sleep(1 + i)
    raise RuntimeError(m)


def logs(topics, b, e, step):
    out = []
    while b <= e:
        end = min(e, b + step - 1)
        try:
            out += rpc("eth_getLogs", [{"address": a.core, "topics": topics, "fromBlock": hex(b), "toBlock": hex(end)}])
            b = end + 1
        except OverflowError:
            step //= 4
    return out


t0, t1, cfg = a.pool_key.lower().split(",")
target = k256(bytes.fromhex(f"{int(t0, 16):064x}{int(t1, 16):064x}{cfg[2:]:0<64}"))
pools = {}
for l in logs([INIT], 0, a.to_block, 10_000_000):
    w = [l["data"][2:][i:i + 64] for i in range(0, 256, 64)]
    if ("0x" + w[1][24:], "0x" + w[2][24:]) == (t0, t1):
        pools[w[0]] = {"extension": "0x" + w[3][:40], "created_block": int(l["blockNumber"], 16)}
assert target in pools, "target pool not found among PoolInitialized events"
same_ext = [p for p, v in pools.items() if v["extension"] == cfg[:42] and p != target]
assert not same_ext, f"other pools on this pair share the extension: {same_ext}"
print(f"{len(pools)} pools on this pair; target 0x{target[:8]}…{target[-4:]} is the only one with extension {cfg[:42]}")

sw = pd.concat([pd.read_csv(f) for f in a.swaps]).drop_duplicates(["block", "log_index"])
ev = pd.read_csv(a.events)
b0, b1 = int(sw.block.min()), a.to_block
n_sw, n_upd = dict.fromkeys(pools, 0), dict.fromkeys(pools, 0)
for l in logs(None, b0, b1, 1_000_000):
    d = l["data"][2:]
    if not l["topics"] and len(d) == 232 and d[40:104] in pools:
        n_sw[d[40:104]] += 1
    elif l["topics"] and l["topics"][0] == UPD and d[64:128] in pools:
        n_upd[d[64:128]] += 1
print(f"blocks {b0:,}-{b1:,}:")
for p in sorted(pools, key=lambda p: -n_sw[p]):
    if n_sw[p] or n_upd[p]:
        print(f"  {'TARGET' if p == target else '      '} 0x{p[:8]}…{p[-4:]} ext {pools[p]['extension'][:10]}  "
              f"swaps {n_sw[p]:>7,}  position updates {n_upd[p]:>6,}")
ours_upd = int(((ev.event == "position") & ev.block.between(b0, b1)).sum())
assert n_sw[target] == len(sw[sw.block.between(b0, b1)]), "swap count differs from the target pool on chain"
assert n_upd[target] == ours_upd, "position update count differs from the target pool on chain"
print(f"ok: our files hold exactly the target pool's {n_sw[target]:,} swaps and {ours_upd} position updates; "
      f"{sum(n_sw.values()) - n_sw[target]:,} swaps on the other pools are not in them")
