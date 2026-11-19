"""
Contract facts for the profit-flow audit, read at the chain head (this RPC has no history and no traces):

  - which contracts owner_1 created: CREATE addresses keccak(rlp(owner_1, nonce))[12:] for every nonce it has used,
    kept when code exists there now
  - the bot contract's function selectors (PUSH4 in its bytecode) matched against candidate withdraw/ownership signatures
  - all logs ever emitted by 0x5cec1a19 (the contract owner_1 used on Nov 10)
  - code of 0x6c6a…7127 (an EIP-7702 wallet: 0xef0100 + delegate address) and of owner_2

  python3 profit-flow-audit/fetch_contracts.py --out profit-flow-audit/data
"""
import argparse, json, os, time
import requests
from Crypto.Hash import keccak

RPC = "https://rpc.mainnet.chain.robinhood.com"
OWNER1, BOT, X5CEC = "0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80", "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7", "0x5cec1a197e0a0213287a9750f1ba25c60ac2855d"
LP6C6A, OWNER2 = "0x6c6a40d2d1fc442e281e1f80314fd86516e17127", "0x0d41d284672c524d14790b230afe3e287ef4d4b2"
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
k = lambda s: keccak.new(digest_bits=256, data=s).hexdigest()


def rpc(m, p):
    for i in range(20):
        try:
            r = requests.post(RPC, timeout=120, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).json()
            if "result" in r:
                return r["result"]
        except requests.RequestException:
            pass
        time.sleep(1 + i)
    raise RuntimeError(m)


def create_addr(sender, nonce):
    rb = lambda b: b if len(b) == 1 and b[0] < 0x80 else bytes([0x80 + len(b)]) + b
    n = b"" if nonce == 0 else nonce.to_bytes((nonce.bit_length() + 7) // 8, "big")
    payload = rb(bytes.fromhex(sender[2:])) + (rb(n) if nonce else b"\x80")
    return "0x" + k(bytes([0xc0 + len(payload)]) + payload)[-40:]


def selectors(code):
    b, i, s = bytes.fromhex(code[2:]), 0, set()
    while i < len(b):
        if b[i] == 0x63:
            s.add(b[i + 1:i + 5].hex())
        i += 1 + (b[i] - 0x5f if 0x60 <= b[i] <= 0x7f else 0)
    return s


nonce = int(rpc("eth_getTransactionCount", [OWNER1, "latest"]), 16)
created = []
for n in range(nonce):
    addr = create_addr(OWNER1, n); code = rpc("eth_getCode", [addr, "latest"])
    if code != "0x":
        created.append({"nonce": n, "address": addr, "code_bytes": (len(code) - 2) // 2})
cands = ["withdrawToken(address,uint256,address)", "withdrawToken(address,address,uint256)", "withdraw(address,address,uint256)",
         "withdrawETH(address,uint256)", "withdrawETH(uint256)", "withdrawETH()", "withdraw(uint256)", "withdraw()", "withdrawNative(address,uint256)",
         "sweep(address,address,uint256)", "rescue(address,address,uint256)", "execute(address,uint256,bytes)",
         "transferOwnership(address)", "acceptOwnership()", "renounceOwnership()", "owner()", "pendingOwner()", "setOperator(address)",
         "pause()", "unpause()", "paused()"]
bs = selectors(rpc("eth_getCode", [BOT, "latest"]))
head = int(rpc("eth_blockNumber", []), 16)
x_logs = []
for b in range(84_000_000, head + 1, 5_000_000):
    x_logs += rpc("eth_getLogs", [{"address": X5CEC, "fromBlock": hex(b), "toBlock": hex(min(b + 4_999_999, head))}])
c6 = rpc("eth_getCode", [LP6C6A, "latest"])
out = {"head": head, "owner_1_nonce": nonce, "owner_1_created_contracts": created,
       "bot_contract_selectors": sorted(bs), "bot_contract_matched_signatures": {c: "0x" + k(c.encode())[:8] for c in cands if k(c.encode())[:8] in bs},
       "x5cec_logs": x_logs, "lp_0x6c6a_code": c6, "lp_0x6c6a_7702_delegate": ("0x" + c6[8:48]) if c6.startswith("0xef0100") else None,
       "owner_2_code_bytes": (len(rpc("eth_getCode", [OWNER2, "latest"])) - 2) // 2}
json.dump(out, open(os.path.join(a.out, "contracts.json"), "w"), indent=1)
print(json.dumps({k_: v for k_, v in out.items() if k_ not in ("x5cec_logs", "bot_contract_selectors")}, indent=1))
