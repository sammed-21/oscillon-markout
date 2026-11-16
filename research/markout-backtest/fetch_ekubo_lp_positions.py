"""
Every LP position in one Ekubo (EVM, v3 Core) pool, with its owner, so each one can be scored against holding.

  PositionUpdated(address locker, bytes32 poolId, bytes32 positionId, int128 liquidityDelta, bytes32 balanceUpdate,
                  bytes32 stateAfter)          positionId = salt bytes24 | tickLower int32 | tickUpper int32
  PositionFeesCollected(address locker, bytes32 poolId, bytes32 positionId, uint128 amount0, uint128 amount1)
  Transfer(address from, address to, uint256 id) on the Positions NFT     the NFT id's low 24 bytes are the salt
  FeesAccumulated(bytes32 poolId, uint128 amount0, uint128 amount1)        fees the extension pays in (check only)

Open positions are read at the end block with Positions.getPositionFeesAndLiquidity (principal and uncollected fees).
This RPC keeps no history, so that call only works at the chain head: run with --to-block latest. The script then
catches up to the head, reads, and accepts the snapshot only if the pool did not change during the read.
Same sign convention as the swaps file: + = pool received.

  python3 fetch_ekubo_lp_positions.py --rpc-url https://rpc.mainnet.chain.robinhood.com \
      --core 0x00000000000014aA86C5d3c41765bb24e11bd701 --nft 0x02d9876a21af7545f8632c3af76ec90b5ad4b66d \
      --pool-id 0xb67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546 \
      --pool-key 0x0000000000000000000000000000000000000000,0x5fc5360d0400a0fd4f2af552add042d716f1d168,0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09000000000000000080000400 \
      --dec0 18 --dec1 6 --from-block 72277109 --to-block latest --out-prefix data_swaps/eth_usdg_ekubo_robinhood_lp
"""
import argparse, json, time
import pandas as pd
import requests
from Crypto.Hash import keccak

ap = argparse.ArgumentParser()
ap.add_argument("--rpc-url", required=True); ap.add_argument("--core", required=True); ap.add_argument("--nft", required=True)
ap.add_argument("--pool-id", required=True); ap.add_argument("--pool-key", required=True, help="token0,token1,config")
ap.add_argument("--dec0", type=int, required=True); ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--from-block", type=int, required=True); ap.add_argument("--to-block", default="latest")
ap.add_argument("--chunk-blocks", type=int, default=2_000_000); ap.add_argument("--out-prefix", required=True)
a = ap.parse_args()
k256 = lambda s: keccak.new(digest_bits=256, data=s.encode()).hexdigest()
topic = lambda s: "0x" + k256(s)
UPD = topic("PositionUpdated(address,bytes32,bytes32,int128,bytes32,bytes32)")
COL = topic("PositionFeesCollected(address,bytes32,bytes32,uint128,uint128)")
TRF = topic("Transfer(address,address,uint256)")
ACC = topic("FeesAccumulated(bytes32,uint128,uint128)")
VIEW = k256("getPositionFeesAndLiquidity(uint256,(address,address,bytes32),int32,int32)")[:8]
pid = a.pool_id.lower()[2:]
s128 = lambda v: v - (1 << 128) if v >= (1 << 127) else v
s32 = lambda h: (lambda v: v - (1 << 32) if v >= (1 << 31) else v)(int(h, 16))


def rpc(method, params):
    for i in range(30):
        try:
            r = requests.post(a.rpc_url, timeout=120, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).json()
            if "result" in r:
                return r["result"]
            if any(m in str(r.get("error", "")) for m in ("exceed", "only", "too many", "spans")):
                raise OverflowError
            if "historical state" in str(r.get("error", "")):
                raise LookupError(r["error"])
        except requests.RequestException:
            pass
        time.sleep(min(20, 1 + i))
    raise RuntimeError(f"{method} failed")


def scan(address, topics, b, e):
    out, step = [], a.chunk_blocks
    while b <= e:
        end = min(b + step - 1, e)
        try:
            got = rpc("eth_getLogs", [{"address": address, "topics": topics, "fromBlock": hex(b), "toBlock": hex(end)}])
        except OverflowError:
            step = max(1_000, step // 2); continue
        out += got; b = end + 1
        if len(got) < 2_000:
            step = min(a.chunk_blocks * 4, step * 2)
    return out


head = lambda: int(rpc("eth_blockNumber", []), 16)


def pool_logs(b, e, swaps=True):
    """This pool's position, fee-collect and fee-payment logs in [b, e], NFT transfers, and its swap count."""
    w1 = lambda l: l["data"][2 + 64:2 + 128]
    upd = [l for l in scan(a.core, [UPD], b, e) + scan(a.core, [COL], b, e) if w1(l) == pid]
    acc = [l for l in scan(a.core, [ACC], b, e) if l["data"][2:66] == pid]
    n_swaps = sum(1 for l in scan(a.core, None, b, e) if not l["topics"] and l["data"][2:][40:104] == pid) if swaps else 0
    return upd, acc, scan(a.nft, [TRF], b, e), n_swaps


def parse(upd):
    rows = []
    for l in upd:
        d = l["data"][2:]; w = [d[i:i + 64] for i in range(0, len(d), 64)]
        base = {"block": int(l["blockNumber"], 16), "log_index": int(l["logIndex"], 16), "tx_hash": l["transactionHash"],
                "locker": "0x" + w[0][24:], "salt": w[2][:48], "tick_lower": s32(w[2][48:56]), "tick_upper": s32(w[2][56:64])}
        if l["topics"][0] == UPD:
            bu = int(w[4], 16)
            rows.append({**base, "event": "position", "liquidity_delta": s128(int(w[3], 16) & ((1 << 128) - 1)),
                         "amount0": s128(bu >> 128) / 10**a.dec0, "amount1": s128(bu & ((1 << 128) - 1)) / 10**a.dec1})
        else:                                                   # fees leave the pool to the position owner
            rows.append({**base, "event": "fees_collected", "liquidity_delta": 0,
                         "amount0": -int(w[3], 16) / 10**a.dec0, "amount1": -int(w[4], 16) / 10**a.dec1})
    ev = pd.DataFrame(rows).sort_values(["block", "log_index"]).reset_index(drop=True)
    ev["pos"] = ev.salt + ":" + ev.tick_lower.astype(str) + ":" + ev.tick_upper.astype(str)
    return ev


def owners(trf, ev):
    own = {}
    for l in sorted(trf, key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16))):
        nid = l["topics"][3][2:]; to = "0x" + l["topics"][2][26:]
        o = own.setdefault(nid[16:], {"nft_id": "0x" + nid, "minted_to": to})
        o["owner"] = to
    for c in ["nft_id", "minted_to", "owner"]:
        ev[c] = ev.salt.map(lambda s: own.get(s, {}).get(c))
    return ev


t0, t1, cfg = a.pool_key.split(",")
key = f"{int(t0, 16):064x}{int(t1, 16):064x}{cfg[2:]:0<64}"
enc = lambda v: f"{v & ((1 << 256) - 1):064x}"


def read_open(ev, tag):
    st = []
    left = ev[ev.event == "position"].groupby("pos").liquidity_delta.sum()
    for p in left[left != 0].index:
        r0 = ev[ev.pos == p].iloc[0]
        assert r0.locker.lower() == a.nft.lower(), f"open position {p} is not held through the Positions NFT"
        res = rpc("eth_call", [{"to": a.nft, "data": "0x" + VIEW + r0.nft_id[2:] + key + enc(int(r0.tick_lower)) + enc(int(r0.tick_upper))}, tag])
        liq, p0, p1, f0, f1 = (int(res[2 + 64 * i:2 + 64 * (i + 1)], 16) for i in range(5))
        assert liq == left[p], f"{p}: liquidity from events {left[p]} != on chain {liq}"
        st.append({"pos": p, "nft_id": r0.nft_id, "owner": r0.owner, "liquidity": liq,
                   "principal0": p0 / 10**a.dec0, "principal1": p1 / 10**a.dec1, "fees0": f0 / 10**a.dec0, "fees1": f1 / 10**a.dec1})
    return st


# This RPC keeps no past state, so the open positions can only be read at the chain head. Scan to the head, read, then
# accept the snapshot only if nothing touched the pool (position change, fee payment or swap) while reading; else
# catch up and read again. With a numeric --to-block the read is done at that block and fails if it is not available.
to_block = head() if a.to_block == "latest" else int(a.to_block)
upd, acc, trf, _ = pool_logs(a.from_block, to_block, swaps=False)
for attempt in range(10):
    ev = owners(trf, parse(upd))
    nft = ev.locker.str.lower() == a.nft.lower()
    assert ev.loc[nft, "nft_id"].notna().all(), "a Positions-NFT position has no matching mint"
    if a.to_block != "latest":
        st = read_open(ev, hex(to_block)); break
    st = read_open(ev, "latest")
    after = head()
    u, c, t, n = pool_logs(to_block + 1, after)
    if not (u or c or n):
        break                                                   # state read equals the state at to_block
    print(f"pool changed while reading ({len(u)} position, {len(c)} fee, {n} swap events); catching up to {after:,}")
    upd += u; acc += c; trf += t; to_block = after
else:
    raise SystemExit("pool kept changing while reading open positions")
print(f"{len(ev):,} position events in blocks {a.from_block:,}-{to_block:,}; lockers {ev.locker.unique().tolist()}")
pd.DataFrame([{"block": int(l["blockNumber"], 16), "log_index": int(l["logIndex"], 16),
               "amount0": int(l["data"][2:][64:128], 16) / 10**a.dec0, "amount1": int(l["data"][2:][128:192], 16) / 10**a.dec1}
              for l in acc]).sort_values(["block", "log_index"]).to_csv(a.out_prefix + "_fees_accumulated.csv", index=False)

ts = {b: int(rpc("eth_getBlockByNumber", [hex(b), False])["timestamp"], 16) for b in ev.block.unique()}
ev["ts"] = ev.block.map(ts)
ev["tx_from"] = ev.tx_hash.map({h: rpc("eth_getTransactionByHash", [h])["from"] for h in ev.tx_hash.unique()})
ev.to_csv(a.out_prefix + "_events.csv", index=False)
end_ts = int(rpc("eth_getBlockByNumber", [hex(to_block), False])["timestamp"], 16)
json.dump({"to_block": to_block, "to_ts": end_ts, "open": [{**r, "read_at_block": to_block} for r in st]},
          open(a.out_prefix + "_open.json", "w"), indent=1)
print(f"wrote {a.out_prefix}_events.csv ({len(ev):,} rows, {ev.pos.nunique()} positions, {ev.owner.nunique()} owners) "
      f"and {a.out_prefix}_open.json ({len(st)} open, state at block {to_block:,})")
