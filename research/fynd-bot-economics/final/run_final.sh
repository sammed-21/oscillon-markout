#!/bin/sh
# Rebuild everything in final/ from data already fetched. Reads ../out and ../../markout-backtest; writes only into final/.
# Network fetches (slow, rate-limited) are separate: fetch_txs.py (external receipts), final/fetch_wallet_transfers.py,
# final/extension_check.py; hedge_legs.py reads v3 protocol fee settings at the current block.
set -e
cd "$(dirname "$0")/.."
M=../markout-backtest; D=$M/data_swaps
FY="$D/eth_usdg_ekubo_robinhood_to1108.csv $D/eth_usdg_ekubo_robinhood_nov9_11.csv $D/eth_usdg_ekubo_robinhood_nov11_13.csv"
UNI="$D/weth_usdg_1bp_robinhood_oct02_15.csv $D/weth_usdg_1bp_robinhood.csv $D/weth_usdg_1bp_robinhood_oct22_nov12.csv"
KL="$M/klines_eth_1s $M/klines_eth_1s_lp data/klines_nov13"
python3 final/hedge_legs.py --txs data/bot_txs.jsonl --meta data/meta.json --T out/_T.pkl --out final/data/hedge_legs.csv
python3 final/fee_split_all.py --external final/data/external_txs.jsonl --T out/_T.pkl --fynd-pool $FY \
  --fees-acc $D/eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv --lp-swaps $M/results_lp_fynd_split_swaps.csv --out final/data/fee_split_all
python3 final/threshold.py --legs final/data/hedge_legs.csv --fynd-pool $FY --uni $UNI --lp-swaps $M/results_lp_fynd_split_swaps.csv \
  --klines $KL --out final/data/threshold.json
python3 final/changepoint.py --compare-daily $M/results_pool_compare_daily.csv --lp-swaps $M/results_lp_fynd_split_swaps.csv --fynd-pool $FY \
  --positions $M/results_lp_fynd_positions.csv --legs final/data/hedge_legs.csv --T out/_T.pkl --klines $KL --split 2026-10-22 \
  --out final/data/changepoint_daily.csv
python3 final/hedge_routes.py --legs final/data/hedge_legs.csv --T out/_T.pkl --uni $UNI --klines $KL --lp-swaps $M/results_lp_fynd_split_swaps.csv \
  --events $D/eth_usdg_ekubo_robinhood_lp_to1113_events.csv --out final
python3 final/combo_sim.py --lp $M --out final/data/combo_sim.csv
python3 final/reconcile.py --root . --lp $M --out final
python3 final/write_final.py --root . --lp $M
python3 final/il_attribution.py --root . --lp $M --out final/data/il_attribution.json > final/data/il_attribution.log
python3 final/write_il_note.py --root . --lp $M > /dev/null
python3 final/chart_il_vs_bot.py --root . --lp $M --png final/il_vs_bot_capture.png
python3 -m pytest tests -q
