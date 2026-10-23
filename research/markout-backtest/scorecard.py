"""
Three-sided scorecard for a pool and its competitor, from markout_horizons.py and backtest.py outputs.

  LPs      : net APR = (fees + net markout at --h seconds) / TVL, annualised; today vs each fee rule (test period)
  Routers  : fee paid by benign sources (those whose flow left LPs better off in the fit period), today vs rule
  Attract  : net APR of this pool minus net APR of the competing pool (today)

TVL is today's pool reserve from GeckoTerminal (history is not available on the free API), so APRs are indicative.

  python3 scorecard.py --pool-name "USDC/WETH 0.05%" --pool 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640 \
      --markouts results_markout_usdc_weth.json --comp-name "USDC/WETH 0.3%" --comp-pool 0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8 \
      --comp-markouts results_markout_usdc_weth_30bp.json --backtest results_eth_usdc_5bp.json --h 60 \
      --out-json results_scorecard_eth.json --png charts_flow/F5_scorecard_eth.png
"""
import argparse, json
import requests
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--pool-name", required=True); ap.add_argument("--pool", required=True); ap.add_argument("--markouts", required=True)
ap.add_argument("--comp-name", required=True); ap.add_argument("--comp-pool", required=True); ap.add_argument("--comp-markouts", required=True)
ap.add_argument("--backtest", default=""); ap.add_argument("--h", type=int, default=60)
ap.add_argument("--lp-fee-share", type=float, default=1.0, help="share of fees LPs keep after the protocol fee")
ap.add_argument("--comp-lp-fee-share", type=float, default=1.0)
ap.add_argument("--out-json", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()


def tvl(addr):
    return float(requests.get(f"https://api.geckoterminal.com/api/v2/networks/eth/pools/{addr}", timeout=60).json()["data"]["attributes"]["reserve_in_usd"])


def today(path, tv, share):
    r = json.load(open(path))
    days = 90.0
    fees = share * sum(d["fees"] for d in r["sides"].values())          # LP share of fees, after protocol fee
    net = sum(d["markout"][str(a.h)]["net"] for d in r["sides"].values())
    return {"fees": fees, "net_markout": net, "lp_net": fees + net, "tvl": tv, "days": days,
            "gross_apr": fees / tv * 365 / days * 100, "net_apr": (fees + net) / tv * 365 / days * 100, "fee_bp": r["fee_bp"]}


tv, tvc = tvl(a.pool), tvl(a.comp_pool)
me, comp = today(a.markouts, tv, a.lp_fee_share), today(a.comp_markouts, tvc, a.comp_lp_fee_share)
out = {"lp_fee_share": a.lp_fee_share, "comp_lp_fee_share": a.comp_lp_fee_share, "pool": a.pool_name, "competitor": a.comp_name, "h_s": a.h, "today": me, "competitor_today": comp,
       "net_apr_gap_vs_competitor_pp": me["net_apr"] - comp["net_apr"], "rules": {}}

if a.backtest:
    bt = json.load(open(a.backtest))
    for e, block in bt.items():
        cfg = block["_config"]; days = cfg["test_days"]
        base_t = block["vanilla"]["test"]
        out["rules"][e] = {}
        for name, v in block.items():
            if name.startswith("_"):
                continue
            t = v["test"]
            benign_fee = None
            if name == "tiered":
                benign_fee = v["params"]["benign_fee"] * 1e4
            elif name in ("vanilla",) or name.startswith("flat_"):
                benign_fee = (v["params"].get("fee") or v["params"].get("fee_test")) * 1e4
            out["rules"][e][name] = {"lp_profit_test": t["lp_pnl"], "edge_vs_vanilla": t["edge_vs_vanilla"],
                                     "edge_ci90": t["edge_vs_vanilla_ci90"], "net_apr": t["lp_pnl"] / tv * 365 / days * 100,
                                     "net_apr_vanilla": base_t["lp_pnl"] / tv * 365 / days * 100,
                                     "avg_fee_bps": t["avg_fee_bps"], "benign_fee_bps": benign_fee,
                                     "volume_kept_pct": t["volume_kept_pct"]}
json.dump(out, open(a.out_json, "w"), indent=2)

print(f"{a.pool_name} (TVL ${tv / 1e6:,.1f}M now) vs {a.comp_name} (TVL ${tvc / 1e6:,.1f}M), markout at {a.h}s, last 90 days")
for lab, d in ((a.pool_name, me), (a.comp_name, comp)):
    print(f"  {lab:18s} fees ${d['fees'] / 1e6:,.2f}M  markout ${d['net_markout'] / 1e6:+,.2f}M  LP net ${d['lp_net'] / 1e6:+,.2f}M  "
          f"gross APR {d['gross_apr']:5.1f}%  net APR {d['net_apr']:+5.1f}%")
print(f"  net APR gap: {out['net_apr_gap_vs_competitor_pp']:+.1f} percentage points")
for e, rules in out["rules"].items():
    print(f"  elasticity {e}, test period:")
    for n, v in rules.items():
        bf = "" if v["benign_fee_bps"] is None else f" · benign sources pay {v['benign_fee_bps']:.2f} bp"
        print(f"    {n:18s} LP {v['lp_profit_test'] / 1e3:>+8,.0f}k  vs vanilla {v['edge_vs_vanilla'] / 1e3:>+7,.0f}k "
              f"[{v['edge_ci90'][0] / 1e3:+,.0f}, {v['edge_ci90'][1] / 1e3:+,.0f}]  net APR {v['net_apr']:+5.2f}%  avg fee {v['avg_fee_bps']:.2f} bp"
              f" · vol kept {v['volume_kept_pct']:.0f}%{bf}")
