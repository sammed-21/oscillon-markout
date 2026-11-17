"""
Independent audit rebuild of every bot transaction, from the raw receipts only (data/bot_txs.jsonl). Does not import decode.py,
build_economics.py or any earlier output; earlier outputs are read only at the end, to compare.

Method (different from decode.py, which starts from Transfer logs):
  - every swap event in the tx is a "leg"; amounts are what the pool RECEIVED (+) or paid (-), raw integers
  - ETH = native ETH or WETH (one asset); USDG; anything else = intermediate token
  - the Fynd fee (charged by Fynd's extension outside the pool's amounts):
        bot pays USDG into Fynd -> fee = USDG Transfer net into Ekubo Core - USDG received by Ekubo legs   (observed)
        bot pays ETH into Fynd  -> fee = bot event word2 (amount paid incl. fee) - ETH the Fynd pool received (bot's own report)
  - router fees: the router's fee event, items paid to anyone other than the bot (observed in ERC20; native = event only)
  - bot's change per asset = -(sum over legs of what pools received) - Fynd fee - router fee          (conservation)
  Independent checks of that:
    C1 USDG: bot's USDG change from Transfer logs to/from the bot's two addresses (observed) must equal the conservation figure
    C2 profit token: the bot event's word3 (profit, in the token it paid into Fynd) must equal the conservation figure
    C3 other token: the bot's change in the token it did not pay in must be zero (no inventory kept)
    C4 intermediates: every non-ETH/USDG token must net to zero over the legs
  Values: Binance ETHUSDC 1 s; price "at T" = close of the candle opening at T-2 (as in the research); horizon h = at T+h.
  On-chain reference U = Uniswap v3 WETH/USDG 0.01% (0x52e65b17), price after its last swap before the tx (never a hedge venue).

  python3 audit/recon.py --root . --lp ../markout-backtest --out audit
"""
import argparse, glob, io, json, os, zipfile
from collections import defaultdict
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
os.makedirs(os.path.join(a.out, "data"), exist_ok=True)

CORE = "0x00000000000014aa86c5d3c41765bb24e11bd701"; PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"; USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
NAT = "0x0000000000000000000000000000000000000000"; EEE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
FY = "b67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546"
EOA = "0x4abfdbac0afa181338dc9c38c9c1264128c684a2"; BC = "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7"
ROUTER = "0x09215a470bd585e59eb3f4b612fbd2678131ff9e"; BOT = {EOA, BC}
TR = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
V4 = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
BOTEV = "0xed370fed53754a96ee9d13a24f69576613bf72421b5cb1c031f813672fc1de7e"
RFEE = "0x90d361ec764fa5642d6f3c5dc38434ac048b8ece7df64dcfa2331ea2114f4480"
FA = "0xf7e050d866774820d81a86ca676f3afe7bc72603ee893f82e99c08fbde39af6c"
WDEP = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"; WWD = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
META = json.load(open(os.path.join(a.root, "data", "meta.json")))
DEC = lambda t: 18 if t in (NAT, WETH) else (META["tokens"].get(t, {}).get("decimals") or 18)
ETHG = lambda t: "ETH" if t in (NAT, WETH) else ("USDG" if t == USDG else t)


def s(h, bits):
    v = int(h, 16)
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def legs_of(rc):
    out = []
    for l in rc["logs"]:
        ad, t, d = l["address"].lower(), l["topics"], l["data"][2:]
        li = int(l["logIndex"], 16)
        if ad == CORE and not t and len(d) == 232:
            pid = d[40:104]
            k = {"token0": NAT, "token1": USDG} if pid == FY else META["ekubo"].get(pid)
            if k is None:
                out.append({"li": li, "dex": "ekubo", "pool": pid, "unknown": True}); continue
            out.append({"li": li, "dex": "fynd" if pid == FY else "ekubo", "pool": pid, "fee_pips": None,
                        "amt": {k["token0"]: s(d[104:136], 128), k["token1"]: s(d[136:168], 128)}})
        elif t and t[0] == V3:
            p = META["v3"].get(ad)
            out.append({"li": li, "dex": "uniswap_v3", "pool": ad, "fee_pips": p["fee"] if p else None, "unknown": p is None,
                        "amt": {p["token0"]: s(d[0:64], 256), p["token1"]: s(d[64:128], 256)} if p else {},
                        "sqrtp": int(d[128:192], 16), "L": int(d[192:256], 16)})
        elif t and t[0] == V4 and ad == PM:
            p = META["v4"].get(t[1])
            out.append({"li": li, "dex": "uniswap_v4", "pool": t[1], "fee_pips": int(d[320:384], 16), "unknown": p is None,
                        "amt": {p["currency0"]: -s(d[0:64], 256), p["currency1"]: -s(d[64:128], 256)} if p else {},   # v4 logs the swapper's side
                        "sqrtp": int(d[128:192], 16), "L": int(d[192:256], 16)})
        elif t and t[0] == V2:
            p = META.get("v2", {}).get(ad)
            i0, i1, o0, o1 = (int(d[k:k + 64], 16) for k in (0, 64, 128, 192))
            out.append({"li": li, "dex": "uniswap_v2", "pool": ad, "fee_pips": 3000, "unknown": p is None,
                        "amt": {p["token0"]: i0 - o0, p["token1"]: i1 - o1} if p else {}})
    return out


KNOWN_T = {TR, V3, V2, V4, WDEP, WWD,
           "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925",   # Approval
           "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1",   # v2 Sync
           "0x37e7f0db430edc9dd31bc66f25f8449353aa0818f503b906747dd8f286cd3802"}   # token bookkeeping emitted next to Transfer
KNOWN_AT = {(CORE, FA), ("0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09", "0xd59d72ec6d1bba1eef52ec72bd29117451b6c411faada758fdea78bf56a87648"),
            (BC, BOTEV), (ROUTER, RFEE)}
OTHER_EXT = {"0xd18685a514e59b06d59824e16db07e73345d9953"}                            # Ekubo stock-pool extension (own bookkeeping)


def unknown_events(rc):
    u = []
    for l in rc["logs"]:
        ad, t = l["address"].lower(), l["topics"]
        if not t:
            if not (ad == CORE and len(l["data"]) == 234):
                u.append(f"{ad[:10]} anonymous")
            continue
        if t[0] in KNOWN_T or (ad, t[0]) in KNOWN_AT or ad in OTHER_EXT:
            continue
        u.append(f"{ad[:10]} {t[0][:10]}")
    return u


def parse(rc):
    logs = rc["logs"]
    tf = []; bev = []; rfe = []; fa = []
    for l in logs:
        ad, t, d = l["address"].lower(), l["topics"], l["data"][2:]
        if not t:
            continue
        if t[0] == TR and len(t) == 3:
            tf.append((ad, "0x" + t[1][-40:], "0x" + t[2][-40:], int(d[:64], 16)))
        elif t[0] in (WDEP, WWD) and ad == WETH:
            who = "0x" + t[1][-40:]
            tf.append((WETH, NAT, who, int(d[:64], 16)) if t[0] == WDEP else (WETH, who, NAT, int(d[:64], 16)))
        elif ad == BC and t[0] == BOTEV:
            w = [d[i:i + 64] for i in range(0, len(d), 64)]
            bev.append({"pool": w[0], "w1": int(w[1], 16), "w2": int(w[2], 16), "w3": int(w[3], 16)})
        elif ad == ROUTER and t[0] == RFEE:
            tok = "0x" + t[1][-40:]; n = int(d[64:128], 16)
            for k in range(n):
                rfe.append((NAT if tok == EEE else tok, "0x" + d[128 + 128 * k + 24:192 + 128 * k], int(d[192 + 128 * k:256 + 128 * k], 16)))
        elif ad == CORE and t[0] == FA and d[:64] == FY:
            fa.append((int(d[64:128], 16), int(d[128:192], 16)))
    return tf, bev, rfe, fa


rows, legrows = [], []
for line in open(os.path.join(a.root, "data", "bot_txs.jsonl")):
    r = json.loads(line); rc = r["receipt"]; tx = r["tx"]
    h = rc["transactionHash"]; blk = int(rc["blockNumber"], 16)
    ts = int((tx or {}).get("blockTimestamp") or next(l["blockTimestamp"] for l in rc["logs"] if l.get("blockTimestamp")), 16)
    L = legs_of(rc); tf, bev, rfe, fa = parse(rc)
    o = {"hash": h, "block": blk, "ts": ts, "tx_index": int(rc["transactionIndex"], 16), "status": int(rc["status"], 16),
         "gas_used": int(rc["gasUsed"], 16), "gas_price_wei": int(rc["effectiveGasPrice"], 16), "issues": []}
    o["gas_eth"] = o["gas_used"] * o["gas_price_wei"] / 1e18
    ue = unknown_events(rc)
    if ue:
        o["issues"].append("unknown events: " + ", ".join(sorted(set(ue))))
    if any(l.get("unknown") for l in L):
        o["issues"].append("swap event on a pool without metadata")
    fy = [l for l in L if l["dex"] == "fynd"]
    if len(fy) != 1:
        o["issues"].append(f"{len(fy)} Fynd legs"); rows.append(o); continue
    F = fy[0]; hed = [l for l in L if l["dex"] != "fynd"]
    o["fynd_eth_raw"], o["fynd_usdg_raw"] = F["amt"][NAT], F["amt"][USDG]
    o["bot_pays"] = "ETH" if F["amt"][NAT] > 0 else "USDG"
    be = [e for e in bev if e["pool"] == FY]
    o["bot_event"] = len(be)
    # ---- Fynd fee
    core_usdg = sum(x for tk, f, t_, x in tf if tk == USDG and t_ == CORE) - sum(x for tk, f, t_, x in tf if tk == USDG and f == CORE)
    ek_usdg = sum(l["amt"].get(USDG, 0) for l in L if l["dex"] in ("fynd", "ekubo") and not l.get("unknown"))
    if o["bot_pays"] == "USDG":
        o["fee_token"], o["fee_raw"], o["fee_source"] = "USDG", core_usdg - ek_usdg, "observed: USDG into Core - USDG received by Ekubo legs"
    else:
        o["fee_token"], o["fee_raw"] = "ETH", (be[0]["w2"] - F["amt"][NAT]) if len(be) == 1 else np.nan
        o["fee_source"] = "bot event: word2 - ETH received by Fynd (bot's own report)"
        o["core_usdg_gap_raw"] = core_usdg - ek_usdg          # must be 0 when the fee is in ETH
    # ---- router fees to anyone outside the bot
    rf = defaultdict(int)
    for tok, who, x in rfe:
        if who not in BOT:
            rf[ETHG(tok)] += x
    o["router_eth_raw"], o["router_usdg_raw"] = rf.get("ETH", 0), rf.get("USDG", 0)
    o["router_other"] = {k: v for k, v in rf.items() if k not in ("ETH", "USDG")}
    # ---- conservation per asset
    pool_recv = defaultdict(int); hedge_recv = defaultdict(int)
    for l in L:
        for tok, x in l.get("amt", {}).items():
            pool_recv[ETHG(tok)] += x
            if l["dex"] != "fynd":
                hedge_recv[ETHG(tok)] += x
    fee_eth = o["fee_raw"] if o["fee_token"] == "ETH" else 0
    fee_usdg = o["fee_raw"] if o["fee_token"] == "USDG" else 0
    o["hedge_eth_raw"], o["hedge_usdg_raw"] = hedge_recv.get("ETH", 0), hedge_recv.get("USDG", 0)
    o["bot_eth_raw"] = -pool_recv.get("ETH", 0) - fee_eth - o["router_eth_raw"]
    o["bot_usdg_raw"] = -pool_recv.get("USDG", 0) - fee_usdg - o["router_usdg_raw"]
    inter = {k: v for k, v in pool_recv.items() if k not in ("ETH", "USDG") and v}
    o["C4_intermediate_left"] = json.dumps(inter) if inter else ""
    # C1: observed USDG Transfers to/from the bot
    obs = sum(x for tk, f, t_, x in tf if tk == USDG and t_ in BOT) - sum(x for tk, f, t_, x in tf if tk == USDG and f in BOT)
    o["C1_usdg_gap_raw"] = obs - o["bot_usdg_raw"]
    # C2 / C3
    if len(be) == 1:
        own = o["bot_eth_raw"] if o["bot_pays"] == "ETH" else o["bot_usdg_raw"]
        o["bot_event_profit_raw"] = be[0]["w3"]; o["C2_profit_gap_raw"] = own - be[0]["w3"]
        o["bot_event_w2_raw"] = be[0]["w2"]
        if o["bot_pays"] == "USDG":                   # second, independent figure for the USDG fee: the bot's own report
            o["fee_bot_event_raw"] = be[0]["w2"] - F["amt"][USDG]
            o["fee_obs_minus_bot_event_raw"] = o["fee_raw"] - o["fee_bot_event_raw"]
    o["C3_other_token_left_raw"] = o["bot_usdg_raw"] if o["bot_pays"] == "ETH" else o["bot_eth_raw"]
    o["hedge_route"] = "+".join(f"{l['dex']}:{l['pool'][:10]}" for l in hed)
    o["n_hedge_legs"] = len(hed)
    o["fa_in_tx"] = len(fa)
    rows.append(o)
    for l in hed:
        amt = l.get("amt", {})
        legrows.append({"hash": h, "block": blk, "ts": ts, "li": l["li"], "dex": l["dex"], "pool": l["pool"], "fee_pips": l.get("fee_pips"),
                        "tokens": "/".join(sorted(ETHG(t) if ETHG(t) in ("ETH", "USDG") else (META["tokens"].get(t, {}).get("symbol") or t[:8]) for t in amt)),
                        "eth_raw": sum(x for t, x in amt.items() if ETHG(t) == "ETH"), "usdg_raw": amt.get(USDG, 0),
                        "other_raw": json.dumps({t: x for t, x in amt.items() if ETHG(t) not in ("ETH", "USDG")}),
                        "eth_is_token0": (min(amt) in (NAT, WETH)) if amt else None,
                        "sqrtp": l.get("sqrtp"), "L": l.get("L"), "n_legs_in_tx": len(hed)})

R = pd.DataFrame(rows); LG = pd.DataFrame(legrows)
R["issues"] = R["issues"].apply("; ".join)

# ---------------------------------------------------------------- prices
frames = []
for d in [os.path.join(a.lp, "klines_eth_1s"), os.path.join(a.lp, "klines_eth_1s_lp"), os.path.join(a.root, "data", "klines_nov13")]:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.Series(k[4].astype(float).values, index=np.where(t > 1e14, t // 10**6, t // 10**3) + 1)
ref = ref[~ref.index.duplicated()].sort_index()
ref.to_frame("close").to_pickle(os.path.join(a.out, "data", "_binance.pkl"))
at = lambda ts: ref.reindex(ts, method="ffill").values
R["B_exec"] = at(R.ts - 1)
for hz in [1, 5, 12, 30, 60]:
    R[f"B_{hz}s"] = at(R.ts + hz)
R["B_ref_time_exec"] = R.ts - 1; R["B_ref_time_12s"] = R.ts + 12
U = pd.concat([pd.read_csv(f, usecols=["block", "tx_index", "log_index", "sqrtPriceX96"]) for f in
               [os.path.join(a.lp, "data_swaps", f) for f in ("weth_usdg_1bp_robinhood_oct02_15.csv", "weth_usdg_1bp_robinhood.csv",
                                                     "weth_usdg_1bp_robinhood_oct22_nov12.csv")]]).drop_duplicates(["block", "log_index"])
U["price"] = (U.sqrtPriceX96.astype(float) / 2**96) ** 2 * 1e12
U = U.sort_values(["block", "tx_index", "log_index"])
key_u = U.block.values * 10**6 + U.tx_index.values
key_r = R.block.values * 10**6 + R.tx_index.values
i = np.searchsorted(key_u, key_r, side="left") - 1                  # last Uniswap swap in an earlier tx
R["U_before"] = np.where(i >= 0, U.price.values[np.clip(i, 0, None)], np.nan)
R.loc[R.block > U.block.max(), "U_before"] = np.nan                  # no Uniswap data after Nov 12
R.to_pickle(os.path.join(a.out, "data", "_R.pkl")); LG.to_pickle(os.path.join(a.out, "data", "_LG.pkl"))
print(len(R), "txs;", len(LG), "hedge legs")
