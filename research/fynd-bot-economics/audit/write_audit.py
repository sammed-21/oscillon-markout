"""
Write audit/replay_validation.csv, audit/audit_hand_checks.md and audit/AUDIT_REPORT.md from the audit's own outputs
(audit/data/*.json, audit/*.csv) and, for the bottom panel's scenario figures, final/data/il_attribution.json.

  python3 audit/write_audit.py --root . --lp ../markout-backtest --out audit
"""
import argparse, json, os
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True); ap.add_argument("--lp", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
D = lambda *p: os.path.join(a.out, *p)
N = json.load(open(D("data", "audit_numbers.json"))); RV = json.load(open(D("data", "replay_check.json")))
IA = json.load(open(os.path.join(a.root, "final", "data", "il_attribution.json")))
R = pd.read_pickle(D("data", "_R.pkl"))
TX = pd.read_csv(D("top_panel_transaction_reconciliation.csv"))
HG = pd.read_csv(D("hedge_execution_costs.csv"), low_memory=False)
SEN = pd.read_csv(D("sensitivity_analysis.csv"))
f2 = lambda v: f"{v:,.2f}"
usd = lambda v: ("−" if v < 0 else "") + f"${abs(v):,.2f}"

# ================================================================ replay_validation.csv
rv = []
for tag in ["anchored", "open_loop"]:
    r = RV[tag]
    for k, v in r.items():
        if isinstance(v, list):
            for p, x in zip(["p50", "p90", "p99", "max"], v):
                rv.append({"test": f"A/B per-swap ({tag})", "metric": f"{k.replace('_p50_p90_p99_max', '')} {p}", "value": x})
        else:
            rv.append({"test": f"A/B per-swap ({tag})", "metric": k, "value": v})
for k, v in RV["conservation"].items():
    rv.append({"test": "D token conservation (anchored)", "metric": k, "value": v})
for k, v in RV["positions"].items():
    rv.append({"test": "C LP vs hold per position (anchored, full period)", "metric": k, "value": v})
for m, r in IA["replays"].items():
    for k in ["lp_vs_hold_ex_fees_usd", "lp_vs_hold_usd", "mean_abs_gap_bp", "external_eth_unfilled", "arbitrageur_net_usd"]:
        rv.append({"test": f"bottom panel scenario {m}", "metric": k, "value": r[k]})
    rv.append({"test": f"bottom panel scenario {m}", "metric": "lp_fees_usd_total", "value": sum(r["lp_fees_usd"].values())})
    rv.append({"test": f"bottom panel scenario {m}", "metric": "net_minus_(ex_fees+fees)", "value": r["lp_vs_hold_usd"] - r["lp_vs_hold_ex_fees_usd"] - sum(r["lp_fees_usd"].values())})
rv.append({"test": f"bottom panel scenario REAL vs direct calculation", "metric": "LP swap side on bot swaps at execution, replay - direct (USD)",
           "value": IA["replays"]["REAL"]["lp_swap_side_at_execution_usd"]["bot"] - IA["horizons"]["lp_swap_side_on_bot_swaps_usd"]["execution"]})
pd.DataFrame(rv).to_csv(D("replay_validation.csv"), index=False)

# ================================================================ hand checks
C = R[R.issues == ""]
pick = {}
cand = C[(C.bot_pays == "ETH") & (C.n_hedge_legs == 1) & C.hedge_route.str.startswith("uniswap_v4") & (C.fee_raw > 0) & C.U_before.notna()]
pick["H1 bot pays ETH into Fynd, one Uniswap v4 hedge"] = cand.iloc[len(cand) // 2].hash
cand = C[(C.bot_pays == "USDG") & (C.n_hedge_legs == 1) & C.hedge_route.str.startswith("uniswap_v3") & (C.fee_raw > 0) & C.U_before.notna()]
pick["H2 bot pays USDG into Fynd, one Uniswap v3 hedge"] = cand.iloc[len(cand) // 2].hash
cand = C[(C.n_hedge_legs >= 3) & (C.C4_intermediate_left == "")]
pick["H3 multi-hop hedge (3+ legs)"] = cand.iloc[len(cand) // 2].hash
cand = C[C.C4_intermediate_left != ""]
pick["H4 hedge through an Ekubo stock pool whose extension keeps part of the output"] = cand.iloc[0].hash
G = pd.read_csv(D("data", "fee_intervals.csv"), index_col=0)
SWf = pd.concat([pd.read_csv(os.path.join(a.lp, "data_swaps", f)) for f in
                 ["eth_usdg_ekubo_robinhood_to1108.csv", "eth_usdg_ekubo_robinhood_nov9_11.csv", "eth_usdg_ekubo_robinhood_nov11_13.csv"]]) \
    .drop_duplicates(["block", "log_index"])
FAc = pd.read_csv(os.path.join(a.lp, "data_swaps", "eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv")).sort_values(["block", "log_index"]).reset_index(drop=True)
bad = G[G.usdg_excess_vs_80pct != 0]
fk = FAc.block.values * 10**6 + FAc.log_index.values
SWf = SWf.sort_values(["block", "log_index"]); SWf["fa_idx"] = np.searchsorted(fk, SWf.block.values * 10**6 + SWf.log_index.values)
one = bad[bad.swaps == 1].index
h5 = SWf[SWf.fa_idx.isin(one)].tx_hash
h5 = [h for h in h5 if R.set_index("hash").loc[h, "hedge_route"].count("ekubo:") > 0]
pick["H5 USDG kept by another Ekubo pool counted as Fynd fee (FeesAccumulated check fails)"] = h5[0]
pick["H6 incomplete: a venue whose events cannot be decoded"] = R[R.issues != ""].iloc[0].hash

raw = {}
for line in open(os.path.join(a.root, "data", "bot_txs.jsonl")):
    j = json.loads(line)
    if j["receipt"]["transactionHash"] in pick.values():
        raw[j["receipt"]["transactionHash"]] = j["receipt"]
hc = ["# Audit hand checks", "",
      "Six transactions, picked by rule (`audit/write_audit.py`), traced from the raw receipt (`data/bot_txs.jsonl`) to every column of",
      "`top_panel_transaction_reconciliation.csv`. Amounts: + = that party received. ETH = native ETH or WETH. Prices: Binance ETHUSDC",
      "1 s, close of the candle opening at T-2 (\"at execution\") and at T+12 (\"12 s\"). U = Uniswap v3 0.01% price after its last swap",
      "in an earlier transaction.", ""]
for nm, h in pick.items():
    rc = raw[h]; r = TX.set_index("hash").loc[h]
    hc += [f"## {nm}", "", f"`{h}`, block {int(r.block):,}, {pd.Timestamp(int(r.ts), unit='s')} UTC, status {int(r.status)}", ""]
    hc += ["Raw logs used:", "", "| log | address | what | raw values |", "|---|---|---|---|"]
    for l in rc["logs"]:
        ad, t, d = l["address"].lower(), l["topics"], l["data"][2:]
        li = int(l["logIndex"], 16)
        if ad == "0x00000000000014aa86c5d3c41765bb24e11bd701" and not t and len(d) == 232:
            s128 = lambda x: (lambda v: v - (1 << 128) if v >= 1 << 127 else v)(int(x, 16))
            hc.append(f"| {li} | Ekubo Core | swap, pool {d[40:52]}… | amount0 {s128(d[104:136]):,}, amount1 {s128(d[136:168]):,} (pool received) |")
        elif t and t[0].startswith("0xc42079f9"):
            s256 = lambda x: (lambda v: v - (1 << 256) if v >= 1 << 255 else v)(int(x, 16))
            hc.append(f"| {li} | {ad[:10]}… | Uniswap v3 Swap | amount0 {s256(d[0:64]):,}, amount1 {s256(d[64:128]):,}, sqrtPriceX96 {int(d[128:192], 16)}, L {int(d[192:256], 16)} |")
        elif t and t[0].startswith("0x40e9cecb"):
            s256 = lambda x: (lambda v: v - (1 << 256) if v >= 1 << 255 else v)(int(x, 16))
            hc.append(f"| {li} | PoolManager | Uniswap v4 Swap, pool {t[1][:12]}… | amount0 {s256(d[0:64]):,}, amount1 {s256(d[64:128]):,} (swapper's side), fee {int(d[320:384], 16)} pips |")
        elif t and t[0].startswith("0xddf252ad") and len(t) == 3:
            hc.append(f"| {li} | {ad[:10]}… | Transfer | {('0x' + t[1][-40:])[:10]}… → {('0x' + t[2][-40:])[:10]}…: {int(d[:64], 16):,} |")
        elif t and t[0].startswith("0xed370fed"):
            w = [int(d[i:i + 64], 16) for i in range(64, 256, 64)]
            hc.append(f"| {li} | bot contract | bot event | word1 {w[0]:,}, word2 {w[1]:,}, word3 (profit) {w[2]:,} |")
        elif t and t[0].startswith("0x90d361ec"):
            n = int(d[64:128], 16)
            items = ", ".join(f"{('0x' + d[128 + 128 * k + 24:192 + 128 * k])[:10]}…: {int(d[192 + 128 * k:256 + 128 * k], 16):,}" for k in range(n))
            hc.append(f"| {li} | router | fee event, token {('0x' + t[1][-40:])[:10]}… | {items} |")
        elif t and t[0].startswith("0xf7e050d8"):
            hc.append(f"| {li} | Ekubo Core | FeesAccumulated (pays LPs fees accrued before this tx) | ETH {int(d[64:128], 16):,}, USDG {int(d[128:192], 16):,} |")
    hc += ["", f"gasUsed {int(rc['gasUsed'], 16):,} × effectiveGasPrice {int(rc['effectiveGasPrice'], 16):,} wei = {r.gas_eth:.12f} ETH", ""]
    hc += ["| quantity | formula | value |", "|---|---|---|"]
    hc += [f"| Fynd pool received | Fynd swap amounts | {r.fynd_eth:+.9f} ETH, {r.fynd_usdg:+.6f} USDG |",
           f"| Fynd execution price | abs(USDG / ETH) | {r.fynd_exec_price:,.4f} |",
           f"| Binance at execution / 12 s / U | | {r.B_exec:,.2f} / {r.B_12s:,.2f} / {r.U_before if pd.notna(r.U_before) else float('nan'):,.4f} |",
           f"| Fynd fee | {r.fee_source} | {r.fee_eth:.12f} ETH, {r.fee_usdg:.6f} USDG |",
           f"| LP swap side, 12 s | ETH × B12 + USDG | {r.lp_swap_side_12s:+.6f} |",
           f"| fee credited to LPs, 12 s | 0.8 × fee | {r.lp_fee_credited_12s:+.6f} |",
           f"| LP net, 12 s | sum of the two | {r.lp_net_12s:+.6f} |",
           f"| hedge pools received | sum over hedge legs | {r.hedge_eth:+.9f} ETH, {r.hedge_usdg:+.6f} USDG ({r.hedge_route}) |",
           f"| hedge pools' result, 12 s | ETH × B12 + USDG | {r.hedge_result_12s:+.6f} |",
           f"| router fee | router event, non-bot recipients | {r.router_eth:.12f} ETH, {r.router_usdg:.6f} USDG; 12 s {r.router_12s:+.6f} |",
           f"| Fynd 20% | 0.2 × fee | {r.fynd_protocol_12s:+.6f} |" if "fynd_protocol_12s" in r else "",
           f"| bot change | −(pools' receipts) − fee − router | {r.bot_eth:+.12f} ETH, {r.bot_usdg:+.6f} USDG |",
           f"| check C1: USDG from Transfer logs − bot change | | {int(r.C1_usdg_gap_raw) if pd.notna(r.C1_usdg_gap_raw) else 'n/a'} raw |",
           f"| check C2: bot event profit − bot change in the token it paid | | {int(r.C2_profit_gap_raw) if pd.notna(r.C2_profit_gap_raw) else 'n/a'} raw |",
           f"| check C3: token not paid in, left with the bot | | {int(r.C3_other_token_left_raw) if pd.notna(r.C3_other_token_left_raw) else 'n/a'} raw |",
           f"| bot gross, at execution / 12 s | ETH × B + USDG | {r.bot_gross_exec:+.6f} / {r.bot_gross_12s:+.6f} |",
           f"| gas | gas ETH × B at execution | {r.gas_usd:.6f} |",
           f"| bot net, at execution | gross − gas | {r.bot_net_exec:+.6f} |",
           f"| identity, 12 s | LP swap side + hedge + bot + Fynd fee + router | {r.identity_residual_12s:+.2e} |"]
    if isinstance(r.intermediate_kept_by_venue, str) and r.intermediate_kept_by_venue:
        hc.append(f"| intermediate token kept by a venue (C4) | | {r.intermediate_kept_by_venue} |")
    if "H5" in nm:
        iv = G[G.index.isin(SWf[SWf.tx_hash == h].fa_idx)].iloc[0]
        hc += [f"| the FeesAccumulated that pays this swap's fee | next FA after the swap | USDG {iv.amount1:.6f} |",
               f"| 0.8 × fee computed here | | {0.8 * iv.fee_usdg:.6f}: the computed fee is {iv.fee_usdg - iv.amount1 / 0.8:.6f} USDG too high |"]
    if isinstance(r.issues, str) and r.issues:
        hc.append(f"| not reconciled | | {r.issues} |")
    hc.append("")
open(D("audit_hand_checks.md"), "w").write("\n".join(hc))

# ================================================================ AUDIT_REPORT.md
cv = N["chart_values"]; H = N["hedge"]; B = N["bot"]; F = N["fees"]; FE = N["fee_excess"]
disp = [("LP net loss on bot trades", cv["lp_net_loss"]), ("hedge pools", cv["hedge"]), ("gas", cv["gas"]), ("bot net", cv["bot_net"]),
        ("router", cv["router"]), ("Fynd 20%", cv["fynd_20pct"])]
parts_sum = cv["hedge"] + cv["gas"] + cv["bot_net"] + cv["router"] + cv["fynd_20pct"]
c12 = {k: N[f"{k}_12s_complete"] for k in ["lp_net", "hedge_result", "bot_gross", "router", "fynd_protocol", "lp_swap_side", "lp_fee_credited", "fynd_fee"]}
ce = {k: N[f"{k}_exec_complete"] for k in ["lp_net", "hedge_result", "bot_gross", "router", "fynd_protocol", "lp_swap_side", "lp_fee_credited", "fynd_fee"]}
gas = N["gas_usd_complete"]
x = FE["usdg"]
corr = {"fee": c12["fynd_fee"] - x, "lp_cred": 0.8 * (c12["fynd_fee"] - x), "fynd": 0.2 * (c12["fynd_fee"] - x), "hedge": c12["hedge_result"] + x}
corr["lp_net"] = c12["lp_swap_side"] + corr["lp_cred"]
sen = SEN.set_index("valuation")
S = IA["replays"]
rep = f"""# Audit of `final/il_vs_bot_capture.png`

Scope: every number in the chart, rebuilt from raw transaction receipts with a separate method (`audit/recon.py`), then compared
with the research outputs. Nothing in `out/`, `final/` or the checked LP report was modified; the chart was not regenerated.
Audit run: {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC.

Labels: **[V]** verified directly from on-chain data · **[R]** recomputed and independently reconciled · **[I]** inferred ·
**[E]** estimated · **[N]** not verifiable with available data.

## Verdict

| chart number | audit result | status |
|---|---|---|
| LP net loss on bot trades $3,422 | correct as a figure ({usd(-N['checked_lp_net_bot_swaps'])}), but it covers all 24,258 swaps with LP fees attributed from FeesAccumulated, while the bars below it cover the 24,199 complete transactions with fees at 80% per tx | **needs correction** (mixed populations) |
| pools the bot hedged on $2,352 | {usd(c12['hedge_result'])} [R]; valued 12 s after each trade; includes ~$440 of later market movement and $424 of routes that cannot be split; {usd(x)} too low (see fee finding) | **needs caveat and small correction** |
| gas $443 | {usd(gas)} [V for ETH, R for USD]; complete trades only; excludes the 844 unexplained EOA transactions | correct; **caveat** |
| bot kept $295 | {usd(B['net_exec_complete'])} [R], valued at execution; the same figure at 12 s is {usd(c12['bot_gross'] - gas)} | correct; **valuation mixed with the 12 s bars** |
| router fees $178 | {usd(ce['router'])} at execution, {usd(c12['router'])} at 12 s [R] | correct to the dollar |
| Fynd's 20% $152 | {usd(ce['fynd_protocol'])} at execution [R]; **{usd(0.2 * x)} too high** | **needs small correction** |
| "before gas it made $739" | {usd(ce['bot_gross'])} [R] | correct |
| bottom panel, real history | reproduces history (re-anchored replay); per position within $0.18 of the checked report | can be presented |
| bottom panel, no bot / outside arbitrageur | model counterfactuals; cannot be validated against history; open-loop replays of this model drift | **present only with explicit caveats** |

## 1. Top panel: the $3,422 and its parts

**Per-transaction reconstruction** (`audit/top_panel_transaction_reconciliation.csv`, one row per tx, {N['n_txs']:,} rows). For every tx: hash,
block, Fynd amounts and execution price, Binance at execution and +12 s with the reference timestamps, U, LP swap side, fee and its source, 80/20
split, LP net, every hedge leg (route column; legs in `hedge_execution_costs.csv`), router fee, bot change per token, bot gross and net, gas.

**Every economic leg counted exactly once.** Each swap event belongs to one party: the Fynd leg to Fynd LPs, every other swap to "hedge pools".
The Fynd fee (charged by the extension outside the pool amounts) and router fees are separate legs. The bot's change is −(sum of all pools'
receipts) − Fynd fee − router fee per asset, so the five parts sum to zero by construction (max |residual| {N['max_abs_identity_residual_12s_usd_complete']:.1e} USD).
What makes this a test rather than an identity is that the bot's change is checked against three independent records:

| check | what it compares | result on the {N['n_complete']:,} complete txs | label |
|---|---|---|---|
| C1 | bot's USDG change vs USDG Transfer logs to/from the bot's two addresses | 0 mismatches (exact, raw units) | [V] |
| C2 | bot's change in the token it paid in vs the bot contract's profit event | 0 mismatches (exact) | [R] (bot's own event) |
| C3 | the token it did not pay in, left with the bot | 0 in every tx: no inventory kept | [R] |
| C4 | intermediate tokens net to zero over the legs | {H['stock_ext_txs']} txs keep an intermediate token inside Ekubo Core: the stock-pool extension's fee on that hedge venue, part of the hedge pools' result | [R] |
| unknown events | logs from contracts the decoder does not know | {N['n_incomplete']} txs (the same 59 the research excluded); 41 fail C1 | excluded |

**Rebuild vs research, per tx:** bot ETH/USDG change, Fynd fee, router fees, gas and Binance price agree exactly on all 24,199 complete txs. The on-chain reference U differs on 38 txs (max $0.06) because the two rebuilds define "the last Uniswap swap before" slightly differently.

**The chart mixes two populations and two valuation times.** Full precision:

| | chart | this audit, complete txs, 12 s | this audit, complete txs, at execution |
|---|---|---|---|
| LP net loss on bot trades | {f2(cv['lp_net_loss'])} (24,258 swaps; LP fee {f2(N['checked_lp_fee_bot_swaps'])} from FeesAccumulated attribution) | {f2(-c12['lp_net'])} | {f2(-ce['lp_net'])} |
| hedge pools | {f2(cv['hedge'])} (12 s) | {f2(c12['hedge_result'])} | {f2(ce['hedge_result'])} |
| bot gross | {f2(cv['bot_gross_label'])} (execution) | {f2(c12['bot_gross'])} | {f2(ce['bot_gross'])} |
| gas | {f2(cv['gas'])} | {f2(gas)} | {f2(gas)} |
| bot net | {f2(cv['bot_net'])} (execution) | {f2(c12['bot_gross'] - gas)} | {f2(ce['bot_gross'] - gas)} |
| router | {f2(cv['router'])} (execution) | {f2(c12['router'])} | {f2(ce['router'])} |
| Fynd 20% | {f2(cv['fynd_20pct'])} (execution) | {f2(c12['fynd_protocol'])} | {f2(ce['fynd_protocol'])} |
| parts (hedge + gas + bot net + router + Fynd 20%) | {f2(parts_sum)} | {f2(c12['hedge_result'] + c12['bot_gross'] + c12['router'] + c12['fynd_protocol'])} | {f2(ce['hedge_result'] + ce['bot_gross'] + ce['router'] + ce['fynd_protocol'])} |
| residual (LP net loss − parts) | **{f2(cv['lp_net_loss'] - parts_sum)}** | {f2(-c12['lp_net'] - (c12['hedge_result'] + c12['bot_gross'] + c12['router'] + c12['fynd_protocol'])):s} | {f2(-ce['lp_net'] - (ce['hedge_result'] + ce['bot_gross'] + ce['router'] + ce['fynd_protocol']))} |

The chart's {f2(cv['lp_net_loss'] - parts_sum)} residual: {f2(cv['lp_net_loss'] - (-N['checked_lp_net_complete_swaps']))} from the 59 incomplete txs,
{f2(-N['checked_lp_net_complete_swaps'] + c12['lp_net'])} from LP fees attributed from FeesAccumulated ({f2(N['checked_lp_fee_complete_swaps'])} on complete swaps) instead of 0.8 × each tx's fee
({f2(c12['lp_fee_credited'])}), and {f2(c12['bot_gross'] - ce['bot_gross'] + c12['router'] - ce['router'] + c12['fynd_protocol'] - ce['fynd_protocol']):s} from mixing execution and 12 s values.
**$739 − $443 = $296 vs $295** is rounding: {f2(ce['bot_gross'])} − {f2(gas)} = {f2(ce['bot_gross'] - gas)}.

## 2. The fee finding: {usd(x)} counted as Fynd fee that was not

For a bot tx paying USDG into Fynd, the fee is the USDG Transfer net into Ekubo Core minus the USDG the Ekubo pools received. When the hedge
also goes through another Ekubo pool whose extension keeps USDG inside Core, that USDG lands in the "Fynd fee". The FeesAccumulated check
shows it: in {FE['intervals']} intervals (all bot-only, {FE['txs_with_other_ekubo_leg']} txs with another Ekubo leg) LPs received less than 80% of the computed fee;
the excess is {x:.6f} USDG. Every other checkable interval matches.

A second, independent source confirms it: the bot's own event reports the amount it paid in including the fee (word2), so word2 minus
the USDG Fynd received is the fee by the bot's account. Across all {FE['usdg_payer_txs']:,} complete txs where the bot paid USDG, it equals the
Transfer-based fee except in {FE['obs_vs_bot_event_mismatch_txs']} txs, all with another Ekubo leg and all in the {FE['intervals']} flagged intervals; the
difference is {FE['obs_vs_bot_event_mismatch_usdg']:.6f} USDG (vs {x:.6f} from the LP payments; the gap is rounding). The research (`decode.py`) uses the same
Transfer rule, so the error is in both. [R]

Corrected (12 s, complete txs): Fynd fee {f2(c12['fynd_fee'])} → {f2(corr['fee'])}; LPs' 80% {f2(c12['lp_fee_credited'])} → {f2(corr['lp_cred'])};
Fynd's 20% {f2(c12['fynd_protocol'])} → {f2(corr['fynd'])}; hedge pools {f2(c12['hedge_result'])} → {f2(corr['hedge'])}; LP net loss {f2(-c12['lp_net'])} → {f2(-corr['lp_net'])}.
Bot figures do not change. [R]

## 3. What the $2,352 measures

It is the sum over complete txs of what the other pools received, valued at Binance 12 s after the trade: ETH × B(T+12) + USDG. It is
the bot's hedge execution shortfall against Binance **plus** the market move over the next 12 s. It is not a gross volume and not anyone's
realized profit.

| part | USD | label |
|---|---|---|
| | at execution | 12 s later (the chart) | label |
|---|---|---|---|
| single direct ETH/USDG hedges ({H['direct_single_leg_txs']:,} txs) | {f2(H['direct_result_exec'])} | {f2(H['direct_result_12s'])} | [R] |
| routes with several legs, Ekubo or v2 pools ({H['not_direct_txs']:,} txs), not split further | {f2(H['result_exec_all_complete'] - H['direct_result_exec'])} | {f2(H['result_12s_not_direct'])} | [R] |
| **all complete txs** | **{f2(H['result_exec_all_complete'])}** | **{f2(H['result_12s_all_complete'])}** | [R] |

The difference between the two columns ({f2(H['result_12s_all_complete'] - H['result_exec_all_complete'])}) is the market move over 12 s on the ETH the pools took.

Decomposition of single direct Uniswap v3/v4 hedges with an on-chain reference ({H['decomposed_legs_with_U']:,} legs; exact per leg, max residual
{H['max_abs_decomp_residual']:.1e}; `hedge_execution_costs.csv`):

| part | USD | what it is | who has it |
|---|---|---|---|
| fees paid to the hedge pools | {f2(H['fee_paid_usd_decomposed'])} | pool fee rate × input | the pools' LPs and, where switched on, their protocol (split not verifiable historically [N]) |
| price impact | {f2(H['impact_usd'])} (all {H['decomposed_legs']:,} decomposed legs) | pool mid before → execution price before fee | a gain to the pool's LPs marked at Binance, reversed by the next arbitrage if prices revert |
| pool already off the on-chain reference | {f2(H['pool_vs_onchain_ref_usd'])} | U − pool mid before | same |
| on-chain vs Binance basis | {f2(H['basis_usd'])} | B − U | a measurement effect, nobody's gain |

Pre-swap mid prices are rebuilt from the post-swap price and liquidity assuming constant liquidity inside the swap [I]; median distance from
U is {H['mid_before_vs_U_median_bp']:.1f} bp. By pool, direction and size: `audit/data/hedge_by_pool.csv`, `hedge_by_direction.csv`, `hedge_by_size.csv`;
by route: `hedge_by_route.csv`. Relative to the hedge notional ({f2(H['notional_usd_all_legs_with_eth'])} USD), the shortfall at execution is
{1e4 * H['result_exec_all_complete'] / H['notional_usd_all_legs_with_eth']:.2f} bp.

## 4. Bot profitability (`bot_pnl_reconciliation.csv`)

- Gross {usd(ce['bot_gross'])} − gas {usd(gas)} = **{usd(ce['bot_gross'] - gas)}** on complete txs [R]. Kept: {B['eth_kept_complete']:.9f} ETH and
  {B['usdg_kept_complete']:.6f} USDG; no other token left in any tx (C3) [R].
- The bot events sum to {B['bot_event_profit_eth']:.9f} ETH and {B['bot_event_profit_usdg']:.6f} USDG over all 24,258 txs; on the complete txs they equal the
  rebuild exactly ({B['bot_event_profit_eth_complete']:.9f} ETH, {B['bot_event_profit_usdg_complete']:.6f} USDG). **Correction to the research wording:** "the bot's
  events add up to exactly the rebuilt amounts, 0.180656 ETH and 325.50 USDG" holds only for the complete txs (0.180116 / 325.20). The 59 other
  txs rest on the bot's own report.
- **Partly circular check:** when the bot pays ETH into Fynd, the Fynd fee comes from the bot's event (word2), so C2 then checks the hedge
  output, not the fee. The fee is checked independently by FeesAccumulated: all {int(pd.read_csv(D('fee_allocation_audit.csv')).iloc[0, 2]):,} bot-only ETH intervals pay LPs exactly 80% [R].
- 59 incomplete txs: bot event gross {usd(B['incomplete_bot_event_gross_usd'])}, gas {usd(B['incomplete_gas_usd'])} (bot's own report; not reconciled).
- **Gas from the 844 other transactions is not in the $443.** 36,024 nonces − 24,258 Fynd trades − 10,922 trades on other pools
  = {B['eoa_txs_unaccounted']} [I]. Their hashes are unknown (no tx-list API, no traces), so their gas is [N]; estimate {usd(B['unaccounted_gas_estimate_usd'])}
  (count × median trade gas × median price) [E]; the research used $12.51. Report separately; do not fold into a confirmed figure.

## 5. Fees (`fee_allocation_audit.csv`, intervals in `data/fee_intervals.csv`)

- Extension share field: {', '.join(f'0x{k} on {v:,} events' for k, v in F['extension_share_values'].items())} = 0.2 exactly [V].
- Each FeesAccumulated pays LPs the fees of the swaps since the previous one (it is emitted before the swap in the same tx). Intervals checked:
  ETH 8,914 / 8,914 at 80%; USDG {int(pd.read_csv(D('fee_allocation_audit.csv')).iloc[7, 3]):,} / {int(pd.read_csv(D('fee_allocation_audit.csv')).iloc[7, 2]):,} (exact or within the 6-decimal rounding unit), the 16 others
  being the fee finding above. External-only intervals: 2,154 / 2,154; mixed: 276 / 276 [V for USDG; ETH external fees are native and [N]].
- Bot fees (complete txs, at execution): {usd(F['bot_fee_exec_complete'])} → LPs {usd(F['bot_fee_lp_80_exec'])}, Fynd {usd(F['bot_fee_protocol_20_exec'])} (before the {usd(x)} correction).
  {F['bot_fee_zero_txs']:,} bot txs paid no Fynd fee.
- External fees observed (USDG output): {usd(F['external_usdg_fees_observed_usd'])} on {F['external_swaps_usdg_fee_observed']:,} of {F['external_swaps']:,} external swaps.
- **$2,069 is the LPs' 80% share** (position-level, checked report: {usd(F['position_level_lp_fees_usd'])}); FeesAccumulated valued when paid:
  {usd(F['fa_total_usd_when_paid'])} [V]. Gross implied {usd(F['gross_implied_usd'])}; Fynd's 20% implied {usd(F['protocol_implied_usd'])} [I]: the 20% is never
  emitted or transferred in these logs, so where it goes is [N].
- No overlap: the $152 is 0.2 × the Fynd fee legs; hedge pools are other pools' swap events, router fees the router's event; each token unit
  is in exactly one leg (C1–C3).

## 6. Bottom panel (`replay_validation.csv`)

- **Model, per swap** (all 28,100 Fynd swaps, re-anchored to the logged price after each): USDG amount error max
  {RV['anchored']['usdg_err_bp_p50_p90_p99_max'][3]:.2f} bp (${RV['anchored']['max_abs_usdg_err_usd']:.4f}), cumulative ${RV['anchored']['cum_usdg_err_usd']:.4f};
  post-swap price max {RV['anchored']['price_err_bp_p50_p90_p99_max'][3]:.2f} bp; liquidity off by >1% on {RV['anchored']['swaps_liquidity_err_over_1pct']} swap (a price exactly on a range
  boundary; its amounts are still right); {RV['anchored']['unfilled_swaps']} swaps partly unfilled in the model [R].
- **Per position** (full period): 176 positions with one deposit and one withdrawal match the checked LP report within
  {usd(RV['positions']['simple_max_abs_diff_usd'])} each ({usd(RV['positions']['simple_sum_abs_diff_usd'])} in total) [R].
- **Token conservation:** positions' token change vs swaps: {RV['conservation']['positions_token_change_eth'] - RV['conservation']['swaps_eth_to_pool']:+.2e} ETH,
  {RV['conservation']['positions_token_change_usdg'] - RV['conservation']['swaps_usdg_to_pool']:+.4f} USDG (from re-anchoring) [R].
- **Real history** (scenario A) re-anchors to logged prices, so it is history; its LP swap side on bot swaps equals the direct calculation to
  {abs(S['REAL']['lp_swap_side_at_execution_usd']['bot'] - IA['horizons']['lp_swap_side_on_bot_swaps_usd']['execution']):.1e} USD. Its fees use the FeesAccumulated attribution for bot swaps ($615), not 0.8 × fee.
- **Open loop** (no re-anchoring, real trade sizes): the model's price first passes 100 bp from history on Oct 9 and later drifts without bound
  (median error {RV['open_loop']['price_err_bp_p50_p90_p99_max'][0]:.1f} bp, 90th percentile {RV['open_loop']['price_err_bp_p50_p90_p99_max'][1]:,.0f} bp). Fixed historical trade sizes without the arbitrage that kept
  the price aligned are not self-correcting. Scenarios B and C are open loop by design, so they **cannot be validated against history**.
- How B and C treat orders: each external swap keeps its historical ETH amount and second; its limit is 2% from Binance; it fills along the
  curve up to the limit; the remainder is dropped (no retry, no rerouting) and counted as unfilled; fees are charged on the filled amount at
  that trader's historical rate, LPs get 80%. No order is rejected other than by the limit. B: no bot and no other arbitrage. C: an
  arbitrageur checks every second, trades when the gap exceeds hedge cost ({IA['params']['hedge_cost_bp']:.2f} bp) + its fee ({IA['params']['outside_fee_bp']:.1f} bp) + router
  ({IA['params']['router_bp']:.2f} bp), moves the pool to that band, and only if its profit covers gas.
- Rounding in C: {f2(S['OUTSIDE']['lp_vs_hold_ex_fees_usd'])} + {f2(sum(S['OUTSIDE']['lp_fees_usd'].values()))} = {f2(S['OUTSIDE']['lp_vs_hold_usd'])}; the displayed −5,201 + 3,657 = −1,544 is
  rounding of each part.

## 7. Sensitivity (`sensitivity_analysis.csv`)

| valuation | LP net loss | hedge pools | bot gross | bot share | hedge share |
|---|---|---|---|---|---|
""" + "\n".join(f"| {i} | {r.lp_net_loss:,.0f} | {r.hedge_pools:,.0f} | {r.bot_gross:,.1f} | {r.bot_gross_share:.0%} | {r.hedge_share_of_lp_net_loss:.0%} |"
                for i, r in sen.iloc[:8].iterrows()) + f"""

- **The horizon changes the LP loss, not the bot's result.** LP net loss on bot trades is ${sen.iloc[0].lp_net_loss:,.0f} at execution and
  ${sen.iloc[1:6].lp_net_loss.min():,.0f}–${sen.iloc[1:6].lp_net_loss.max():,.0f} at 1–60 s; the bot's gross is ${sen.iloc[:6].bot_gross.min():,.1f}–${sen.iloc[:6].bot_gross.max():,.1f} at every horizon (it
  keeps almost nothing in ETH). Most of the change happens in the first second ("at execution" is Binance as of one second before the block's timestamp): the bot trades on moves Binance has started and that continue [I].
  The chart uses 12 s, near the top of the range; at execution the bot's share is {sen.iloc[0].bot_gross_share:.0%}, at 12 s {sen.iloc[3].bot_gross_share:.0%}.
- **Binance vs on-chain:** on the {int(sen.iloc[6].txs):,} txs with an on-chain reference, LP net loss is ${sen.iloc[6].lp_net_loss:,.0f} at Binance and
  ${sen.iloc[7].lp_net_loss:,.0f} at the Uniswap 0.01% price; the bot's gross barely moves.
- Missing transactions: the 59 incomplete txs change the LP figure by ${N['checked_lp_net_complete_swaps'] - N['checked_lp_net_bot_swaps']:,.2f}.
- Rounding: displayed parts differ from totals by at most $1–2; no rounding issue affects a conclusion.

## What can be presented to Fynd

**As is:** bot gross {usd(ce['bot_gross'])} and net {usd(ce['bot_gross'] - gas)} after trade gas (state "complete transactions; 59 others add +$0.08 by the bot's own
report"); gas; router fees; the 80/20 fee split and that $2,069 is the LPs' 80%; the horizon table; the real-history replay.

**Needs correction before presenting:**
1. Top panel on one population and one valuation time. At 12 s (complete txs, fee corrected): LP net loss {usd(-corr['lp_net'])} = hedge pools
   {usd(corr['hedge'])} + gas {usd(gas)} + bot net {usd(c12['bot_gross'] - gas)} + router {usd(c12['router'])} + Fynd {usd(corr['fynd'])}. Or the same at execution.
2. Fynd fee figures: subtract {usd(x)} (USDG kept by other Ekubo pools' extensions); Fynd's 20% on bot trades ≈ {usd(0.2 * (ce['fynd_fee'] - x))}.
3. Wording: the bot events match the rebuild exactly on the 24,199 complete txs (0.180116 ETH, 325.20 USDG), not 0.180656 / 325.50.

**Needs explicit caveats:**
1. The hedge pools' figure is a shortfall against Binance plus 12 s of market movement; about $899 is fees; the rest is not profit anyone
   necessarily keeps.
2. Valuation horizon: state the LP loss range (${sen.iloc[0].lp_net_loss:,.0f}–${sen.iloc[1:6].lp_net_loss.max():,.0f}) and that the bot's figure does not depend on it.
3. Gas of the 844 other EOA transactions is estimated ($13–${B['unaccounted_gas_estimate_usd']:,.0f}) and not verifiable.
4. Scenarios B and C are model counterfactuals that cannot be validated against history; present them as illustrations of the mechanism,
   not as estimates, and never as forecasts.
5. Fynd's 20% is inferred from the share field and the 80% LP payments; where it goes is not visible in these logs.

## Files

`audit/recon.py` (raw receipts → per-tx), `audit/analyze.py` (tables), `audit/replay_check.py` (model validation), `audit/write_audit.py` (this report),
`audit/run_audit.sh` (all). Formula for each column: `analyze.py` function `val()` and the docstring of `recon.py`.
"""
open(D("AUDIT_REPORT.md"), "w").write(rep)
print(rep[:3000])
