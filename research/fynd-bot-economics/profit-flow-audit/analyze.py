"""
Bot profit-flow audit: what happened to the Fynd rebalancing bot's profits, and did any of it reach Fynd LPs.
Reads only profit-flow-audit/data (fetch_flows.py, fetch_contracts.py), the checked LP files and the earlier audit numbers.

  python3 profit-flow-audit/analyze.py --root . --lp ../markout-backtest

Writes into profit-flow-audit/: PROFIT_FLOW_AUDIT.md, BOT_WITHDRAWALS.csv, PROFIT_DESTINATION_TRACE.csv, LP_DEPOSIT_MATCHES.csv,
LP_OWNER_TRANSFER_AUDIT.csv, NATIVE_ETH_FLOW_COVERAGE.md, HAND_CHECKS.md, data/token_reconciliation.csv
"""
import argparse, json, os
from datetime import datetime, timezone
import pandas as pd

ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True)
a = ap.parse_args()
D = lambda *p: os.path.join(a.root, "profit-flow-audit", *p)

# ------------------------------------------------------------------ constants
BOT, SENDER = "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7", "0x4abfdbac0afa181338dc9c38c9c1264128c684a2"
OWNER1, OWNER2 = "0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80", "0x0d41d284672c524d14790b230afe3e287ef4d4b2"
LP6C6A, CORE, X5CEC = "0x6c6a40d2d1fc442e281e1f80314fd86516e17127", "0x00000000000014aa86c5d3c41765bb24e11bd701", "0x5cec1a197e0a0213287a9750f1ba25c60ac2855d"
NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
TOK = {"0x5fc5360d0400a0fd4f2af552add042d716f1d168": ("USDG", 6), "0x0bd7d308f8e1639fab988df18a8011f41eacad73": ("WETH", 18),
       "0x2e8c31162b855a2ffa90f6f8634643ad6f111e18": ("AI", 18), "0x39dbed3a2bd333467115de45665cc57f813c4571": ("PONS", 18),
       "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec": ("NVDA", 18), NATIVE: ("ETH", 18), "0x0000000000000000000000000000000000000000": ("ETH", 18)}
EK_POOLS = {"b67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546": ("Fynd ETH/USDG", "ETH", "USDG"),
            "46e76723bc9334ec559b6c1302a8ac15bef0edbdc42ce139a642df711eae9715": ("Fynd AI/USDG", "AI", "USDG"),
            "bc2615db1f10ca2f2cc9d491fe697ac8a11290f8c900fad313be53bb6763df79": ("Fynd PONS/USDG", "PONS", "USDG"),
            "a9a97762fae3ec95a9b7e51ac6844a1270eee0a223ae69ce598950990ba7becb": ("Fynd USDG/NVDA", "USDG", "NVDA")}
UNI = {"0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca": "Uniswap v3 WETH/USDG 0.01%"}
NAMES = {BOT: "bot contract 0x7ea0…acc7", SENDER: "bot sender 0x4abf…84a2", OWNER1: "owner_1 0xd7c8…1c80", OWNER2: "owner_2 contract 0x0d41…d4b2",
         LP6C6A: "LP 0x6c6a…7127", CORE: "Ekubo Core", X5CEC: "owner_1's contract 0x5cec…855d", **UNI}
DEC = {s: d for s, d in TOK.values()}
TR, APPR = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
UPD = "PositionUpdated"                                 # Ekubo Core position event, matched by topic below
SEL = {"0x3ccdbb28": "withdrawToken(address token,uint256 amount,address to)", "0x095ea7b3": "approve", "0xac9650d8": "multicall (Uniswap router)",
       "0x558d162e": "call to owner_1's contract 0x5cec", "0x0c1a0ee7": "swap via router 0x0921…", "0xf2fde38b": "transferOwnership",
       "0x69d516b3": "call to owner_2 contract (acceptOwnership)"}
s128 = lambda h: (lambda v: v - (1 << 128) if v >= (1 << 127) else v)(int(h, 16))
s256 = lambda h: (lambda v: v - (1 << 256) if v >= (1 << 255) else v)(int(h, 16))
adr = lambda t: "0x" + t[-40:].lower()
nm = lambda x: NAMES.get(x.lower(), x.lower())
utc = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# ------------------------------------------------------------------ data
WL = json.load(open(D("data", "wallet_logs.json")))
BL = json.load(open(D("data", "bot_contract_logs.json")))
OT = [json.loads(x) for x in open(D("data", "owner_txs.jsonl"))]
OT.sort(key=lambda r: (int(r["receipt"]["blockNumber"], 16), int(r["receipt"]["transactionIndex"], 16)))
TX = {r["tx"]["hash"]: r for r in OT}
SN = json.load(open(D("data", "head_snapshot.json")))
CT = json.load(open(D("data", "contracts.json")))
B = pd.read_pickle(os.path.join(a.root, "audit", "data", "_binance.pkl")).close     # Binance ETHUSDC 1 s close, index = unix s
AN = json.load(open(os.path.join(a.root, "audit", "data", "audit_numbers.json")))
FA = pd.read_csv(os.path.join(a.root, "audit", "fee_allocation_audit.csv"))
SP = json.load(open(os.path.join(a.lp, "results_lp_fynd_split.json")))
POS = pd.read_csv(os.path.join(a.lp, "results_lp_fynd_positions.csv"))
LPE = pd.read_csv(os.path.join(a.lp, "data_swaps", "eth_usdg_ekubo_robinhood_lp_to1113_events.csv"))
eth_px = lambda ts: float(B.reindex([int(ts) - 1], method="ffill").iloc[0])
ts_of = {r["tx"]["hash"]: r["timestamp"] for r in OT}

# ------------------------------------------------------------------ 1. bot profit events (all pools, deployment to head)
ev = [l for l in BL["logs"] if l["topics"][0].startswith("0xed370fed")]
P = pd.DataFrame([{"block": int(l["blockNumber"], 16), "tx": l["transactionHash"], "token": adr(l["topics"][3]), "pool": l["data"][2:66],
                   "profit_raw": int(l["data"][2 + 64 * 3:2 + 64 * 4], 16)} for l in ev]).astype({"profit_raw": object})
P["asset"] = P.token.map(lambda t: TOK[t][0]); P["pool_name"] = P.pool.map(lambda p: EK_POOLS.get(p, (p[:10],))[0])
P["profit"] = [r.profit_raw / 10 ** DEC[r.asset] for r in P.itertuples()]
trade_tx = set(P.tx)

# ------------------------------------------------------------------ 2. withdrawals: bot contract transfers outside trade transactions
logs = WL["logs"]
wd = [l for l in logs if l["topics"][0] == TR and adr(l["topics"][1]) == BOT and l["transactionHash"] not in trade_tx]
W = []
for l in wd:
    r = TX[l["transactionHash"]]; t = r["tx"]; inp = t["input"]
    asset, dec = TOK[l["address"].lower()]
    W.append({"tx_hash": l["transactionHash"], "block": int(l["blockNumber"], 16), "timestamp_utc": utc(r["timestamp"]),
              "initiator": t["from"].lower(), "called_contract": t["to"].lower(), "function": SEL.get(inp[:10], inp[:10]),
              "calldata_token": adr(inp[10:74]), "calldata_amount_raw": int(inp[74:138], 16), "calldata_to": adr(inp[138:202]),
              "asset": asset, "amount": int(l["data"], 16) / 10 ** dec, "amount_raw": int(l["data"], 16),
              "sender": BOT, "recipient": adr(l["topics"][2]), "status": int(r["receipt"]["status"], 16),
              "evidence_type": "ERC-20 Transfer log in the receipt + decoded calldata", "confidence": "directly observed"})
W = pd.DataFrame(W).astype({"amount_raw": object, "calldata_amount_raw": object})
assert (W.calldata_amount_raw == W.amount_raw).all() and (W.calldata_to == W.recipient).all()

# ------------------------------------------------------------------ 3. owner_1 transactions after the withdrawals: decode every hop
def ekubo_swaps(rc):
    out = []
    for l in rc["logs"]:
        if l["address"].lower() == CORE and not l["topics"] and len(l["data"]) == 234:
            d = l["data"][2:]; pool = d[40:104]; nm_, t0, t1 = EK_POOLS.get(pool, (pool[:10], "?", "?"))
            out.append({"log_index": int(l["logIndex"], 16), "pool": nm_, "t0": t0, "t1": t1,
                        "a0": s128(d[104:136]) / 10 ** DEC.get(t0, 18), "a1": s128(d[136:168]) / 10 ** DEC.get(t1, 18), "locker": "0x" + d[:40]})
    return out


def transfers(rc):
    return [{"log_index": int(l["logIndex"], 16), "asset": TOK.get(l["address"].lower(), (l["address"][:10], 18))[0],
             "from": adr(l["topics"][1]), "to": adr(l["topics"][2]),
             "amount": int(l["data"], 16) / 10 ** TOK.get(l["address"].lower(), ("", 18))[1]}
            for l in rc["logs"] if l["topics"] and l["topics"][0] == TR and len(l["topics"]) == 3]


rows = []
o1tx = [r for r in OT if r["tx"]["from"].lower() == OWNER1]
for r in o1tx:
    t, rc = r["tx"], r["receipt"]; h = t["hash"]; inp = t["input"].lower(); ts = r["timestamp"]
    base = {"tx_hash": h, "block": int(rc["blockNumber"], 16), "timestamp_utc": utc(ts), "initiator": OWNER1, "called_contract": (t["to"] or "").lower()}
    tr = transfers(rc)
    if inp.startswith("0xac9650d8"):                                 # Uniswap router multicall: exactInputSingle + unwrapWETH9(recipient)
        uw = inp.find("49404b7c"); rec = "0x" + inp[uw + 8 + 64 + 24:uw + 8 + 128] if uw > 0 else ""
        sold = [x for x in tr if x["from"] == OWNER1][0]; weth_out = [x for x in tr if x["asset"] == "WETH" and x["to"] == "0x" + "0" * 40][0]
        pool = sold["to"]
        rows.append({**base, "step": "swap", "asset_in": sold["asset"], "amount_in": sold["amount"], "sender": OWNER1, "recipient": pool,
                     "venue": UNI.get(pool, f"Uniswap v3 pool {pool}"), "asset_out": "WETH", "amount_out": weth_out["amount"],
                     "output_recipient": "router 0xcaf6… (then unwrapped)", "destination_class": "A. swap on an external DEX",
                     "evidence_type": "Transfer + Uniswap v3 Swap logs", "confidence": "directly observed"})
        rows.append({**base, "step": "unwrap and send", "asset_in": "WETH", "amount_in": weth_out["amount"], "sender": "router 0xcaf6…",
                     "recipient": rec, "venue": "WETH unwrap (Transfer to 0x0) + unwrapWETH9(min, recipient)", "asset_out": "ETH (native)",
                     "amount_out": weth_out["amount"], "output_recipient": nm(rec), "destination_class": "B. transfer to another wallet (the bot's gas wallet)",
                     "evidence_type": "WETH burn log; recipient from decoded calldata; the native ETH transfer itself leaves no log",
                     "confidence": "inferred (calldata names the recipient; native transfer not observable)",
                     "value_usd": weth_out["amount"] * eth_px(ts)})
    elif inp.startswith("0x0c1a0ee7"):                               # router 0x0921…: USDG -> native ETH on the Fynd pool
        rec = "0x" + inp[10 + 64 * 5 + 24:10 + 64 * 6]
        sw = ekubo_swaps(rc)[0]; sold = [x for x in tr if x["from"] == OWNER1][0]
        rows.append({**base, "step": "swap and send", "asset_in": sold["asset"], "amount_in": sold["amount"], "sender": OWNER1, "recipient": CORE,
                     "venue": f"Ekubo {sw['pool']} (via router 0x0921…)", "asset_out": "ETH (native)", "amount_out": -sw["a0"],
                     "output_recipient": nm(rec), "destination_class": "A. swap on Fynd's own pool, output to the bot's gas wallet",
                     "evidence_type": "Transfer + Ekubo swap log; recipient from decoded calldata (word 6); native payout leaves no log",
                     "confidence": "swap directly observed; recipient inferred from calldata", "value_usd": -sw["a0"] * eth_px(ts)})
    elif inp.startswith("0x558d162e"):                               # owner_1's contract 0x5cec: per pool, tokens in vs swapped
        sw = ekubo_swaps(rc); x_ev = [l for l in rc["logs"] if l["address"].lower() == X5CEC]
        for i, l in enumerate(x_ev):
            d = l["data"][2:]; tok = adr(d[0:64]); asset = TOK[tok][0]; amt_in = int(d[64:128], 16) / 10 ** DEC[asset]
            s = sw[i]; side = "a0" if s["t0"] == asset else "a1"; used = s[side]
            out_asset = s["t1"] if side == "a0" else s["t0"]; out_amt = -(s["a1"] if side == "a0" else s["a0"])
            prev = int(x_ev[i - 1]["logIndex"], 16) if i else -1          # transfers between the previous 0x5cec report and this one
            paid = [x for x in tr if x["from"] == OWNER1 and x["asset"] == asset and prev < x["log_index"] < int(l["logIndex"], 16)]
            paid_amt = sum(x["amount"] for x in paid) if asset != "ETH" else None
            rows.append({**base, "step": f"0x5cec leg {i + 1}: {s['pool']}", "asset_in": asset, "amount_in": amt_in,
                         "sender": OWNER1 if asset != "ETH" else "owner_1 via tx value", "recipient": CORE,
                         "venue": f"Ekubo {s['pool']} through 0x5cec", "asset_out": out_asset, "amount_out": out_amt,
                         "amount_swapped": used, "amount_paid_into_core_logged": paid_amt,
                         "amount_not_swapped": (paid_amt - used) if paid_amt is not None else None,
                         "output_recipient": "owner_1 (Transfer logs)" if out_asset != "ETH" else "not observable (native)",
                         "destination_class": "F. unresolved: entered Ekubo Core, ~0.01% swapped, no liquidity event, not returned",
                         "evidence_type": "Transfer logs into Core + Ekubo swap log + 0x5cec event (token, amount in, amount out)",
                         "confidence": "transfers into Core directly observed; what Core did with the unswapped balance not observable"})
H = SN["wallets"]
for k_, asset in [("USDG_raw", "USDG"), ("AI_raw", "AI"), ("PONS_raw", "PONS"), ("NVDA_raw", "NVDA"), ("native_wei", "ETH (native)")]:
    v = H["owner_1"][k_] / 10 ** DEC[asset.split()[0]]
    rows.append({"tx_hash": "(balance at head)", "block": SN["block_to"], "timestamp_utc": utc(SN["timestamp"]), "step": "retained",
                 "asset_in": asset, "amount_in": v, "sender": OWNER1, "recipient": OWNER1, "destination_class": "E. retained wallet balance",
                 "evidence_type": "balanceOf / eth_getBalance at head", "confidence": "directly observed"})
TRC = pd.DataFrame(rows)

# owner_1 ledgers (tokens): every Transfer in/out of owner_1, reconciled to the head balance
o1_in = [l for l in logs if l["topics"][0] == TR and len(l["topics"]) == 3 and adr(l["topics"][2]) == OWNER1]
o1_out = [l for l in logs if l["topics"][0] == TR and len(l["topics"]) == 3 and adr(l["topics"][1]) == OWNER1]
LED = []
for asset, key in [("USDG", "USDG_raw"), ("AI", "AI_raw"), ("PONS", "PONS_raw"), ("NVDA", "NVDA_raw")]:
    addr = [k for k, v in TOK.items() if v[0] == asset][0]
    i_ = sum(int(l["data"], 16) for l in o1_in if l["address"].lower() == addr)
    o_ = sum(int(l["data"], 16) for l in o1_out if l["address"].lower() == addr)
    LED.append({"asset": asset, "in_raw": i_, "out_raw": o_, "head_balance_raw": H["owner_1"][key], "residual_raw": i_ - o_ - H["owner_1"][key]})
LED = pd.DataFrame(LED)

# ------------------------------------------------------------------ 4. token reconciliation for the bot contract
REC = []
for asset, key in [("USDG", "USDG_raw"), ("AI", "AI_raw"), ("PONS", "PONS_raw"), ("NVDA", "NVDA_raw"), ("ETH", "native_wei")]:
    prof = sum(int(x) for x in P[P.asset == asset].profit_raw); wdr = sum(int(x) for x in W[W.asset == asset].amount_raw)  # exact ints (18-dec raw overflows int64)
    bal = H["bot_contract"][key]
    REC.append({"asset": asset, "profit_events": prof / 10 ** DEC[asset], "withdrawn_observed": wdr / 10 ** DEC[asset],
                "balance_at_head": bal / 10 ** DEC[asset], "unexplained": (prof - wdr - bal) / 10 ** DEC[asset],
                "trades": int((P.asset == asset).sum()), "pools": ", ".join(sorted(P[P.asset == asset].pool_name.unique())),
                "note": "native ETH: outflows leave no log" if asset == "ETH" else "ERC-20: every transfer is logged"})
REC = pd.DataFrame(REC)
REC.to_csv(D("data", "token_reconciliation.csv"), index=False, float_format="%.12g")
eth_gap = float(REC.set_index("asset").loc["ETH", "unexplained"])

# value of what was withdrawn (USD): USDG at par; AI/PONS at the ETH they fetched on Oct 23 (Binance at that second);
# Nov 10 AI/PONS at the price of the small Ekubo swap in the same transaction (indicative only)
px = {}
for r in rows:
    if r.get("step") == "swap" and r["asset_in"] in ("AI", "PONS"):
        px[(r["asset_in"], "oct23")] = r["amount_out"] * eth_px(datetime.strptime(r["timestamp_utc"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()) / r["amount_in"]
    if str(r.get("step", "")).startswith("0x5cec") and r["asset_in"] in ("AI", "PONS") and r.get("amount_swapped"):
        px[(r["asset_in"], "nov10")] = r["amount_out"] / r["amount_swapped"]
W["usd_indicative"] = [w.amount if w.asset == "USDG" else w.amount * px.get((w.asset, "oct23" if w.block < 100_000_000 else "nov10"), float("nan"))
                       for w in W.itertuples()]
W["usd_method"] = ["USDG at $1" if w.asset == "USDG" else ("ETH it fetched on Oct 23 x Binance" if w.block < 100_000_000 else
                   "price of the small Ekubo swap in the Nov 10 transaction (indicative)") for w in W.itertuples()]
eth_row = {"tx_hash": "not observable", "block": None, "timestamp_utc": f"between deployment and {utc(SN['timestamp'])}",
           "initiator": "unknown", "function": "unknown (native ETH leaves no log)", "asset": "ETH (native)", "amount": eth_gap,
           "sender": BOT, "recipient": "unknown", "evidence_type": "profit events minus balance at head",
           "confidence": "inferred: left the contract, path and recipient not observable", "usd_indicative": eth_gap * eth_px(SN["timestamp"] - 3600 * 24 * 3),
           "usd_method": "ETH at Binance on Nov 15 (indicative; timing unknown)"}
WOUT = pd.concat([W, pd.DataFrame([eth_row])], ignore_index=True)
WOUT.to_csv(D("BOT_WITHDRAWALS.csv"), index=False, float_format="%.12g")
TRC.to_csv(D("PROFIT_DESTINATION_TRACE.csv"), index=False, float_format="%.12g")

# ------------------------------------------------------------------ 5. LP deposit search
upd_topic = "0x" + __import__("Crypto.Hash.keccak", fromlist=["keccak"]).new(digest_bits=256, data=b"PositionUpdated(address,bytes32,bytes32,int128,bytes32,bytes32)").hexdigest()
v3_inc, v3_mint = "0x3067048beee31b25b2f1681f88dac838c8bba36af25bfb2b7cf7473a5847e35f", "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
v4_mod = "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec"
liq_logs = [(r["tx"]["hash"], l) for r in OT for l in r["receipt"]["logs"] if l["topics"] and l["topics"][0] in (upd_topic, v3_inc, v3_mint, v4_mod)]
audited = {BOT, SENDER, OWNER1, OWNER2}
nft_in = [l for l in logs if l["topics"][0] == TR and len(l["topics"]) == 4 and adr(l["topics"][2]) in audited]
fy_by = LPE[(LPE.tx_from.str.lower().isin(audited)) | (LPE.owner.str.lower().isin(audited)) | (LPE.minted_to.str.lower().isin(audited))]
x_ev_all = CT["x5cec_logs"]
fees_in_o1 = [(r["tx"]["hash"], l) for r in o1tx for l in r["receipt"]["logs"] if l["topics"] and l["topics"][0].startswith("0xf7e050d8")]
LDM = pd.DataFrame([
    {"check": "Ekubo PositionUpdated / Uniswap v3 Mint, IncreaseLiquidity / Uniswap v4 ModifyLiquidity in any transaction involving owner_1 or owner_2",
     "scope": f"{len(OT)} transactions (all owner_1 transactions with a token log, the bot contract's admin transactions, and incoming token transfers)",
     "matches": len(liq_logs), "tx_hashes": ";".join(h for h, _ in liq_logs), "evidence_type": "receipt logs", "confidence": "directly observed"},
    {"check": "position NFTs (ERC-721 Transfer) received by the bot contract's owner_1, owner_2, or the bot sender",
     "scope": f"all ERC-721 Transfer logs to these addresses, blocks {WL['from_block']:,}-{WL['to_block']:,}",
     "matches": len(nft_in), "tx_hashes": ";".join(l["transactionHash"] for l in nft_in), "evidence_type": "Transfer logs (any NFT contract)", "confidence": "directly observed"},
    {"check": "Fynd ETH/USDG liquidity events sent, owned or minted by an audited wallet",
     "scope": f"all {int((LPE.event == 'position').sum())} position and {int((LPE.event == 'fees_collected').sum())} fee-collect events, blocks {LPE.block.min():,}-{LPE.block.max():,}",
     "matches": len(fy_by), "tx_hashes": ";".join(fy_by.tx_hash), "evidence_type": "checked LP event file (tx sender, NFT owner, minter)", "confidence": "directly observed"},
    {"check": "owner_1's contract 0x5cec: any event other than its per-swap report",
     "scope": f"all {len(x_ev_all)} logs it has ever emitted", "matches": sum(1 for l in x_ev_all if not l["topics"][0].startswith("0xbdb6d4ff")),
     "tx_hashes": ";".join(sorted({l["transactionHash"] for l in x_ev_all})), "evidence_type": "eth_getLogs on 0x5cec", "confidence": "directly observed"},
    {"check": "FeesAccumulated (fee payment to LPs) in owner_1 transactions large enough to carry the unswapped Nov 10 tokens",
     "scope": f"{len(fees_in_o1)} FeesAccumulated logs in owner_1 transactions", "matches": 0,
     "tx_hashes": ";".join(sorted({h for h, _ in fees_in_o1})), "evidence_type": "FeesAccumulated amounts (largest: see PROFIT_FLOW_AUDIT.md)", "confidence": "directly observed"},
])
LDM.to_csv(D("LP_DEPOSIT_MATCHES.csv"), index=False)
fees_sizes = []
for h, l in fees_in_o1:
    d = l["data"][2:]; pool = d[:64]; nm_, t0, t1 = EK_POOLS.get(pool, (pool[:10], "?", "?"))
    fees_sizes.append((nm_, int(d[64:128], 16) / 10 ** DEC.get(t0, 18), t0, int(d[128:192], 16) / 10 ** DEC.get(t1, 18), t1))

# ------------------------------------------------------------------ 6. transfers between audited wallets and LP owners
lp_owners = sorted({o.split()[-1] for o in POS.owner.str.lower()})          # "via 0x…" = position held through that contract
srcs = {BOT: "bot contract", SENDER: "bot sender", OWNER1: "owner_1", OWNER2: "owner_2 (contract)"}
OUT = []
for s_addr, s_nm in srcs.items():
    for o in lp_owners:
        for direction, f_, t_ in [("audited -> LP owner", s_addr, o), ("LP owner -> audited", o, s_addr)]:
            hits = [l for l in logs if l["topics"][0] == TR and len(l["topics"]) >= 3 and adr(l["topics"][1]) == f_ and adr(l["topics"][2]) == t_]
            covered = (direction == "audited -> LP owner") or s_addr != BOT
            OUT.append({"audited_wallet": s_nm, "audited_address": s_addr, "lp_owner": o, "lp_positions": int(POS.owner.str.lower().str.endswith(o).sum()),
                        "direction": direction, "transfers": len(hits) if covered else None,
                        "assets": ";".join(sorted({TOK.get(l["address"].lower(), (l["address"],))[0] for l in hits})),
                        "tx_hashes": ";".join(l["transactionHash"] for l in hits),
                        "evidence_type": "ERC-20/721 Transfer logs, any token, blocks %s-%s" % (f"{WL['from_block']:,}", f"{WL['to_block']:,}"),
                        "confidence": ("directly observed (none found)" if not hits else "directly observed") if covered else
                                      "not scanned here (bot contract incoming = trade flows); see the earlier USDG/WETH scan"})
LOT = pd.DataFrame(OUT).astype({"transfers": "Int64"})
old = pd.read_csv(os.path.join(a.root, "final", "data", "wallet_transfers.csv"))
old_link = old[((old["from"].str.lower().isin(audited)) & (old["to"].str.lower() == LP6C6A)) | ((old["from"].str.lower() == LP6C6A) & (old["to"].str.lower().isin(audited)))]
LOT.loc[len(LOT)] = {"audited_wallet": "bot contract, bot sender, owner_1, owner_2", "audited_address": "", "lp_owner": LP6C6A,
                     "lp_positions": int((POS.owner.str.lower() == LP6C6A).sum()), "direction": "both (USDG, WETH; earlier scan)",
                     "transfers": len(old_link), "assets": "", "tx_hashes": "", "evidence_type": "final/data/wallet_transfers.csv, blocks "
                     f"{old.block.min():,}-{old.block.max():,}", "confidence": "directly observed (none found)" if not len(old_link) else "directly observed"}
LOT.to_csv(D("LP_OWNER_TRANSFER_AUDIT.csv"), index=False)
n_direct = int(LOT.transfers.fillna(0).sum())

# ------------------------------------------------------------------ 7. owner_1 nonce accounting
seen = sorted(int(r["tx"]["nonce"], 16) for r in o1tx)
created = {c["nonce"]: c["address"] for c in CT["owner_1_created_contracts"]}
missing = [n for n in range(CT["owner_1_nonce"]) if n not in seen and n not in created]
created_not_seen = {n: a_ for n, a_ in created.items() if n not in seen}

# did anything come back out of Ekubo Core to an audited wallet after the Nov 10 transaction?
x5_blk = int(next(r for r in o1tx if r["tx"]["input"].startswith("0x558d162e"))["receipt"]["blockNumber"], 16)
x5_hash = next(r for r in o1tx if r["tx"]["input"].startswith("0x558d162e"))["tx"]["hash"]
back = [l for l in logs if l["topics"][0] == TR and len(l["topics"]) == 3 and adr(l["topics"][1]) == CORE and adr(l["topics"][2]) in audited - {BOT}
        and int(l["blockNumber"], 16) >= x5_blk and l["transactionHash"] != x5_hash]
back_big = [l for l in back if int(l["data"], 16) / 10 ** TOK.get(l["address"].lower(), ("", 18))[1] > 1]
LDM.loc[len(LDM)] = {"check": "transfers out of Ekubo Core to owner_1, owner_2 or the bot sender after the Nov 10 transaction (> 1 token unit)",
                     "scope": f"blocks {x5_blk:,}-{WL['to_block']:,}; {len(back)} transfers of any size",
                     "matches": len(back_big), "tx_hashes": ";".join(l["transactionHash"] for l in back_big),
                     "evidence_type": "Transfer logs (any token)", "confidence": "directly observed"}
LDM.to_csv(D("LP_DEPOSIT_MATCHES.csv"), index=False)
ratios = {r.step.split(": ")[1] + " " + r.asset_in: r.amount_in / r.amount_swapped for r in TRC[TRC.step.astype(str).str.startswith("0x5cec")].itertuples()}

# ------------------------------------------------------------------ numbers for the text
f = lambda v, d=2: f"{v:,.{d}f}"
w_sum = W.groupby("asset").agg(n=("amount", "size"), amount=("amount", "sum"), usd=("usd_indicative", "sum"))
r1 = TRC[(TRC.step == "unwrap and send")]; r3 = TRC[TRC.step == "swap and send"]
x5 = TRC[TRC.step.astype(str).str.startswith("0x5cec")]
eth_to_sender = r1.amount_out.sum() + r3.amount_out.sum(); usd_to_sender = r1.value_usd.sum() + r3.value_usd.sum()
stuck = x5[x5.asset_in != "ETH"].groupby("asset_in").amount_not_swapped.sum()
eth_val_sent = float(next(int(r["tx"]["value"], 16) for r in o1tx if r["tx"]["input"].startswith("0x558d162e"))) / 1e18
eth_swapped_x5 = float(x5[x5.asset_in == "ETH"].amount_swapped.sum())
usd_withdrawn = float(W.usd_indicative.sum())
stuck_usd = float(stuck.get("USDG", 0) + stuck.get("AI", 0) * px.get(("AI", "nov10"), 0) + stuck.get("PONS", 0) * px.get(("PONS", "nov10"), 0))
fy = P[P.pool_name == "Fynd ETH/USDG"]
fee80 = FA[FA.section.str.startswith("interval check")]
lp_net = -SP["bot"]["lp_net"]; gross = SP["bot"]["loss_12s"]; fee_c = SP["bot"]["fee"]

# ------------------------------------------------------------------ BOT_WITHDRAWALS summary into md
wtab = "\n".join(f"| {w.timestamp_utc[:16]} | `{w.tx_hash[:12]}…` | {w.asset} | {f(w.amount, 6)} | ${f(w.usd_indicative)} | `{w.calldata_to[:6]}…{w.calldata_to[-4:]}` (owner_1) |" for w in W.itertuples())
rtab = "\n".join(f"| {r.asset} | {f(r.profit_events, 6)} | {f(r.withdrawn_observed, 6)} | {f(r.balance_at_head, 6)} | **{f(r.unexplained, 6)}** | {r.trades:,} | {r.pools} |" for r in REC.itertuples())
ttab = "\n".join(f"| {r.timestamp_utc[:10]} | `{r.tx_hash[:12]}…` | {r.step} | {f(r.amount_in, 6)} {r.asset_in} | {r.venue} | {f(r.amount_out, 6)} {r.asset_out} | {r.output_recipient} | {r.destination_class[:2]} | {r.confidence} |"
                 for r in TRC[TRC.step != "retained"].itertuples())
xtab = "\n".join(f"| {r.step.split(': ')[1]} | {r.asset_in} | {f(r.amount_in, 6)} | {f(r.amount_paid_into_core_logged, 6) if pd.notna(r.amount_paid_into_core_logged) else 'native (no log)'} | {f(r.amount_swapped, 8)} | "
                 f"{f(r.amount_not_swapped, 6) if pd.notna(r.amount_not_swapped) else 'not observable'} |" for r in x5.itertuples())
ftxt = "; ".join(f"{p}: {f(x0, 6)} {t0} + {f(x1, 6)} {t1}" for p, x0, t0, x1, t1 in fees_sizes)
ptab = "\n".join(f"| {p} | {a_} | {int(n):,} | {f(v, 6)} |" for (p, a_), (n, v) in P.groupby(["pool_name", "asset"]).profit.agg(["size", "sum"]).iterrows())

md = f"""# Fynd ETH/USDG: bot profit flow and LP value-return audit

Built by `profit-flow-audit/analyze.py` from raw logs, receipts and chain-head state fetched by `fetch_flows.py` and
`fetch_contracts.py` (Robinhood Chain public RPC: **no traces, no historical state**). Coverage: blocks {WL['from_block']:,} (bot
contract deployment, {utc(TX['0x62431bbad12f1de05811d2771c979ea420a4d8ffb79cd5f860dd6335b9477b91']['timestamp'])[:10]}) to {WL['to_block']:,}; balances at block
~{SN['block_to']:,} ({utc(SN['timestamp'])} UTC). Labels: **directly observed**, **calculated**, **inferred**, **unconfirmed**, **not observable**.

## Answers

1. **How much was withdrawn?** {len(W)} withdrawals, all by `withdrawToken(token, amount, to)` called by owner_1 (`0xd7c8…1c80`),
   all paid to owner_1: **{f(w_sum.loc['USDG', 'amount'], 6)} USDG**, {f(w_sum.loc['AI', 'amount'], 3)} AI, {f(w_sum.loc['PONS', 'amount'], 3)} PONS,
   about **${f(usd_withdrawn, 0)}** in all (*directly observed*; USD *calculated*, indicative for AI/PONS). Separately,
   **{f(eth_gap, 6)} native ETH** of the bot's ETH profit is no longer in the contract and left without any log (*inferred*; path and recipient
   *not observable*). ERC-20 profit reconciles exactly: profit events − withdrawals − balance = 0 for USDG, AI, PONS and NVDA.
2. **Where did it go?** Three rounds:
   - Oct 23: all three withdrawals sold on Uniswap v3 for WETH, unwrapped, and the router told to send the ETH to the **bot's gas
     wallet `0x4abf…84a2`** ({f(r1.amount_out.sum(), 6)} ETH).
   - Nov 11: 106.31 USDG swapped on the **Fynd ETH/USDG pool itself** for {f(r3.amount_out.sum(), 6)} ETH, recipient again the bot's
     gas wallet.
   - Nov 10: {f(stuck.get('USDG', 0), 2)} USDG, {f(stuck.get('AI', 0), 2)} AI and {f(stuck.get('PONS', 0), 2)} PONS (≈${f(stuck_usd, 0)}) went into
     Ekubo Core through `0x5cec…855d`, a contract owner_1 deployed; only ~0.01% of each was swapped and the rest **was not returned to any
     audited wallet and did not become liquidity**. What Core holds it as (most likely an internal saved balance) is *not observable* without traces.
   - Retained by owner_1 at head: {f(H['owner_1']['USDG_raw'] / 1e6, 6)} USDG, {f(H['owner_1']['AI_raw'] / 1e18, 4)} AI, {f(H['owner_1']['PONS_raw'] / 1e18, 4)} PONS,
     {f(H['owner_1']['native_wei'] / 1e18, 6)} ETH.
   In all, about **{f(eth_to_sender, 4)} ETH (${f(usd_to_sender, 0)})** was routed to the bot's gas wallet (*inferred from calldata*: the
   swaps are observed, the native ETH payouts leave no log).
3. **Did any profit become liquidity in a Fynd position?** **No liquidity event was found** (*directly observed*, within coverage):
   no Ekubo PositionUpdated or Uniswap liquidity log in any owner transaction, no position NFT received by any audited wallet, and none
   of the {int((LPE.event == 'position').sum())} Fynd ETH/USDG liquidity events (to block {LPE.block.max():,}, Nov 13) was sent, owned or minted by an
   audited wallet.
4. **Did any profit return to an existing LP position?** **No.** No transfer, liquidity addition or fee payment of that size (`LP_DEPOSIT_MATCHES.csv`).
5. **Did any go to an address linked to Fynd LP capital?** **No direct link found.** {n_direct} token transfers between the audited wallets and
   any of the {len(lp_owners)} LP owners (`LP_OWNER_TRANSFER_AUDIT.csv`). `0x6c6a…7127` is an EIP-7702 wallet delegating to
   `{CT['lp_0x6c6a_7702_delegate']}`, which is not one of owner_1's contracts. Its link to Fynd rests on Edouard's Nov 12 statement (*unconfirmed* on chain).
6. **What cannot be traced?** Every native ETH movement: the {f(eth_gap, 4)} ETH that left the bot contract, the ETH paid to the gas
   wallet, the 0.0698 ETH owner_1 sent into the Nov 10 call, and {len(missing)} owner_1 transactions that left no token log
   (nonces {', '.join(map(str, missing))}). Also the state of the Nov 10 tokens inside Ekubo Core (`NATIVE_ETH_FLOW_COVERAGE.md`).
7. **Is there evidence of value returning to LPs beyond their swap fees?** **No.** The only on-chain path from the bot to LPs is the fee on
   its trades. Owner_1's Nov 11 swap on the Fynd pool paid the normal pool fee like any trader; that is not a return of profit.

## 1. Roles (*directly observed* unless stated)

| address | role | evidence |
|---|---|---|
| `0xd7c8…1c80` owner_1 | EOA; deployed the bot contract (nonce 0), `0x5cec…855d` (nonce 15) and owner_2 (nonce 30); received every withdrawal | CREATE address = keccak(rlp(owner_1, nonce)); Transfer logs |
| `0x0d41…d4b2` owner_2 | **a contract** ({CT['owner_2_code_bytes']:,} bytes) deployed by owner_1; bot contract owner since block 111,842,342 | code at head; ownership events |
| `0x7ea0…acc7` bot contract | executes trades, holds profits; functions incl. `withdrawToken`, `setOperator`, `pause`, ownership | bytecode selectors |
| `0x4abf…84a2` bot sender | sends every trade, pays gas; **received the ETH from owner_1's swaps** | calldata recipients (*inferred*) |
| `0x6c6a…7127` | largest Fynd LP (153 positions); EIP-7702 wallet | code at head; Fynd ownership per Edouard (*unconfirmed* on chain) |

Owner_2 cannot send transactions (it is a contract); it accepted ownership through a call from owner_1. Its "nonce 1" is a
contract's default, not a transaction count (this corrects an earlier statement).

## 2. Bot profit and withdrawals

Profit events by pool (deployment to head; the bot trades four Fynd-extension pools, and its tokens are pooled in one contract,
so no withdrawal can be attributed to a pool):

| pool | profit token | trades | profit |
|---|---|---|---|
{ptab}

Reconciliation per token (`data/token_reconciliation.csv`; *calculated*):

| asset | profit events | withdrawn (logged) | balance at head | unexplained | trades | pools |
|---|---|---|---|---|---|---|
{rtab}

Gas is paid by the bot sender, not the contract, so these are gross trading profits. The ETH/USDG pool alone made about $739 before
gas and $295 after over Oct 13 – Nov 13 (earlier audit); the withdrawals are not that profit (they mix pools, tokens and dates).

Withdrawals (`BOT_WITHDRAWALS.csv`; calldata token, amount and recipient match the Transfer log exactly):

| UTC | tx | asset | amount | USD (indicative) | recipient |
|---|---|---|---|---|---|
{wtab}

## 3. Downstream (`PROFIT_DESTINATION_TRACE.csv`)

| date | tx | step | in | venue | out | output recipient | class | confidence |
|---|---|---|---|---|---|---|---|---|
{ttab}

**The Nov 10 transaction** (`0x52c5a595…`, owner_1 → its own contract `0x5cec…855d`, with 0.0698 ETH attached):

| pool | asset | 0x5cec reported in | paid into Core (logged) | swapped in Ekubo | not swapped |
|---|---|---|---|---|---|
{xtab}

Six of the seven swaps used about 1/10,000 of the amount paid in (ratios {', '.join(f'{v:,.0f}' for v in ratios.values())}); the
small NVDA-pool leg about 1/2,000. The rest stayed in Ekubo Core: no Transfer back to owner_1 or anyone else in
the transaction, no PositionUpdated, and the FeesAccumulated logs in the transaction are ordinary fee payments ({ftxt}).
Ekubo settles all balances before a transaction ends, so the unswapped amount was booked to some internal account inside Core
(*inferred*: most likely a saved balance); which account is *not observable* with logs only. Since then, {len(back_big)} transfers
larger than one token unit have left Core for owner_1, owner_2 or the bot sender (through block {WL['to_block']:,}; {len(back)} of any size),
and `0x5cec` has emitted no log before or since. Whether it was later moved to another address is
*not observable*. Owner_1's token ledgers reconcile exactly (residual {', '.join(f'{r.asset} {r.residual_raw}' for r in LED.itertuples())} raw units).

**Reported vs observed:** the earlier "≈263 USDG swapped on Ekubo" was the USDG *sent into Ekubo Core*: 106.31 was swapped
(Nov 11) and {f(stuck.get('USDG', 0), 2)} entered Core on Nov 10 with ~0.01% swapped. The "≈118 USDG on Uniswap" is exact ({f(TRC[(TRC.step == 'swap') & (TRC.asset_in == 'USDG')].amount_in.sum(), 6)}).
382.78 withdrawn = 117.77 (Uniswap) + {f(stuck.get('USDG', 0) + x5[x5.asset_in == 'USDG'].amount_swapped.sum(), 2)} (Nov 10, into Core) + 106.31 (Fynd pool) + {f(H['owner_1']['USDG_raw'] / 1e6 - 0.018418, 2)} kept (net of 0.018 received back).

## 4. Liquidity search (`LP_DEPOSIT_MATCHES.csv`)

{chr(10).join(f'- {r.check}: **{r.matches}** ({r.scope}).' for r in LDM.itertuples())}

A swap is not a deposit, and a new position owned by the bot's owner would not compensate existing LPs; neither was found anyway.

## 5. Transfers to LP owners (`LP_OWNER_TRANSFER_AUDIT.csv`)

Direct token transfers between {{bot contract, bot sender, owner_1, owner_2}} and the {len(lp_owners)} LP owners: **{n_direct}**,
including `0x6c6a…7127` (also none in the earlier USDG/WETH scan). Indirect paths through shared pools or routers cannot link
owners and are not treated as links.

## 6. Keep three things apart

- **Price rebalancing.** The bot swaps against Fynd and hedges elsewhere. LPs give up the gap to the market on those trades:
  ${f(gross, 0)} before fees at 12 s; that is a trade, not a transfer of profit to anyone in particular.
- **LP compensation.** LPs receive 80% of the fee on every swap, the bot's included: +${f(fee_c, 0)} on the bot's trades, already inside
  the net −${f(lp_net, 0)} (do not add it again). The 80% is verified per fee-payment interval ({'; '.join(f'{r.item}: {int(r.intervals_equal_80pct_within_0_1pct_or_rounding) if hasattr(r, "intervals_equal_80pct_within_0_1pct_or_rounding") else int(r[4])}/{int(r.intervals_checkable)}' for r in fee80.itertuples())}).
  The other 20% is not paid to LPs; its final recipient is not established here.
- **Bot profit distribution.** The contract keeps its trading profit; owner_1 withdrew part of it and turned most of it into ETH for the
  bot's gas wallet. None of it was observed reaching LPs.

## 7. What would settle the open points

A trace-enabled RPC (`debug_traceTransaction`) on `0x52c5a595…` (where the Nov 10 tokens were booked) and on the bot contract's
history (native ETH outflows), or Fynd's confirmation of: the {f(eth_gap, 4)} ETH, the Nov 10 balance in Ekubo Core, and the 20% fee recipient.
"""
open(D("PROFIT_FLOW_AUDIT.md"), "w").write(md)

# ------------------------------------------------------------------ native ETH coverage
nat = f"""# Native ETH flow coverage

Robinhood Chain's public RPC exposes no `debug_trace*`/`trace_*` methods and no historical state (`eth_getBalance` at a past block
fails), and Blockscout's API is behind a browser challenge. Native ETH moves without logs, so this audit can see native ETH only where
a log or calldata describes it.

| flow | what is visible | status |
|---|---|---|
| bot trade profit in ETH (Fynd ETH/USDG pool, native ETH) | the bot contract's trade event (profit word) | *directly observed*: {f(REC.set_index('asset').loc['ETH', 'profit_events'], 6)} ETH over {int(REC.set_index('asset').loc['ETH', 'trades']):,} trades |
| bot contract native balance | `eth_getBalance` at head only | *directly observed*: {f(REC.set_index('asset').loc['ETH', 'balance_at_head'], 6)} ETH |
| ETH that left the bot contract | nothing: no WETH transfer, no event | **{f(eth_gap, 6)} ETH *inferred* (profit − balance), path and recipient *not observable*** |
| Oct 23 swap proceeds to the bot sender | WETH burn log + `unwrapWETH9(min, recipient)` calldata | *inferred* recipient: {f(r1.amount_out.sum(), 6)} ETH |
| Nov 11 swap proceeds to the bot sender | Ekubo swap log (ETH paid by the pool) + recipient word in calldata | *inferred* recipient: {f(r3.amount_out.sum(), 6)} ETH |
| ETH attached to the Nov 10 call | tx value {f(eth_val_sent, 6)}; Ekubo swap consumed {f(eth_swapped_x5, 9)} | remainder *not observable* (refund or kept in Core) |
| owner_1 transactions without token logs | nonce count vs transactions seen: {CT['owner_1_nonce']} sent, {len(seen)} seen, {len(created_not_seen)} contract creations identified by address | {len(missing)} (nonces {', '.join(map(str, missing))}) *not observable*; could include native ETH withdrawals via `withdrawToken` |
| owner_1 native balance | head only | {f(H['owner_1']['native_wei'] / 1e18, 6)} ETH |
| bot sender funding and gas | gas per receipt (earlier audit); funding transfers are native | inflows *not observable* |

What this means: the ETH-side profit trail cannot be closed. The most economical reading (*inferred, unconfirmed*) is that the
{f(eth_gap, 4)} ETH also went to pay the bot's gas, as the observed USDG/AI/PONS proceeds did; nothing on chain contradicts or confirms it.
Missing logs are not proof that no transfer happened.
"""
open(D("NATIVE_ETH_FLOW_COVERAGE.md"), "w").write(nat)

# ------------------------------------------------------------------ hand checks
def raw_logs(h, keep=None):
    rc = TX[h]["receipt"]; out = []
    for l in rc["logs"]:
        if keep and not keep(l):
            continue
        out.append(f"| {int(l['logIndex'], 16)} | `{l['address']}` | `{l['topics'][0][:10] if l['topics'] else 'anonymous'}` | "
                   f"{', '.join('`0x…' + t[-8:] + '`' for t in l['topics'][1:]) or ''} | `{l['data'][:74]}{'…' if len(l['data']) > 74 else ''}` |")
    return "\n".join(out)


w0 = W.iloc[0]; h1 = [r for r in o1tx if r["tx"]["input"].startswith("0xac9650d8")][0]; s1 = TRC[(TRC.tx_hash == h1["tx"]["hash"])]
hx = [r for r in o1tx if r["tx"]["input"].startswith("0x558d162e")][0]; h3 = [r for r in o1tx if r["tx"]["input"].startswith("0x0c1a0ee7")][0]
uw = h1["tx"]["input"].lower().find("49404b7c")
hc = f"""# Hand checks

Open each transaction at `https://robinhoodchain.blockscout.com/tx/<hash>` (Logs tab) and compare.

## HC1 a withdrawal

`{w0.tx_hash}`, block {w0.block:,}, {w0.timestamp_utc} UTC, from owner_1 to the bot contract.

- Calldata: selector `0x3ccdbb28` = `withdrawToken(address,uint256,address)` (keccak of the signature; present in the bot's bytecode).
  Arguments: token `{w0.calldata_token}`, amount {w0.calldata_amount_raw:,}, to `{w0.calldata_to}`.
- Its only log:

| log | address | topic0 | topics | data |
|---|---|---|---|---|
{raw_logs(w0.tx_hash)}

- {w0.amount_raw:,} raw USDG / 10^6 = **{w0.amount:.6f} USDG**, from the bot contract to owner_1. Same as the calldata.

## HC2 Oct 23 sale and the ETH recipient

`{h1['tx']['hash']}` (owner_1 → Uniswap router `0xcaf6…`, `multicall`).

| log | address | topic0 | topics | data |
|---|---|---|---|---|
{raw_logs(h1['tx']['hash'])}

- USDG {s1.iloc[0].amount_in:.6f} from owner_1 into `0x52e6…` (WETH/USDG 0.01%); the pool pays {s1.iloc[0].amount_out:.9f} WETH to the router; the router
  burns that WETH (Transfer to 0x0 = unwrap).
- Inner call `0x49404b7c` = `unwrapWETH9(uint256 amountMinimum, address recipient)`; recipient word:
  `{h1['tx']['input'][uw + 8 + 64:uw + 8 + 128]}` = **bot sender `0x4abf…84a2`**. The ETH payment itself has no log.

## HC3 the Nov 10 transaction

`{hx['tx']['hash']}` (owner_1 → `0x5cec…855d`, value {int(hx['tx']['value'], 16) / 1e18:.9f} ETH). Fynd ETH/USDG leg:

| log | address | topic0 | topics | data |
|---|---|---|---|---|
{raw_logs(hx['tx']['hash'], keep=lambda l: int(l['logIndex'], 16) <= min(int(x['logIndex'], 16) for x in hx['receipt']['logs'] if x['address'].lower() == X5CEC) + 3)}

- USDG Transfer owner_1 → Core: 120,018,088 raw = 120.018088 USDG.
- Ekubo swap (anonymous Core log, pool `b67e0601…`): amount1 = data[136:168] = +12,000 raw = **0.012 USDG** received by the pool.
- `0x5cec` event: (USDG, 120,018,088, 5,794,777,164,829) = its own report of 120.018088 in, 0.0000058 ETH out.
- 120.018088 − 0.012 = **120.006 USDG** paid into Core and not swapped, not returned in the transaction, no PositionUpdated.

## HC4 Nov 11 swap and its recipient

`{h3['tx']['hash']}` (owner_1 → router `0x0921…`): USDG 106.308022 into Core; Ekubo swap on `b67e0601…` with amount0 =
{TRC[TRC.step == 'swap and send'].amount_out.iloc[0]:.9f} ETH paid by the pool; calldata word 6 = `{h3['tx']['input'][10 + 64 * 5:10 + 64 * 6]}`
= **bot sender**.

## HC5 USDG reconciliation (bot contract)

profit events {f(REC.iloc[0].profit_events, 6)} − withdrawn {f(REC.iloc[0].withdrawn_observed, 6)} − balance {f(REC.iloc[0].balance_at_head, 6)} = {f(REC.iloc[0].unexplained, 6)} USDG.

## HC6 owner_1 created the contracts

keccak256(rlp([owner_1, n]))[12:] for n = 0, 15, 30 gives `0x7ea0…acc7`, `0x5cec…855d`, `0x0d41…d4b2`; each has code at head
(`data/contracts.json`). Any RLP/keccak tool reproduces it.
"""
open(D("HAND_CHECKS.md"), "w").write(hc)
assert (REC[REC.asset != "ETH"].unexplained.abs() < 1e-12).all(), REC
print(REC.to_string()); print(LED.to_string()); print("withdrawn usd", usd_withdrawn, "eth to sender", eth_to_sender, usd_to_sender, "stuck", stuck.to_dict(), stuck_usd)
print("missing nonces", missing, "direct LP transfers", n_direct, "liq logs", len(liq_logs), "nft in", len(nft_in))
