"""
Look up what each pool and token touched by the fetched transactions is, from chain state that never changes:
  Uniswap v3 pools      token0(), token1(), fee() by eth_call
  Uniswap v4 pools      Initialize event on the PoolManager (currency0, currency1, fee, hooks)
  Ekubo pools           PoolInitialized event on Core (token0, token1, config = extension + fee + tick spacing)
  ERC20 tokens          symbol(), decimals() by eth_call
Incremental: keeps what data/meta.json already has. Unknown (address, event) pairs are listed for manual review.

  python3 fetch_meta.py --txs data/bot_txs.jsonl data/lp6c6a_txs.jsonl --out data/meta.json
"""
import argparse, json, os, time
from collections import Counter
import requests
from decode import (s256, CORE, PM, T_TRANSFER, T_V3SWAP, T_V2SWAP, T_V4SWAP, T_EK_FEES, T_APPROVAL, KNOWN_EVENTS, NATIVE)

RPC = "https://rpc.mainnet.chain.robinhood.com"
T_V4INIT = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
T_EKINIT = "0x5e4688b340694b7c7fd30047fd082117dc46e32acfbf81a44bb1fac0ae65154d"

ap = argparse.ArgumentParser()
ap.add_argument("--txs", nargs="+", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
M = json.load(open(a.out)) if os.path.exists(a.out) else {"v3": {}, "v4": {}, "ekubo": {}, "tokens": {}}
M.setdefault("v2", {})


def rpc(m, p):
    for i in range(30):
        try:
            r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=120).json()
            if "result" in r:
                return r["result"]
            if "execution reverted" in str(r.get("error")):
                return None
            if "429" not in str(r.get("error")):
                raise RuntimeError(f"{m}: {r.get('error')}")
        except requests.RequestException:
            pass
        time.sleep(10)
    raise RuntimeError(m)


def call(to, sel):
    return rpc("eth_call", [{"to": to, "data": sel}, "latest"])


def calls(pairs):
    """Batch eth_call; None where it reverts."""
    out = []
    for i in range(0, len(pairs), 40):
        chunk = pairs[i:i + 40]
        for attempt in range(40):
            r = requests.post(RPC, json=[{"jsonrpc": "2.0", "id": j, "method": "eth_call", "params": [{"to": t, "data": s}, "latest"]}
                                         for j, (t, s) in enumerate(chunk)], timeout=120).json()
            if isinstance(r, list):
                break
            time.sleep(10)
        by = {x["id"]: x.get("result") for x in r}
        out += [by.get(j) for j in range(len(chunk))]
        time.sleep(3)
    return out


def logs_all(address, topics, latest):
    out, b, step = [], 0, 10_000_000
    while b <= latest:
        e = min(latest, b + step - 1)
        r = rpc("eth_getLogs", [{"address": address, "topics": topics, "fromBlock": hex(b), "toBlock": hex(e)}])
        out += r
        b = e + 1
    return out


v2, v3, v4, ek, tokens, unknown = set(), set(), set(), set(), set(), Counter()
for f in a.txs:
    for line in open(f):
        for l in json.loads(line)["receipt"]["logs"]:
            ad, t = l["address"].lower(), l["topics"]
            t0 = t[0] if t else None
            if t0 == T_V3SWAP:
                v3.add(ad)
            elif t0 == T_V2SWAP:
                v2.add(ad)
            elif t0 == T_V4SWAP and ad == PM:
                v4.add(t[1])
            elif ad == CORE and not t:
                ek.add(l["data"][42:106])
            elif t0 in (T_TRANSFER, T_APPROVAL) and len(t) == 3:
                tokens.add(ad)
            elif (ad, t0) not in KNOWN_EVENTS:
                unknown[(ad, t0)] += 1
latest = int(rpc("eth_blockNumber", []), 16)

need = sorted(v3 - set(M["v3"]))
res = calls([(p, s) for p in need for s in ("0x0dfe1681", "0xd21220a7", "0xddca3f43")])
for i, p in enumerate(need):
    t0, t1, f = res[3 * i:3 * i + 3]
    M["v3"][p] = {"token0": "0x" + t0[-40:], "token1": "0x" + t1[-40:], "fee": int(f, 16)}
print("v3 done", len(need), flush=True)
need = sorted(v2 - set(M["v2"]))
res = calls([(p, s) for p in need for s in ("0x0dfe1681", "0xd21220a7")])
for i, p in enumerate(need):
    M["v2"][p] = {"token0": "0x" + res[2 * i][-40:], "token1": "0x" + res[2 * i + 1][-40:]}
need = sorted(set(v4) - set(M["v4"]))
# This RPC allows 10M blocks only with one value per topic position, and caps results at 10,000 logs (there are more
# v4 pools than that per 10M blocks), so each pool id gets its own query, oldest chunk first, stopping at the match.
found = []
for pid in need:
    for b in range(0, latest + 1, 10_000_000):
        got = rpc("eth_getLogs", [{"address": PM, "topics": [T_V4INIT, pid], "fromBlock": hex(b), "toBlock": hex(min(latest, b + 9_999_999))}])
        if got:
            found += got; break
        time.sleep(0.2)
print("v4 pool ids found", len(found), "of", len(need), flush=True)
for l in found:
    if True:
        d = l["data"][2:]
        M["v4"][l["topics"][1]] = {"currency0": "0x" + l["topics"][2][26:], "currency1": "0x" + l["topics"][3][26:],
                                    "fee": int(d[0:64], 16), "tick_spacing": s256(d[64:128]), "hooks": "0x" + d[152:192],
                                    "created_block": int(l["blockNumber"], 16)}
print("v4 done", len(M["v4"]), flush=True)
need = ek - set(M["ekubo"])
if need:
    for l in logs_all(CORE, [T_EKINIT], latest):
        w = [l["data"][2:][j:j + 64] for j in range(0, 256, 64)]
        if w[0] in need:
            M["ekubo"][w[0]] = {"token0": "0x" + w[1][24:], "token1": "0x" + w[2][24:], "config": "0x" + w[3],
                                "extension": "0x" + w[3][:40], "created_block": int(l["blockNumber"], 16)}
for pool in list(M["v2"].values()) + list(M["v3"].values()) + list(M["v4"].values()) + list(M["ekubo"].values()):
    tokens |= {pool.get(k) for k in ("token0", "token1", "currency0", "currency1") if pool.get(k)}
need = sorted(tokens - set(M["tokens"]) - {NATIVE})
res = calls([(t, s) for t in need for s in ("0x95d89b41", "0x313ce567")])
print("token calls done", len(need), flush=True)
for i, tkn in enumerate(need):
    s, d = res[2 * i], res[2 * i + 1]
    sym = None
    if s and len(s) > 130:
        n = int(s[66:130], 16); sym = bytes.fromhex(s[130:130 + 2 * n]).decode(errors="replace")
    elif s:
        sym = bytes.fromhex(s[2:]).rstrip(b"\0").decode(errors="replace")
    M["tokens"][tkn] = {"symbol": sym, "decimals": int(d, 16) if d else None}
M["tokens"][NATIVE] = {"symbol": "ETH", "decimals": 18}
missing = {"v4": sorted(v4 - set(M["v4"])), "ekubo": sorted(ek - set(M["ekubo"]))}
M["unknown_events"] = {f"{k[0]} {k[1]}": v for k, v in unknown.most_common()}
json.dump(M, open(a.out, "w"), indent=1)
print(f"v3 {len(M['v3'])}, v4 {len(M['v4'])}, ekubo {len(M['ekubo'])}, tokens {len(M['tokens'])}; missing {missing}")
print("unknown (address, event):", M["unknown_events"])
