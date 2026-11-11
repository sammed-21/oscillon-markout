Fynd AMM ETH/USDG on Robinhood Chain: LP net markout vs Binance, 2026-10-06 to 2026-11-05 (UTC)

Files
  Fynd_LP_report_2026-11-10.pdf                              the report (1 page of text + 2 chart pages)
  fynd_eth_usdg_swaps_2026-10-06_to_2026-11-05.csv           one row per swap, 20,326 rows
  fynd_eth_usdg_summary_2026-10-06_to_2026-11-05.csv         the report's results table, computed from the swaps file
  fynd_eth_usdg_excluded_swaps_2026-10-06_to_2026-11-05.csv  68 swaps left out, with the reason for each

Swaps file columns
  time_utc, block, tx_hash        the swap; time is the block timestamp
  sender                          transaction sender
  likely_fynd_bot                 TRUE for 0x4abfdbac0afa181338dc9c38c9c1264128c684a2 (my label, not confirmed)
  pool_eth_change                 ETH the pool received (+) or paid out (-) on the swap, fee excluded
  pool_usdg_change                USDG the pool received (+) or paid out (-), fee excluded
  pool_price_before / _after      pool price (USDG per ETH) before and after the swap
  binance_price                   Binance ETHUSDC 1 s close just before the block
  gap_to_binance_bp               (pool_price_before / binance_price - 1) x 10,000
  toward_binance_gap_gt_fee       TRUE if the swap moved the pool toward Binance and the gap was bigger than its fee
  volume_usd                      |pool_eth_change| x binance_price
  fee_usd, fee_bp                 fee paid to LPs. From the extension's FeesAccumulated events; each event pays in at the
                                  pool's next interaction, so it is split by size over the swaps since the previous event
  lp_markout_0s/12s/60s_usd       pool_eth_change x Binance price h seconds later + pool_usdg_change (negative = LPs lost)
  lp_net_markout_usd              fee_usd + lp_markout_12s_usd

Summing lp_net_markout_usd over the file gives the report's -$3,196. USDG is taken as $1.
This is markout, not position P&L or return on capital.
