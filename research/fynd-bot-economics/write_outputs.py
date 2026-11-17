"""
Write the deliverable CSVs and summary.json from build_economics.py's frames. Every aggregate in the report is a sum or
median of a column in these CSVs, recomputed here.

  python3 write_outputs.py --out out --lp-results ../markout-backtest/results_lp_fynd.json \
      --lp-split ../markout-backtest/results_lp_fynd_split.json --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv \
      --fees-acc ../markout-backtest/data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv \
      --contract-logs data/bot_contract_logs.json --other-pool-txs data/bot_other_pool_txs.jsonl \
      --klines ../markout-backtest/klines_eth_1s ../markout-backtest/klines_eth_1s_lp data/klines_nov13
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd
from decode import FYND_POOL, T_BOT, USDG, BOT_EOA, addr

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True); ap.add_argument("--lp-results", required=True); ap.add_argument("--lp-split", required=True)
ap.add_argument("--lp-swaps", required=True); ap.add_argument("--fees-acc", required=True)
ap.add_argument("--contract-logs", required=True); ap.add_argument("--other-pool-txs", required=True)
ap.add_argument("--klines", nargs="+", required=True)
ap.add_argument("--last-tx", required=True, help="tx body of the bot's last Fynd trade (for its nonce)")
a = ap.parse_args()
H = [1, 5, 12, 30, 60, 300]
T = pd.read_pickle(os.path.join(a.out, "_T.pkl"))
FP = pd.read_pickle(os.path.join(a.out, "_FP.pkl"))
BM = json.load(open(os.path.join(a.out, "_build_meta.json")))
R = json.load(open(a.lp_results)); S = json.load(open(a.lp_split))
SW = pd.read_csv(a.lp_swaps)
PROTO = BM["protocol_share"]
SNAP_BLOCK = R["period"]["snapshot_block"]
frames = []
for d in a.klines:
    for p in sorted(glob.glob(os.path.join(d, "*.zip"))):
        with zipfile.ZipFile(p) as z:
            frames += [pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]) for n in z.namelist() if n.endswith(".csv")]
    frames += [pd.read_csv(p, header=None, usecols=[0, 4]) for p in sorted(glob.glob(os.path.join(d, "*.csv")))]
k = pd.concat(frames); t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}) \
    .drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
at = lambda ts: pd.merge_asof(pd.DataFrame({"ts": np.asarray(ts, dtype="int64")}), ref, on="ts")["mid"].values
summary = {}

# ------------------------------------------------------------------ per-transaction economics
T["router_fee_eth"] = T.router_fee_eth_wei / 1e18
T["router_fee_usdg"] = T.router_fee_usdg_raw / 1e6
T["router_fee_usd"] = T.router_fee_eth * T.b0 + T.router_fee_usdg
P_END = float(at([int(pd.Timestamp(R["period"]["end_utc"]).timestamp()) - 1])[0])
T["bot_unrealized_to_snapshot_usd"] = T.bot_eth * (P_END - T.b0)     # ETH kept as profit, revalued at the LP snapshot
T["identity_check_usd"] = T.identity_gap_usd_exec + T.router_fee_usd
econ = pd.DataFrame({
    "tx_hash": T.hash, "block": T.block, "tx_index": T.tx_index, "utc": T.utc, "nonce": T.nonce, "tx_body_fetched": T.tx_body,
    "sender": T["from"], "to": T.to, "status": T.status, "completeness": T.completeness, "issues": T.issues,
    "direction": T.fynd_direction, "other_venues": T.venues, "n_other_legs": T.n_other_legs,
    "fynd_eth_to_pool": T.fynd_eth, "fynd_usdg_to_pool": T.fynd_usdg, "notional_usd": T.notional_usd,
    "binance_at_exec": T.b0, "fynd_fee_token": T.fee_token, "fynd_fee_amount": T.fee_units, "fynd_fee_source": T.fee_source,
    "fynd_fee_usd": T.fee_usd, "fynd_fee_bp": T.fee_bp, "fynd_fee_to_lps_usd": T.fee_lp_usd, "fynd_fee_to_protocol_usd": T.fee_protocol_usd,
    "router_fee_eth": T.router_fee_eth, "router_fee_usdg": T.router_fee_usdg, "router_fee_usd": T.router_fee_usd,
    "bot_eth_change": T.bot_eth, "bot_usdg_change": T.bot_usdg, "bot_event_profit": T.bot_event_profit_units,
    "bot_event_check_gap": T.bot_event_profit_gap_units, "bot_gross_usd": T.bot_gross_usd, "gas_eth": T.gas_eth, "gas_usd": T.gas_usd,
    "bot_net_usd": T.bot_net_usd, "bot_unrealized_to_snapshot_usd": T.bot_unrealized_to_snapshot_usd,
    "residual_other_tokens": T.bot_other_tokens.apply(lambda d: json.dumps(d) if d else ""),
    "lp_swap_side_exec_usd": T.fynd_lp_trade_usd_exec, "lp_swap_side_12s_usd": T.fynd_lp_trade_usd_12s,
    "other_venues_exec_usd": T.other_venues_usd_exec, "other_venues_12s_usd": T.other_venues_usd_12s,
    "identity_check_usd": T.identity_check_usd})
econ.to_csv(os.path.join(a.out, "bot_transaction_economics.csv"), index=False)
C = T[T.completeness.str.startswith("complete")]
summary["coverage"] = {"fynd_bot_txs_expected": int(S["bot"]["swaps"]), "fetched": int(len(T)),
                       "complete": int((T.completeness == "complete").sum()), "complete_with_residual": int((T.completeness == "complete, residual inventory").sum()),
                       "incomplete": int((~T.completeness.str.startswith("complete")).sum()),
                       "bot_event_matches_reconstruction": int((T.bot_event_profit_gap == 0).sum()),
                       "max_abs_identity_check_usd": float(C.identity_check_usd.abs().max()),
                       "first_utc": str(T.utc.min()), "last_utc": str(T.utc.max())}
I = T[~T.completeness.str.startswith("complete")]
summary["coverage"]["incomplete_note"] = "a hedge leg on a DEX type not decoded; the bot's own profit still matches the reconstruction" \
    if len(I) and (I.bot_event_profit_gap == 0).all() else "see issues column"
summary["coverage"]["incomplete_bot_gross_usd"] = float(I.bot_gross_usd.sum())
summary["coverage"]["incomplete_bot_net_usd"] = float(I.bot_net_usd.sum())
summary["coverage"]["incomplete_lp_markout_12s_usd"] = float(I.fynd_lp_trade_usd_12s.sum())

# ------------------------------------------------------------------ execution quality
eq = pd.DataFrame({"tx_hash": T.hash, "block": T.block, "utc": T.utc, "direction": T.fynd_direction, "notional_usd": T.notional_usd,
                   "pool_price_before": T.pool_before, "pool_price_after": T.pool_after, "binance_at_exec": T.b0,
                   "onchain_ref_before": T.uni_before, "onchain_ref_after": T.uni_after,
                   "gap_before_bp": T.gap_before_bp, "gap_after_bp": T.gap_after_bp,
                   "gap_onchain_before_bp": T.gap_onchain_before_bp, "gap_onchain_after_bp": T.gap_onchain_after_bp,
                   "moved_toward_binance": T.toward_binance, "crossed_binance": T.crossed_binance, "moved_toward_onchain_ref": T.toward_onchain,
                   "impact_bp": T.impact_bp, "depth_1pct_eth": T.depth_1pct_eth, "size_vs_depth_1pct": T.size_vs_depth_1pct,
                   "fynd_exec_price": T.fynd_exec_price, "hedge_price": T.hedge_price, "hedge_vs_binance_bp": T.hedge_vs_binance_bp,
                   "hedge_vs_onchain_ref_bp": 1e4 * np.log(T.hedge_price / T.uni_before), "fynd_fee_bp": T.fee_bp,
                   "bot_gross_usd": T.bot_gross_usd, "bot_net_usd": T.bot_net_usd, "bot_gross_bp": T.bot_gross_bp,
                   **{f"lp_markout_{h}s_usd": T[f"lp_markout_{h}s_usd"] for h in H},
                   **{f"lp_markout_{h}s_bp": T[f"lp_markout_{h}s_bp"] for h in H}})
# was the gap already closing? Binance move over the 5 s before the trade, signed toward the pool
b_prev5 = at(T.ts - 6)
eq["binance_move_prior_5s_toward_pool_bp"] = 1e4 * np.log(T.b0 / b_prev5) * np.sign(T.gap_before_bp)
eq.to_csv(os.path.join(a.out, "bot_execution_quality.csv"), index=False)
E = eq[T.completeness.str.startswith("complete").values]
summary["execution"] = {
    "trades": int(len(E)), "moved_toward_binance_share": float(E.moved_toward_binance.mean()),
    "crossed_binance_share": float(E.crossed_binance.mean()), "moved_toward_onchain_share": float(E.moved_toward_onchain_ref.mean()),
    "abs_gap_before_bp_median": float(E.gap_before_bp.abs().median()), "abs_gap_after_bp_median": float(E.gap_after_bp.abs().median()),
    "abs_gap_before_bp_p05": float(E.gap_before_bp.abs().quantile(.05)), "trades_abs_gap_below_3bp": int((E.gap_before_bp.abs() < 3).sum()),
    "trades_where_binance_moved_toward_pool_over_5s_by_1bp_or_more": int((E.binance_move_prior_5s_toward_pool_bp >= 1).sum()),
    "abs_impact_bp_median": float(E.impact_bp.abs().median()), "size_vs_depth_1pct_median": float(E.size_vs_depth_1pct.median()),
    "hedge_vs_binance_bp_median_by_direction": E.groupby("direction").hedge_vs_binance_bp.median().to_dict(),
    "hedge_vs_onchain_bp_median_by_direction": E.groupby("direction").hedge_vs_onchain_ref_bp.median().to_dict(),
    "gap_before_median_by_direction": E.groupby("direction").gap_before_bp.median().to_dict(),
    "gap_after_median_by_direction": E.groupby("direction").gap_after_bp.median().to_dict(),
    "bot_gross_negative_trades": int((E.bot_gross_usd < 0).sum()), "bot_net_negative_trades": int((E.bot_net_usd < 0).sum()),
    "markout_curve": {f"{h}s": {"usd": float(E[f"lp_markout_{h}s_usd"].sum()), "n": int(E[f"lp_markout_{h}s_usd"].notna().sum()),
                                "bp": float(1e4 * E[f"lp_markout_{h}s_usd"].sum() / E.notional_usd[E[f"lp_markout_{h}s_usd"].notna()].sum())}
                      for h in H}}

summary["bot_fee"] = {"volume_weighted_bp": float(1e4 * C.fee_usd.sum() / C.notional_usd.sum()), "median_bp": float(C.fee_bp.median()),
                      "share_zero": float((C.fee_bp == 0).mean()), "p95_bp": float(C.fee_bp.quantile(.95)),
                      "other_traders_bp_incl_protocol": float(1e4 * SW[~SW.bot_wallet].fee_usd.sum() / (1 - PROTO) / SW[~SW.bot_wallet].volume_usd.sum())}
bt_all = np.sort(SW[SW.bot_wallet].ts.values); dg = np.diff(bt_all)
summary["idle"] = {"gaps_over_1h": int((dg > 3600).sum()), "hours_in_gaps_over_1h": float(dg[dg > 3600].sum() / 3600),
                   "hours_total": float((bt_all[-1] - bt_all[0]) / 3600), "longest_gap_h": float(dg.max() / 3600),
                   "longest_gap_start_utc": str(pd.Timestamp(bt_all[np.argmax(dg)], unit="s"))}
summary["lp"] = {"avg_capital_usd": R["avg_capital_usd"], "days": R["period"]["days"], "lp_minus_hold_per_30d_pct": R["lp_minus_hold_per_30d_pct"],
                 "fees_per_30d_pct": R["fees_per_30d_pct"], "il_per_30d_pct": R["il_per_30d_pct"], "totals": R["totals"],
                 "open_positions": R["open_positions"] if not isinstance(R["open_positions"], list) else len(R["open_positions"]),
                 "period": R["period"]}

# ------------------------------------------------------------------ gap over time: does the bot only act on wide gaps?
w0, w1 = int(T.ts.min()), int(T.ts.max())
sec = np.arange(w0, w1 + 1)
fp = FP.groupby("ts").price.last()
pool = pd.Series(fp).reindex(sec, method="ffill").values
gap = 1e4 * np.log(pool / at(sec - 1))
traded = np.isin(sec, C.ts.values)
edges = [0, 2, 4, 6, 8, 10, 15, 25, 1e9]
b = pd.cut(np.abs(gap), edges, right=False)
gp = pd.DataFrame({"abs_gap_bucket_bp": b, "traded": traded}).groupby("abs_gap_bucket_bp", observed=False) \
    .agg(seconds=("traded", "size"), seconds_with_bot_trade=("traded", "sum"))
gp["share_of_time"] = gp.seconds / gp.seconds.sum()
gp["bot_trade_prob_per_second"] = gp.seconds_with_bot_trade / gp.seconds
gp.to_csv(os.path.join(a.out, "gap_time_profile.csv"))
summary["gap_time"] = {"window_utc": [str(pd.Timestamp(w0, unit="s")), str(pd.Timestamp(w1, unit="s"))],
                       "time_weighted_abs_gap_bp_median": float(np.nanmedian(np.abs(gap))),
                       "time_weighted_abs_gap_bp_mean": float(np.nanmean(np.abs(gap))),
                       "share_of_time_abs_gap_over_8bp": float(np.nanmean(np.abs(gap) >= 8))}

# ------------------------------------------------------------------ external swaps: do they trade at better prices after a bot trade?
X = SW[~SW.bot_wallet].copy()
bt = np.sort(SW[SW.bot_wallet].ts.values)
i = np.searchsorted(bt, X.ts.values, side="left") - 1
X["since_bot_s"] = np.where(i >= 0, X.ts.values - bt[np.clip(i, 0, None)], np.nan)
X = X.merge(FP[["tx_hash", "price_before"]].drop_duplicates("tx_hash"), on="tx_hash", how="left")
X["gap_before_bp"] = 1e4 * np.log(X.price_before / X.binance_before)
X["trader_gain_12s_bp"] = 1e4 * (X.loss_12s_usd - X.fee_usd / (1 - PROTO)) / X.volume_usd     # + = trader beat Binance 12 s after fees
X["lp_net_bp"] = 1e4 * X.net_for_lps_usd / X.volume_usd
X = X[X.ts >= w0]
X["bucket"] = pd.cut(X.since_bot_s, [0, 10, 60, 300, 3600, 1e9], right=False)
ext = X.groupby("bucket", observed=False).agg(swaps=("ts", "size"), volume_usd=("volume_usd", "sum"),
                                              abs_gap_before_bp_median=("gap_before_bp", lambda s: s.abs().median()),
                                              lp_loss_12s_usd=("loss_12s_usd", "sum"), fees_to_lps_usd=("fee_usd", "sum"),
                                              net_for_lps_usd=("net_for_lps_usd", "sum"))
ext["lp_net_bp"] = 1e4 * ext.net_for_lps_usd / ext.volume_usd
ext.to_csv(os.path.join(a.out, "external_swaps_by_time_since_bot.csv"))
Xa = SW[~SW.bot_wallet]
summary["external"] = {"swaps": int(len(Xa)), "volume_usd": float(Xa.volume_usd.sum()), "lp_loss_12s_usd": float(Xa.loss_12s_usd.sum()),
                       "fees_to_lps_usd": float(Xa.fee_usd.sum()), "fees_total_incl_protocol_usd": float(Xa.fee_usd.sum() / (1 - PROTO)),
                       "trader_result_12s_after_all_fees_usd": float(Xa.loss_12s_usd.sum() - Xa.fee_usd.sum() / (1 - PROTO))}

# ------------------------------------------------------------------ the bot EOA's other transactions and costs
ot = []
if os.path.exists(a.other_pool_txs):
    for line in open(a.other_pool_txs):
        rc = json.loads(line)["receipt"]
        ot.append({"hash": rc["transactionHash"], "block": int(rc["blockNumber"], 16), "from": rc["from"].lower(),
                   "status": int(rc["status"], 16), "gas_eth": int(rc["gasUsed"], 16) * int(rc["effectiveGasPrice"], 16) / 1e18})
OT = pd.DataFrame(ot, columns=["hash", "block", "from", "status", "gas_eth"])
L = json.load(open(a.contract_logs))["logs"]
ev = pd.DataFrame([{"hash": l["transactionHash"], "block": int(l["blockNumber"], 16), "pool": l["data"][2:66],
                    "token": addr(l["topics"][3]), "profit_raw": int(l["data"][2:][192:256], 16)}
                   for l in L if l["topics"] and l["topics"][0] == T_BOT])
ev["profit_units"] = np.where(ev.token == USDG, ev.profit_raw / 1e6, ev.profit_raw / 1e18)
ev["is_fynd"] = ev.pool == FYND_POOL
ev["pre_snapshot"] = ev.block <= SNAP_BLOCK
last_fynd_block = int(T.block.max())
oth_pre = ev[~ev.is_fynd & (ev.block <= last_fynd_block)]
OTp = OT[OT.block <= last_fynd_block]
nonce = BM["nonce"]
gas_med = float(T.gas_eth.median())
summary["bot_costs_outside_fynd_swaps"] = {
    "other_pool_trades_until_last_fynd_tx": int(len(oth_pre)), "other_pool_receipts_fetched": int(len(OTp)),
    "other_pool_trades_sent_by_bot_eoa": int((OTp["from"] == BOT_EOA).sum()), "other_pool_gas_eth": float(OTp.gas_eth.sum()),
    "nonce_info": nonce, "median_gas_eth_per_fynd_tx": gas_med}
LT = json.load(open(a.last_tx))
assert LT["hash"] == T.sort_values(["block", "tx_index"]).hash.iloc[-1], "last-tx is not the last bot Fynd trade"
n_eoa = int(LT["nonce"], 16) + 1                                         # nonces start at 0 (first Fynd trade has nonce 0)
eoa_share = float((OT["from"] == BOT_EOA).mean()) if len(OT) else float("nan")
n_other_by_eoa = len(oth_pre) * eoa_share                               # sample-based share sent by the bot EOA
summary["bot_costs_outside_fynd_swaps"].update({
    "eoa_txs_through_last_fynd_tx": n_eoa, "fynd_trades": int(len(T)), "other_pool_trades_until_last_fynd_tx": int(len(oth_pre)),
    "other_pool_sample_size": int(len(OT)), "other_pool_sample_share_from_bot_eoa": eoa_share,
    "other_pool_sample_median_gas_eth": float(OT.gas_eth.median()) if len(OT) else None,
    "eoa_txs_not_a_successful_trade": int(round(n_eoa - len(T) - n_other_by_eoa))})
summary["bot_reported_profit_other_pools"] = {p[:10]: {tk: float(g.profit_units.sum()) for tk, g in gg.groupby("token")}
                                              for p, gg in ev[~ev.is_fynd & ev.pre_snapshot].groupby("pool")}

# ------------------------------------------------------------------ wallet and contract map (evidence from the data)
lp_ev = pd.read_csv(a.lp_swaps.replace("results_lp_fynd_split_swaps.csv", "data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_events.csv"))
n_pos_6c = int(((lp_ev.owner == "0x6c6a40d2d1fc442e281e1f80314fd86516e17127") & (lp_ev.event == "position")).sum())
n_sw_6c = int((SW.tx_from == "0x6c6a40d2d1fc442e281e1f80314fd86516e17127").sum())
adm = [l for l in L if l["topics"] and l["topics"][0] != T_BOT]
wm = [
    ("0x4abfdbac0afa181338dc9c38c9c1264128c684a2", "bot EOA (sends the trades)", "confirmed by the user (Nov 11); observed",
     f"sent all {len(T):,} bot Fynd swaps; nonce 0 = its first Fynd trade (block {int(T.block.min()):,}); registered in the bot contract at deployment (event 0xd58299b7, block 84,286,819); pays all gas"),
    ("0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7", "bot contract (executes trades, holds profits)", "observed",
     f"target of every bot tx; emits one trade event per trade ({len(ev):,} all-time, 4 Ekubo pools); receives the Fynd leg and keeps the profit"),
    ("0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80", "bot contract owner until block 111,842,342", "observed", "OwnershipTransferred at deployment, then a two-step transfer away"),
    ("0x0d41d284672c524d14790b230afe3e287ef4d4b2", "bot contract owner from block 111,842,342", "observed", "OwnershipTransferStarted + OwnershipTransferred"),
    ("0x09215a470bd585e59eb3f4b612fbd2678131ff9e", "router used by the bot for the hedge legs", "observed", "receives and forwards every hedge leg; emits (recipient, amount) fee events; unwraps WETH"),
    ("0xa5503d92ee16a78e602996ad362674dc49034a14", "router fee recipient", "observed (role); owner not known", f"named in router fee events; total charged to the bot ${float(C.router_fee_usd.sum()):,.2f} on Fynd trades"),
    ("0x550cfe1292d0d9c0d28f232b3f42edb4439b1d09", "Fynd extension on the ETH/USDG pool", "observed", "charges the dynamic fee; pays LPs 80% via FeesAccumulated; its event carries share = 0.2"),
    ("0x4f2826f91f74c315aac59eb091c4178f913d0312", "address inside the Fynd extension's event", "observed; role not known", "constant in every extension event; possibly a signer or fee recipient (not verified)"),
    ("0x00000000000014aa86c5d3c41765bb24e11bd701", "Ekubo Core (holds the pool)", "observed", "swap and fee logs; native ETH settles here"),
    ("0x8366a39cc670b4001a1121b8f6a443a643e40951", "Uniswap v4 PoolManager", "observed", "most hedge legs (pools 0x84bd4e2d WETH/USDG 0.02%, 0x24107d15 ETH/USDG 0.01%)"),
    ("0x6c6a40d2d1fc442e281e1f80314fd86516e17127", "largest LP of the Fynd pool (EIP-7702 delegated EOA)", "observed; the brief calls it the bot, the data does not support that",
     f"{n_pos_6c} position events, {n_sw_6c} swaps (multi-pool routes sent to itself); code = 0xef0100 + 0x000000005c84f8fd50b21cac312528a64437030e; never sends bot trades"),
]
pd.DataFrame(wm, columns=["address", "role", "evidence_label", "evidence"]).to_csv(os.path.join(a.out, "bot_wallet_and_contract_map.csv"), index=False)

# ------------------------------------------------------------------ reconciliation
FA = pd.read_csv(a.fees_acc)
fa_ts = FA.block.map(FP.groupby("block").ts.first())
FA["ts"] = fa_ts.ffill().bfill()
lp_fees_fa = float((FA.amount0 * at(FA.ts - 1) + FA.amount1).sum())
c12 = C.lp_markout_12s_usd if "lp_markout_12s_usd" in C else C.fynd_lp_trade_usd_12s
rows = []
add = lambda sec, item, usd, ev_, note="": rows.append({"section": sec, "item": item, "usd": usd, "evidence": ev_, "note": note})
s1 = "1. LP position level, all LPs, Oct 2 - Nov 13 (checked Nov 13 report)"
add(s1, "fees earned (LP share)", R["totals"]["fees_usd"], "calculated", "fees collected + uncollected, valued when paid")
add(s1, "impermanent loss vs holding", R["totals"]["il_usd"], "calculated", "tokens out - tokens in, at Binance at each position's end")
add(s1, "LP vs holding", R["totals"]["lp_minus_hold_usd"], "calculated", "= fees + IL")
s2 = "2. LP trading side, per swap at Binance 12 s (lp_split.py), Oct 6 - Nov 13"
add(s2, "LP markout on bot swaps", -S["bot"]["loss_12s"], "calculated", f"{S['bot']['swaps']:,} swaps")
add(s2, "fees to LPs attributed to bot swaps (proportional split)", S["bot"]["fee"], "calculated", "lp_split.py splits each fee payment by |USDG| across the swaps it covers")
add(s2, "LP markout on other swaps", -S["other"]["loss_12s"], "calculated", f"{S['other']['swaps']:,} swaps")
add(s2, "fees to LPs attributed to other swaps", S["other"]["fee"], "calculated", "")
add(s2, "later price moves (12 s after each swap to position end)", S["drift"], "calculated", "")
add(s2, "total = LP vs holding", S["lp_minus_hold"], "calculated", "sections 1 and 2 are two views of the same -$3,925; do not add them")
s3 = f"3. Bot swaps rebuilt from chain ({len(C):,} complete txs): where the LPs' swap-side result went (tokens are conserved in each tx)"
for tag, lab in [("exec", "at Binance at execution"), ("12s", "at Binance 12 s later")]:
    lp = C[f"fynd_lp_trade_usd_{tag}"].sum(); fee = (C.fee_usd if tag == "exec" else np.where(C.fee_token == "ETH", C.fee_units * C.b12, C.fee_units)).sum()
    add(s3, f"Fynd LPs, swap side ({lab})", lp, "calculated", "fee excluded; + = LPs gained")
    add(s3, f"  Fynd fee paid by the bot ({lab})", fee, "observed (USDG) / inferred from bot event (ETH)", f"LPs get {1 - PROTO:.0%}, protocol {PROTO:.0%}")
    add(s3, f"  router fee paid by the bot ({lab})", C.router_fee_usd.sum(), "observed (USDG) / router event (ETH)", "recipient 0xa5503d92...")
    add(s3, f"  bot, gross trading result ({lab})", C[f"bot_usd_{tag}"].sum(), "calculated; matches bot's own event in every tx", "")
    add(s3, f"  other venues' LPs and protocols ({lab})", C[f"other_venues_usd_{tag}"].sum(), "calculated", "the pools the bot hedged on")
    add(s3, f"  check: sum of the five ({lab})", lp + fee + C.router_fee_usd.sum() + C[f"bot_usd_{tag}"].sum() + C[f"other_venues_usd_{tag}"].sum(),
        "calculated", "0 up to rounding and the fee's own revaluation")
Cu = C[C.uni_before.notna()]
Pu = Cu.uni_before
oc_lp = (Cu.fynd_eth * Pu + Cu.fynd_usdg).sum(); oc_fee = np.where(Cu.fee_token == "ETH", Cu.fee_units * Pu, Cu.fee_units).sum()
oc_rt = (Cu.router_fee_eth * Pu + Cu.router_fee_usdg).sum(); oc_bot = (Cu.bot_eth * Pu + Cu.bot_usdg).sum()
oc_oth = (Cu.other_eth_recv * Pu + Cu.other_usdg_recv).sum()
lab = f"at the on-chain reference (Uniswap v3 0.01% mid before the tx; {len(Cu):,} txs with it)"
add(s3, f"Fynd LPs, swap side ({lab})", oc_lp, "calculated", "sensitivity: removes the ~2.6 bp Binance basis")
add(s3, f"  Fynd fee paid by the bot ({lab})", oc_fee, "calculated", "")
add(s3, f"  router fee paid by the bot ({lab})", oc_rt, "calculated", "")
add(s3, f"  bot, gross trading result ({lab})", oc_bot, "calculated", "")
add(s3, f"  other venues' LPs and protocols ({lab})", oc_oth, "calculated", "")
add(s3, f"  check: sum of the five ({lab})", oc_lp + oc_fee + oc_rt + oc_bot + oc_oth, "calculated", "")
add(s3, "Fynd fee paid by the bot, LP share (exact, per swap)", C.fee_lp_usd.sum(), "calculated", "compare the proportional split in section 2")
add(s3, "Fynd fee paid by the bot, protocol share", C.fee_protocol_usd.sum(), "calculated", "")
s4 = "4. Bot economics on Fynd ETH/USDG"
add(s4, "gross trading P&L (after router fees)", C.bot_gross_usd.sum(), "calculated", "ETH/USDG kept by the bot, Binance at execution")
add(s4, "gas on these txs", -C.gas_usd.sum(), "observed", "gasUsed x effectiveGasPrice (includes L1 part)")
add(s4, "net realized P&L", C.bot_net_usd.sum(), "calculated", "")
add(s4, "unrealized: ETH profits revalued to the Nov 13 snapshot", C.bot_unrealized_to_snapshot_usd.sum(), "calculated", f"ETH ${P_END:,.2f} at snapshot")
add(s4, "residual inventory", float(C.bot_usdg.where(C.fynd_direction == "bot_sells_eth", 0).abs().sum() + 0), "observed", "USDG left after ETH-profit trades; 0 = none")
oc = summary["bot_costs_outside_fynd_swaps"]
if "eoa_txs_not_a_successful_trade" in oc:
    add(s4, "gas on the EOA's other txs (failed or non-trading), upper bound", -oc["eoa_txs_not_a_successful_trade"] * gas_med * P_END,
        "assumed", f"{oc['eoa_txs_not_a_successful_trade']:,} txs x median Fynd-tx gas; not listable on this RPC")
s5 = "5. Protocol and external traders"
add(s5, "all fees paid to LPs (FeesAccumulated, whole period)", lp_fees_fa, "observed", "valued at Binance when paid")
add(s5, f"protocol share of all Fynd fees ({PROTO:.0%})", lp_fees_fa * PROTO / (1 - PROTO), "calculated",
    "share read from the extension event; verified on bot-only fee intervals")
ex = summary["external"]
add(s5, "external traders' result vs Binance 12 s, after all Fynd fees", ex["trader_result_12s_after_all_fees_usd"], "calculated", f"{ex['swaps']:,} swaps")
rec = pd.DataFrame(rows)
rec.to_csv(os.path.join(a.out, "bot_value_reconciliation.csv"), index=False)
summary["reconciliation"] = rows
summary["protocol_share"] = PROTO
summary["fee_split_check"] = BM["fee_split_check"]
summary["eth_at_snapshot"] = P_END
json.dump(summary, open(os.path.join(a.out, "summary.json"), "w"), indent=1, default=str)
print(rec.to_string())
print(json.dumps({k: summary[k] for k in ["coverage", "execution", "gap_time", "external", "bot_costs_outside_fynd_swaps"]}, indent=1, default=str))
