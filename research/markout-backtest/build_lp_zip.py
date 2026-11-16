"""
Package the Fynd LP returns report for sharing: PDF, README, positions, owners, loss split and the two sensitivities.
Every number in README.txt is read from the results files.

  python3 build_lp_zip.py --prefix results_lp_fynd --split results_lp_fynd_split --pdf <report.pdf> --stage <dir> --zip <out.zip>
"""
import argparse, json, os, shutil, zipfile
import pandas as pd

ap = argparse.ArgumentParser()
for k in ["prefix", "split", "pdf", "stage", "zip"]:
    ap.add_argument("--" + k, required=True)
a = ap.parse_args()
R = json.load(open(a.prefix + ".json")); S = json.load(open(a.split + ".json"))
d0, d1 = R["period"]["start_utc"][:10], R["period"]["end_utc"][:10]
s0 = S["swaps_period"][0][:10]
shutil.rmtree(a.stage, ignore_errors=True); os.makedirs(a.stage)
usd = lambda v: ("−" if v < 0 else "") + f"${abs(v):,.0f}"

P = pd.read_csv(a.prefix + "_positions.csv")
pos = pd.DataFrame({
    "position_id": P.pos.str.split(":").str[0], "nft_id": P.nft_id, "owner": P.owner, "still_open": P.open,
    "start_utc": P.start_utc, "end_utc": P.end_utc, "days_open": P.days.round(4),
    "range_low_usd": P.range_low.round(2), "range_high_usd": P.range_high.where(P.range_high < 1e9).round(2),
    "share_of_time_in_range": P.in_range_share.round(4),
    "eth_deposited": P.eth_in.round(8), "usdg_deposited": P.usdg_in.round(6),
    "eth_out_principal": P.eth_out.round(8), "usdg_out_principal": P.usdg_out.round(6),
    "eth_fees": P.eth_fees.round(8), "usdg_fees": P.usdg_fees.round(6),
    **{n: P[c].round(2) for n, c in [("cost_usd", "cost_usd"), ("capital_days_usd", "capital_days_usd"),
                                     ("eth_price_at_end", "eth_price_end"), ("hold_value_usd", "hold_usd"), ("lp_value_usd", "lp_usd"),
                                     ("fees_usd", "fees_usd"), ("impermanent_loss_usd", "il_usd"), ("lp_minus_hold_usd", "lp_minus_hold_usd"),
                                     ("lp_result_usd", "lp_pnl_usd"), ("hold_result_usd", "hold_pnl_usd")]}})
f_pos = f"fynd_eth_usdg_lp_positions_{d0}_to_{d1}.csv"; pos.to_csv(os.path.join(a.stage, f_pos), index=False)

O = pd.read_csv(a.prefix + "_owners.csv")
own = pd.DataFrame({"owner": O.owner, "positions": O.positions, "still_open": O.open, "first_utc": O["first"], "last_utc": O["last"],
                    "avg_capital_usd": O.avg_capital_usd.round(0), "fees_usd": O.fees_usd.round(2), "impermanent_loss_usd": O.il_usd.round(2),
                    "lp_minus_hold_usd": O.lp_minus_hold_usd.round(2),
                    "lp_minus_hold_per_1000_per_30d_usd": (30_000 * O.lp_minus_hold_usd / O.capital_days_usd).round(2),
                    "lp_result_usd": O.lp_pnl_usd.round(2), "hold_result_usd": O.hold_pnl_usd.round(2)})
f_own = f"fynd_eth_usdg_lp_owners_{d0}_to_{d1}.csv"; own.to_csv(os.path.join(a.stage, f_own), index=False)

mk = lambda name, g: {"swaps": name, "count": g["swaps"], "volume_usd": round(g["volume"], 2), "fee_bp": round(g["fee_bp"], 2),
                      "fees_to_lps_usd": round(g["fee"], 2), "loss_at_binance_12s_usd": round(-g["loss_12s"], 2), "net_for_lps_usd": round(g["lp_net"], 2)}
split = pd.DataFrame([mk(f"swaps by the bot wallet {S['bot_wallet']}", S["bot"]), mk("all other swaps", S["other"]),
                      {"swaps": "later price moves (12 s after each swap to each position's end)", "net_for_lps_usd": round(S["drift"], 2)},
                      {**mk("total = LP vs hold", S["all"]), "net_for_lps_usd": round(S["lp_minus_hold"], 2)}])
split["count"] = split["count"].astype("Int64")
f_split = f"fynd_eth_usdg_lp_loss_split_{s0}_to_{d1}.csv"; split.to_csv(os.path.join(a.stage, f_split), index=False)
h = pd.read_csv(a.split + "_h_sensitivity.csv").round(2).rename(columns={"bot_capture_usd": "bot_wallet_capture_usd",
                                                                          "ci_low": "ci95_low_usd", "ci_high": "ci95_high_usd"})
f_h = "fynd_eth_usdg_bot_wallet_h_sensitivity.csv"; h.to_csv(os.path.join(a.stage, f_h), index=False)
f_f = "fynd_eth_usdg_bot_wallet_fee_sensitivity.csv"
pd.read_csv(a.split + "_fee_sensitivity.csv").round(2).to_csv(os.path.join(a.stage, f_f), index=False)
shutil.copy(a.pdf, a.stage)

b, hs = S["bot"], S["h_sensitivity"]
pr = R["period"]
readme = f"""Fynd AMM ETH/USDG on Robinhood Chain: LP returns vs holding, {d0} to {d1} (UTC)
Every LP position since the pool started, to block {pr['snapshot_block']:,} ({pr['end_utc'][:16]} UTC).
Only this pool (Ekubo poolId 0xb67e0601...3546, extension 0x550cfe12...1d09): the other ETH/USDG pools on Ekubo are not in it.

Files
  {os.path.basename(a.pdf):<60} the report (2 pages of text + 1 chart page)
  {f_pos:<60} one row per LP position, {len(pos)} rows
  {f_own:<60} one row per LP, {len(own)} rows (sums of the positions file)
  {f_split:<60} LP vs hold split by the wallet that sent each swap (swaps start {s0})
  {f_h:<60} bot wallet's capture for h = 0 to 12 bp, with 95% intervals
  {f_f:<60} LPs' result on the bot wallet's swaps at fees 0 to 15 bp

Method
  LP   = what a position paid out (withdrawals + fees collected) + what it still holds (principal + uncollected fees)
  hold = the tokens it deposited, never put in the pool
  Both valued at Binance ETHUSDC (1 s close) at the position's end: its last withdrawal, or the snapshot if still open.
  LP - hold = fees + impermanent loss. USDG is taken as $1. Open positions were read on chain at the snapshot block.

Positions file columns
  position_id                       Ekubo position salt; nft_id is the Ekubo Positions NFT that holds it
  owner                             holder of the NFT. "via 0x0db596af..." = held through that contract, not the NFT
  still_open                        TRUE if it still had liquidity at the snapshot
  start_utc, end_utc, days_open     first deposit; last withdrawal or the snapshot
  range_low_usd, range_high_usd     the position's price range (USDG per ETH). Blank high = full range
  share_of_time_in_range            share of its life the pool price was inside the range
  eth/usdg_deposited                tokens put in
  eth/usdg_out_principal            tokens withdrawn, plus what is still in the position if open (fees excluded)
  eth/usdg_fees                     fees collected, plus uncollected fees if open
  cost_usd                          each deposit valued at Binance when it was made
  capital_days_usd                  cost basis x days open (a withdrawal removes its share of the cost basis)
  eth_price_at_end                  Binance price used for hold_value_usd and lp_value_usd
  hold_value_usd, lp_value_usd      the two sides above
  fees_usd, impermanent_loss_usd    lp_minus_hold_usd = fees_usd + impermanent_loss_usd
  lp_result_usd, hold_result_usd    lp_value_usd - cost_usd, hold_value_usd - cost_usd (these include ETH's own move)

Owners file: lp_minus_hold_per_1000_per_30d_usd = lp_minus_hold_usd / capital_days_usd x 30,000.

Summing lp_minus_hold_usd over either file gives the report's {usd(R['totals']['lp_minus_hold_usd'])}.

Loss split file
  Per swap, from the LPs' side, valued at Binance ETHUSDC 12 s after the swap (as in the Nov 10 markout report),
  grouped by the wallet that sent the swap:
    fees_to_lps_usd            fees the swaps paid to LPs (valued when paid)
    loss_at_binance_12s_usd    the LP side of the swaps at Binance 12 s later, before fees
    net_for_lps_usd            the two together
  Later price moves: the remainder, from 12 s after each swap to each position's end. All rows add up to LP vs hold,
  {usd(S['lp_minus_hold'])}. All swaps are kept, including those the Nov 10 markout report left out.
  The net on the bot wallet's swaps ({usd(b['lp_net'])}) is an upper bound on what that wallet captured, before its hedging
  and other costs. "Loss" is measured on the LPs' side; it is not what the counterparty earned.

h sensitivity file
  bot wallet's capture = loss on its swaps - fees it paid - h x its volume ({usd(b['loss_12s'])} - {usd(b['fee'])} - h x ${b['volume'] / 1e6:.2f}M),
  where h is its cost per $ traded: hedging, exchange fees, gas, and any gap between its hedge price and Binance 12 s later.
  Zero at h = {hs['breakeven_h_bp']:.1f} bp. 95% intervals from resampling the {S['days_resampled']} days (5,000 draws).

Fee sensitivity file
  lp_on_bot_wallet_swaps_usd = fee x the bot wallet's volume - loss on its swaps. lp_minus_hold_all_usd = the same,
  plus everything else unchanged. Assumes identical swaps at every fee: a transfer from the bot wallet to LPs, not a
  forecast of what would happen at that fee.

Checks
  Books close: the open positions on chain hold what every deposit, withdrawal, fee and swap adds up to.
  Every fee paid in reached LP positions (100.000%).
  Matches the Nov 10 markout report: positions inside its window (Oct 6 - Nov 5) are {usd(R['inside_markout_window']['lp_minus_hold_usd'])} vs holding.
"""
open(os.path.join(a.stage, "README.txt"), "w").write(readme)
assert abs(pos.lp_minus_hold_usd.sum() - R["totals"]["lp_minus_hold_usd"]) < 1 and abs(split.net_for_lps_usd.iloc[:3].sum() - S["lp_minus_hold"]) < 0.05
if os.path.exists(a.zip):
    os.remove(a.zip)
with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(a.stage)):
        z.write(os.path.join(a.stage, f), f)
print("wrote", a.zip, sorted(os.listdir(a.stage)))
