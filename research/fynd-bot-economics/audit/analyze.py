"""
Audit tables from audit/data/_R.pkl and _LG.pkl (built by audit/recon.py from raw receipts). Earlier research outputs are
read only to compare. Writes:
  audit/top_panel_transaction_reconciliation.csv   one row per bot tx
  audit/hedge_execution_costs.csv                  one row per hedge leg (+ decomposition where the pool math allows)
  audit/bot_pnl_reconciliation.csv                 summary steps
  audit/fee_allocation_audit.csv                   summary rows; interval detail in audit/data/fee_intervals.csv
  audit/sensitivity_analysis.csv
  audit/data/audit_numbers.json                    every headline number at full precision

  python3 audit/analyze.py --root . --lp ../markout-backtest --out audit
"""
import argparse, json, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
D = lambda *p: os.path.join(a.out, *p)
R = pd.read_pickle(D("data", "_R.pkl")); LG = pd.read_pickle(D("data", "_LG.pkl"))
SHARE = 0.2                     # Fynd extension share, read from its event (0x3333333333333333 / 2^64); checked below
N = {}                          # headline numbers

# ================================================================ per-tx table
R["complete"] = ((R.C1_usdg_gap_raw == 0) & (R.C2_profit_gap_raw == 0) & (R.C3_other_token_left_raw == 0) & R.status.eq(1)
                 & (R.issues == "") & ((R.C4_intermediate_left == "") | R.hedge_route.str.contains("ekubo:")))
R["intermediate_kept_by_venue"] = R.C4_intermediate_left
e = lambda c: R[c].astype(float) / 1e18
u = lambda c: R[c].astype(float) / 1e6
R["fynd_eth"], R["fynd_usdg"] = e("fynd_eth_raw"), u("fynd_usdg_raw")
R["fynd_exec_price"] = (R.fynd_usdg / R.fynd_eth).abs()
R["fee_eth"] = np.where(R.fee_token == "ETH", R.fee_raw.astype(float) / 1e18, 0.0)
R["fee_usdg"] = np.where(R.fee_token == "USDG", R.fee_raw.astype(float) / 1e6, 0.0)
R["hedge_eth"], R["hedge_usdg"] = e("hedge_eth_raw"), u("hedge_usdg_raw")
R["router_eth"], R["router_usdg"] = e("router_eth_raw"), u("router_usdg_raw")
R["bot_eth"], R["bot_usdg"] = e("bot_eth_raw"), u("bot_usdg_raw")
HZ = {"exec": "B_exec", "1s": "B_1s", "5s": "B_5s", "12s": "B_12s", "30s": "B_30s", "60s": "B_60s"}


def val(px, tag):
    p = R[px]
    R[f"lp_swap_side_{tag}"] = R.fynd_eth * p + R.fynd_usdg                     # Fynd pool's token change, valued
    R[f"fynd_fee_{tag}"] = R.fee_eth * p + R.fee_usdg
    R[f"lp_fee_credited_{tag}"] = (1 - SHARE) * R[f"fynd_fee_{tag}"]
    R[f"fynd_protocol_{tag}"] = SHARE * R[f"fynd_fee_{tag}"]
    R[f"lp_net_{tag}"] = R[f"lp_swap_side_{tag}"] + R[f"lp_fee_credited_{tag}"]
    R[f"hedge_result_{tag}"] = R.hedge_eth * p + R.hedge_usdg                  # hedge pools' token change, valued
    R[f"router_{tag}"] = R.router_eth * p + R.router_usdg
    R[f"bot_gross_{tag}"] = R.bot_eth * p + R.bot_usdg
    R[f"identity_residual_{tag}"] = (R[f"lp_swap_side_{tag}"] + R[f"hedge_result_{tag}"] + R[f"bot_gross_{tag}"]
                                     + R[f"fynd_fee_{tag}"] + R[f"router_{tag}"])


for tag, px in HZ.items():
    val(px, tag)
R["U_exec"] = R.U_before
val("U_exec", "onchain")
R["gas_usd"] = R.gas_eth * R.B_exec
R["bot_net_exec"] = R.bot_gross_exec - R.gas_usd
cols = ["hash", "block", "ts", "tx_index", "status", "complete", "issues", "bot_pays", "fynd_eth", "fynd_usdg", "fynd_exec_price",
        "B_ref_time_exec", "B_exec", "B_ref_time_12s", "B_12s", "U_before",
        "lp_swap_side_exec", "lp_swap_side_12s", "fee_token", "fee_eth", "fee_usdg", "fee_source", "fynd_fee_12s", "lp_fee_credited_12s",
        "fynd_protocol_12s", "lp_net_12s", "hedge_route", "n_hedge_legs", "hedge_eth", "hedge_usdg", "hedge_result_exec", "hedge_result_12s", "lp_swap_side_onchain", "hedge_result_onchain",
        "router_eth", "router_usdg", "router_12s", "bot_eth", "bot_usdg", "bot_gross_exec", "bot_gross_12s", "gas_eth", "gas_usd", "bot_net_exec",
        "bot_event_profit_raw", "fee_bot_event_raw", "fee_obs_minus_bot_event_raw", "C1_usdg_gap_raw", "C2_profit_gap_raw", "C3_other_token_left_raw", "intermediate_kept_by_venue",
        "identity_residual_exec", "identity_residual_12s"]
R[cols].to_csv(D("top_panel_transaction_reconciliation.csv"), index=False)
C = R[R.complete]; X = R[~R.complete]
N["n_txs"], N["n_complete"], N["n_incomplete"] = len(R), len(C), len(X)
N["max_abs_identity_residual_12s_usd_complete"] = float(C.identity_residual_12s.abs().max())
for tag in ["exec", "12s"]:
    for k in ["lp_swap_side", "fynd_fee", "lp_fee_credited", "fynd_protocol", "lp_net", "hedge_result", "router", "bot_gross"]:
        N[f"{k}_{tag}_complete"] = float(C[f"{k}_{tag}"].sum())
N["gas_usd_complete"] = float(C.gas_usd.sum()); N["bot_net_exec_complete"] = float(C.bot_net_exec.sum())

# ---------------------------------------------------------------- the chart's numbers vs this rebuild
SP = json.load(open(os.path.join(a.lp, "results_lp_fynd_split.json")))
SW = pd.read_csv(os.path.join(a.lp, "results_lp_fynd_split_swaps.csv"))
bsw = SW[SW.bot_wallet].merge(R[["hash", "complete", "lp_swap_side_12s", "lp_fee_credited_12s"]], left_on="tx_hash", right_on="hash", how="left")
N["checked_lp_net_bot_swaps"] = float(SP["bot"]["lp_net"]); N["checked_lp_swap_side_12s"] = -float(SP["bot"]["loss_12s"])
N["checked_lp_fee_bot_swaps"] = float(SP["bot"]["fee"])
N["checked_swaps_matched_to_txs"] = int(bsw.hash.notna().sum())
N["checked_swap_side_vs_audit_max_abs_usd"] = float((-bsw.loss_12s_usd - bsw.lp_swap_side_12s).abs().max())
N["checked_lp_fee_complete_swaps"] = float(bsw[bsw.complete == True].fee_usd.sum())
N["checked_lp_net_complete_swaps"] = float(bsw[bsw.complete == True].net_for_lps_usd.sum())
RC = json.load(open(os.path.join(a.root, "final", "data", "reconcile.json")))
N["chart_values"] = {"lp_net_loss": -N["checked_lp_net_bot_swaps"], "hedge": 2351.77148511468, "gas": 443.4585631094759,
                     "bot_net": 295.094693468845, "router": 177.56868605338468, "fynd_20pct": 760.2934638936168 * 0.2,
                     "bot_gross_label": 738.5532565783209}

# ================================================================ hedge legs
LG = LG.merge(R[["hash", "complete", "B_exec", "B_12s", "U_before", "bot_pays"]], on="hash")
LG["eth"], LG["usdg"] = LG.eth_raw.astype(float) / 1e18, LG.usdg_raw.astype(float) / 1e6
LG["direct_eth_usdg"] = (LG.tokens == "ETH/USDG") & (LG.n_legs_in_tx == 1)
LG["eth_to_pool"] = LG.eth
LG["notional_usd"] = LG.eth.abs() * LG.B_exec
LG["exec_price"] = np.where(LG.tokens == "ETH/USDG", (LG.usdg / LG.eth).abs(), np.nan)
LG["leg_result_exec"] = np.where(LG.direct_eth_usdg, LG.eth * LG.B_exec + LG.usdg, np.nan)
LG["leg_result_12s"] = np.where(LG.direct_eth_usdg, LG.eth * LG.B_12s + LG.usdg, np.nan)
f = LG.fee_pips.astype(float) / 1e6
ok = LG.direct_eth_usdg & LG.dex.isin(["uniswap_v3", "uniswap_v4"]) & LG.sqrtp.notna() & (LG.L.astype(float) > 0)
sa = LG.sqrtp.astype(float) / 2**96                                     # sqrt(raw price) after, ETH is token0 (checked below)
Lq = LG.L.astype(float)
x_in = np.where(LG.eth_raw.astype(float) > 0, LG.eth_raw.astype(float) * (1 - f), 0.0)
y_in = np.where(LG.usdg_raw.astype(float) > 0, LG.usdg_raw.astype(float) * (1 - f), 0.0)
sb = np.where(x_in > 0, 1 / (1 / sa - x_in / Lq), sa - y_in / Lq)      # constant liquidity within the swap
LG["mid_before"] = np.where(ok, sb ** 2 * 1e12, np.nan)
LG["mid_after"] = np.where(ok, sa ** 2 * 1e12, np.nan)
p_ex = LG.exec_price
p_nf = np.where(LG.eth > 0, p_ex / (1 - f), p_ex * (1 - f))             # price before the pool's fee
LG["fee_paid_usd"] = np.where(LG.direct_eth_usdg, LG.eth * (p_nf - p_ex), np.nan)
LG["impact_usd"] = np.where(ok, LG.eth * (LG.mid_before - p_nf), np.nan)
LG["pool_vs_onchain_ref_usd"] = np.where(ok, LG.eth * (LG.U_before - LG.mid_before), np.nan)
LG["basis_onchain_vs_binance_usd"] = np.where(ok, LG.eth * (LG.B_exec - LG.U_before), np.nan)
LG["move_12s_usd"] = np.where(LG.direct_eth_usdg, LG.eth * (LG.B_12s - LG.B_exec), np.nan)
LG["decomp_residual_usd"] = LG.leg_result_exec - (LG.fee_paid_usd + LG.impact_usd + LG.pool_vs_onchain_ref_usd + LG.basis_onchain_vs_binance_usd)
LG["shortfall_vs_binance_bp"] = 1e4 * LG.leg_result_exec / LG.notional_usd
LG["shortfall_vs_onchain_bp"] = 1e4 * (LG.eth * LG.U_before + LG.usdg) / LG.notional_usd
LG["direction"] = np.where(LG.eth > 0, "bot sells ETH to hedge pool", np.where(LG.eth < 0, "bot buys ETH from hedge pool", "no ETH (intermediate leg)"))
LG["size_bucket"] = pd.cut(LG.notional_usd, [0, 100, 250, 500, 1000, 1e9], labels=["<$100", "$100-250", "$250-500", "$500-1k", ">$1k"])
LG.to_csv(D("hedge_execution_costs.csv"), index=False, columns=[
    "hash", "block", "ts", "li", "complete", "dex", "pool", "fee_pips", "tokens", "n_legs_in_tx", "direct_eth_usdg", "direction", "eth_to_pool",
    "usdg", "other_raw", "notional_usd", "size_bucket", "exec_price", "B_exec", "U_before", "mid_before", "mid_after", "leg_result_exec",
    "fee_paid_usd", "impact_usd", "pool_vs_onchain_ref_usd", "basis_onchain_vs_binance_usd", "decomp_residual_usd", "move_12s_usd",
    "leg_result_12s", "shortfall_vs_binance_bp", "shortfall_vs_onchain_bp"])
LGc = LG[LG.complete]
dd = LGc[LGc.direct_eth_usdg]
N["hedge"] = {
    "result_exec_all_complete": N["hedge_result_exec_complete"], "result_12s_all_complete": N["hedge_result_12s_complete"],
    "direct_single_leg_txs": int(dd.hash.nunique()), "direct_result_exec": float(dd.leg_result_exec.sum()),
    "direct_result_12s": float(dd.leg_result_12s.sum()),
    "decomposed_legs": int(dd.impact_usd.notna().sum()), "decomposed_legs_with_U": int((dd.impact_usd.notna() & dd.U_before.notna()).sum()),
    "fee_paid_usd_direct": float(dd.fee_paid_usd.sum()),
    "fee_paid_usd_decomposed": float(dd[dd.impact_usd.notna() & dd.U_before.notna()].fee_paid_usd.sum()),
    "impact_usd": float(dd.impact_usd.sum()), "pool_vs_onchain_ref_usd": float(dd.pool_vs_onchain_ref_usd.sum()),
    "basis_usd": float(dd.basis_onchain_vs_binance_usd.sum()),
    "result_exec_decomposed": float(dd[dd.impact_usd.notna() & dd.U_before.notna()].leg_result_exec.sum()),
    "move_12s_direct": float(dd.move_12s_usd.sum()),
    "max_abs_decomp_residual": float(dd.decomp_residual_usd.abs().max()),
    "mid_before_vs_U_median_bp": float((1e4 * np.log(dd.mid_before / dd.U_before)).abs().median()),
    "negative_mid_before": int((dd.mid_before <= 0).sum()),
    "notional_usd_all_legs_with_eth": float(LGc[LGc.tokens.str.contains("ETH")].notional_usd.sum())}
g = (dd.groupby(["dex", "pool", "fee_pips"]).agg(legs=("hash", "size"), notional_usd=("notional_usd", "sum"),
     result_exec=("leg_result_exec", "sum"), fee_paid=("fee_paid_usd", "sum"), impact=("impact_usd", "sum"),
     pool_vs_ref=("pool_vs_onchain_ref_usd", "sum"), basis=("basis_onchain_vs_binance_usd", "sum"), move_12s=("move_12s_usd", "sum"),
     result_12s=("leg_result_12s", "sum")).sort_values("notional_usd", ascending=False))
g["cost_bp_exec"] = 1e4 * g.result_exec / g.notional_usd
g.to_csv(D("data", "hedge_by_pool.csv"))
dd.groupby("direction").agg(legs=("hash", "size"), notional_usd=("notional_usd", "sum"), result_exec=("leg_result_exec", "sum"),
                            fee_paid=("fee_paid_usd", "sum"), impact=("impact_usd", "sum")).to_csv(D("data", "hedge_by_direction.csv"))
dd.groupby("size_bucket", observed=True).agg(legs=("hash", "size"), notional_usd=("notional_usd", "sum"), result_exec=("leg_result_exec", "sum"),
                                             impact=("impact_usd", "sum")).to_csv(D("data", "hedge_by_size.csv"))
rt = C.groupby("hedge_route").agg(txs=("hash", "size"), result_exec=("hedge_result_exec", "sum"), result_12s=("hedge_result_12s", "sum")) \
    .sort_values("result_12s", ascending=False)
rt.to_csv(D("data", "hedge_by_route.csv"))
N["hedge"]["not_direct_txs"] = int(C.n_hedge_legs.ne(1).sum() + 0)
N["hedge"]["result_12s_not_direct"] = float(N["hedge_result_12s_complete"] - dd.leg_result_12s.sum())
N["hedge"]["stock_ext_txs"] = int((C.intermediate_kept_by_venue != "").sum())

# ================================================================ bot P&L
ev_tok = np.where(R.bot_pays == "ETH", "ETH", "USDG")
N["bot"] = {"eth_kept_complete": float(C.bot_eth.sum()), "usdg_kept_complete": float(C.bot_usdg.sum()),
            "bot_event_profit_eth": float((R[ev_tok == "ETH"].bot_event_profit_raw.astype(float)).sum() / 1e18),
            "bot_event_profit_usdg": float((R[ev_tok == "USDG"].bot_event_profit_raw.astype(float)).sum() / 1e6),
            "bot_event_profit_eth_complete": float(C[C.bot_pays == "ETH"].bot_event_profit_raw.astype(float).sum() / 1e18),
            "bot_event_profit_usdg_complete": float(C[C.bot_pays == "USDG"].bot_event_profit_raw.astype(float).sum() / 1e6),
            "other_token_left_complete_max": float(C.C3_other_token_left_raw.abs().max()),
            "gross_exec_complete": N["bot_gross_exec_complete"], "gas_complete": N["gas_usd_complete"],
            "net_exec_complete": N["bot_net_exec_complete"]}
# incomplete txs: only the bot's own event is complete; value it at execution
Xe = X.copy()
Xe["ev_usd"] = np.where(Xe.bot_pays == "ETH", Xe.bot_event_profit_raw.astype(float) / 1e18 * Xe.B_exec, Xe.bot_event_profit_raw.astype(float) / 1e6)
N["bot"]["incomplete_bot_event_gross_usd"] = float(Xe.ev_usd.sum()); N["bot"]["incomplete_gas_usd"] = float((Xe.gas_eth * Xe.B_exec).sum())
SM = json.load(open(os.path.join(a.root, "out", "summary.json")))["bot_costs_outside_fynd_swaps"]
N["bot"]["eoa_txs_through_last_fynd_tx"] = SM["eoa_txs_through_last_fynd_tx"]
N["bot"]["other_pool_trades"] = SM["other_pool_trades_until_last_fynd_tx"]
N["bot"]["eoa_txs_unaccounted"] = SM["eoa_txs_through_last_fynd_tx"] - len(R) - SM["other_pool_trades_until_last_fynd_tx"]
gas_med_eth = float(R.gas_eth.median()); px_med = float(R.B_exec.median())
N["bot"]["unaccounted_gas_estimate_usd"] = N["bot"]["eoa_txs_unaccounted"] * gas_med_eth * px_med
steps = [
    ("A1 bot gross trading P&L, complete txs (ETH kept x Binance at exec + USDG kept)", N["bot_gross_exec_complete"], "recomputed and independently reconciled", "sum(bot_gross_exec) over complete rows of top_panel_transaction_reconciliation.csv"),
    ("A2 gas on those txs", -N["gas_usd_complete"], "verified directly from on-chain data", "gasUsed x effectiveGasPrice x B_exec"),
    ("A3 = net realized, complete txs", N["bot_net_exec_complete"], "recomputed and independently reconciled", "A1 + A2"),
    ("B1 incomplete txs: bot's own profit event, valued at exec", N["bot"]["incomplete_bot_event_gross_usd"], "bot's own report (not independently reconciled)", "bot event word3"),
    ("B2 incomplete txs: gas", -N["bot"]["incomplete_gas_usd"], "verified directly from on-chain data", ""),
    ("B3 = net including incomplete txs", N["bot_net_exec_complete"] + N["bot"]["incomplete_bot_event_gross_usd"] - N["bot"]["incomplete_gas_usd"], "partly the bot's own report", "A3 + B1 + B2"),
    ("C1 EOA txs neither Fynd trades nor other-pool trades (count)", N["bot"]["eoa_txs_unaccounted"], "inferred from nonces", "36,024 nonces - Fynd trades - other-pool trades"),
    ("C2 their gas (estimate: count x median Fynd-trade gas x median price)", -N["bot"]["unaccounted_gas_estimate_usd"], "estimated", "not observable: no tx hashes"),
    ("C3 = net after the estimate", N["bot_net_exec_complete"] + N["bot"]["incomplete_bot_event_gross_usd"] - N["bot"]["incomplete_gas_usd"] - N["bot"]["unaccounted_gas_estimate_usd"], "estimated", "B3 + C2"),
    ("D1 ETH kept by the bot (complete txs, ETH)", N["bot"]["eth_kept_complete"], "recomputed and independently reconciled", "sum(bot_eth)"),
    ("D2 USDG kept by the bot (complete txs, USDG)", N["bot"]["usdg_kept_complete"], "verified directly from on-chain data (Transfer logs, check C1)", "sum(bot_usdg)"),
    ("D3 bot events: ETH profit, all 24,258 txs (ETH)", N["bot"]["bot_event_profit_eth"], "bot's own report", ""),
    ("D4 bot events: USDG profit, all 24,258 txs (USDG)", N["bot"]["bot_event_profit_usdg"], "bot's own report", ""),
    ("D5 bot events: ETH profit, complete txs (ETH)", N["bot"]["bot_event_profit_eth_complete"], "bot's own report", "equals D1 exactly (check C2)"),
    ("D6 bot events: USDG profit, complete txs (USDG)", N["bot"]["bot_event_profit_usdg_complete"], "bot's own report", "equals D2 exactly (check C2)"),
    ("E1 token not paid in, left with the bot per tx (max abs, raw)", N["bot"]["other_token_left_complete_max"], "recomputed", "check C3: 0 = no inventory kept"),
]
pd.DataFrame(steps, columns=["step", "value", "label", "formula"]).to_csv(D("bot_pnl_reconciliation.csv"), index=False)

# ================================================================ fees: every FeesAccumulated interval, bot and external
FAc = pd.read_csv(os.path.join(a.lp, "data_swaps", "eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv"))
SWf = pd.concat([pd.read_csv(os.path.join(a.lp, "data_swaps", f)) for f in
                 ["eth_usdg_ekubo_robinhood_to1108.csv", "eth_usdg_ekubo_robinhood_nov9_11.csv", "eth_usdg_ekubo_robinhood_nov11_13.csv"]]) \
    .drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])
# fee per swap: bot -> this rebuild; external -> from external receipts (charged on output; USDG output observed)
CORE = "0x00000000000014aa86c5d3c41765bb24e11bd701"; USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
TR = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"; FY = "b67e0601a0363a1ad259dd848cad1c52d6cc4eb18bc526a0dd4f4bdf83773546"
ext = {}
for line in open(os.path.join(a.root, "final", "data", "external_txs.jsonl")):
    rc = json.loads(line)["receipt"]
    lg = rc["logs"]
    fy = [l for l in lg if l["address"].lower() == CORE and not l["topics"] and len(l["data"]) == 234 and l["data"][42:106] == FY]
    others = [l for l in lg if l["address"].lower() == CORE and not l["topics"] and len(l["data"]) == 234 and l["data"][42:106] != FY]
    if len(fy) != 1:
        continue
    d = fy[0]["data"][2:]
    a0 = int(d[104:136], 16); a0 = a0 - (1 << 128) if a0 >= 1 << 127 else a0
    a1 = int(d[136:168], 16); a1 = a1 - (1 << 128) if a1 >= 1 << 127 else a1
    core_in = sum(int(l["data"][2:66], 16) for l in lg if l["topics"] and l["topics"][0] == TR and l["address"].lower() == USDG
                  and "0x" + l["topics"][2][-40:] == CORE)
    core_out = sum(int(l["data"][2:66], 16) for l in lg if l["topics"] and l["topics"][0] == TR and l["address"].lower() == USDG
                   and "0x" + l["topics"][1][-40:] == CORE)
    key = (int(rc["blockNumber"], 16), int(fy[0]["logIndex"], 16))
    if others:
        ext[key] = {"usdg_fee": np.nan, "eth_fee": np.nan, "why": "other Ekubo pools in the same tx"}
    elif a1 < 0:                     # trader receives USDG: fee = what the pool paid out - what left Core
        ext[key] = {"usdg_fee": ((-a1) - (core_out - core_in)) / 1e6, "eth_fee": 0.0, "why": "observed"}
    else:                            # trader receives native ETH: fee in ETH, not observable; USDG side must show no fee
        ext[key] = {"usdg_fee": (core_in - core_out - a1) / 1e6, "eth_fee": np.nan, "why": "ETH output: fee not observable"}
SWf["key"] = list(zip(SWf.block, SWf.log_index))
# bot swaps: match by tx hash
bmap = R.set_index("hash")[["fee_eth", "fee_usdg", "complete"]]
SWf["is_bot"] = SWf.tx_hash.isin(bmap.index)
SWf["fee_eth"] = np.nan; SWf["fee_usdg"] = np.nan; SWf["fee_known_eth"] = False; SWf["fee_known_usdg"] = False
bm = SWf.is_bot
SWf.loc[bm, "fee_eth"] = bmap.loc[SWf[bm].tx_hash, "fee_eth"].values
SWf.loc[bm, "fee_usdg"] = bmap.loc[SWf[bm].tx_hash, "fee_usdg"].values
SWf.loc[bm, ["fee_known_eth", "fee_known_usdg"]] = True
em = ~bm
SWf.loc[em, "fee_usdg"] = [ext.get(k, {}).get("usdg_fee", np.nan) for k in SWf[em].key]
SWf.loc[em, "fee_eth"] = [ext.get(k, {}).get("eth_fee", np.nan) for k in SWf[em].key]
SWf["fee_known_eth"] = SWf.fee_eth.notna(); SWf["fee_known_usdg"] = SWf.fee_usdg.notna()
FAc = FAc.sort_values(["block", "log_index"]).reset_index(drop=True)
fk = FAc.block.values * 10**6 + FAc.log_index.values
sk = SWf.block.values * 10**6 + SWf.log_index.values
SWf["fa_idx"] = np.searchsorted(fk, sk, side="left")              # each swap's fee is paid out at the next FeesAccumulated
SWf = SWf[SWf.fa_idx < len(FAc)]
G = SWf.groupby("fa_idx").agg(swaps=("key", "size"), bot_swaps=("is_bot", "sum"), fee_eth=("fee_eth", "sum"), fee_usdg=("fee_usdg", "sum"),
                              eth_known=("fee_known_eth", "all"), usdg_known=("fee_known_usdg", "all"))
G = G.join(FAc[["block", "log_index", "amount0", "amount1"]], how="left")
G["lp_share_eth"] = G.amount0 / G.fee_eth; G["lp_share_usdg"] = G.amount1 / G.fee_usdg
G["kind"] = np.where(G.bot_swaps == G.swaps, "bot only", np.where(G.bot_swaps == 0, "external only", "mixed"))
G["usdg_excess_vs_80pct"] = np.where(G.usdg_known & (G.fee_usdg > 0) & ((G.amount1 - 0.8 * G.fee_usdg).abs() > 2.5e-6),
                                     G.fee_usdg - G.amount1 / 0.8, 0.0)
G.to_csv(D("data", "fee_intervals.csv"))
bad = G[G.usdg_excess_vs_80pct != 0]
N["fee_excess"] = {"intervals": int(len(bad)), "all_bot_only": bool((bad.kind == "bot only").all()), "usdg": float(bad.usdg_excess_vs_80pct.sum()),
                   "eth_intervals_off": int((G.eth_known & (G.fee_eth > 0) & ((G.amount0 - 0.8 * G.fee_eth).abs() > 2.5e-15)).sum())}
ivs = set(bad.index)
SWf["usdg_excess_interval"] = SWf.fa_idx.isin(ivs)
xs = SWf[SWf.usdg_excess_interval & SWf.is_bot].tx_hash
xu = R[(R.bot_pays == "USDG") & R.complete]
mm = xu[xu.fee_obs_minus_bot_event_raw != 0]
N["fee_excess"]["usdg_payer_txs"] = int(len(xu)); N["fee_excess"]["obs_vs_bot_event_mismatch_txs"] = int(len(mm))
N["fee_excess"]["obs_vs_bot_event_mismatch_usdg"] = float(mm.fee_obs_minus_bot_event_raw.sum() / 1e6)
N["fee_excess"]["mismatch_txs_with_other_ekubo_leg"] = int(mm.hedge_route.str.contains("ekubo:").sum())
N["fee_excess"]["mismatch_txs_in_flagged_intervals"] = int(mm.hash.isin(xs).sum())
N["fee_excess"]["txs"] = int(len(xs)); N["fee_excess"]["txs_with_other_ekubo_leg"] = int(R[R.hash.isin(xs)].hedge_route.str.contains("ekubo:").sum())
tol = 1e-3


def chk(sub, tok):
    s = sub[(sub[f"{tok}_known"]) & (sub[f"fee_{tok}"] > 0)]
    r = s[f"lp_share_{tok}"]
    unit = 2.5e-6 if tok == "usdg" else 2.5e-15                    # rounding of the 6- / 18-decimal amounts
    ok_ = ((r.sub(0.8).abs() < tol) | ((s[f"amount{0 if tok == 'eth' else 1}"] - 0.8 * s[f"fee_{tok}"]).abs() <= unit))
    return len(s), int(ok_.sum()), float(r.median()) if len(r) else np.nan, float(s[f"amount{0 if tok == 'eth' else 1}"].sum()), float(s[f"fee_{tok}"].sum())


rows = []
for kind in ["bot only", "mixed", "external only", "all"]:
    sub = G if kind == "all" else G[G.kind == kind]
    for tok in ["eth", "usdg"]:
        n, m, med, fa_amt, fee_amt = chk(sub, tok)
        rows.append({"section": "interval check: LP payment / fees charged", "item": f"{kind}, {tok.upper()} fees",
                     "intervals_checkable": n, "intervals_equal_80pct_within_0.1pct_or_rounding": m, "median_ratio": med,
                     "lp_paid": fa_amt, "fees_charged": fee_amt, "ratio_of_sums": fa_amt / fee_amt if fee_amt else np.nan,
                     "label": "verified directly from on-chain data" if tok == "usdg" or kind == "external only"
                     else "recomputed: bot ETH fees come from the bot's own event; the LP payment is independent"})
# value FeesAccumulated at Binance when paid (ts from the swap files' block -> ts)
bts = SWf.groupby("block").ts.first()
FAc["ts"] = bts.reindex(FAc.block).values
ref = pd.read_pickle(D("data", "_binance.pkl")).close
FAc["p"] = ref.reindex(FAc.ts.ffill().astype("int64") - 1, method="ffill").values
fa_usd = float((FAc.amount0 * FAc.p + FAc.amount1).sum())
LPR = json.load(open(os.path.join(a.lp, "results_lp_fynd.json")))
lp_pos_fees = float(LPR["totals"].get("fees_usd", np.nan)) if isinstance(LPR.get("totals"), dict) else np.nan
N["fees"] = {"fa_total_usd_when_paid": fa_usd, "fa_eth": float(FAc.amount0.sum()), "fa_usdg": float(FAc.amount1.sum()),
             "position_level_lp_fees_usd": lp_pos_fees, "gross_implied_usd": fa_usd / 0.8, "protocol_implied_usd": fa_usd / 0.8 * 0.2,
             "bot_fee_exec_complete": N["fynd_fee_exec_complete"], "bot_fee_lp_80_exec": 0.8 * N["fynd_fee_exec_complete"],
             "bot_fee_protocol_20_exec": 0.2 * N["fynd_fee_exec_complete"],
             "bot_fee_exec_all": float(R.fynd_fee_exec.sum()), "bot_fee_zero_txs": int((R.fee_raw == 0).sum()),
             "external_usdg_fees_observed_usd": float(SWf[~SWf.is_bot].fee_usdg.where(SWf[~SWf.is_bot].fee_usdg > 0).sum()),
             "external_swaps": int((~SWf.is_bot).sum()),
             "external_swaps_usdg_fee_observed": int(((~SWf.is_bot) & (SWf.fee_usdg > 0)).sum())}
ext_share = json.load(open(os.path.join(a.root, "final", "data", "extension_check.json")))
N["fees"]["extension_share_values"] = ext_share["per_block_event_fields"]["share_raw"]
fee_rows = rows + [
    {"section": "totals", "item": "FeesAccumulated paid to LPs, valued when paid (USD)", "lp_paid": fa_usd, "label": "verified directly from on-chain data"},
    {"section": "totals", "item": "position-level LP fee income (checked LP report, USD)", "lp_paid": lp_pos_fees, "label": "recomputed (checked report)"},
    {"section": "totals", "item": "gross fees implied = LP payments / 0.8 (USD)", "fees_charged": fa_usd / 0.8, "label": "inferred (80% verified on intervals)"},
    {"section": "totals", "item": "Fynd 20% implied (USD)", "fees_charged": fa_usd / 0.8 * 0.2, "label": "inferred: where the 20% goes is not visible"},
    {"section": "bot", "item": "Fynd fees paid by the bot, complete txs, at exec (USD)", "fees_charged": N["fynd_fee_exec_complete"], "label": "USDG observed; ETH from bot event"},
    {"section": "bot", "item": "  80% to LPs", "fees_charged": 0.8 * N["fynd_fee_exec_complete"], "label": "recomputed"},
    {"section": "bot", "item": "  20% to Fynd", "fees_charged": 0.2 * N["fynd_fee_exec_complete"], "label": "recomputed"},
    {"section": "bot", "item": "bot txs with zero Fynd fee", "intervals_checkable": N["fees"]["bot_fee_zero_txs"], "label": "recomputed"},
]
pd.DataFrame(fee_rows).to_csv(D("fee_allocation_audit.csv"), index=False)

# ================================================================ sensitivity
srows = []
for tag in ["exec", "1s", "5s", "12s", "30s", "60s"]:
    lpn = -C[f"lp_net_{tag}"].sum()
    srows.append({"valuation": f"Binance {tag if tag != 'exec' else 'at execution (T-1)'}", "txs": len(C),
                  "lp_swap_side": C[f"lp_swap_side_{tag}"].sum(), "lp_fee_credited": C[f"lp_fee_credited_{tag}"].sum(),
                  "lp_net_loss": lpn, "hedge_pools": C[f"hedge_result_{tag}"].sum(), "bot_gross": C[f"bot_gross_{tag}"].sum(),
                  "router": C[f"router_{tag}"].sum(), "fynd_20pct": C[f"fynd_protocol_{tag}"].sum(),
                  "hedge_share_of_lp_net_loss": C[f"hedge_result_{tag}"].sum() / lpn, "bot_gross_share": C[f"bot_gross_{tag}"].sum() / lpn,
                  "max_abs_identity_residual": C[f"identity_residual_{tag}"].abs().max()})
CU = C[C.U_before.notna()]
for tag, nm in [("exec", "Binance at execution, txs with an on-chain reference"), ("onchain", "on-chain reference (Uniswap v3 0.01%) at execution")]:
    lpn = -CU[f"lp_net_{tag}"].sum()
    srows.append({"valuation": nm, "txs": len(CU), "lp_swap_side": CU[f"lp_swap_side_{tag}"].sum(), "lp_fee_credited": CU[f"lp_fee_credited_{tag}"].sum(),
                  "lp_net_loss": lpn, "hedge_pools": CU[f"hedge_result_{tag}"].sum(), "bot_gross": CU[f"bot_gross_{tag}"].sum(),
                  "router": CU[f"router_{tag}"].sum(), "fynd_20pct": CU[f"fynd_protocol_{tag}"].sum(),
                  "hedge_share_of_lp_net_loss": CU[f"hedge_result_{tag}"].sum() / lpn, "bot_gross_share": CU[f"bot_gross_{tag}"].sum() / lpn,
                  "max_abs_identity_residual": CU[f"identity_residual_{tag}"].abs().max()})
srows.append({"valuation": "checked LP split (chart's $3,422): all 24,258 swaps, LP fee from FeesAccumulated attribution, 12 s",
              "txs": len(R), "lp_swap_side": N["checked_lp_swap_side_12s"], "lp_fee_credited": N["checked_lp_fee_bot_swaps"],
              "lp_net_loss": -N["checked_lp_net_bot_swaps"]})
srows.append({"valuation": "this audit, all 24,258 txs incl. incomplete (their legs are partly unknown), 12 s",
              "txs": len(R), "lp_swap_side": R.lp_swap_side_12s.sum(), "lp_fee_credited": R.lp_fee_credited_12s.sum(),
              "lp_net_loss": -R.lp_net_12s.sum()})
pd.DataFrame(srows).to_csv(D("sensitivity_analysis.csv"), index=False)
json.dump(N, open(D("data", "audit_numbers.json"), "w"), indent=1, default=float)
print(json.dumps(N, indent=1, default=float))
