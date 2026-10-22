"""
Markout backtest: vanilla vs dynamic (volatility) fee vs markout-based fee.

LP accounting follows the markout decomposition:
    LP PnL per swap = fee earned + LP markout at horizon h
where LP markout is the value of what the LP received minus what it gave,
both marked at the reference (CEX) price h seconds after the swap.

Counterfactual (first-order; see README "Limits"):
  * "Informed" swaps (trader edge at the decision horizon > historical fee)
    happen under a policy only if their edge still beats the policy fee.
  * Other swaps shrink with fee elasticity eps when the policy fee is above
    the historical fee (no extra volume is assumed when it is lower).
  * Trade sizes and the price path are unchanged.

Every policy fee is computed only from information available before the swap
(markouts are used only after they have matured). No lookahead.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import dataclass, field, asdict
from itertools import product

import numpy as np
import pandas as pd

BPS = 1e4
KEEPER_LAG_S = 12          # seconds; set with --keeper-lag (Ethereum ~12, L2s ~1-2)


# --------------------------------------------------------------------------- data
def load(swaps_csv: str, ref_csv: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """swaps.csv: ts, dir, a0, a1   |   ref.csv: ts, mid
    ts   : unix seconds (int)
    dir  : +1 trader buys token0 from the pool, -1 trader sells token0 to the pool
    a0,a1: absolute gross amounts in token units (decimals already applied)
    mid  : reference price of token0 in token1 (e.g. CEX mid)
    """
    s = pd.read_csv(swaps_csv).sort_values("ts").reset_index(drop=True)
    r = pd.read_csv(ref_csv).sort_values("ts").reset_index(drop=True)
    return s, r


def enrich(s: pd.DataFrame, r: pd.DataFrame, f0: float, horizons: list[int]) -> pd.DataFrame:
    """Attach reference prices and LP markouts at each horizon (net of the historical fee)."""
    s = s.copy()
    r = r[["ts", "mid"]].copy()
    s["ref_t"] = pd.merge_asof(s[["ts"]], r, on="ts", direction="backward")["mid"].values
    buy0 = s["dir"].values > 0
    a0, a1 = s["a0"].values.astype(float), s["a1"].values.astype(float)
    a1_net = np.where(buy0, a1 * (1 - f0), a1)          # fee was paid on the input side
    a0_net = np.where(buy0, a0, a0 * (1 - f0))
    s["notional"] = a0 * s["ref_t"].values               # token1 units
    for h in horizons:
        fut = pd.merge_asof(pd.DataFrame({"ts": s["ts"] + h}), r, on="ts", direction="backward")["mid"].values
        lp_mark = np.where(buy0, a1_net - a0 * fut, a0_net * fut - a1)
        s[f"mark_{h}"] = lp_mark                          # token1, + = LP gained
        s[f"mark_bps_{h}"] = lp_mark / s["notional"].values * BPS
    s = s.dropna(subset=["ref_t"]).reset_index(drop=True)
    s["day"] = pd.to_datetime(s["ts"], unit="s").dt.floor("D")
    return s


def realized_vol_bps(r: pd.DataFrame, ts: np.ndarray, window: int) -> np.ndarray:
    """sqrt(sum of squared log returns) of the reference over the `window` seconds before each ts, in bps."""
    rt = r["ts"].values
    lr = np.diff(np.log(r["mid"].values), prepend=np.log(r["mid"].values[0]))
    csum = np.cumsum(lr ** 2)
    hi = np.searchsorted(rt, ts, side="left") - 1          # strictly before ts
    lo = np.searchsorted(rt, ts - window, side="left") - 1
    hi_v = np.where(hi >= 0, csum[np.clip(hi, 0, None)], 0.0)
    lo_v = np.where(lo >= 0, csum[np.clip(lo, 0, None)], 0.0)
    return np.sqrt(np.maximum(hi_v - lo_v, 0.0)) * BPS


# --------------------------------------------------------------------------- policies
@dataclass
class Policy:
    name: str
    kind: str                     # "vanilla" | "vol" | "markout"
    params: dict = field(default_factory=dict)


def fees_for(policy: Policy, s: pd.DataFrame, r: pd.DataFrame, f0: float,
             fmin: float, fmax: float, h_dec: int, eps: float) -> np.ndarray:
    """Per-swap fee under `policy`, plus kept-weight bookkeeping for markout feedback."""
    n = len(s)
    if policy.kind == "vanilla":
        return np.full(n, policy.params.get("fee", f0))
    if policy.kind == "vol":
        p = policy.params
        vol = realized_vol_bps(r, s["ts"].values, p["window"])
        return np.clip(p["base"] + p["a"] * vol / BPS, fmin, fmax)
    if policy.kind == "markout":
        return _markout_fees(policy.params, s, f0, fmin, fmax, h_dec, eps)
    if policy.kind == "depeg":
        return _depeg_fees(policy.params, s, r, fmin, fmax)
    raise ValueError(policy.kind)


def _depeg_fees(p: dict, s: pd.DataFrame, r: pd.DataFrame, fmin: float, fmax: float) -> np.ndarray:
    """Oscillon stable-depeg keeper policy (reference divergence), using only data from before each swap.
        staleDev = |pool price before swap - reference|      (how far the pool lags the market)
        pegDev   = |reference - peg|                          (how far the asset is off its peg)
        fee      = clamp(base + k*staleDev + m*max(0, pegDev - deadband))
    directional=True charges the extra only on swaps that move the pool toward the reference
    (needs a two-sided fee in the contract); False = one fee for both sides (what the hook supports today)."""
    base, k, m, db = p["base"], p["k"], p["m"], p["deadband_bps"]
    peg, directional = p.get("peg", 1.0), p.get("directional", False)
    lag = p.get("keeper_lag_s", KEEPER_LAG_S)                      # keeper sees the reference one block early
    ref_prev = pd.merge_asof(pd.DataFrame({"ts": s["ts"] - lag}), r[["ts", "mid"]], on="ts",
                             direction="backward")["mid"].values
    px = s["pool_px_after"].values if "pool_px_after" in s.columns else (s["a1"] / s["a0"]).values
    pool_prev = np.concatenate([[np.nan], px[:-1]])               # pool price before this swap
    pool_prev = np.where(np.isnan(pool_prev), ref_prev, pool_prev)
    stale = np.abs(pool_prev - ref_prev) / ref_prev * BPS
    pegdev = np.abs(ref_prev - peg) / peg * BPS
    extra = (k * stale + m * np.maximum(0.0, pegdev - db)) / BPS
    if directional:
        toward = np.where(pool_prev > ref_prev, s["dir"].values < 0, s["dir"].values > 0)
        extra = np.where(toward, extra, 0.0)
    return np.clip(base + extra, fmin, fmax)


def _kept_weight(edge_bps: float, fee: float, f0: float, eps: float) -> float:
    informed = edge_bps > f0 * BPS
    if informed:
        return 1.0 if edge_bps > fee * BPS else 0.0
    return 1.0 if fee <= f0 else (fee / f0) ** (-eps)


def _markout_fees(p: dict, s: pd.DataFrame, f0: float, fmin: float, fmax: float,
                  h_dec: int, eps: float) -> np.ndarray:
    """Keeper fee from the volume-weighted LP markout of matured swaps (per direction or pooled).
    Never below base: blocks the 'make cheap good trades to unlock a discount' attack."""
    h, look, base, kappa = p["h"], p["lookback"], p["base"], p["kappa"]
    directional = p.get("directional", True)
    ts = s["ts"].values; d = s["dir"].values
    mk = s[f"mark_bps_{h}"].values; nt = s["notional"].values
    edge = -s[f"mark_bps_{h_dec}"].values
    fees = np.empty(len(s))
    pending: deque = deque()                     # swaps not yet matured: (mature_ts, dir, mark_bps, w*notional)
    matured = {1: deque(), -1: deque(), 0: deque()}
    sums = {k: [0.0, 0.0] for k in matured}      # sum(w*notional*mark), sum(w*notional)
    for i in range(len(s)):
        t = ts[i]
        while pending and pending[0][0] < t:     # matured strictly before this swap
            m_ts, dd, mb, wn = pending.popleft()
            for key in ((dd, 0) if directional else (0,)):
                matured[key].append((m_ts, mb, wn)); sums[key][0] += wn * mb; sums[key][1] += wn
        for key in matured:                      # drop observations older than lookback
            q = matured[key]
            while q and q[0][0] < t - look:
                _, mb, wn = q.popleft(); sums[key][0] -= wn * mb; sums[key][1] -= wn
        key = d[i] if directional else 0
        tox = sums[key][0] / sums[key][1] if sums[key][1] > 0 else 0.0
        fee = float(np.clip(base + kappa * max(0.0, -tox) / BPS, fmin, fmax))
        fees[i] = fee
        w = _kept_weight(edge[i], fee, f0, eps)
        pending.append((t + h, d[i], mk[i], w * nt[i]))
    return fees


# --------------------------------------------------------------------------- evaluation
def evaluate(s: pd.DataFrame, fees: np.ndarray, f0: float, h_dec: int, h_eval: int, eps: float) -> pd.DataFrame:
    edge = -s[f"mark_bps_{h_dec}"].values
    w = np.array([_kept_weight(e, f, f0, eps) for e, f in zip(edge, fees)])
    out = pd.DataFrame({
        "day": s["day"].values,
        "w": w,
        "fee_rev": w * fees * s["notional"].values,
        "markout": w * s[f"mark_{h_eval}"].values,
        "volume": w * s["notional"].values,
        "fee": fees,
    })
    out["lp_pnl"] = out["fee_rev"] + out["markout"]
    return out


def summarize(ev: pd.DataFrame, base_ev: pd.DataFrame, n_boot: int = 500, seed: int = 0) -> dict:
    daily = ev.groupby("day")[["lp_pnl", "fee_rev", "markout", "volume"]].sum()
    bdaily = base_ev.groupby("day")[["lp_pnl", "volume"]].sum()
    diff = (daily["lp_pnl"] - bdaily["lp_pnl"]).values
    rng = np.random.default_rng(seed)
    boots = [rng.choice(diff, size=len(diff), replace=True).sum() for _ in range(n_boot)] if len(diff) else [0]
    vol = daily["volume"].sum()
    return {
        "lp_pnl": daily["lp_pnl"].sum(),
        "lp_pnl_bps_of_volume": daily["lp_pnl"].sum() / vol * BPS if vol else np.nan,
        "fee_revenue": daily["fee_rev"].sum(),
        "markout_loss": daily["markout"].sum(),
        "volume_kept_pct": vol / bdaily["volume"].sum() * 100 if bdaily["volume"].sum() else np.nan,
        "avg_fee_bps": float(np.average(ev["fee"], weights=np.maximum(ev["w"], 1e-12)) * BPS),
        "win_pct_days_vs_vanilla": float((diff > 0).mean() * 100) if len(diff) else np.nan,
        "edge_vs_vanilla": float(diff.sum()),
        "edge_vs_vanilla_ci90": [float(np.percentile(boots, 5)), float(np.percentile(boots, 95))],
        "days": int(len(daily)),
    }


def grid(kind: str, f0: float) -> list[dict]:
    if kind == "vol":
        return [{"base": b, "a": a, "window": w}
                for b, a, w in product([f0 * 0.6, f0], [0.02, 0.05, 0.1, 0.2, 0.5, 1.0], [300, 900, 3600, 14400])]
    if kind == "markout":
        return [{"base": b, "kappa": k, "h": h, "lookback": lb, "directional": dr}
                for b, k, h, lb, dr in product([f0 * 0.6, f0], [0.25, 0.5, 1.0, 2.0, 4.0], [12, 60],
                                               [900, 3600], [True, False])]
    if kind == "depeg":
        return [{"base": f0, "k": k, "m": m, "deadband_bps": db, "directional": dr}
                for k, m, db, dr in product([0.0, 0.25, 0.5, 1.0], [0.0, 0.5, 1.0, 2.0], [5, 20], [False, True])]
    return [{}]


def run(swaps_csv: str, ref_csv: str, f0: float, fmin: float, fmax: float,
        h_dec: int, h_eval: int, eps: float, train_frac: float,
        kinds: tuple = ("vol", "markout", "depeg")) -> dict:
    horizons = sorted({h_dec, h_eval, 12, 60})
    s, r = load(swaps_csv, ref_csv)
    s = enrich(s, r, f0, horizons)
    cut = s["day"].quantile(train_frac) if s["day"].nunique() > 1 else s["day"].max()
    train, test = s[s["day"] <= cut].reset_index(drop=True), s[s["day"] > cut].reset_index(drop=True)
    if len(test) == 0:
        raise SystemExit("Not enough days for an out-of-sample split.")

    def ev(pol, df):
        return evaluate(df, fees_for(pol, df, r, f0, fmin, fmax, h_dec, eps), f0, h_dec, h_eval, eps)

    vanilla = Policy("vanilla", "vanilla", {"fee": f0})
    base_train, base_test = ev(vanilla, train), ev(vanilla, test)
    results = {"vanilla": {"params": {"fee": f0},
                           "train": summarize(base_train, base_train),
                           "test": summarize(base_test, base_test)}}
    labels = {"vol": "dynamic_vol", "markout": "markout", "depeg": "oscillon_depeg"}
    for kind in kinds:
        best, best_val = None, -np.inf
        for p in grid(kind, f0):                                   # fit on train only
            val = ev(Policy(kind, kind, p), train)["lp_pnl"].sum()
            if val > best_val:
                best, best_val = p, val
        pol = Policy(labels[kind], kind, best)                      # frozen, then tested
        results[labels[kind]] = {"params": best,
                                 "train": summarize(ev(pol, train), base_train),
                                 "test": summarize(ev(pol, test), base_test)}
    results["_config"] = {"f0": f0, "fmin": fmin, "fmax": fmax, "h_decision_s": h_dec,
                          "h_eval_s": h_eval, "elasticity": eps, "train_frac": train_frac,
                          "train_days": int(train["day"].nunique()), "test_days": int(test["day"].nunique()),
                          "swaps": int(len(s))}
    return results


def print_table(res: dict) -> None:
    rows = []
    for name, v in res.items():
        if name.startswith("_"):
            continue
        t = v["test"]
        rows.append([name, f"{t['lp_pnl']:,.0f}", f"{t['lp_pnl_bps_of_volume']:.2f}", f"{t['fee_revenue']:,.0f}",
                     f"{t['markout_loss']:,.0f}", f"{t['volume_kept_pct']:.1f}", f"{t['avg_fee_bps']:.2f}",
                     f"{t['win_pct_days_vs_vanilla']:.0f}",
                     f"{t['edge_vs_vanilla']:,.0f} [{t['edge_vs_vanilla_ci90'][0]:,.0f}, {t['edge_vs_vanilla_ci90'][1]:,.0f}]"])
    hdr = ["policy", "LP PnL", "PnL bps/vol", "fees", "markout", "vol kept %", "avg fee bps",
           "win % days", "vs vanilla [90% CI]"]
    w = [max(len(str(x)) for x in col) for col in zip(hdr, *rows)]
    print("OUT-OF-SAMPLE (test period), amounts in token1 units")
    print("  ".join(h.ljust(n) for h, n in zip(hdr, w)))
    for r in rows:
        print("  ".join(str(x).ljust(n) for x, n in zip(r, w)))
    print("\nconfig:", res["_config"])
    for name in res:
        if not name.startswith("_") and name != "vanilla":
            print(f"{name} fitted params:", res[name]["params"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--swaps", required=True); ap.add_argument("--ref", required=True)
    ap.add_argument("--fee", type=float, default=0.0005, help="historical pool fee (0.0005 = 5 bp)")
    ap.add_argument("--fmin", type=float, default=0.0001); ap.add_argument("--fmax", type=float, default=0.01)
    ap.add_argument("--h-decision", type=int, default=12, help="seconds: horizon that decides if a trade is informed")
    ap.add_argument("--h-eval", type=int, default=60, help="seconds: horizon for LP PnL markout")
    ap.add_argument("--elasticity", type=float, default=0.5)
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--sweep", default="", help="comma list of elasticities, e.g. 0.5,2,5 (re-fits each)")
    ap.add_argument("--policies", default="vol,markout,depeg", help="subset of vol,markout,depeg")
    ap.add_argument("--keeper-lag", type=int, default=12, help="seconds between the reference the keeper reads and the swap")
    a = ap.parse_args()
    KEEPER_LAG_S = a.keeper_lag
    kinds = tuple(x.strip() for x in a.policies.split(",") if x.strip())
    if a.sweep:
        allres = {}
        for e in [float(x) for x in a.sweep.split(",")]:
            res = run(a.swaps, a.ref, a.fee, a.fmin, a.fmax, a.h_decision, a.h_eval, e, a.train_frac, kinds)
            allres[str(e)] = res
            print(f"\n=== elasticity {e} ===")
            print_table(res)
        with open(a.out, "w") as fh:
            json.dump(allres, fh, indent=2, default=str)
    else:
        res = run(a.swaps, a.ref, a.fee, a.fmin, a.fmax, a.h_decision, a.h_eval, a.elasticity, a.train_frac, kinds)
        with open(a.out, "w") as fh:
            json.dump(res, fh, indent=2, default=str)
        print_table(res)
