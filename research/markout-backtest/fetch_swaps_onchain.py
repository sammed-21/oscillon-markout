"""
Individual Uniswap v3 swaps for one pool, with who routed them.

Source (default --source rpc): eth_getLogs on the pool -> block time, block, tx index, log index, tx hash,
  sender (the contract that called the pool: router, aggregator or bot), recipient, amounts, sqrtPrice, liquidity, tick.
  --tx-from additionally looks up each transaction's signer ("from") and target ("to"); one RPC call per tx.
Source --source dune: same fields plus tx from/to in one SQL join (needs Dune datapoint allowance).
Cross-check: daily volume vs GeckoTerminal's daily pool volume (an independent indexer; last ~180 days only).

Keys are read from an env file (default research-backtest/.env, read-only): ETH_RPC_URL, DUNE_API_KEY.

  python3 fetch_swaps_onchain.py --pool 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640 --dec0 6 --dec1 18 \
      --start 2026-07-24 --end 2026-10-22 --out data_swaps/usdc_weth_5bp.csv --check-gecko --usd-token 0
"""
import argparse, os, re, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests

SWAP_TOPIC0 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
DUNE_SQL = """
SELECT l.block_time, l.block_number, l.tx_hash, l.index AS log_index, t.index AS tx_index,
       l.topic1, l.topic2, l.data, t."from" AS tx_from, t."to" AS tx_to
FROM ethereum.logs l
JOIN ethereum.transactions t ON t.hash = l.tx_hash AND t.block_number = l.block_number
 AND t.block_time >= TIMESTAMP '{start}' AND t.block_time < TIMESTAMP '{end}'
WHERE l.contract_address = {pool} AND l.topic0 = {topic0}
  AND l.block_time >= TIMESTAMP '{start}' AND l.block_time < TIMESTAMP '{end}'
ORDER BY l.block_number, l.index
"""

ap = argparse.ArgumentParser()
ap.add_argument("--pool", required=True); ap.add_argument("--dec0", type=int, required=True); ap.add_argument("--dec1", type=int, required=True)
ap.add_argument("--start", required=True); ap.add_argument("--end", required=True, help="exclusive")
ap.add_argument("--source", choices=["rpc", "dune"], default="rpc")
ap.add_argument("--tx-from", action="store_true", help="rpc source: look up tx from/to (one call per tx)")
ap.add_argument("--chunk-blocks", type=int, default=10_000)
ap.add_argument("--env", default="../../../research-backtest/.env")
ap.add_argument("--check-gecko", action="store_true"); ap.add_argument("--usd-token", type=int, default=0,
                help="which token is the USD stable, for USD volume (0 or 1)")
ap.add_argument("--out", required=True)
a = ap.parse_args()
os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
env = {m.group(1): m.group(2).strip('"') for line in open(a.env) if (m := re.match(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line))}


def s256(h: str) -> int:
    v = int(h, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def rpc(method: str, params: list, tries: int = 6):
    for i in range(tries):
        try:
            r = requests.post(env["ETH_RPC_URL"], json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=120).json()
            if "result" in r:
                return r["result"]
            err = r.get("error")
        except Exception as e:  # network hiccup
            err = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{method}: {err}")


def block_at(ts: int, lo: int, hi: int) -> int:
    """Highest block with timestamp < ts."""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if int(rpc("eth_getBlockByNumber", [hex(mid), False])["timestamp"], 16) < ts:
            lo = mid
        else:
            hi = mid - 1
    return lo


def from_rpc() -> pd.DataFrame:
    head = int(rpc("eth_blockNumber", []), 16)
    t0, t1 = int(pd.Timestamp(a.start, tz="UTC").timestamp()), int(pd.Timestamp(a.end, tz="UTC").timestamp())
    b0 = block_at(t0, head - 400 * 7200, head) + 1
    b1 = block_at(t1, b0, head)
    rows, b, step = [], b0, a.chunk_blocks
    while b <= b1:
        e = min(b + step - 1, b1)
        try:
            logs = rpc("eth_getLogs", [{"address": a.pool, "topics": [SWAP_TOPIC0], "fromBlock": hex(b), "toBlock": hex(e)}], tries=2)
        except RuntimeError:                                    # too many results: halve the span
            step = max(500, step // 2); continue
        for l in logs:
            d = l["data"][2:]
            rows.append({"ts": int(l["blockTimestamp"], 16), "block": int(l["blockNumber"], 16),
                         "tx_index": int(l["transactionIndex"], 16), "log_index": int(l["logIndex"], 16),
                         "tx_hash": l["transactionHash"], "sender": "0x" + l["topics"][1][-40:],
                         "recipient": "0x" + l["topics"][2][-40:],
                         "amount0": s256(d[0:64]) / 10**a.dec0, "amount1": s256(d[64:128]) / 10**a.dec1,
                         "sqrtPriceX96": str(int(d[128:192], 16)), "liquidity": float(int(d[192:256], 16)), "tick": s256(d[256:320])})
        print(f"  blocks {b:,}-{e:,}: {len(logs):,} swaps (total {len(rows):,})", flush=True)
        b = e + 1
    sw = pd.DataFrame(rows)
    if a.tx_from and len(sw):
        hashes = sw.tx_hash.unique().tolist()

        def look(h):
            t = rpc("eth_getTransactionByHash", [h])
            return h, t["from"], t.get("to")
        with ThreadPoolExecutor(8) as ex:
            got = dict((h, (f, t)) for h, f, t in ex.map(look, hashes))
        sw["tx_from"] = sw.tx_hash.map(lambda h: got[h][0]); sw["tx_to"] = sw.tx_hash.map(lambda h: got[h][1])
    return sw


def from_dune() -> pd.DataFrame:
    H = {"X-DUNE-API-KEY": env["DUNE_API_KEY"]}
    out = []
    for s_, e_ in zip(pd.date_range(a.start, a.end, freq="5D"), list(pd.date_range(a.start, a.end, freq="5D"))[1:] + [pd.Timestamp(a.end)]):
        r = requests.post("https://api.dune.com/api/v1/sql/execute", headers=H, timeout=300,
                          json={"sql": DUNE_SQL.format(start=s_.date(), end=e_.date(), pool=a.pool, topic0=SWAP_TOPIC0)})
        if r.status_code != 200:
            raise SystemExit(f"Dune execute failed ({r.status_code}): {r.text[:300]}")
        eid = r.json()["execution_id"]
        while (st := requests.get(f"https://api.dune.com/api/v1/execution/{eid}/status", headers=H, timeout=60).json())["state"] != "QUERY_STATE_COMPLETED":
            if st["state"] in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
                raise SystemExit(st)
            time.sleep(4)
        off = 0
        while True:
            rows = requests.get(f"https://api.dune.com/api/v1/execution/{eid}/results", headers=H, timeout=300,
                                params={"limit": 50000, "offset": off}).json()["result"]["rows"]
            out += rows
            if len(rows) < 50000:
                break
            off += 50000
    d = pd.DataFrame(out); w = d["data"].str[2:]
    return pd.DataFrame({"ts": pd.to_datetime(d.block_time.str.replace(" UTC", ""), utc=True).astype("int64") // 10**9,
                         "block": d.block_number, "tx_index": d.tx_index, "log_index": d.log_index, "tx_hash": d.tx_hash,
                         "sender": "0x" + d.topic1.str[-40:], "recipient": "0x" + d.topic2.str[-40:],
                         "amount0": w.str[0:64].map(s256) / 10**a.dec0, "amount1": w.str[64:128].map(s256) / 10**a.dec1,
                         "sqrtPriceX96": w.str[128:192].map(lambda h: str(int(h, 16))),
                         "liquidity": w.str[192:256].map(lambda h: float(int(h, 16))), "tick": w.str[256:320].map(s256),
                         "tx_from": d.tx_from, "tx_to": d.tx_to})


sw = (from_rpc() if a.source == "rpc" else from_dune()).drop_duplicates(["tx_hash", "log_index"]).sort_values(["block", "log_index"])
sw.to_csv(a.out, index=False)
print(f"wrote {len(sw):,} swaps -> {a.out} | {pd.to_datetime(sw.ts.min(), unit='s')} .. {pd.to_datetime(sw.ts.max(), unit='s')}")

if a.check_gecko:
    usd = sw["amount0" if a.usd_token == 0 else "amount1"].abs()
    mine = usd.groupby(pd.to_datetime(sw.ts, unit="s").dt.floor("D")).sum()
    g = requests.get(f"https://api.geckoterminal.com/api/v2/networks/eth/pools/{a.pool}/ohlcv/day", params={"limit": 1000}, timeout=60).json()
    gk = pd.Series({pd.Timestamp(x[0], unit="s"): x[5] for x in g["data"]["attributes"]["ohlcv_list"]})
    j = pd.concat({"onchain": mine, "gecko": gk}, axis=1).dropna()
    j = j[(j.index > j.index.min()) & (j.index < j.index.max())]          # drop partial edge days
    print(f"GeckoTerminal cross-check over {len(j)} full days: on-chain ${j.onchain.sum() / 1e9:,.3f}B vs Gecko ${j.gecko.sum() / 1e9:,.3f}B "
          f"({(j.onchain.sum() / j.gecko.sum() - 1) * 100:+.2f}%); daily ratio median {(j.onchain / j.gecko).median():.4f}, "
          f"p5–p95 {(j.onchain / j.gecko).quantile(.05):.3f}–{(j.onchain / j.gecko).quantile(.95):.3f}")
    j.to_csv(a.out.replace(".csv", "_gecko_check.csv"))
