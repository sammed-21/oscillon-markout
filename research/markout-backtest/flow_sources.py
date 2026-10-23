"""
Who causes LP losses? Net LP markout by flow source, where the source is the contract that called the pool
(the Swap event's `sender`: a router, aggregator, solver settlement or a bot contract). Flagged off-market swaps are
excluded. Top sources are named from a built-in list of public routers and, for the rest, Etherscan's verified
contract name (ETHERSCAN_API_KEY from the env file, read-only).

  python3 flow_sources.py --swaps data_swaps/usdc_weth_5bp.csv --markouts data_swaps/usdc_weth_5bp_markouts.csv \
      --name "USDC/WETH 0.05%" --h 12 --out-json results_flow_sources_weth.json --png charts_flow/F3_sources_weth.png
"""
import argparse, json, os, re, time
import numpy as np
import pandas as pd
import requests

KNOWN = {
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap Universal Router", "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router v4",
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "Uniswap Universal Router (old)", "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap SwapRouter02",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap SwapRouter", "0x111111125421ca6dc452d289314280a0f8842a65": "1inch Router v6",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch Router v5", "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Exchange Proxy",
    "0x9008d19f58aabd9ed0d60971565aa8510560ab41": "CoW Protocol settlement", "0x6a000f20005980200259b80c5102003040001068": "ParaSwap Augustus v6",
    "0xdef171fe48cf0115b1d80b88dc8eab59176fee57": "ParaSwap Augustus v5", "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "KyberSwap router",
    "0xcf5540fffcdc3d510b18bfca6d2b9987b0772559": "Odos router v2", "0x881d40237659c251811cec9c364ef91dc08d300c": "MetaMask swap router",
    "0xbbbbbbb520d69a9775e85b458c58c648259fad5f": "Bebop settlement", "0x0000000000001ff3684f28c67538d4d072c22734": "0x Settler",
}

ap = argparse.ArgumentParser()
ap.add_argument("--swaps", required=True); ap.add_argument("--markouts", required=True); ap.add_argument("--name", required=True)
ap.add_argument("--h", type=int, default=12); ap.add_argument("--top", type=int, default=20)
ap.add_argument("--env", default="../../../research-backtest/.env")
ap.add_argument("--out-json", required=True); ap.add_argument("--png", required=True)
a = ap.parse_args()
os.makedirs(os.path.dirname(a.png), exist_ok=True)
env = {m.group(1): m.group(2).strip('"') for line in open(a.env) if (m := re.match(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line))}

sw = pd.read_csv(a.swaps, usecols=["sender", "tx_hash", "block", "log_index"]).sort_values(["block", "log_index"]).reset_index(drop=True)
mk = pd.read_csv(a.markouts)
d = pd.concat([sw, mk], axis=1)
d = d[~d.flagged.astype(bool)]
d["sender"] = d.sender.str.lower()
g = d.groupby("sender").agg(swaps=("notional", "size"), volume=("notional", "sum"), fees=("fee", "sum"),
                            net=(f"mk_{a.h}", "sum"), net_60=("mk_60", "sum")).sort_values("net")
g["lp_profit"] = g.fees + g.net
g["net_bp"] = g.net / g.volume * 1e4
tot_net, tot_vol = g.net.sum(), g.volume.sum()
losers = g[g.net < 0]
loss_total = losers.net.sum()
conc = {n: float(losers.net.head(n).sum() / loss_total) for n in (1, 5, 20)}
vol_share = {n: float(losers.volume.head(n).sum() / tot_vol) for n in (5, 20)}


def name(addr: str) -> str:
    if addr in KNOWN:
        return KNOWN[addr]
    key = env.get("ETHERSCAN_API_KEY")
    if key:
        try:
            r = requests.get("https://api.etherscan.io/v2/api", timeout=30, params={"chainid": 1, "module": "contract",
                             "action": "getsourcecode", "address": addr, "apikey": key}).json()
            time.sleep(0.25)
            n = (r.get("result") or [{}])[0].get("ContractName") or ""
            return f"{n} (Etherscan name)" if n else "no verified source (likely bot)"
        except Exception:
            pass
    return "unknown"


rows = []
for addr, x in pd.concat([g.head(a.top), g.tail(5)]).iterrows():
    rows.append({"sender": addr, "label": name(addr), **{k: float(v) for k, v in x.items()}})
out = {"pool": a.name, "horizon_s": a.h, "sources": int(len(g)), "total_net_markout": float(tot_net), "total_volume": float(tot_vol),
       "total_fees": float(g.fees.sum()), "loss_from_losing_sources": float(loss_total),
       "share_of_loss_top1": conc[1], "share_of_loss_top5": conc[5], "share_of_loss_top20": conc[20],
       "volume_share_top5_losers": vol_share[5], "volume_share_top20_losers": vol_share[20], "top": rows}
json.dump(out, open(a.out_json, "w"), indent=2)

print(f"{a.name}: {len(g):,} sources · net LP markout at {a.h}s ${tot_net / 1e6:+,.2f}M on ${tot_vol / 1e9:,.2f}B, fees ${g.fees.sum() / 1e6:,.2f}M")
print(f"  losses from loss-making sources ${loss_total / 1e6:,.2f}M: top 1 {conc[1] * 100:.0f}%, top 5 {conc[5] * 100:.0f}%, "
      f"top 20 {conc[20] * 100:.0f}% (top 5 carry {vol_share[5] * 100:.0f}% of volume, top 20 {vol_share[20] * 100:.0f}%)")
for r_ in rows[:a.top]:
    print(f"  {r_['sender'][:10]}… {r_['label'][:38]:38s} swaps {r_['swaps']:>7,.0f} vol ${r_['volume'] / 1e6:>7,.0f}M "
          f"net {r_['net'] / 1e3:>+8,.0f}k ({r_['net_bp']:+6.2f} bp) fees {r_['fees'] / 1e3:>6,.0f}k LP {r_['lp_profit'] / 1e3:>+8,.0f}k")
print("  ... most LP-friendly sources:")
for r_ in rows[a.top:]:
    print(f"  {r_['sender'][:10]}… {r_['label'][:38]:38s} vol ${r_['volume'] / 1e6:>7,.0f}M net {r_['net'] / 1e3:>+8,.0f}k ({r_['net_bp']:+6.2f} bp)")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": GRID, "axes.spines.top": False, "axes.spines.right": False,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID})
show = rows[:15] + rows[a.top:]
fig, ax = plt.subplots(figsize=(14, 0.42 * len(show) + 1.8))
y = np.arange(len(show))[::-1]
ax.set_axisbelow(True)
ax.barh(y, [r_["net"] / 1e3 for r_ in show], color=["#e34948" if r_["net"] < 0 else "#1baf7a" for r_ in show], height=0.65)
ax.set_yticks(y); ax.set_yticklabels([f"{r_['label'][:34]} · {r_['sender'][:8]}…" for r_ in show], fontsize=8.5)
for yy, r_ in zip(y, show):
    ax.annotate(f"${r_['volume'] / 1e6:,.0f}M vol · {r_['net_bp']:+.1f} bp", (r_["net"] / 1e3, yy), xytext=(5 if r_["net"] >= 0 else -5, 0),
                textcoords="offset points", ha="left" if r_["net"] >= 0 else "right", va="center", fontsize=8, color=INK)
ax.axvline(0, color=INK2, lw=1); ax.set_xlabel(f"Net LP markout at {a.h} s, fee excluded ($k) · below 0 = source hurt LPs")
lo, hi = ax.get_xlim(); ax.set_xlim(lo * 1.35, hi * 1.35 if hi > 0 else hi)
ax.set_title(f"{a.name}: who causes LP losses · top 5 loss-making sources = {conc[5] * 100:.0f}% of losses, top 20 = {conc[20] * 100:.0f}%",
             loc="left", fontsize=12)
fig.savefig(a.png, dpi=160, bbox_inches="tight"); print("wrote", a.png)
