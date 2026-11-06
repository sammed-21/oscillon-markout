"""
Who trades against LPs, and what it costs them, for one ETH/stable pool: arbitrage vs other flow, per swap and per wallet.

Per swap (token0 = ETH in both Robinhood pools; reference = Binance ETH/USDC 1 s, stable taken as $1):
  gap_bp      pool price just before the swap vs Binance at the block (pre-swap price = previous swap's post price)
  arbitrage   the swap moves the pool toward Binance AND |gap| exceeds the fee it paid: decided from the state the
              trader saw, not from how the trade turned out
  markout_h   LP value change, fee excluded, valued at Binance h seconds later (negative = trade hurt LPs)
  lp_pnl      fee + markout_12
Per wallet (tx signer when the file has it, else the contract that called the pool):
  arbitrage bot  >= 50% of its swaps are arbitrage and >= 20 swaps
  toxic          not a bot, and markout_12 per $ worse than minus the fee it paid (LPs lose on it after fees)
  genuine        the rest: fees cover what it took
Wallet classes use the whole window (after the fact); --persistence also labels wallets on the first half and scores
them on the second, which is the honest test of whether a class could be priced in advance.

  python3 flow_classify.py --swaps data_swaps/eth_usdg_ekubo_robinhood.csv --fee-mode columns --name "Fynd AMM ETH/USDG (Ekubo)" \
      --tvl 23906 --end 2026-10-29 --out-prefix results_flow_fynd
  python3 flow_classify.py --swaps data_swaps/weth_usdg_1bp_robinhood.csv --fee-mode fixed --fee-bp 1 --lp-fee-share 0.75 \
      --name "Uniswap v3 USDG/WETH 0.01%" --tvl 12818600 --out-prefix results_flow_uni_usdg
"""
import argparse, glob, io, json, os, zipfile
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--klines", default="klines_eth_1s")
ap.add_argument("--fee-mode", choices=["fixed", "columns"], required=True,
                help="fixed: pool fee taken from the input amount (Uniswap); columns: fee0/fee1 per swap (Ekubo extension)")
ap.add_argument("--fee-bp", type=float, default=0.0); ap.add_argument("--lp-fee-share", type=float, default=1.0)
ap.add_argument("--dec0", type=int, default=18); ap.add_argument("--dec1", type=int, default=6)
ap.add_argument("--name", required=True); ap.add_argument("--tvl", type=float, default=0.0, help="USD, today's (no history)")
ap.add_argument("--start", default=""); ap.add_argument("--end", default="", help="exclusive, UTC date")
ap.add_argument("--max-dev-bp", type=float, default=100.0); ap.add_argument("--persistence", action="store_true")
ap.add_argument("--out-prefix", required=True)
a = ap.parse_args()
H = [0, 12, 60, 300]

frames = []
for p in sorted(glob.glob(os.path.join(a.klines, "*.zip"))):
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            frames.append(pd.read_csv(io.BytesIO(z.read(n)), header=None, usecols=[0, 4]))
k = pd.concat(frames)
t = k[0].astype("int64").values
ref = pd.DataFrame({"ts": np.where(t > 1e14, t // 10**6, t // 10**3) + 1, "mid": k[4].astype(float).values}) \
    .drop_duplicates("ts").sort_values("ts")

sw = pd.read_csv(a.swaps).sort_values(["block", "log_index"]).reset_index(drop=True)
if "price" not in sw:                                           # Uniswap: sqrtPriceX96 after the swap
    sw["price"] = (sw.sqrtPriceX96.astype(float) / 2**96) ** 2 * 10 ** (a.dec0 - a.dec1)
sw["pre"] = sw.price.shift(1)
t0 = pd.Timestamp(a.start, tz="UTC").timestamp() if a.start else 0
t1 = pd.Timestamp(a.end, tz="UTC").timestamp() if a.end else ref.ts.max() - 3600
sw = sw[(sw.ts >= t0) & (sw.ts < t1) & sw.pre.notna()].reset_index(drop=True)
wallet = sw.tx_from if "tx_from" in sw else sw.sender
sw["wallet"] = wallet.str.lower()

b, q = sw.amount0.values, sw.amount1.values
p0 = pd.merge_asof(pd.DataFrame({"ts": sw.ts - 1}), ref, on="ts")["mid"].values
if a.fee_mode == "fixed":
    f = a.fee_bp / 1e4
    b_net, q_net = np.where(b > 0, b * (1 - f), b), np.where(q > 0, q * (1 - f), q)
    fee = np.abs(np.where(b > 0, b * p0 * f, q * f)) * a.lp_fee_share
else:                                                           # Core deltas exclude the extension's fee
    b_net, q_net = b, q
    fee = sw.fee0.values * p0 + sw.fee1.values
notional = np.abs(b) * p0
sw["notional"], sw["fee"], sw["fee_bp"] = notional, fee, fee / notional * 1e4
for h in H:
    ph = p0 if h == 0 else pd.merge_asof(pd.DataFrame({"ts": sw.ts + h}), ref, on="ts")["mid"].values
    sw[f"mk_{h}"] = b_net * ph + q_net
sw["gap_bp"] = (sw.pre / p0 - 1) * 1e4
buys_eth = b < 0
sw["toward"] = np.where(buys_eth, sw.gap_bp < 0, sw.gap_bp > 0)
sw["arb"] = sw.toward & (sw.gap_bp.abs() > sw.fee_bp)
sw["flagged"] = np.abs(np.abs(q / b) / p0 - 1) * 1e4 > a.max_dev_bp
sw["lp_pnl"] = sw.fee + sw.mk_12
d = sw[~sw.flagged]
days = (d.ts.max() - d.ts.min()) / 86400


def summary(x):
    v = x.notional.sum()
    return {"swaps": int(len(x)), "volume": float(v), "fees": float(x.fee.sum()), "fee_bp": float(x.fee.sum() / v * 1e4),
            **{f"markout_{h}": float(x[f"mk_{h}"].sum()) for h in H}, "markout_12_bp": float(x.mk_12.sum() / v * 1e4),
            "lp_pnl": float(x.lp_pnl.sum())}


def wallets(x):
    g = x.groupby("wallet").agg(swaps=("ts", "size"), volume=("notional", "sum"), fees=("fee", "sum"), mk12=("mk_12", "sum"),
                                mk60=("mk_60", "sum"), arb_share=("arb", "mean"), first=("ts", "min"), last=("ts", "max"))
    g["lp_pnl"] = g.fees + g.mk12
    g["mk12_bp"] = g.mk12 / g.volume * 1e4
    g["fee_bp"] = g.fees / g.volume * 1e4
    g["cls"] = np.where((g.arb_share >= 0.5) & (g.swaps >= 20), "arbitrage bot",
                        np.where(g.mk12_bp < -g.fee_bp, "toxic", "genuine"))
    return g.sort_values("lp_pnl")


g = wallets(d)

# Theoretical LVR (Milionis et al.) for concentrated liquidity, per minute: sigma^2 * L * sqrt(S) / (4 * 10^((dec0+dec1)/2)),
# sigma^2 = squared 60 s Binance log return, L = active liquidity in force (from the swap events), S = Binance price.
# Same form whichever token is the risky one; see lvr_theory_check.py.
grid = pd.date_range(pd.to_datetime(d.ts.min(), unit="s").ceil("min"), pd.to_datetime(d.ts.max(), unit="s").floor("min"), freq="min")
S = ref.set_index(pd.to_datetime(ref.ts, unit="s")).mid.reindex(grid, method="ffill")
Ls = pd.Series(sw.liquidity.values, index=pd.to_datetime(sw.ts, unit="s")).groupby(level=0).last()
L = Ls.reindex(Ls.index.union(grid)).ffill().reindex(grid)
lvr_theory = float((np.log(S).diff() ** 2 * L * np.sqrt(S) / (4 * 10 ** ((a.dec0 + a.dec1) / 2))).sum())

res = {"pool": a.name, "window": [str(pd.to_datetime(d.ts.min(), unit="s")), str(pd.to_datetime(d.ts.max(), unit="s"))],
       "days": days, "tvl_today": a.tvl, "flagged_swaps": int(sw.flagged.sum()), "all": summary(d),
       "by_swap": {"arbitrage": summary(d[d.arb]), "other": summary(d[~d.arb])},
       "by_wallet_class": {c: {**summary(d[d.wallet.isin(g.index[g.cls == c])]), "wallets": int((g.cls == c).sum())}
                           for c in ("arbitrage bot", "toxic", "genuine")},
       "share_of_loss_at_trade_time": float(d.mk_0.sum() / d.mk_12.sum()) if d.mk_12.sum() else None,
       "lvr_theory": lvr_theory,
       # fees / (fees + what arbitrage took): the share of arbitrage loss the fee gave back to LPs
       "lp_capture_rate": float(d.fee[d.arb].sum() / (d.fee[d.arb].sum() - d.mk_12[d.arb].sum()))}
if a.tvl:
    A = res["all"]
    res["apr"] = {"fees": A["fees"] / a.tvl * 365 / days, "markout_12": A["markout_12"] / a.tvl * 365 / days,
                  "lp_net": A["lp_pnl"] / a.tvl * 365 / days}
if a.persistence:
    mid = d.ts.min() + (d.ts.max() - d.ts.min()) / 2
    g1 = wallets(d[d.ts < mid])
    later = d[d.ts >= mid]
    res["persistence"] = {c: {**summary(later[later.wallet.isin(g1.index[g1.cls == c])]), "wallets": int((g1.cls == c).sum())}
                          for c in ("arbitrage bot", "toxic", "genuine")}
    res["persistence"]["new wallets"] = summary(later[~later.wallet.isin(g1.index)])

json.dump(res, open(a.out_prefix + ".json", "w"), indent=2)
g.to_csv(a.out_prefix + "_wallets.csv")
d.assign(p_binance=p0[~sw.flagged.values], cls=d.wallet.map(g.cls))[
    ["ts", "block", "tx_hash", "wallet", "cls", "amount0", "amount1", "pre", "price", "p_binance", "gap_bp", "arb",
     "notional", "fee", "fee_bp"] + [f"mk_{h}" for h in H] + ["lp_pnl"]].to_csv(a.out_prefix + "_swaps.csv", index=False)
pd.DataFrame({"t": grid, "lvr_theory": (np.log(S).diff() ** 2 * L * np.sqrt(S) / (4 * 10 ** ((a.dec0 + a.dec1) / 2))).values}) \
    .to_csv(a.out_prefix + "_lvr_minute.csv", index=False)


def line(k, s):
    return (f"  {k:16s} swaps {s['swaps']:>9,} vol ${s['volume'] / 1e6:>9,.2f}M fees ${s['fees'] / 1e3:>8,.1f}k ({s['fee_bp']:.2f} bp) "
            f"markout12 ${s['markout_12'] / 1e3:>+9,.1f}k ({s['markout_12_bp']:+.2f} bp)  LP ${s['lp_pnl'] / 1e3:>+9,.1f}k")


print(f"{a.name}: {res['window'][0][:16]} – {res['window'][1][:16]} ({days:.1f} d), flagged {res['flagged_swaps']:,} swaps excluded")
print(line("ALL", res["all"]))
print(f"  markout by horizon: " + "  ".join(f"{h}s ${res['all'][f'markout_{h}'] / 1e3:+,.1f}k" for h in H)
      + f"  | at trade time = {res['share_of_loss_at_trade_time']:.0%} of 12 s")
A = res["all"]
print(f"  theoretical LVR ${lvr_theory / 1e3:,.1f}k | measured loss at 12 s = {-A['markout_12'] / lvr_theory:.2f}x LVR | "
      f"fees = {A['fees'] / lvr_theory:.2f}x LVR | capture rate on arbitrage {res['lp_capture_rate']:.0%}")
print(" by swap:"); [print(line(k, s)) for k, s in res["by_swap"].items()]
print(" by wallet class (whole window):")
for k, s in res["by_wallet_class"].items():
    print(line(f"{k} ({s['wallets']})", s))
if a.tvl:
    print(f"  per year on today's TVL ${a.tvl:,.0f}: fees {res['apr']['fees']:+.1%}, markout {res['apr']['markout_12']:+.1%}, "
          f"LP net {res['apr']['lp_net']:+.1%}")
if a.persistence:
    print(" persistence (labelled on first half, scored on second):")
    for k, s in res["persistence"].items():
        print(line(f"{k} ({s.get('wallets', '-')})", s))
print(" top wallets by LP loss:")
for w, r in g.head(8).iterrows():
    print(f"  {w[:12]}… {r.cls:13s} swaps {r.swaps:>7,} vol ${r.volume / 1e6:>8,.2f}M arb {r.arb_share:>4.0%} "
          f"markout {r.mk12_bp:+6.2f} bp fee {r.fee_bp:.2f} bp LP ${r.lp_pnl / 1e3:+,.1f}k")
