"""
Final accounting: one bot P&L waterfall, one value-flow table, LP results by owner group, the fee split, and wallet
links. Reads the existing outputs (out/, final/data/) and the checked LP files; writes only into final/.

  python3 final/reconcile.py --root . --lp ../markout-backtest --out final
"""
import argparse, json, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
J = lambda *p: os.path.join(a.root, *p)
T = pd.read_pickle(J("out", "_T.pkl"))
SUM = json.load(open(J("out", "summary.json")))
REC = pd.read_csv(J("out", "bot_value_reconciliation.csv"))
H = pd.read_csv(J("final", "data", "hedge_legs.csv"))
R = json.load(open(os.path.join(a.lp, "results_lp_fynd.json")))
O = pd.read_csv(os.path.join(a.lp, "results_lp_fynd_owners.csv"))
FA = pd.read_csv(os.path.join(a.lp, "data_swaps", "eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv"))
FS = json.load(open(J("final", "data", "fee_split_all.json")))
WT = pd.read_csv(J("final", "data", "wallet_transfers.csv"))
CL = json.load(open(J("data", "bot_contract_logs.json")))["logs"]
PROTO = SUM["protocol_share"]
C = T[T.completeness.str.startswith("complete")].copy()
I = T[~T.completeness.str.startswith("complete")]
C["router_usd"] = C.router_fee_eth_wei / 1e18 * C.b0 + C.router_fee_usdg_raw / 1e6
oc = SUM["bot_costs_outside_fynd_swaps"]
gas_med_eth = oc["median_gas_eth_per_fynd_tx"]; P_END = SUM["eth_at_snapshot"]
res = {}

# ------------------------------------------------------------------ bot P&L waterfall
gross = C.bot_gross_usd.sum(); fee = C.fee_usd.sum(); router = C.router_usd.sum(); gas = C.gas_usd.sum()
other_gas = oc["eoa_txs_not_a_successful_trade"] * gas_med_eth * P_END
inc_net = I.bot_net_usd.sum(); unreal = (C.bot_eth * (P_END - C.b0)).sum()
W = []
add = lambda step, usd, kind, ev, note: W.append({"step": step, "usd": usd, "metric": kind, "evidence": ev, "note": note})
edge = gross + fee + router
add("1. Price edge captured: Fynd price vs hedge price, before any fee", edge, "gross, realized", "calculated",
    f"{len(C):,} complete bot txs, valued at Binance at execution")
add("2. less Fynd fee paid by the bot", -fee, "cost", "observed (USDG) / inferred from bot event (ETH)",
    f"goes {1 - PROTO:.0%} to LPs (${fee * (1 - PROTO):,.2f}) and {PROTO:.0%} to the protocol (${fee * PROTO:,.2f})")
add("3. less router fees", -router, "cost", "observed (USDG) / router event (ETH)", "to 0xa5503d92...")
add("4. = Gross trading P&L", gross, "gross, realized", "calculated", "this is the $739 in the replay table (REAL row) and in out/ section 4")
add("5. less gas on these txs", -gas, "cost", "observed", "gasUsed x effectiveGasPrice, includes the L1 part")
add("6. = Net realized P&L on complete txs", gross - gas, "net, realized", "calculated", "the reported $295")
add("7. plus the incomplete txs, net", inc_net, "net, realized", "calculated", f"{len(I)} txs; bot result confirmed by its event")
add("8. less gas on the EOA's txs that were not trades (estimate)", -other_gas, "cost estimate", "assumed",
    f"{oc['eoa_txs_not_a_successful_trade']} txs x median trade gas; reverts not listable")
net_all = gross - gas + inc_net - other_gas
add("9. = Net after all measurable costs", net_all, "net, realized", "calculated", "")
add("10. ETH kept as profit, revalued to the Nov 13 snapshot", unreal, "unrealized", "calculated", f"ETH ${P_END:,.2f} at snapshot")
add("11. = Net, marked to the snapshot", net_all + unreal, "net, realized + unrealized", "calculated", "")
# reconciling items (not additive)
cu = C[C.uni_before.notna()]
g_b_cu = cu.bot_gross_usd.sum(); g_u_cu = (cu.bot_eth * cu.uni_before + cu.bot_usdg).sum()
add("R1. Gross, trades without an on-chain reference price (Nov 13) removed", g_b_cu, "gross, realized", "calculated", f"{len(cu):,} txs")
add("R2. same trades, ETH profit valued at the on-chain price instead of Binance", g_u_cu, "gross, realized", "calculated",
    "this is the $725 in the on-chain column of the value split")
add("R3. Gross at Binance 12 s later", C.bot_usd_12s.sum(), "gross", "calculated", "differs from step 4 only by the 12 s move on ETH held as profit")
ev = pd.DataFrame([{"pool": l["data"][2:66], "token": "0x" + l["topics"][3][-40:], "w3": int(l["data"][2:][192:256], 16), "hash": l["transactionHash"]}
                   for l in CL if l["topics"][0].startswith("0xed370fed")])
evf = ev[ev.hash.isin(T.hash)]
res["bot_event_vs_reconstruction"] = {"eth_event": float(evf[evf.token.str.startswith("0xeeee")].w3.sum() / 1e18), "eth_rebuilt": float(T.bot_eth.sum()),
                                      "usdg_event": float(evf[evf.token == "0x5fc5360d0400a0fd4f2af552add042d716f1d168"].w3.sum() / 1e6), "usdg_rebuilt": float(T.bot_usdg.sum())}
Wd = pd.DataFrame(W); Wd.to_csv(os.path.join(a.out, "BOT_PNL_WATERFALL.csv"), index=False)

# ------------------------------------------------------------------ value flow
V = []
vadd = lambda sec, item, usd, ev_, note="": V.append({"section": sec, "item": item, "usd": usd, "evidence": ev_, "note": note})
s = "A. LP results vs holding, by owner group (Oct 2 - Nov 13)"
O["group"] = np.where(O.owner == "0x6c6a40d2d1fc442e281e1f80314fd86516e17127", "0x6c6a...7127 (Fynd, confirmed by Edouard Nov 12)",
                      np.where(O.owner.str.startswith("via"), "held through contract 0x0db596af (owner unresolved)", "other EOAs (ownership unresolved)"))
days = R["period"]["days"]
grp = O.groupby("group")[["positions", "capital_days_usd", "fees_usd", "il_usd", "lp_minus_hold_usd"]].sum()
grp["avg_capital_usd"] = grp.capital_days_usd / days
grp["lp_minus_hold_pct_period"] = 100 * grp.lp_minus_hold_usd / grp.avg_capital_usd
grp["lp_minus_hold_pct_30d"] = 100 * 30 * grp.lp_minus_hold_usd / grp.capital_days_usd
ind = O[O.owner != "0x6c6a40d2d1fc442e281e1f80314fd86516e17127"]
for gname, r in grp.iterrows():
    vadd(s, f"{gname}: LP vs hold", r.lp_minus_hold_usd, "calculated", f"{int(r.positions)} positions, avg capital ${r.avg_capital_usd:,.0f}, {r.lp_minus_hold_pct_30d:.1f}% per 30 days (fees ${r.fees_usd:,.0f}, IL ${r.il_usd:,.0f})")
ind_cd = ind.capital_days_usd.sum()
vadd(s, "all LPs other than 0x6c6a: LP vs hold", ind.lp_minus_hold_usd.sum(), "calculated",
     f"avg capital ${ind_cd / days:,.0f}, {100 * 30 * ind.lp_minus_hold_usd.sum() / ind_cd:.1f}% per 30 days")
vadd(s, "all LPs: LP vs hold (checked report)", O.lp_minus_hold_usd.sum(), "calculated", "")
res["owner_groups"] = grp.reset_index().to_dict(orient="records")
res["independent"] = {"lp_minus_hold_usd": float(ind.lp_minus_hold_usd.sum()), "avg_capital_usd": float(ind_cd / days),
                      "pct_30d": float(100 * 30 * ind.lp_minus_hold_usd.sum() / ind_cd), "fees_usd": float(ind.fees_usd.sum()), "il_usd": float(ind.il_usd.sum()),
                      "pct_period": float(100 * ind.lp_minus_hold_usd.sum() / (ind_cd / days))}

s = "B. Fynd fees: who paid, who received"
lp_pos = R["totals"]["fees_usd"]
fa_val = float(next(r.usd for r in REC.itertuples() if r.item.startswith("all fees paid to LPs")))
vadd(s, "LP fee income, position level (checked report)", lp_pos, "calculated", "LPs' 80% share: every FeesAccumulated payment reached positions (checked report: 100.000%); valued at each position's end")
vadd(s, "same LP fees valued when paid (FeesAccumulated)", fa_val, "observed tokens, Binance when paid", f"differs from the row above by valuation timing only (${fa_val - lp_pos:,.2f})")
vadd(s, "gross Fynd fees, all payers (= LP fees / 0.8)", fa_val / (1 - PROTO), "calculated", "assumes the 20% share held for every payer (tested in B2)")
vadd(s, "protocol (owner) share, 20%", fa_val * PROTO / (1 - PROTO), "calculated", "the $521")
vadd(s, "  paid by the bot (exact per swap)", fee, "observed / inferred", f"LPs ${fee * (1 - PROTO):,.2f}, protocol ${fee * PROTO:,.2f}")
vadd(s, "  paid by everyone else (gross fees minus the bot's)", fa_val / (1 - PROTO) - fee, "calculated", "includes Oct 2-13, before the bot")
vadd(s, "B2. external traders' fees observed (charged on their USDG output)", FS["external_output_fee_usd_observed"], "observed",
     f"{FS['external_swaps_fee_observed_in_usdg']:,} external swaps receiving USDG; {FS['external_output_fee_bp_volume_weighted']:.1f} bp volume-weighted, "
     f"median {FS['external_output_fee_bp_median']:.1f} bp; swaps paying USDG in are charged nothing on input ({FS['external_usdg_input_swaps_checked']:,} checked)")
vadd(s, "B2. LP fee payments that include external fees and equal exactly 80%", np.nan, "observed",
     f"{FS['match_80pct_with_external_fees']:,} of {FS['fa_intervals_usdg_checkable_with_external_fees']:,} (median LP share {FS['lp_share_median_with_external_fees']:.5f}); "
     f"all checkable payments: {FS['match_80pct_all_checkable']:,} of {FS['fa_intervals_usdg_checkable']:,}")

s = "C. The bot's swaps: where the LPs' swap-side result went (exact per tx)"
for tag, lab in [("exec", "Binance at execution"), ("12s", "Binance 12 s later")]:
    lp = C[f"fynd_lp_trade_usd_{tag}"].sum()
    fee_t = (C.fee_usd if tag == "exec" else np.where(C.fee_token == "ETH", C.fee_units * C.b12, C.fee_units)).sum()
    parts = {"pools the bot hedged on": C[f"other_venues_usd_{tag}"].sum(), "bot, gross": C[f"bot_usd_{tag}"].sum(),
             "Fynd fee": fee_t, "router fees": router}
    vadd(s, f"Fynd LPs' swap side ({lab})", lp, "calculated", "")
    tot = sum(parts.values())
    for k_, v_ in parts.items():
        vadd(s, f"  {k_} ({lab})", v_, "calculated", f"{100 * v_ / -lp:.2f}% of the LPs' swap-side loss")
    vadd(s, f"  residual: LPs' side + parts ({lab})", lp + tot, "calculated",
         "tokens are conserved; any residual is the fee valued at a different price than the swap (12 s) and float rounding")
res["split_pct_12s"] = {k: float(100 * v / -C.fynd_lp_trade_usd_12s.sum()) for k, v in
                        {"hedge": C.other_venues_usd_12s.sum(), "bot": C.bot_usd_12s.sum(),
                         "fee": np.where(C.fee_token == "ETH", C.fee_units * C.b12, C.fee_units).sum(), "router": router}.items()}

Sd = H[(H.single_direct_hedge == True) & H.uni_before.notna()]
s = f"D. The hedge pools' result split ({len(Sd):,} single direct ETH/USDG hedges with an on-chain reference price, Binance at execution)"
items = [("fees charged by the hedge pools, to their LPs", Sd.h_fee_lp_usd.sum(), "calculated from swap event fee and pool fee tier"),
         ("fees charged by the hedge pools, to their protocols", Sd.h_fee_protocol_usd.sum(), "calculated; v4 from event fee - LP fee; v3 from slot0 now"),
         ("fees charged by the hedge pools, LP/protocol split unknown", Sd.h_fee_split_unknown_usd.sum(), "calculated; non-standard pools"),
         ("price impact of the bot's hedge on those pools", Sd.h_impact_usd.sum(), "calculated; constant liquidity within the swap"),
         ("those pools' price vs the on-chain reference before the hedge", Sd.h_own_dev_usd.sum(), "calculated"),
         ("on-chain reference vs Binance (basis)", Sd.h_basis_usd.sum(), "calculated"),
         ("= hedge pools' result at execution", Sd.h_total_usd.sum(), "calculated"),
         ("Binance move over the next 12 s on what they took", Sd.h_move_12s_usd.sum(), "calculated; market movement, not income"),
         ("other bot trades (multi-hop hedges, or no on-chain reference on Nov 13), 12 s", C[~C.hash.isin(Sd.hash)].other_venues_usd_12s.sum(), "calculated; not split")]
for k_, v_, e_ in items:
    vadd(s, k_, v_, e_)
res["hedge_split"] = {k_: float(v_) for k_, v_, _ in items}

fy = H[H.hash.isin(C.hash) & H.uni_before.notna()]
s = f"E. The Fynd pool's side split ({len(fy):,} complete bot swaps with an on-chain reference price, Binance at execution)"
for k_, col in [("Fynd's price vs the on-chain reference before the trade (staleness)", "f_own_dev_usd"),
                ("on-chain reference vs Binance (basis)", "f_basis_usd"), ("Fynd's own curve (the pool gains from the trade's impact)", "f_impact_usd"),
                ("= Fynd LPs' swap side", "f_total_usd")]:
    vadd(s, k_, fy[col].sum(), "calculated")
res["fynd_split"] = {c: float(fy[c].sum()) for c in ["f_own_dev_usd", "f_basis_usd", "f_impact_usd", "f_total_usd"]}

s = "F. External traders (not the bot), whole period"
ex = SUM["external"]
vadd(s, "LPs' swap side on external swaps, 12 s", -ex["lp_loss_12s_usd"], "calculated", f"{ex['swaps']:,} swaps")
vadd(s, "fees external traders paid (gross)", ex["fees_total_incl_protocol_usd"], "calculated", "proportional attribution from lp_split.py")
vadd(s, "external traders' result after fees", ex["trader_result_12s_after_all_fees_usd"], "calculated", "")
VD = pd.DataFrame(V); VD.to_csv(os.path.join(a.out, "VALUE_FLOW_RECONCILIATION.csv"), index=False)

# ------------------------------------------------------------------ wallet links (USDG/WETH transfers)
names = {"0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7": "bot_contract", "0x4abfdbac0afa181338dc9c38c9c1264128c684a2": "bot_eoa",
         "0xd7c8c4ebf30c2825d73a36b8b6e9d1a842e61c80": "bot_owner_1", "0x0d41d284672c524d14790b230afe3e287ef4d4b2": "bot_owner_2",
         "0x6c6a40d2d1fc442e281e1f80314fd86516e17127": "lp_0x6c6a", "0xa5503d92ee16a78e602996ad362674dc49034a14": "router_fee_recipient"}
trade_tx = set(ev.hash)
WT = WT.drop_duplicates(["tx_hash", "log_index"])
WT["from_name"] = WT["from"].map(names); WT["to_name"] = WT["to"].map(names)
links = WT[WT.from_name.notna() & WT.to_name.notna() & (WT.from_name != WT.to_name)]
bot_out = WT[(WT["from"] == "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7") & ~WT.tx_hash.isin(trade_tx)]
bot_in = WT[(WT["to"] == "0x7ea0ab3bf0ba63dfdcf3fcb73b68c04d89bcacc7") & ~WT.tx_hash.isin(trade_tx)]
dec = lambda tok: 1e6 if tok == "0x5fc5360d0400a0fd4f2af552add042d716f1d168" else 1e18
fmt = lambda df: [{"block": int(r.block), "tx": r.tx_hash, "token": "USDG" if r.token.startswith("0x5fc5") else "WETH",
                   "from": names.get(r["from"], r["from"]), "to": names.get(r["to"], r["to"]), "amount": r.raw / dec(r.token)} for _, r in df.iterrows()]
res["wallet_links"] = {"direct_transfers_between_named_wallets": fmt(links), "bot_contract_out_not_trades": fmt(bot_out),
                       "bot_contract_in_not_trades": fmt(bot_in),
                       "owner_1_transfers": fmt(WT[WT.wallet == "bot_owner_1"])}
res["waterfall"] = W; res["fee_split_all"] = FS
json.dump(res, open(os.path.join(a.out, "data", "reconcile.json"), "w"), indent=1, default=float)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
print(Wd[["step", "usd", "metric"]].round(2).to_string())
print(VD[["section", "item", "usd"]].round(2).to_string())
print(json.dumps({k: res[k] for k in ["bot_event_vs_reconstruction", "independent", "split_pct_12s"]}, indent=1, default=float))
print(json.dumps(res["wallet_links"], indent=1, default=float)[:3000])
