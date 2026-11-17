"""
Fynd ETH/USDG bot economics: one row per bot transaction, a value-flow reconciliation, and execution quality.

Inputs (all read-only; nothing in research/markout-backtest is written):
  --txs            data/bot_txs.jsonl              tx + receipt for every Fynd swap sent by the bot EOA (fetch_txs.py)
  --meta           data/meta.json                  pool keys and token decimals (fetch_meta.py)
  --contract-logs  data/bot_contract_logs.json     every event the bot contract emitted (fetch_contract_logs.py)
  --lp-swaps       results_lp_fynd_split_swaps.csv per-swap LP view from lp_split.py (checked Nov 13 numbers)
  --fynd-pool      Fynd swap files (pool price after every swap)
  --fees-acc       FeesAccumulated events of the Fynd pool
  --uni            Uniswap v3 WETH/USDG 0.01% swap files (on-chain reference price)
  --klines         Binance ETHUSDC 1 s kline folders

Price conventions (same as lp_split.py / compare_pools.py):
  Binance price "at T" = close of the 1 s candle opening at T-2 (ref.ts = open second + 1, looked up at T-1).
  Markout at horizon h = close of the candle opening at T+h-1 (looked up at T+h). USDG = $1 (assumed).
  On-chain reference = Uniswap v3 WETH/USDG 0.01% pool price after its last swap before the bot tx (same block
  ordering by tx index).

  python3 build_economics.py --txs data/bot_txs.jsonl --meta data/meta.json --contract-logs data/bot_contract_logs.json \
      --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv \
      --fynd-pool ../markout-backtest/data_swaps/eth_usdg_ekubo_robinhood_to1108.csv ../markout-backtest/data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv ../markout-backtest/data_swaps/eth_usdg_ekubo_robinhood_nov11_13.csv \
      --fees-acc ../markout-backtest/data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv \
      --uni ../markout-backtest/data_swaps/weth_usdg_1bp_robinhood_oct02_15.csv ../markout-backtest/data_swaps/weth_usdg_1bp_robinhood.csv ../markout-backtest/data_swaps/weth_usdg_1bp_robinhood_oct22_nov12.csv \
      --klines ../markout-backtest/klines_eth_1s ../markout-backtest/klines_eth_1s_lp data/klines_nov13 --out out
"""
import argparse, glob, io, json, os, zipfile
from collections import Counter
import numpy as np
import pandas as pd
from decode import (decode, economics, FYND_POOL, NATIVE, USDG, WETH, T_BOT, T_FYND_EXT, BOT_CONTRACT, addr)

H = [1, 5, 12, 30, 60, 300]
ap = argparse.ArgumentParser()
ap.add_argument("--txs", required=True); ap.add_argument("--meta", required=True); ap.add_argument("--contract-logs", required=True)
ap.add_argument("--lp-swaps", required=True); ap.add_argument("--fynd-pool", nargs="+", required=True)
ap.add_argument("--fees-acc", required=True); ap.add_argument("--uni", nargs="+", required=True)
ap.add_argument("--klines", nargs="+", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
meta = json.load(open(a.meta))

# ---------------------------------------------------------------- Binance 1 s reference
frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames)
t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}) \
    .drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
REF_MAX = int(ref.ts.max())


def at(ts):
    ts = np.asarray(ts, dtype="int64")
    v = pd.merge_asof(pd.DataFrame({"ts": ts}), ref, on="ts")["mid"].values
    return np.where(ts <= REF_MAX, v, np.nan)


# ---------------------------------------------------------------- decode every bot tx
rows, decoded = [], {}
for line in open(a.txs):
    x = json.loads(line)
    d = decode(x["tx"], x["receipt"], meta)
    decoded[d["hash"]] = d
    e = economics(d)
    e["tx_index"] = d["tx_index"]; e["from"] = d["from"]; e["to"] = d["to"]; e["selector"] = d["selector"]
    e["value_wei"] = d["value_wei"]; e["tx_body"] = d["tx_body"]; e["gas_used"] = d["gas_used"]; e["gas_price_wei"] = d["gas_price"]
    e["protocol_share_events"] = ";".join(str(f["share"]) for f in d["fynd_ext_events"])
    rows.append(e)
T = pd.DataFrame(rows).sort_values(["block", "tx_index"]).reset_index(drop=True)
print(f"decoded {len(T):,} bot txs")

# ---------------------------------------------------------------- protocol share of the Fynd fee (extension event)
shares = Counter()
for d in decoded.values():
    for f in d["fynd_ext_events"]:
        shares[f["share"]] += 1
assert len(shares) == 1, f"protocol share changes over time: {shares}"
PROTO = next(iter(shares))
print(f"Fynd extension share field = {PROTO} in all {sum(shares.values()):,} events seen")

# ---------------------------------------------------------------- amounts in units
T["fee_units"] = np.where(T.fee_token == "ETH", T.fee_raw / 1e18, T.fee_raw / 1e6)
T["bot_eth"] = T.bot_eth_wei / 1e18
T["bot_usdg"] = T.bot_usdg_raw / 1e6
T["legs_eth_net"] = T.legs_eth_net_wei / 1e18
T["legs_usdg_net"] = T.legs_usdg_net_raw / 1e6
T["other_eth_recv"] = T.legs_eth_net - T.fynd_eth            # what the other venues (all non-Fynd legs) received
T["other_usdg_recv"] = T.legs_usdg_net - T.fynd_usdg
T["b0"] = at(T.ts - 1)
for h in H:
    T[f"b{h}"] = at(T.ts + h)
T["utc"] = pd.to_datetime(T.ts, unit="s")
T["notional_usd"] = T.fynd_eth.abs() * T.b0
T["fee_usd"] = np.where(T.fee_token == "ETH", T.fee_units * T.b0, T.fee_units)
T["fee_lp_usd"] = T.fee_usd * (1 - PROTO)
T["fee_protocol_usd"] = T.fee_usd * PROTO
T["fee_bp"] = 1e4 * T.fee_usd / T.notional_usd
T["gas_usd"] = T.gas_eth * T.b0
# bot's gross trading P&L: its token change valued at Binance at execution; USDG at $1
T["bot_gross_usd"] = T.bot_eth * T.b0 + T.bot_usdg
T["bot_net_usd"] = T.bot_gross_usd - T.gas_usd
T["bot_gross_bp"] = 1e4 * T.bot_gross_usd / T.notional_usd
# the bot's own profit figure, in its input token
T["bot_event_profit_units"] = np.where(T.fynd_direction == "bot_sells_eth", T.bot_event_w3 / 1e18, T.bot_event_w3 / 1e6)
T["bot_event_profit_gap_units"] = np.where(T.fynd_direction == "bot_sells_eth", T.bot_event_profit_gap / 1e18, T.bot_event_profit_gap / 1e6)
# value flows at Binance price P: Fynd pool's swap side, the fee, the other venues, the bot. Tokens are conserved inside
# the tx, so these four add to 0 at any one price (gas is separate). Checked below.
for tag, P in [("exec", T.b0)] + [(f"{h}s", T[f"b{h}"]) for h in H]:
    T[f"fynd_lp_trade_usd_{tag}"] = T.fynd_eth * P + T.fynd_usdg          # LPs' swap side, fee excluded (- = LP loss)
    T[f"other_venues_usd_{tag}"] = T.other_eth_recv * P + T.other_usdg_recv
    T[f"bot_usd_{tag}"] = T.bot_eth * P + T.bot_usdg
fee_at = lambda P: np.where(T.fee_token == "ETH", T.fee_units * P, T.fee_units)
T["identity_gap_usd_exec"] = T.fynd_lp_trade_usd_exec + fee_at(T.b0) + T.other_venues_usd_exec + T.bot_usd_exec

# ---------------------------------------------------------------- completeness
def classify(r):
    iss = r["issues"]
    if r["status"] != 1:
        return "incomplete: reverted"
    if any(s.startswith("unknown") or "gap" in s or "not determinable" in s or "intermediate" in s or "router kept" in s for s in iss):
        return "incomplete"
    if not r["has_bot_event"] or abs(r["bot_event_profit_gap_units"]) > (1e-12 if r["fynd_direction"] == "bot_sells_eth" else 1e-6):
        return "incomplete: native ETH not confirmed by bot event"
    res = (abs(r["bot_usdg"]) > 1e-6) if r["fynd_direction"] == "bot_sells_eth" else (abs(r["bot_eth"]) > 1e-12)
    if res or iss:
        return "complete, residual inventory"
    return "complete"


T["completeness"] = T.apply(classify, axis=1)
T["issues"] = T.issues.apply(lambda v: "; ".join(v))
print(T.completeness.value_counts().to_string())

# ---------------------------------------------------------------- tie to the checked LP per-swap file
S = pd.read_csv(a.lp_swaps)
Sb = S[S.tx_hash.isin(T.hash)].set_index("tx_hash")
T["lp_split_fee_usd"] = T.hash.map(Sb.fee_usd)
T["lp_split_loss_12s_usd"] = T.hash.map(Sb.loss_12s_usd)
d12 = (T.lp_split_loss_12s_usd + T.fynd_lp_trade_usd_12s).abs()
print(f"12 s LP markout vs lp_split.py: max abs diff ${d12.max():.2e} over {d12.notna().sum():,} swaps")

# ---------------------------------------------------------------- pool price before / after, on-chain reference
FP = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "tx_hash", "price", "liquidity", "amount0", "amount1", "ts", "tx_from"])
                for f in a.fynd_pool]).drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"]).reset_index(drop=True)
FP["price_before"] = FP.price.shift(1)
fp = FP.drop_duplicates("tx_hash", keep="first").set_index("tx_hash")
T["pool_before"] = T.hash.map(fp.price_before)
T["pool_after"] = T.hash.map(FP.drop_duplicates("tx_hash", keep="last").set_index("tx_hash").price)
T["liquidity"] = T.hash.map(fp.liquidity)
U = pd.concat([pd.read_csv(f, usecols=["block", "tx_index", "log_index", "sqrtPriceX96", "ts"]) for f in a.uni]) \
    .drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"]).reset_index(drop=True)
U["p"] = (U.sqrtPriceX96.astype(float) / 2**96) ** 2 * 1e12
U["key"] = U.block * 100_000.0 + U.tx_index
UMAX = U.key.max()
key = T.block * 100_000.0 + T.tx_index
for nm, off in [("uni_before", -0.5), ("uni_after", 0.5)]:
    v = pd.merge_asof(pd.DataFrame({"key": key + off}).reset_index(), U[["key", "p"]].sort_values("key"), on="key") \
        .sort_values("index")["p"].values
    T[nm] = np.where(key + off <= UMAX, v, np.nan)
bp = lambda x, y: 1e4 * np.log(x / y)
T["gap_before_bp"] = bp(T.pool_before, T.b0)            # + = Fynd pool above Binance
T["gap_after_bp"] = bp(T.pool_after, T.b0)
T["gap_onchain_before_bp"] = bp(T.pool_before, T.uni_before)
T["gap_onchain_after_bp"] = bp(T.pool_after, T.uni_after)
T["uni_vs_binance_bp"] = bp(T.uni_before, T.b0)
T["impact_bp"] = bp(T.pool_after, T.pool_before)
T["toward_binance"] = T.gap_after_bp.abs() < T.gap_before_bp.abs()
T["toward_onchain"] = T.gap_onchain_after_bp.abs() < T.gap_onchain_before_bp.abs()
T["crossed_binance"] = np.sign(T.gap_after_bp) == -np.sign(T.gap_before_bp)
Pr = T.pool_before * 1e-12                                # raw USDG units per raw ETH unit
T["depth_1pct_eth"] = T.liquidity * (1 / np.sqrt(Pr) - 1 / np.sqrt(Pr * 1.01)) / 1e18
T["size_vs_depth_1pct"] = T.fynd_eth.abs() / T.depth_1pct_eth
T["hedge_price"] = (T.other_usdg_recv / -T.other_eth_recv).where(T.other_eth_recv != 0)   # USDG per ETH on the other legs
T["fynd_exec_price"] = -T.fynd_usdg / T.fynd_eth
T["hedge_vs_binance_bp"] = bp(T.hedge_price, T.b0)
for h in H:
    T[f"lp_markout_{h}s_usd"] = T[f"fynd_lp_trade_usd_{h}s"]
    T[f"lp_markout_{h}s_bp"] = 1e4 * T[f"fynd_lp_trade_usd_{h}s"] / T.notional_usd

# ---------------------------------------------------------------- the Fynd fee split: LPs get (1 - share)
# Each FeesAccumulated pays LPs for the swaps since the previous one. Where every swap in between is a bot swap, the
# bot's fees are known exactly, so FeesAccumulated should equal (1 - share) x those fees, token by token.
FA = pd.read_csv(a.fees_acc).sort_values(["block", "log_index"]).reset_index(drop=True)
fee_by_hash = T.set_index("hash")
sw = FP[["block", "log_index", "tx_hash"]].copy()
sw["k"] = sw.block * 1e6 + sw.log_index
FA["k"] = FA.block * 1e6 + FA.log_index
sw["fa_idx"] = np.searchsorted(FA.k.values, sw.k.values, side="left")     # the FeesAccumulated that pays this swap
chk = []
for i, g in sw.groupby("fa_idx"):
    if i >= len(FA) or not g.tx_hash.isin(fee_by_hash.index).all():
        continue
    f = fee_by_hash.loc[g.tx_hash]
    e = f.fee_units.where(f.fee_token == "ETH", 0).sum(); u = f.fee_units.where(f.fee_token == "USDG", 0).sum()
    chk.append({"fa_block": FA.block[i], "fa_log_index": FA.log_index[i], "swaps": len(g), "fa_eth": FA.amount0[i], "fa_usdg": FA.amount1[i],
                "bot_fee_eth": e, "bot_fee_usdg": u})
chk = pd.DataFrame(chk)
chk["lp_share_eth"] = chk.fa_eth / chk.bot_fee_eth.where(chk.bot_fee_eth > 1e-12)
chk["lp_share_usdg"] = chk.fa_usdg / chk.bot_fee_usdg.where(chk.bot_fee_usdg > 1e-4)
chk["ok"] = ((chk.fa_eth - (1 - PROTO) * chk.bot_fee_eth).abs() < 1e-12 + 1e-9 * chk.bot_fee_eth) & \
            ((chk.fa_usdg - (1 - PROTO) * chk.bot_fee_usdg).abs() <= 2e-6)
chk.to_csv(os.path.join(a.out, "check_fee_split.csv"), index=False)
FEE_SPLIT = {"intervals_with_only_bot_swaps": int(len(chk)), "match_80pct": int(chk.ok.sum()),
             "lp_share_eth_median": float(chk.lp_share_eth.median()), "lp_share_usdg_median": float(chk.lp_share_usdg.median())}
print("fee split check:", FEE_SPLIT)

# ---------------------------------------------------------------- nonce coverage of the bot EOA
nn = np.sort(T.nonce.dropna().values)
NONCE = {"txs_with_body": int(len(nn)), "first_nonce": int(nn[0]), "last_nonce_seen": int(nn[-1]),
         "fynd_txs_up_to_that_nonce": int((T.nonce <= nn[-1]).sum() if T.tx_body.all() else len(nn)),
         "non_fynd_txs_up_to_that_nonce": int(nn[-1] + 1 - len(nn)), "last_nonce_block": int(T.block[T.nonce == nn[-1]].iloc[0])}
print("nonce:", NONCE)
T.to_pickle(os.path.join(a.out, "_T.pkl")); FP.to_pickle(os.path.join(a.out, "_FP.pkl"))
json.dump({"protocol_share": PROTO, "fee_split_check": FEE_SPLIT, "nonce": NONCE, "binance_last_ts": REF_MAX},
          open(os.path.join(a.out, "_build_meta.json"), "w"), indent=1)
print("saved intermediate frames")
