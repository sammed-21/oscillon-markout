#!/bin/sh
# Rebuild every output from the fetched data. Inputs in ../markout-backtest are only read.
set -e
M=../markout-backtest
python3 build_economics.py --txs data/bot_txs.jsonl --meta data/meta.json --contract-logs data/bot_contract_logs.json \
  --lp-swaps $M/results_lp_fynd_split_swaps.csv \
  --fynd-pool $M/data_swaps/eth_usdg_ekubo_robinhood_to1108.csv $M/data_swaps/eth_usdg_ekubo_robinhood_nov9_11.csv $M/data_swaps/eth_usdg_ekubo_robinhood_nov11_13.csv \
  --fees-acc $M/data_swaps/eth_usdg_ekubo_robinhood_lp_to1113_fees_accumulated.csv \
  --uni $M/data_swaps/weth_usdg_1bp_robinhood_oct02_15.csv $M/data_swaps/weth_usdg_1bp_robinhood.csv $M/data_swaps/weth_usdg_1bp_robinhood_oct22_nov12.csv \
  --klines $M/klines_eth_1s $M/klines_eth_1s_lp data/klines_nov13 --out out
