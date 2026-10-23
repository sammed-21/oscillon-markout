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
LP_FEE_SHARE = 1.0        # share of the swap fee LPs keep; set with --lp-fee-share (Uniswap v3 fee switch 1/4 -> 0.75)
TVL_USD = 500_000_000.0   # for bp/year annualization; set with --tvl (500M matches BACKTEST.md's convention)


# --------------------------------------------------------------------------- data
def load(swaps_csv: str, ref_csv: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """swaps.csv: ts, dir, a0, a1   |   ref.csv: ts, mid
    ts   : unix seconds (int)
    dir  : +1 trader buys token0 from the pool, -1 trader sells token0 to the pool
    a0,a1: absolute gross amounts in token units (decimals already applied)
    mid  : reference price of token0 in token1 (e.g. CEX mid)
    """
    s = pd.read_csv(swaps_csv).sort_values("ts", kind="stable").reset_index(drop=True)
    r = pd.read_csv(ref_csv).sort_values("ts").reset_index(drop=True)
    return s, r


def attach_oracle(s: pd.DataFrame, oracle_csv: str) -> pd.DataFrame:
    """oracle.csv: ts, price (e.g. Chainlink USDC/USD). Attaches the last oracle value strictly before each swap."""
    o = pd.read_csv(oracle_csv).sort_values("ts")
    s = s.copy()
    s["oracle"] = pd.merge_asof(pd.DataFrame({"ts": s["ts"] - 1}), o[["ts", "price"]], on="ts",
                                direction="backward")["price"].values
    return s


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
    if policy.kind in ("markout", "markout_hook", "markout_hook_poolfee", "keeper"):
        return _markout_fees(policy.params, s, f0, fmin, fmax, h_dec, eps)
    if policy.kind == "depeg":
        return _depeg_fees(policy.params, s, r, fmin, fmax)
    if policy.kind in ("hook", "hook_poolfee"):
        return _hook_fees(policy.params, s)
    if policy.kind == "tiered":                  # flow-tiered: sources that were benign in the fit period pay less
        p = policy.params
        benign = s["sender"].str.lower().isin(set(p["benign"])).values
        return np.where(benign, p["benign_fee"], p["other_fee"])
    raise ValueError(policy.kind)


def _hybrid_surcharge_bps(dev_bps: np.ndarray, k: float) -> np.ndarray:
    """Oscillon hybrid surcharge = max(piecewise, quadratic), capped at 100 bp.
    Mirrors research-backtest/src/oscillon_fee.py (_piecewise/_quadratic/_hybrid_surcharge_bps, float path)."""
    d = np.asarray(dev_bps, dtype=float)
    ex = np.maximum(0.0, d - 3.0)
    piece = np.where(d <= 3, 1.0, np.where(d <= 20, 1.0 + 204.0 * ex ** 2 / BPS,
                                           (BPS + 204.0 * 17 ** 2 + 1100.0 * (d - 20)) / BPS))
    quad = 1.0 + k * ex ** 2 / BPS
    return np.minimum(np.maximum(piece, quad), 100.0)


def _hybrid_surcharge_bps_int(dev_bps: np.ndarray, k: int) -> np.ndarray:
    """Whole-bp surcharge exactly as OscillonFeePolicy.sol computes it (select_fee_pips path): the depeg is truncated
    to whole bp and each leg uses integer division. E.g. 10 bp depeg -> 1 bp surcharge (float path: 2.0)."""
    d = np.floor(np.asarray(dev_bps, dtype=float)).astype(np.int64)
    ex = np.maximum(0, d - 3)
    piece = np.where(d <= 3, 1, np.where(d <= 20, (10_000 + 204 * ex * ex) // 10_000,
                                         np.minimum((10_000 + 204 * 289 + 1100 * (d - 20)) // 10_000, 100)))
    quad = np.minimum(1 + (k * ex * ex) // 10_000, 100)
    return np.maximum(piece, quad).astype(float)


def _hybrid_scalar(d: float, k: float, onchain: bool = True) -> float:
    """Scalar surcharge for the per-swap keeper loop; onchain=True rounds like the contract."""
    if onchain:
        di = int(d); ex = max(0, di - 3)
        piece = 1 if di <= 3 else (10_000 + 204 * ex * ex) // 10_000 if di <= 20 else min((10_000 + 204 * 289 + 1100 * (di - 20)) // 10_000, 100)
        return float(max(piece, min(1 + (int(k) * ex * ex) // 10_000, 100)))
    ex = max(0.0, d - 3.0)
    piece = 1.0 if d <= 3 else 1.0 + 204.0 * ex * ex / BPS if d <= 20 else (BPS + 204.0 * 289 + 1100.0 * (d - 20)) / BPS
    return min(max(piece, 1.0 + k * ex * ex / BPS), 100.0)


def _hook_fees(p: dict, s: pd.DataFrame) -> np.ndarray:
    """Oscillon stable-fee hook (OscillonFeePolicy.sol): base fee on every swap; a drain swap (token0 sold into
    the pool while the oracle shows token0 below peg by >= 3 bp) pays base + hybrid surcharge. No fitting."""
    if "oracle" not in s.columns:
        raise SystemExit("the hook policy needs --oracle")
    peg = p.get("peg", 1.0)
    o = s["oracle"].fillna(peg).values
    dev = np.maximum(0.0, (peg - o) / peg * BPS)
    drain = (o < peg) & (s["dir"].values < 0) & (dev >= 3.0)
    curve = _hybrid_surcharge_bps_int(dev, p["k"]) if p.get("onchain", True) else _hybrid_surcharge_bps(dev, p["k"])
    fee_bps = p["base"] * BPS + np.where(drain, curve, 0.0)
    return np.minimum(fee_bps, 100.0) / BPS


_ANCHOR_CACHE: dict = {}


def _depeg_fees(p: dict, s: pd.DataFrame, r: pd.DataFrame, fmin: float, fmax: float) -> np.ndarray:
    """Oscillon stable-depeg keeper policy (reference divergence), using only data from before each swap.
        staleDev = |pool price before swap - reference|      (how far the pool lags the market)
        pegDev   = |reference - peg|                          (how far the asset is off its peg)
        fee      = clamp(base + k*staleDev + m*max(0, pegDev - deadband))
    directional=True charges the extra only on swaps that move the pool toward the reference
    (needs a two-sided fee in the contract); False = one fee for both sides (what the hook supports today).

    decision_source="market" (default): the keeper reads the fast exchange reference `r` -- an
    idealized, always-fresh keeper. decision_source="oracle": the keeper reads whatever was
    attached via --oracle (e.g. real Chainlink, updates only on a >0.25% move or 24h) instead --
    this is what a real deployed keeper actually sees. Markouts are ALWAYS scored against `r`
    regardless of this setting; only the policy's own decision input changes."""
    base, k, m, db = p["base"], p["k"], p["m"], p["deadband_bps"]
    peg, directional = p.get("peg", 1.0), p.get("directional", False)
    lag = p.get("keeper_lag_s", KEEPER_LAG_S)                      # keeper sees the reference one block early
    decision_source = p.get("decision_source", "market")
    if decision_source == "oracle":
        if "oracle" not in s.columns:
            raise SystemExit("depeg decision_source='oracle' needs --oracle")
        ref_prev = s["oracle"].astype(float).to_numpy()           # already as-of (ts-1), strictly before the swap
    else:
        ref_prev = pd.merge_asof(pd.DataFrame({"ts": s["ts"] - lag}), r[["ts", "mid"]], on="ts",
                                 direction="backward")["mid"].values
    px = s["pool_px_after"].values if "pool_px_after" in s.columns else (s["a1"] / s["a0"]).values
    pool_prev = np.concatenate([[np.nan], px[:-1]])               # pool price before this swap
    pool_prev = np.where(np.isnan(pool_prev), ref_prev, pool_prev)
    stale = np.abs(pool_prev - ref_prev) / ref_prev * BPS
    w = p.get("peg_window_s", 0)                                  # 0 = fixed peg ($1); >0 = trailing median of the decision source
    if w:                                                          # a steady offset (e.g. USDT at -10 bp for weeks) is a level,
        if decision_source == "oracle":                            # not a move; only moves away from it pay
            key = (id(s), "oracle", int(w))
            if key not in _ANCHOR_CACHE:
                oo = pd.Series(ref_prev, index=pd.to_datetime(s["ts"].values, unit="s")).sort_index()
                _ANCHOR_CACHE[key] = oo.rolling(f"{int(w)}s").median().reindex(oo.index).to_numpy()
            peg = _ANCHOR_CACHE[key]
        else:
            key = (id(r), id(s), int(w), lag)
            if key not in _ANCHOR_CACHE:
                rr = r.set_index(pd.to_datetime(r["ts"], unit="s"))["mid"]
                anchor = rr.rolling(f"{int(w)}s").median().values
                anc = pd.DataFrame({"ts": r["ts"].values, "anchor": anchor})
                _ANCHOR_CACHE[key] = pd.merge_asof(pd.DataFrame({"ts": s["ts"] - lag}), anc, on="ts",
                                                   direction="backward")["anchor"].values
            peg = _ANCHOR_CACHE[key]
    pegdev = np.abs(ref_prev - peg) / peg * BPS
    extra = (k * stale + m * np.maximum(0.0, pegdev - db)) / BPS
    if directional:
        toward = np.where(pool_prev > ref_prev, s["dir"].values < 0, s["dir"].values > 0)
        extra = np.where(toward, extra, 0.0)
    return np.clip(base + np.nan_to_num(extra, nan=0.0), fmin, fmax)   # no prior price → charge base


def _kept_weight(edge_bps: float, fee: float, f0: float, eps: float) -> float:
    informed = edge_bps > f0 * BPS
    if informed:
        return 1.0 if edge_bps > fee * BPS else 0.0
    return 1.0 if fee <= f0 else (fee / f0) ** (-eps)


def _markout_fees(p: dict, s: pd.DataFrame, f0: float, fmin: float, fmax: float,
                  h_dec: int, eps: float) -> np.ndarray:
    """Keeper fee from the volume-weighted LP markout of matured swaps (per direction or pooled).
    Never below base: blocks the 'make cheap good trades to unlock a discount' attack.
    curve="hybrid": fee = base + Oscillon hybrid surcharge(toxicity bp) once toxicity >= 3 bp, instead of base + kappa*toxicity."""
    h, look, base = p["h"], p["lookback"], p["base"]
    kappa = p.get("kappa", 0.0)
    hybrid, curve_k, onchain = p.get("curve") == "hybrid", p.get("k", 45), p.get("onchain", True)
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
        if hybrid:                               # measured LP loss (bp) takes the depeg's place in the Oscillon curve
            dev = max(0.0, -tox)
            fee = min(base + (_hybrid_scalar(dev, curve_k, onchain) if dev >= 3.0 else 0.0) / BPS, 0.01)
        else:
            fee = float(np.clip(base + kappa * max(0.0, -tox) / BPS, fmin, fmax))
        fees[i] = fee
        w = _kept_weight(edge[i], fee, f0, eps)
        pending.append((t + h, d[i], mk[i], w * nt[i]))
    return fees


# --------------------------------------------------------------------------- evaluation
def evaluate(s: pd.DataFrame, fees: np.ndarray, f0: float, h_dec: int, h_eval: int, eps: float) -> pd.DataFrame:
    edge = -s[f"mark_bps_{h_dec}"].values
    informed = edge > f0 * BPS                                   # vectorized _kept_weight
    w = np.where(informed, (edge > fees * BPS).astype(float),
                 np.where(fees <= f0, 1.0, (np.maximum(fees, 1e-12) / f0) ** (-eps)))
    out = pd.DataFrame({
        "day": s["day"].values,
        "dir": s["dir"].values,
        "w": w,
        "fee_rev": w * fees * s["notional"].values * LP_FEE_SHARE,
        "markout": w * s[f"mark_{h_eval}"].values,
        "volume": w * s["notional"].values,
        "fee": fees,
    })
    out["lp_pnl"] = out["fee_rev"] + out["markout"]
    return out


def average_fee(ev: pd.DataFrame) -> float:
    """Volume-weighted average fee actually paid (by the volume that stayed)."""
    wv = ev["volume"].values
    return float(np.average(ev["fee"].values, weights=wv)) if wv.sum() > 0 else float(ev["fee"].mean())


def summarize(ev: pd.DataFrame, base_ev: pd.DataFrame, n_boot: int = 500, seed: int = 0) -> dict:
    daily = ev.groupby("day")[["lp_pnl", "fee_rev", "markout", "volume"]].sum()
    bdaily = base_ev.groupby("day")[["lp_pnl", "volume"]].sum()
    diff = (daily["lp_pnl"] - bdaily["lp_pnl"]).values
    rng = np.random.default_rng(seed)
    boots = [rng.choice(diff, size=len(diff), replace=True).sum() for _ in range(n_boot)] if len(diff) else [0]
    vol = daily["volume"].sum()
    by_dir = {}
    for d, name in ((-1, "sell_token0"), (1, "buy_token0")):        # -1: trader sold token0, +1: trader bought it
        e, b = ev[ev["dir"] == d], base_ev[base_ev["dir"] == d]
        dv = e["volume"].sum()
        by_dir[name] = {
            "lp_pnl": float(e["lp_pnl"].sum()),
            "fee_revenue": float(e["fee_rev"].sum()),
            "markout_loss": float(e["markout"].sum()),
            "lp_pnl_bps_of_volume": float(e["lp_pnl"].sum() / dv * BPS) if dv else np.nan,
            "volume": float(dv),
            "volume_kept_pct": float(dv / b["volume"].sum() * 100) if b["volume"].sum() else np.nan,
            "avg_fee_bps": float(np.average(e["fee"], weights=np.maximum(e["w"], 1e-12)) * BPS) if len(e) else np.nan,
            "edge_vs_vanilla": float(e["lp_pnl"].sum() - b["lp_pnl"].sum()),
        }
    fee_rev_sum = float(daily["fee_rev"].sum())
    net_markout = float(daily["markout"].sum())
    # Loss ratio, as asked: -(net markout) / fees. Net, not floored per swap -- a
    # policy whose good trades outweigh its bad ones can show a negative ratio.
    loss_ratio = (-net_markout / fee_rev_sum) if fee_rev_sum else np.nan
    # capture_pct mirrors research-backtest/src/supply_shock_analysis.py's
    # static_lp_capture_pct / dynamic_lp_capture_pct (the real 14.8%/33.2% figures):
    # capture = LP_income / (LP_income + LVR), where that LVR is a per-swap loss
    # floored at zero and never net against gains elsewhere. markout_loss_floor
    # reproduces that floor so the two numbers are comparable on the same basis.
    markout_loss_floor = float(-(ev["markout"].clip(upper=0).sum()))
    cap_total = fee_rev_sum + markout_loss_floor
    capture_pct = (fee_rev_sum / cap_total * 100) if cap_total > 0 else 100.0
    days = max(int(len(daily)), 1)
    gain_bp_per_year_tvl = (diff.sum() / days * 365 / TVL_USD * BPS) if TVL_USD else np.nan
    return {
        "lp_pnl": daily["lp_pnl"].sum(),
        "lp_pnl_bps_of_volume": daily["lp_pnl"].sum() / vol * BPS if vol else np.nan,
        "fee_revenue": fee_rev_sum,
        "markout_loss": net_markout,
        "markout_loss_floor": markout_loss_floor,
        "loss_ratio": loss_ratio,
        "capture_pct": capture_pct,
        "gain_bp_per_year_tvl": float(gain_bp_per_year_tvl),
        "volume_kept_pct": vol / bdaily["volume"].sum() * 100 if bdaily["volume"].sum() else np.nan,
        "avg_fee_bps": float(np.average(ev["fee"], weights=np.maximum(ev["w"], 1e-12)) * BPS),
        "win_pct_days_vs_vanilla": float((diff > 0).mean() * 100) if len(diff) else np.nan,
        "edge_vs_vanilla": float(diff.sum()),
        "edge_vs_vanilla_ci90": [float(np.percentile(boots, 5)), float(np.percentile(boots, 95))],
        "days": int(len(daily)),
        "by_direction": by_dir,
    }


def grid(kind: str, f0: float, h_eval: int = 60) -> list[dict]:
    if kind == "hook":                       # as coded on-chain: 3 bp base, k = 45
        return [{"base": 0.0003, "k": 45}]
    if kind == "hook_poolfee":               # same surcharge, on top of the pool's own fee
        return [{"base": f0, "k": 45}]
    if kind in ("markout_hook", "markout_hook_poolfee"):   # Oscillon curve driven by measured markout, not the oracle
        return [{"base": 0.0003 if kind == "markout_hook" else f0, "curve": "hybrid", "k": 45,
                 "h": h, "lookback": lb, "directional": dr}
                for h, lb, dr in product(sorted({60, h_eval}), [900, 3600], [True, False])]
    if kind == "keeper":                     # the Oscillon product: per-side markout keeper, base = pool fee, 100 bp cap
        return [{"base": f0, "kappa": k, "h": h, "lookback": lb, "directional": True}
                for k, h, lb in product([0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0], sorted({12, 60, h_eval}), [300, 900, 3600])]
    if kind == "tiered":                     # benign list is filled in by run() from the fit period
        return [{"benign_mult": d, "other_mult": u} for d, u in product([0.6, 0.8, 1.0], [1.0, 1.2, 1.5, 2.0]) if (d, u) != (1.0, 1.0)]
    if kind == "vol":
        return [{"base": b, "a": a, "window": w}
                for b, a, w in product([f0 * 0.6, f0], [0.02, 0.05, 0.1, 0.2, 0.5, 1.0], [300, 900, 3600, 14400])]
    if kind == "markout":
        return [{"base": b, "kappa": k, "h": h, "lookback": lb, "directional": dr}
                for b, k, h, lb, dr in product([f0 * 0.6, f0], [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0], sorted({12, 60, h_eval}),
                                               [900, 3600], [True, False])]
    if kind == "depeg":
        return [{"base": f0, "k": k, "m": m, "deadband_bps": db, "directional": dr, "peg_window_s": pw}
                for k, m, db, dr, pw in product([0.0, 0.25, 0.5, 1.0], [0.0, 0.5, 1.0, 2.0], [5, 20], [False, True],
                                                [0, 3600, 86400])]
    return [{}]


def run(swaps_csv: str, ref_csv: str, f0: float, fmin: float, fmax: float,
        h_dec: int, h_eval: int, eps: float, train_frac: float,
        kinds: tuple = ("vol", "markout", "depeg"), oracle_csv: str = "", daily: list | None = None,
        depeg_decision: str = "market") -> dict:
    horizons = sorted({h_dec, h_eval, 12, 60})
    s, r = load(swaps_csv, ref_csv)
    if oracle_csv:
        s = attach_oracle(s, oracle_csv)
    s = enrich(s, r, f0, horizons)
    cut = s["day"].quantile(train_frac) if s["day"].nunique() > 1 else s["day"].max()
    train, test = s[s["day"] <= cut].reset_index(drop=True), s[s["day"] > cut].reset_index(drop=True)
    if len(test) == 0:
        raise SystemExit("Not enough days for an out-of-sample split.")

    def ev(pol, df):
        return evaluate(df, fees_for(pol, df, r, f0, fmin, fmax, h_dec, eps), f0, h_dec, h_eval, eps)

    def keep_daily(name, period, e):
        if daily is None:
            return
        g = e.groupby(["day", "dir"])[["lp_pnl", "fee_rev", "markout", "volume"]].sum().reset_index()
        g["policy"], g["period"], g["elasticity"] = name, period, eps
        daily.append(g)

    vanilla = Policy("vanilla", "vanilla", {"fee": f0})
    base_train, base_test = ev(vanilla, train), ev(vanilla, test)
    keep_daily("vanilla", "train", base_train); keep_daily("vanilla", "test", base_test)
    results = {"vanilla": {"params": {"fee": f0},
                           "train": summarize(base_train, base_train),
                           "test": summarize(base_test, base_test)}}
    labels = {"vol": "dynamic_vol", "markout": "markout", "depeg": "oscillon_depeg",
              "hook": "oscillon_hook", "hook_poolfee": "oscillon_hook_poolfee",
              "markout_hook": "markout_hook", "markout_hook_poolfee": "markout_hook_poolfee", "tiered": "tiered",
              "keeper": "oscillon_keeper"}
    benign = []
    if "tiered" in kinds:                                           # sources whose fit-period flow left LPs better off
        src = train.assign(sender=train["sender"].str.lower()).groupby("sender").agg(
            net=(f"mark_{h_dec}", "sum"), vol=("notional", "sum"))
        benign = sorted(src[(src.net > 0) & (src.vol >= 5e6)].index)
    for kind in kinds:
        best, best_val = None, -np.inf
        for p in grid(kind, f0, h_eval):                            # fit on train only
            if kind == "tiered":
                p = {"benign": benign, "benign_fee": f0 * p["benign_mult"], "other_fee": f0 * p["other_mult"]}
            if kind == "depeg":
                p = {**p, "decision_source": depeg_decision}
            val = ev(Policy(kind, kind, p), train)["lp_pnl"].sum()
            if val > best_val:
                best, best_val = p, val
        if kind == "depeg":
            labels["depeg"] = "oscillon_depeg" if depeg_decision == "market" else "oscillon_depeg_chainlink"
        pol = Policy(labels[kind], kind, best)                      # frozen, then tested
        e_train, e_test = ev(pol, train), ev(pol, test)
        keep_daily(labels[kind], "train", e_train); keep_daily(labels[kind], "test", e_test)
        results[labels[kind]] = {"params": best,
                                 "train": summarize(e_train, base_train),
                                 "test": summarize(e_test, base_test)}
        # control: one flat fee equal to this rule's own average fee in that period. Beating it shows the rule's
        # timing/direction adds value; losing to it means the gain only came from charging more.
        flat = {}
        for period, e_rule, df, b in (("train", e_train, train, base_train), ("test", e_test, test, base_test)):
            fl = average_fee(e_rule)
            e_flat = ev(Policy("flat", "vanilla", {"fee": fl}), df)
            keep_daily(f"flat_{labels[kind]}", period, e_flat)
            flat[period] = summarize(e_flat, b)
            flat[f"{period}_fee"] = fl
        results[f"flat_{labels[kind]}"] = {"params": {"fee_train": flat.pop("train_fee"), "fee_test": flat.pop("test_fee")},
                                          **flat}
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
        rows.append([name, f"{t['lp_pnl']:,.0f}", f"{t['fee_revenue']:,.0f}", f"{t['markout_loss']:,.0f}",
                     f"{t['loss_ratio']:.3f}" if np.isfinite(t['loss_ratio']) else "nan",
                     f"{t['capture_pct']:.1f}", f"{t['gain_bp_per_year_tvl']:+.3f}",
                     f"{t['volume_kept_pct']:.1f}", f"{t['avg_fee_bps']:.2f}",
                     f"{t['win_pct_days_vs_vanilla']:.0f}",
                     f"{t['edge_vs_vanilla']:,.0f} [{t['edge_vs_vanilla_ci90'][0]:,.0f}, {t['edge_vs_vanilla_ci90'][1]:,.0f}]"])
    hdr = ["policy", "LP PnL", "fees", "markout", "loss ratio", "capture %", "bp/yr@TVL", "vol kept %",
           "avg fee bps", "win % days", "vs vanilla [90% CI]"]
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
    ap.add_argument("--policies", default="vol,markout,depeg",
                    help="subset of vol,markout,depeg,hook,hook_poolfee,markout_hook,markout_hook_poolfee,tiered (hook, hook_poolfee need --oracle; tiered needs a sender column)")
    ap.add_argument("--oracle", default="", help="oracle.csv (ts, price) for the hook policies, e.g. Chainlink USDC/USD")
    ap.add_argument("--daily-out", default="", help="also write per-day, per-direction results to this CSV")
    ap.add_argument("--keeper-lag", type=int, default=12, help="seconds between the reference the keeper reads and the swap")
    ap.add_argument("--tvl", type=float, default=500_000_000.0, help="USD TVL for the bp/year annualization")
    ap.add_argument("--lp-fee-share", type=float, default=1.0, help="share of fees LPs keep after the protocol fee (0.75 for a 1/4 fee switch)")
    ap.add_argument("--depeg-decision", choices=["market", "oracle"], default="market",
                    help="market = depeg policy decides off --ref (idealized, always-fresh); "
                         "oracle = decides off --oracle (e.g. real Chainlink) instead. Markouts are "
                         "always scored off --ref either way.")
    a = ap.parse_args()
    KEEPER_LAG_S = a.keeper_lag
    TVL_USD = a.tvl
    LP_FEE_SHARE = a.lp_fee_share
    kinds = tuple(x.strip() for x in a.policies.split(",") if x.strip())
    daily = [] if a.daily_out else None
    if a.sweep:
        allres = {}
        for e in [float(x) for x in a.sweep.split(",")]:
            res = run(a.swaps, a.ref, a.fee, a.fmin, a.fmax, a.h_decision, a.h_eval, e, a.train_frac, kinds,
                      a.oracle, daily, a.depeg_decision)
            allres[str(e)] = res
            print(f"\n=== elasticity {e} ===")
            print_table(res)
        with open(a.out, "w") as fh:
            json.dump(allres, fh, indent=2, default=str)
    else:
        res = run(a.swaps, a.ref, a.fee, a.fmin, a.fmax, a.h_decision, a.h_eval, a.elasticity, a.train_frac, kinds,
                  a.oracle, daily, a.depeg_decision)
        with open(a.out, "w") as fh:
            json.dump(res, fh, indent=2, default=str)
        print_table(res)
    if daily:
        pd.concat(daily).to_csv(a.daily_out, index=False)
