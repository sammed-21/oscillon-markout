#!/usr/bin/env python3
"""
First-pass markout backtest on the real USDe/USDT tape already fetched and
verified in research-backtest/data/oscillon_test_2/usde_usdt.

What this DOES show: using the pool's own forward price as the reference
(ref_source="pool_forward" — see src/markout.py for why that's a weaker
proxy than an independent CEX price), how toxic was flow in each direction
on this real tape, and what fee the markout keeper would have quoted,
swap-by-swap, with zero lookahead.

What this does NOT show yet: whether raising the fee on toxic flow would
have driven that flow elsewhere (the "once arbitrage reacts to the fee"
question from the original brief). This is the fixed-volume counterfactual
— same trades replayed under a different fee, same caveat already used for
every Oscillon fee-mechanism backtest in the sibling project. An
elasticity/routing layer is a separate, later step.

Train/test split: first 60% of the tape by time decides nothing (no fitting
happens here — config is fixed by hand below), but the split is still
applied so the headline numbers are reported out-of-sample-style, matching
how every other result in this project is reported.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keeper_policy import KeeperPolicyConfig, simulate_keeper_fees  # noqa: E402
from markout import compute_markouts  # noqa: E402

TAPE = Path("/Users/sammedsbetadur/Desktop/oscillon/research-backtest/data/oscillon_test_2/usde_usdt/swaps.csv.gz")
OUT = ROOT / "output"
DECIMALS0, DECIMALS1 = 18, 6  # USDe, USDT
HORIZONS = [1, 12, 60]


def load_tape() -> pd.DataFrame:
    # amount0 is 18-decimal USDe raw units and can exceed int64 range on large
    # trades -- read as string, convert via Python's arbitrary-precision int,
    # same fix already applied in src/lp_inventory_replay.py for this tape.
    df = pd.read_csv(TAPE, dtype={"amount0": str, "amount1": str})
    df["amount0"] = df["amount0"].apply(int)
    df["amount1"] = df["amount1"].apply(int)
    df["ts"] = pd.to_datetime(df["ts"].astype(str).str.replace(" UTC", "", regex=False), utc=True)
    return df.sort_values(["blk", "idx"]).reset_index(drop=True)


def notional_usd(df: pd.DataFrame) -> np.ndarray:
    return (np.abs(df["amount1"]) / 10.0**DECIMALS1).to_numpy()  # USDT leg = USD notional


def vwa_markout(df: pd.DataFrame, col: str, notional: np.ndarray) -> dict:
    out = {}
    for d, name in ((1, "buy_usde"), (-1, "sell_usde")):
        mask = (df["direction"] == d) & df[col].notna()
        w = notional[mask.to_numpy()]
        v = df.loc[mask, col].to_numpy()
        out[name] = float(np.average(v, weights=w)) if w.sum() > 0 else None
        out[f"{name}_n"] = int(mask.sum())
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    print(f"Loading real tape: {TAPE}")
    raw = load_tape()
    print(f"{len(raw):,} real swaps, {raw['ts'].min()} -> {raw['ts'].max()}")

    print(f"Computing markouts at horizons {HORIZONS} blocks (ref_source=pool_forward) ...")
    df = compute_markouts(raw, horizons_blocks=HORIZONS, decimals0=DECIMALS0, decimals1=DECIMALS1)
    notional = notional_usd(df)

    print("\n=== Raw toxicity in the real tape (volume-weighted avg markout, bps) ===")
    print("(negative = that direction has been bad for the LP, on average)")
    for h in HORIZONS:
        col = f"lp_markout_bps_h{h}"
        n_known = df[col].notna().sum()
        print(f"h={h:>3} blocks ({n_known:,}/{len(df):,} swaps have a known outcome): "
              f"{vwa_markout(df, col, notional)}")

    split = int(len(df) * 0.6)
    split_ts = df["ts"].iloc[split]
    train, test = df.iloc[:split].copy(), df.iloc[split:].copy()
    print(f"\nSplit at {split_ts} ({split:,} train / {len(df) - split:,} test swaps)")

    configs = {
        "static_1bps": None,
        "markout_shared_fee": KeeperPolicyConfig(
            base_fee_bps=1.0, min_fee_bps=1.0, max_fee_bps=30.0, kappa=0.05,
            markout_horizon_blocks=12, decay_halflife_swaps=20, hysteresis_bps=0.2,
            same_fee_both_directions=True,
        ),
        "markout_per_direction": KeeperPolicyConfig(
            base_fee_bps=1.0, min_fee_bps=1.0, max_fee_bps=30.0, kappa=0.05,
            markout_horizon_blocks=12, decay_halflife_swaps=20, hysteresis_bps=0.2,
            same_fee_both_directions=False,
        ),
    }

    print("\n=== Fee revenue on the real tape, same trades, fixed-volume (no routing response modeled) ===")
    rows = []
    for name, cfg in configs.items():
        for label, part, notl in (("train", train, notional[:split]), ("test", test, notional[split:])):
            if cfg is None:
                fee_bps = np.full(len(part), 1.0)
            else:
                out = simulate_keeper_fees(part, cfg)
                fee_bps = out["quoted_fee_bps"].to_numpy()
            revenue_usd = float((notl * fee_bps / 10_000).sum())
            avg_fee = float(np.average(fee_bps, weights=notl)) if notl.sum() > 0 else float("nan")
            rows.append({"policy": name, "period": label, "n_swaps": len(part),
                        "volume_usd": float(notl.sum()), "avg_fee_bps_volwtd": avg_fee,
                        "fee_revenue_usd": revenue_usd})
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    res.to_csv(OUT / "markout_backtest_results.csv", index=False)

    df.to_csv(OUT / "usde_usdt_markouts_full.csv.gz", index=False, compression="gzip")
    print(f"\nFull per-swap markouts: {OUT / 'usde_usdt_markouts_full.csv.gz'}")
    print(f"Summary table: {OUT / 'markout_backtest_results.csv'}")


if __name__ == "__main__":
    main()
