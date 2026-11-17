"""
Per bot transaction: the Fynd leg and the hedge leg(s), with each pool's price before and after, so that what each
pool gained against Binance can be split into parts that add up exactly.

For one swap leg, pool side (x = ETH received by the pool, y = USDG received, valued at Binance B at execution):
    pool result = x*B + y = x*(B - mid_before)        price gap: where that pool's price sat vs Binance
                          + x*(mid_before - p_nofee)   price impact: moving along its own curve
                          + x*(p_nofee - p_exec)       fee charged on the input
p_exec = -y/x; p_nofee is the price on the input net of the fee. mid_before is rebuilt from the logged price and
liquidity after the swap, assuming the swap stayed inside one liquidity range (checked: the rebuilt pre-swap price is
compared with the pool's previous logged price where we have it, for the Uniswap 0.01% pool).
The price gap is further split at the on-chain reference U (Uniswap v3 0.01% mid before the tx):
    x*(B - U)   the Binance/on-chain basis          x*(U - mid_before)   that pool's own deviation from U

Only hedges that are a single direct ETH/USDG (or WETH/USDG) swap are split; multi-hop routes are reported as one
aggregate (not split). Fees: Uniswap v4's Swap event carries the total fee in pips (LP fee + protocol fee); the LP
part is the pool key's fee. Uniswap v3: pool fee tier; protocol share from slot0.feeProtocol read at the current block
(assumed unchanged over the period).

  python3 final/hedge_legs.py --txs data/bot_txs.jsonl --meta data/meta.json --T out/_T.pkl --out final/data/hedge_legs.csv
"""
import argparse, json, math, sys, os
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from decode import decode, NATIVE, WETH, USDG  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--txs", required=True); ap.add_argument("--meta", required=True); ap.add_argument("--T", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
meta = json.load(open(a.meta))
T = pd.read_pickle(a.T).set_index("hash")
ETHS = {NATIVE, WETH}


def v3_protocol_share(pools):
    """slot0().feeProtocol at the current block: low 4 bits = token0 denominator, high 4 bits = token1 (0 = off)."""
    out = {}
    for p in pools:
        for _ in range(30):
            r = requests.post("https://rpc.mainnet.chain.robinhood.com", json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                              "params": [{"to": p, "data": "0x3850c7bd"}, "latest"]}, timeout=60).json()
            if "result" in r:
                break
        words = [int(r["result"][2 + 64 * i:2 + 64 * (i + 1)], 16) for i in range((len(r["result"]) - 2) // 64)]
        fp = words[5] if len(words) == 7 else None
        if fp is None or fp > 255 or any(v not in (0, 4, 5, 6, 7, 8, 9, 10) for v in (fp % 16, fp >> 4)):
            out[p] = (float("nan"), float("nan"))                    # not a standard Uniswap v3 slot0: split unknown
            continue
        d0, d1 = fp % 16, fp >> 4
        out[p] = (1 / d0 if d0 else 0.0, 1 / d1 if d1 else 0.0)
    return out


rows = []
v3_pools = set()
for line in open(a.txs):
    x = json.loads(line)
    h = x["receipt"]["transactionHash"]
    if h not in T.index or not T.loc[h, "completeness"].startswith("complete"):
        continue
    d = decode(x["tx"], x["receipt"], meta)
    oth = [l for l in d["legs"] if l["venue"] != "fynd"]
    fy = [l for l in d["legs"] if l["venue"] == "fynd"][0]
    single = len(oth) == 1 and set(oth[0]["raw"]) <= ETHS | {USDG} and len(oth[0]["raw"]) == 2 and oth[0]["venue"] in ("uniswap_v3", "uniswap_v4")
    r = {"hash": h, "single_direct_hedge": single, "route": "+".join(f"{l['venue']}:{l['pool'][:10]}" for l in oth)}
    # Fynd leg: price after from the Ekubo log; before = previous swap's price (from the build)
    if single:
        l = oth[0]
        eth_t = next(t for t in l["raw"] if t in ETHS)
        xr, yr = l["raw"][eth_t], l["raw"][USDG]                      # raw, pool side
        sp_a = l["sqrt_price_x96"] / 2**96                           # sqrt(raw USDG / raw ETH)
        L = float(l["liquidity"])
        if l["venue"] == "uniswap_v4":
            fee_total = l["fee"] / 1e6
            lp_fee = meta["v4"][l["pool"]]["fee"] / 1e6
            proto_share = 0.0 if fee_total <= 0 else max(0.0, (fee_total - lp_fee) / fee_total)
        else:
            fee_total = l["fee"] / 1e6
            v3_pools.add(l["pool"]); proto_share = None
        if xr > 0:                                                    # ETH into the hedge pool
            net = xr * (1 - fee_total)
            sp_b = 1 / (1 / sp_a - net / L)
        else:                                                         # USDG into the hedge pool
            net = yr * (1 - fee_total)
            sp_b = sp_a - net / L
        r.update({"hedge_venue": l["venue"], "hedge_pool": l["pool"], "hedge_fee_total": fee_total, "hedge_protocol_share": proto_share,
                  "hedge_eth": xr / 1e18, "hedge_usdg": yr / 1e6, "hedge_mid_before": sp_b ** 2 * 1e12, "hedge_mid_after": sp_a ** 2 * 1e12,
                  "hedge_input": "ETH" if xr > 0 else "USDG", "hedge_pool_key_fee": meta["v4"][l["pool"]]["fee"] / 1e6 if l["venue"] == "uniswap_v4" else l["fee"] / 1e6})
    rows.append(r)
H = pd.DataFrame(rows).set_index("hash")
ps = v3_protocol_share(sorted(v3_pools))
for p, (s0, s1) in ps.items():
    m = H.hedge_pool == p
    H.loc[m, "hedge_protocol_share"] = np.where(H.loc[m, "hedge_input"] == "ETH", s0, s1)   # protocol fee is taken in the input token
H = H.join(T[["block", "ts", "fynd_direction", "notional_usd", "b0", "b12", "uni_before", "pool_before", "pool_after", "fynd_eth", "fynd_usdg",
              "other_eth_recv", "other_usdg_recv", "fee_usd", "fee_bp", "bot_gross_usd", "bot_net_usd", "gas_usd",
              "router_fee_eth_wei", "router_fee_usdg_raw", "gap_before_bp", "gap_after_bp", "venues"]])
S = H.single_direct_hedge.fillna(False)
x, y, B, U = H.hedge_eth, H.hedge_usdg, H.b0, H.uni_before
p_exec = -y / x
p_nf = np.where(H.hedge_input == "ETH", -y / (x * (1 - H.hedge_fee_total)), y * (1 - H.hedge_fee_total) / -x)
H["h_total_usd"] = (x * B + y).where(S)
H["h_basis_usd"] = (x * (B - U)).where(S)
H["h_own_dev_usd"] = (x * (U - H.hedge_mid_before)).where(S)
H["h_price_gap_usd"] = (x * (B - H.hedge_mid_before)).where(S)
H["h_impact_usd"] = (x * (H.hedge_mid_before - p_nf)).where(S)
H["h_fee_usd"] = (x * (p_nf - p_exec)).where(S)
H["h_fee_protocol_usd"] = H.h_fee_usd * H.hedge_protocol_share
H["h_fee_lp_usd"] = H.h_fee_usd - H.h_fee_protocol_usd
H["h_fee_split_unknown_usd"] = H.h_fee_usd.where(H.hedge_protocol_share.isna() & S)
H["h_move_12s_usd"] = (x * (H.b12 - B)).where(S)
H["h_check_usd"] = H.h_total_usd - (H.h_price_gap_usd + H.h_impact_usd + H.h_fee_usd)
H["h_mid_vs_binance_bp"] = 1e4 * np.log(H.hedge_mid_before / B)
H["h_mid_vs_onchain_bp"] = 1e4 * np.log(H.hedge_mid_before / U)
H["h_exec_vs_binance_bp"] = 1e4 * np.log(p_exec / B)
# Fynd leg, same split (pool side; the Fynd fee is charged outside the pool's amounts)
xf, yf = H.fynd_eth, H.fynd_usdg
pf = -yf / xf
H["f_total_usd"] = xf * B + yf
H["f_basis_usd"] = xf * (B - U)
H["f_own_dev_usd"] = xf * (U - H.pool_before)
H["f_price_gap_usd"] = xf * (B - H.pool_before)
H["f_impact_usd"] = xf * (H.pool_before - pf)
H.reset_index().to_csv(a.out, index=False)
s = H[S]
print(f"{len(H):,} complete txs; single direct hedge: {S.sum():,} ({S.mean():.1%}); split check max |gap| ${s.h_check_usd.abs().max():.2e}")
print("v3 protocol shares (token0, token1):", ps)
print(s[["h_total_usd", "h_basis_usd", "h_own_dev_usd", "h_impact_usd", "h_fee_lp_usd", "h_fee_protocol_usd", "h_fee_split_unknown_usd", "h_move_12s_usd"]].sum().round(1).to_string())
