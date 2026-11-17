#!/bin/sh
# Rebuild every output from the fetched data (data/). Files in ../markout-backtest are only read.
# Fetching (network, slow, rate-limited): fetch_txs.py, fetch_meta.py, fetch_contract_logs.py, fetch_uni_mint_burn.py.
set -e
M=../markout-backtest
D=$M/data_swaps
./run_build.sh
python3 write_outputs.py --out out --lp-results $M/results_lp_fynd.json --lp-split $M/results_lp_fynd_split.json \
  --lp-swaps $M/results_lp_fynd_split_swaps.csv --fees-acc $D/eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv \
  --contract-logs data/bot_contract_logs.json --other-pool-txs data/bot_other_pool_txs.jsonl \
  --klines $M/klines_eth_1s $M/klines_eth_1s_lp data/klines_nov13 --last-tx data/last_bot_fynd_tx.json > out/write_outputs.log
python3 validate_pool_model.py --events $D/eth_usdg_ekubo_robinhood_lp_to1113_events.csv \
  --swaps $D/eth_usdg_ekubo_robinhood_to1108.csv $D/eth_usdg_ekubo_robinhood_nov9_11.csv $D/eth_usdg_ekubo_robinhood_nov11_13.csv --out out/check_pool_model.csv
python3 policy_sim.py --out out --lp-swaps $M/results_lp_fynd_split_swaps.csv --klines $M/klines_eth_1s $M/klines_eth_1s_lp data/klines_nov13 \
  --events $D/eth_usdg_ekubo_robinhood_lp_to1113_events.csv > out/policy_sim.log
python3 uni_audit.py --uni $D/weth_usdg_1bp_robinhood_oct22_nov12.csv --mint-burn data/uni_1bp_mint_burn_oct22_nov12.csv \
  --compare-daily $M/results_pool_compare_daily.csv --compare $M/results_pool_compare.json --lp-swaps $M/results_lp_fynd_split_swaps.csv \
  --klines $M/klines_eth_1s $M/klines_eth_1s_lp --out out/uniswap_comparison_audit.json > out/uni_audit.log
python3 hand_checks.py --txs data/bot_txs.jsonl --meta data/meta.json --out out
python3 chart_value_split.py --out out --png out/value_split.png
python3 build_report.py --out out --compare $M/results_pool_compare.json
python3 -m pytest tests -q
