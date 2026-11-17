"""
Decode one Robinhood Chain transaction (tx + receipt JSON from the public RPC) into swap legs, token transfers and
the bot's own event, then rebuild what each party received.

Sign convention everywhere: + = that party received the token.

What is observed and what is inferred
  observed   ERC20 Transfer logs (exact), every swap event's amounts (exact), gas = gasUsed x effectiveGasPrice
             (gasUsed already includes the L1 part on this chain), the bot contract's own event (exact, but it is the
             bot's own report).
  inferred   native-ETH movements. The Fynd pool and some Uniswap v4 pools hold native ETH, and native transfers emit no
             log; this RPC has no traces. The bot's native ETH change is rebuilt from the swap events, the WETH
             mint/burn logs (wrap/unwrap) and, for the Fynd fee paid in ETH, the bot contract's event. It assumes the
             router keeps no native ETH; that is checked against the bot event's own profit figure.
"""
from collections import defaultdict

CORE = "0x00000000000014aa86c5d3c41765bb24e11bd701"          # Ekubo Core
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"            # Uniswap v4 PoolManager (Robinhood Chain)
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
NATIVE = "0x0000000000000000000000000000000000000000"
ZERO = NATIVE
FYND_POOL = "b67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546"
FYND_EXT = "0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09"
BOT_EOA = "0x4abfdbac0afa181338dc9c38c9c1264128c684a2"
BOT_CONTRACT = "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7"
ROUTER = "0x09215a470bd585e59eb3f4b612fbd2678131ff9e"
BOT = {BOT_EOA, BOT_CONTRACT}

T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
T_APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
T_V3SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
T_V2SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
T_V2SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
T_V4SWAP = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
T_EK_FEES = "0xf7e050d866774820d81a86ca676f3afe7bc72603ee893f82e99c08fbde39af6c"     # FeesAccumulated(poolId, a0, a1)
T_FYND_EXT = "0xd59d72ec6d1bba1eef52ec72bd29117451b6c411faada758fdea78bf56a87648"    # Fynd extension, per block
T_BOT = "0xed370fed53754a96ee9d13a24f69576613bf72421b5cb1c031f813672fc1de7e"          # bot contract, per trade
T_ROUTER = "0x90d361ec764fa5642d6f3c5dc38434ac048b8ece7df64dcfa2331ea2114f4480"       # router, (recipient, amount) list
T_WDEP = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"
T_WWD = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
# events understood and not needed for value flows
OTHER_EKUBO_EXTENSIONS = {"0xd18685a514e59b06d59824e16db07e73345d9953"}   # extension of the Ekubo stock-token pools
KNOWN_EVENTS = {(CORE, T_EK_FEES), (FYND_EXT, T_FYND_EXT), (BOT_CONTRACT, T_BOT), (ROUTER, T_ROUTER)}
T_SHARES = "0x37e7f0db430edc9dd31bc66f25f8449353aa0818f503b906747dd8f286cd3802"   # emitted next to Transfer by some tokens
KNOWN_TOPICS_ANY = {T_TRANSFER, T_APPROVAL, T_V3SWAP, T_V2SYNC, T_V4SWAP, T_WDEP, T_WWD, T_SHARES}


def s256(h):
    v = int(h, 16)
    return v - (1 << 256) if v >= 1 << 255 else v


def s128(h):
    v = int(h, 16)
    return v - (1 << 128) if v >= 1 << 127 else v


def addr(topic):
    return "0x" + topic[-40:].lower()


def decode(tx, rc, meta):
    """Return a dict of raw decoded pieces, amounts in token units (float) and raw integers where exactness matters."""
    dec = lambda t: meta["tokens"].get(t, {}).get("decimals") or 18
    # tx may be None when only the receipt was fetched: nonce/selector unknown, value taken as 0 (it is 0 in every
    # bot tx whose body was fetched) and flagged by tx_body = False
    ts_hex = tx["blockTimestamp"] if tx else next((l["blockTimestamp"] for l in rc["logs"] if l.get("blockTimestamp")), None)
    out = {"hash": rc["transactionHash"], "block": int(rc["blockNumber"], 16), "ts": int(ts_hex, 16) if ts_hex else None,
           "tx_index": int(rc["transactionIndex"], 16), "nonce": int(tx["nonce"], 16) if tx else None,
           "from": rc["from"].lower(), "to": (rc["to"] or "").lower(), "selector": tx["input"][:10] if tx else None,
           "value_wei": int(tx["value"], 16) if tx else 0, "tx_body": tx is not None,
           "status": int(rc["status"], 16), "gas_used": int(rc["gasUsed"], 16),
           "gas_l1": int(rc.get("gasUsedForL1", "0x0"), 16), "gas_price": int(rc["effectiveGasPrice"], 16),
           "legs": [], "transfers": [], "bot_events": [], "router_events": [], "fynd_fees_accumulated": [],
           "fynd_ext_events": [], "unknown": []}
    out["gas_eth"] = out["gas_used"] * out["gas_price"] / 1e18
    for l in rc["logs"]:
        ad, t, d, li = l["address"].lower(), l["topics"], l["data"][2:], int(l["logIndex"], 16)
        t0 = t[0] if t else None
        if ad == CORE and not t and len(d) == 232:                        # Ekubo swap (anonymous)
            pid = d[40:104]
            key = {"token0": NATIVE, "token1": USDG} if pid == FYND_POOL else meta["ekubo"].get(pid)
            if key is None:
                out["unknown"].append((li, ad, "ekubo pool without key " + pid)); continue
            a0, a1 = s128(d[104:136]), s128(d[136:168])                  # + = pool received
            out["legs"].append({"log_index": li, "venue": "fynd" if pid == FYND_POOL else "ekubo", "pool": pid,
                                "locker": "0x" + d[:40], "raw": {key["token0"]: a0, key["token1"]: a1},
                                "recv": {key["token0"]: a0 / 10 ** dec(key["token0"]), key["token1"]: a1 / 10 ** dec(key["token1"])},
                                "sqrt_ratio_word": d[168:192], "liquidity": int(d[200:232], 16)})
        elif t0 == T_V3SWAP:
            p = meta["v3"].get(ad)
            if p is None:
                out["unknown"].append((li, ad, "v3 pool without tokens")); continue
            a0, a1 = s256(d[0:64]), s256(d[64:128])                      # + = pool received
            out["legs"].append({"log_index": li, "venue": "uniswap_v3", "pool": ad, "fee": p["fee"],
                                "raw": {p["token0"]: a0, p["token1"]: a1},
                                "recv": {p["token0"]: a0 / 10 ** dec(p["token0"]), p["token1"]: a1 / 10 ** dec(p["token1"])},
                                "sqrt_price_x96": int(d[128:192], 16), "liquidity": int(d[192:256], 16)})
        elif t0 == T_V2SWAP:
            p = meta.get("v2", {}).get(ad)
            if p is None:
                out["unknown"].append((li, ad, "v2 pool without tokens")); continue
            i0, i1, o0, o1 = (int(d[k:k + 64], 16) for k in (0, 64, 128, 192))
            a0, a1 = i0 - o0, i1 - o1                                     # + = pool received
            out["legs"].append({"log_index": li, "venue": "uniswap_v2", "pool": ad, "fee": None,
                                "raw": {p["token0"]: a0, p["token1"]: a1},
                                "recv": {p["token0"]: a0 / 10 ** dec(p["token0"]), p["token1"]: a1 / 10 ** dec(p["token1"])}})
        elif t0 == T_V4SWAP and ad == PM:
            p = meta["v4"].get(t[1])
            if p is None:
                out["unknown"].append((li, ad, "v4 pool without key " + t[1])); continue
            a0, a1 = -s128(d[32:64]), -s128(d[96:128])                   # v4 reports the swapper's side: flip
            c0, c1 = p["currency0"], p["currency1"]
            out["legs"].append({"log_index": li, "venue": "uniswap_v4", "pool": t[1], "fee": int(d[320:384], 16),
                                "hooks": p["hooks"], "raw": {c0: a0, c1: a1},
                                "recv": {c0: a0 / 10 ** dec(c0), c1: a1 / 10 ** dec(c1)},
                                "sqrt_price_x96": int(d[128:192], 16), "liquidity": int(d[192:256], 16)})
        elif t0 == T_TRANSFER and len(t) == 3:
            out["transfers"].append({"log_index": li, "token": ad, "from": addr(t[1]), "to": addr(t[2]),
                                     "raw": int(d[:64], 16), "amount": int(d[:64], 16) / 10 ** dec(ad)})
        elif t0 in (T_WDEP, T_WWD) and ad == WETH:                        # standard WETH9 events, if ever emitted
            out["transfers"].append({"log_index": li, "token": ad, "from": ZERO if t0 == T_WDEP else addr(t[1]),
                                     "to": addr(t[1]) if t0 == T_WDEP else ZERO, "raw": int(d[:64], 16),
                                     "amount": int(d[:64], 16) / 1e18, "weth9_event": True})
        elif ad == BOT_CONTRACT and t0 == T_BOT:
            w = [d[i:i + 64] for i in range(0, len(d), 64)]
            out["bot_events"].append({"log_index": li, "kind": int(t[1], 16), "venue": addr(t[2]), "token": addr(t[3]),
                                      "pool": w[0], "w1": int(w[1], 16), "w2": int(w[2], 16), "w3": int(w[3], 16),
                                      "id": w[4] if len(w) > 4 else None})
        elif ad == ROUTER and t0 == T_ROUTER:
            n = int(d[64:128], 16)
            out["router_events"].append({"log_index": li, "token": addr(t[1]),
                                         "items": [(addr(d[128 + 128 * k:192 + 128 * k]), int(d[192 + 128 * k:256 + 128 * k], 16))
                                                   for k in range(n)]})
        elif ad == CORE and t0 == T_EK_FEES:
            if d[:64] == FYND_POOL:
                out["fynd_fees_accumulated"].append({"log_index": li, "eth": int(d[64:128], 16) / 1e18, "usdg": int(d[128:192], 16) / 1e6})
        elif ad == FYND_EXT and t0 == T_FYND_EXT:
            out["fynd_ext_events"].append({"log_index": li, "addr": "0x" + d[:40], "ts": int(d[40:48], 16),
                                           "share_raw": int(d[48:64], 16), "share": int(d[48:64], 16) / 2 ** 64})
        elif ad in OTHER_EKUBO_EXTENSIONS:
            pass                                                           # that extension's own bookkeeping events
        elif t0 in KNOWN_TOPICS_ANY:
            pass                                                           # approvals, token-specific bookkeeping
        else:
            out["unknown"].append((li, ad, t0))
    return out


def eth_group(t):
    return "ETH" if t in (NATIVE, WETH) else t


def economics(d, tol_wei=0):
    """Rebuild each party's token change for one decoded bot transaction and classify how complete it is."""
    r = {"hash": d["hash"], "block": d["block"], "ts": d["ts"], "nonce": d["nonce"], "status": d["status"],
         "gas_eth": d["gas_eth"], "n_legs": len(d["legs"]), "issues": []}
    fynd = [l for l in d["legs"] if l["venue"] == "fynd"]
    other = [l for l in d["legs"] if l["venue"] != "fynd"]
    r["n_fynd_legs"], r["n_other_legs"] = len(fynd), len(other)
    r["venues"] = "+".join(sorted({f"{l['venue']}:{l['pool'][:10]}" for l in other}))
    if d["status"] != 1:
        r["issues"].append("reverted")
    if len(fynd) != 1:
        r["issues"].append(f"{len(fynd)} Fynd legs")
    if d["unknown"]:
        r["issues"].append("unknown events: " + "; ".join(f"{u[1][:10]} {str(u[2])[:18]}" for u in d["unknown"]))
    if not fynd:
        return r
    F = fynd[0]
    r["fynd_eth_raw"], r["fynd_usdg_raw"] = F["raw"][NATIVE], F["raw"][USDG]
    r["fynd_eth"], r["fynd_usdg"] = F["recv"][NATIVE], F["recv"][USDG]
    r["fynd_direction"] = "bot_sells_eth" if F["raw"][NATIVE] > 0 else "bot_buys_eth"

    # ---- ERC20 net per address (observed). WETH mint/burn = wrap/unwrap.
    net = defaultdict(lambda: defaultdict(int))
    for t in d["transfers"]:
        net[t["from"]][t["token"]] -= t["raw"]; net[t["to"]][t["token"]] += t["raw"]
    unwrap = net[ZERO].get(WETH, 0)                     # WETH burnt - minted = native ETH released (negative = wrapped)
    # ---- venue check: what each swap says a venue received vs the ERC20 transfers into that venue
    venue_recv = defaultdict(lambda: defaultdict(int))
    for l in d["legs"]:
        v = CORE if l["venue"] in ("fynd", "ekubo") else PM if l["venue"] == "uniswap_v4" else l["pool"]
        for tkn, x in l["raw"].items():
            venue_recv[v][tkn] += x
    fee_usdg_obs = None
    for v, toks in venue_recv.items():
        for tkn, x in toks.items():
            if tkn == NATIVE:
                continue
            gap = net[v].get(tkn, 0) - x
            if v == CORE and tkn == USDG and F["raw"][USDG] > 0:
                fee_usdg_obs = gap                         # bot paid USDG in: the Fynd fee shows up as the extra USDG
            elif v == CORE and tkn not in (USDG, WETH) and gap > 0 and any(l["venue"] == "ekubo" for l in d["legs"]):
                # another Ekubo pool's extension kept part of its output inside Core: a fee paid on that venue
                r.setdefault("other_ekubo_ext_fee", {})[tkn] = gap
            elif abs(gap) > tol_wei:
                r["issues"].append(f"venue {v[:10]} {tkn[:10]} swap/transfer gap {gap}")
    # router fee: the router's event lists (recipient, amount) pairs; amounts to anyone outside the bot are a cost the bot
    # paid. In native ETH the router's event is the only record (inferred); in ERC20 the router keeps the tokens and the
    # Transfer logs show it (observed), so the two must agree.
    rfee = defaultdict(int)
    for ev in d["router_events"]:
        tk = NATIVE if ev["token"] == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee" else ev["token"]
        for who, amt in ev["items"]:
            if who not in BOT:
                rfee[tk] += amt
    r["router_fee_eth_wei"] = rfee.get(NATIVE, 0) + rfee.get(WETH, 0)
    r["router_fee_usdg_raw"] = rfee.get(USDG, 0)
    r["router_fee_other"] = {t: x for t, x in rfee.items() if t not in (NATIVE, WETH, USDG)}
    for v in (ROUTER,):
        for tkn, x in net[v].items():
            if x and x != rfee.get(tkn, 0):
                r["issues"].append(f"router kept {x} of {tkn[:10]}, its event says {rfee.get(tkn, 0)}")
    # ---- the bot's own report
    be = [e for e in d["bot_events"] if e["pool"] == FYND_POOL]
    r["has_bot_event"] = bool(be)
    if len(be) == 1:
        e = be[0]
        r["bot_event_kind"], r["bot_event_w1"], r["bot_event_w2"], r["bot_event_w3"] = e["kind"], e["w1"], e["w2"], e["w3"]
    # ---- Fynd fee paid by the bot
    if F["raw"][NATIVE] > 0:      # bot paid ETH into Fynd: the fee is native, only visible through the bot's event
        r["fee_token"] = "ETH"
        r["fee_raw"] = (be[0]["w2"] - F["raw"][NATIVE]) if len(be) == 1 else None
        r["fee_source"] = "bot event (inferred)"
    else:                          # bot paid USDG into Fynd: the fee is in the USDG transfer to Core (observed)
        r["fee_token"] = "USDG"
        r["fee_raw"] = fee_usdg_obs
        r["fee_source"] = "USDG transfer to Core minus swap amount (observed)"
    fee_native = r["fee_raw"] if (r["fee_token"] == "ETH" and r["fee_raw"] is not None) else 0
    if r["fee_raw"] is None:
        r["issues"].append("Fynd fee not determinable")
    elif r["fee_raw"] < 0:
        r["issues"].append("negative Fynd fee")
    # ---- native ETH (inferred): pools' native receipts, the native Fynd fee, and unwraps (released to the router)
    native_pools = sum(l["raw"].get(NATIVE, 0) for l in d["legs"])
    bot_native = -native_pools - fee_native + unwrap + d["value_wei"] - rfee.get(NATIVE, 0)   # tx value sent by the EOA to its contract stays in the bot
    bot_erc = defaultdict(int)
    for a_ in BOT:
        for tkn, x in net[a_].items():
            bot_erc[tkn] += x
    r["bot_native_wei"] = bot_native
    r["bot_weth_wei"] = bot_erc.get(WETH, 0)
    r["bot_eth_wei"] = bot_native + bot_erc.get(WETH, 0)
    r["bot_usdg_raw"] = bot_erc.get(USDG, 0)
    r["bot_other_tokens"] = {t: x for t, x in bot_erc.items() if t not in (WETH, USDG) and x}
    if r["bot_other_tokens"]:
        r["issues"].append("bot holds other tokens after tx")
    # ---- cross-check against the bot's own profit figure (w3 = amount out - amount paid, in the output token)
    if len(be) == 1:
        own = r["bot_eth_wei"] if r["fynd_direction"] == "bot_sells_eth" else r["bot_usdg_raw"]
        r["bot_event_profit_gap"] = own - be[0]["w3"]
    # ---- every leg's tokens accounted for: non-ETH tokens other than USDG must net to 0 across legs (intermediates)
    leg_net = defaultdict(int)
    for l in d["legs"]:
        for tkn, x in l["raw"].items():
            leg_net[eth_group(tkn)] += x
    # intermediate tokens (anything but ETH/WETH/USDG) must not stay with the bot or the router (observed transfers)
    r["intermediate_residual"] = {t: net[a_][t] for a_ in BOT | {ROUTER} for t in net[a_]
                                  if t not in (WETH, USDG) and net[a_][t] and net[a_][t] != (rfee.get(t, 0) if a_ == ROUTER else 0)}
    if r["intermediate_residual"]:
        r["issues"].append("intermediate token left with bot or router")
    r["legs_eth_net_wei"] = leg_net.get("ETH", 0)
    r["legs_usdg_net_raw"] = leg_net.get(USDG, 0)
    return r
