"""
Build a 1-minute token0/token1 reference from Kraken public trades (no API key), e.g. USDC/USDT = USDC/USD ÷ USDT/USD.
Used to fill hours a Binance pair didn't trade (Binance USDC/USDT only relisted at 2023-03-11 14:00 UTC).

Output: Binance-kline-shaped CSV (col 0 = minute open time in ms, col 4 = close) so prepare_minute_year.py reads it
next to the Binance files; on overlapping minutes the Binance file wins (it sorts first).

  python3 fetch_kraken.py --base USDCUSD --quote USDTZUSD --start 2023-03-10 --end 2023-03-12T12:00 \
      --out klines_2023_03/kraken_USDCUSDT-1m.csv
"""
import argparse, time
import pandas as pd
import requests

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True); ap.add_argument("--quote", required=True)
ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
t0, t1 = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")


def trades(pair: str) -> pd.DataFrame:
    rows, since = [], int(t0.value)
    while True:
        for attempt in range(6):
            d = requests.get("https://api.kraken.com/0/public/Trades", params={"pair": pair, "since": since}, timeout=30).json()
            if not d["error"]:
                break
            time.sleep(3 * (attempt + 1))                       # public rate limit
        else:
            raise RuntimeError(d["error"])
        res = d["result"]
        batch = next(v for k, v in res.items() if k != "last")
        rows += [(float(x[2]), float(x[0]), float(x[1])) for x in batch]
        last = int(res["last"])
        if not batch or last == since or batch[-1][2] >= t1.timestamp():
            break
        since = last
        print(f"  {pair}: {len(rows):,} trades, up to {pd.to_datetime(batch[-1][2], unit='s')}", flush=True)
        time.sleep(1.1)
    df = pd.DataFrame(rows, columns=["t", "price", "qty"])
    return df[(df.t >= t0.timestamp()) & (df.t < t1.timestamp())]


def minute_close(df: pd.DataFrame) -> pd.Series:
    s = df.assign(m=pd.to_datetime(df.t, unit="s").dt.floor("min")).groupby("m").price.last()
    return s.reindex(pd.date_range(t0.tz_localize(None), t1.tz_localize(None), freq="min", inclusive="left")).ffill()


b, q = minute_close(trades(a.base)), minute_close(trades(a.quote))
px = (b / q).dropna()
out = pd.DataFrame({0: (px.index.astype("int64") // 10**6), 1: px, 2: px, 3: px, 4: px})
out.to_csv(a.out, header=False, index=False)
print(f"wrote {len(out):,} minutes -> {a.out}  ({px.index.min()} .. {px.index.max()}, min {px.min():.4f})")
