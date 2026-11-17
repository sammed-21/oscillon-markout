"""
Is the 80/20 split of Fynd's fee (LPs / protocol) true for every payer, not only the bot?

Observed fee per swap:
  bot swaps            from the rebuilt bot transactions (USDG-paid: observed transfer; ETH-paid: bot event)
  external swaps       net USDG transferred into Ekubo Core in the tx minus the Fynd swap's USDG amount. External
                       traders are charged on their OUTPUT: a trader receiving USDG gets less than the pool paid out
                       (observed); a trader paying USDG in pays exactly the swap amount. So this measures the fee of
                       every external swap that receives USDG; the fee of external swaps that receive ETH is native ETH
                       and not observable. Used only when the tx has no other Ekubo swap or position change.
Test: each FeesAccumulated (FA) pays LPs for the swaps since the previous FA. For every FA whose USDG-paying swaps all
have an observed fee (bot or external), compare FA's USDG amount with 0.8 x their fees. Same for the ETH side where
every ETH-paying swap is a bot swap.

  python3 final/fee_split_all.py --external final/data/external_txs.jsonl --T out/_T.pkl --fynd-pool <files> \
      --fees-acc <FA file> --lp-swaps ../markout-backtest/results_lp_fynd_split_swaps.csv --out final/data/fee_split_all
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from decode import CORE, USDG, FYND_POOL, T_TRANSFER, s128  # noqa: E402

UPD = "0x704b3ab4"     # Ekubo PositionUpdated topic prefix
ap = argparse.ArgumentParser()
ap.add_argument("--external", required=True); ap.add_argument("--T", required=True); ap.add_argument("--fynd-pool", nargs="+", required=True)
ap.add_argument("--fees-acc", required=True); ap.add_argument("--lp-swaps", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()

ext = []
for line in open(a.external):
    rc = json.loads(line)["receipt"]
    fy, other_core_swap, pos_upd, usdg_net = [], False, False, 0
    for l in rc["logs"]:
        ad, t, d = l["address"].lower(), l["topics"], l["data"][2:]
        if ad == CORE and not t and len(d) == 232:
            if d[40:104] == FYND_POOL:
                fy.append((int(l["logIndex"], 16), s128(d[104:136]), s128(d[136:168])))
            else:
                other_core_swap = True
        elif ad == CORE and t and t[0].startswith(UPD):
            pos_upd = True
        elif ad == USDG and t and t[0] == T_TRANSFER and len(t) == 3:
            amt = int(d[:64], 16)
            if "0x" + t[2][-40:] == CORE:
                usdg_net += amt
            if "0x" + t[1][-40:] == CORE:
                usdg_net -= amt
    clean = len(fy) == 1 and not other_core_swap and not pos_upd and int(rc["status"], 16) == 1
    for li, a0, a1 in fy:
        ext.append({"tx_hash": rc["transactionHash"], "block": int(rc["blockNumber"], 16), "log_index": li, "eth_raw": a0, "usdg_raw": a1,
                    "clean": clean, "fee_usdg_raw": (usdg_net - a1) if clean else np.nan})
X = pd.DataFrame(ext)
T = pd.read_pickle(a.T)
FP = pd.concat([pd.read_csv(f, usecols=["block", "log_index", "tx_hash", "tx_from"]) for f in a.fynd_pool]).drop_duplicates(["block", "log_index"]).sort_values(["block", "log_index"])
SW = pd.read_csv(a.lp_swaps)[["block", "log_index", "bot_wallet", "usdg_to_pool", "eth_to_pool", "volume_usd", "fee_usd"]]
FP = FP.merge(SW, on=["block", "log_index"], how="left")
FP["pays_usdg"] = FP.usdg_to_pool > 0
# observed fee per swap
bot = T.set_index("hash")
FP["fee_usdg_obs"] = np.nan; FP["fee_eth_obs"] = np.nan
bmask = FP.tx_hash.isin(bot.index)
bt = bot.loc[FP.loc[bmask, "tx_hash"]]
FP.loc[bmask, "fee_usdg_obs"] = np.where(bt.fee_token.values == "USDG", bt.fee_units.values, 0.0)
FP.loc[bmask, "fee_eth_obs"] = np.where(bt.fee_token.values == "ETH", bt.fee_units.values, 0.0)
xm = FP.merge(X[["block", "log_index", "fee_usdg_raw", "clean"]], on=["block", "log_index"], how="left")
em = (~bmask.values) & xm.fee_usdg_raw.notna().values
FP.loc[em, "fee_usdg_obs"] = xm.loc[em, "fee_usdg_raw"].values / 1e6
FA = pd.read_csv(a.fees_acc).sort_values(["block", "log_index"]).reset_index(drop=True)
k_sw = FP.block.values * 1e6 + FP.log_index.values
FP["fa_idx"] = np.searchsorted(FA.block.values * 1e6 + FA.log_index.values, k_sw, side="left")
rows = []
for i, g in FP.groupby("fa_idx"):
    if i >= len(FA):
        continue
    usdg_known = g.fee_usdg_obs.notna().all()
    has_ext_usdg = ((~g.tx_hash.isin(bot.index)) & (g.fee_usdg_obs > 0)).any()  # includes a positive external USDG fee
    eth_known = g.tx_hash.isin(bot.index).all()
    rows.append({"fa_idx": i, "fa_block": FA.block[i], "fa_usdg": FA.amount1[i], "fa_eth": FA.amount0[i], "swaps": len(g),
                 "usdg_known": usdg_known, "includes_external_usdg_fee": has_ext_usdg,
                 "fee_usdg": g.fee_usdg_obs.sum() if usdg_known else np.nan,
                 "eth_known": eth_known, "fee_eth": g.fee_eth_obs.fillna(0).sum() if eth_known else np.nan})
C = pd.DataFrame(rows)
C["usdg_ok"] = (C.fa_usdg - 0.8 * C.fee_usdg).abs() <= 2e-6 + 1e-9 * C.fee_usdg
C["usdg_share"] = C.fa_usdg / C.fee_usdg.where(C.fee_usdg > 1e-4)
C.to_csv(a.out + ".csv", index=False)
ext = FP[~FP.tx_hash.isin(bot.index)]
ex_out = ext[(ext.usdg_to_pool < 0) & ext.fee_usdg_obs.notna()]          # external swaps receiving USDG: fee observed
ex_in = ext[(ext.usdg_to_pool > 0) & ext.fee_usdg_obs.notna()]
res = {"external_swaps": int(len(ext)), "external_swaps_fee_observed_in_usdg": int(len(ex_out)),
       "external_usdg_input_swaps_checked": int(len(ex_in)), "external_usdg_input_fee_max_usdg": float(ex_in.fee_usdg_obs.max()),
       "external_output_fee_bp_median": float((1e4 * ex_out.fee_usdg_obs / -ex_out.usdg_to_pool).median()),
       "external_output_fee_bp_volume_weighted": float(1e4 * ex_out.fee_usdg_obs.sum() / -ex_out.usdg_to_pool.sum()),
       "external_output_fee_usd_observed": float(ex_out.fee_usdg_obs.sum()),
       "fa_intervals_usdg_checkable": int(C.usdg_known.sum()),
       "fa_intervals_usdg_checkable_with_external_fees": int((C.usdg_known & C.includes_external_usdg_fee).sum()),
       "match_80pct_with_external_fees": int((C.usdg_known & C.includes_external_usdg_fee & C.usdg_ok).sum()),
       "match_80pct_all_checkable": int((C.usdg_known & C.usdg_ok).sum()),
       "lp_share_median_with_external_fees": float(C[C.usdg_known & C.includes_external_usdg_fee].usdg_share.median()),
       "external_fee_usd_with_80pct_verified": float(sum(FP.loc[(FP.fa_idx == i) & ~FP.tx_hash.isin(bot.index), "fee_usdg_obs"].sum()
                                                       for i in C.fa_idx[C.usdg_known & C.includes_external_usdg_fee & C.usdg_ok]))}
json.dump(res, open(a.out + ".json", "w"), indent=1)
print(json.dumps(res, indent=1))
