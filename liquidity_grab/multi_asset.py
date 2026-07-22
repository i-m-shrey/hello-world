"""MULTI-ASSET / MULTI-TIMEFRAME backtest of the liquidity-grab spec v2.

Instruments: XAUUSD + EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF (Dukascopy M1,
2015-12 -> 2026-07-21, volume>0 bars only — same validated pipeline as gold).
Execution timeframes: 1m 5m 15m 30m 1h 4h (resampled in NY tz from M1).
Config: literal spec v2 (fake-out-extreme SL, body>=25% signal candle, max 2
full SLs per zone, T1 = recent swing [M15 k=2 fractal, degrades to exec-TF
resolution above 15m], 80% booked, BE runner to session end) plus an rr5-target
variant. Sessions NY 17:00->17:00; eval window 2016+ with train<=2022 /
valid>=2023; costs = house all-in round trips, with 0x and 2x stress.

USDJPY/AUDUSD costs are documented estimates (no house live-fill number).
"""
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg

HERE = os.path.dirname(os.path.abspath(__file__))
DL = os.path.join(HERE, "data", "fx")
FROM, TO = "2015-12-01", "2026-07-22"
TRAIN_END = 2022
TFS = (1, 5, 15, 30, 60, 240)
MINBARS = {1: 500, 5: 100, 15: 33, 30: 17, 60: 9, 240: 3}
COSTS = {"XAUUSD": 0.23, "EURUSD": 0.00008, "GBPUSD": 0.00010,
         "USDCHF": 0.00010, "USDCAD": 0.00014,
         "USDJPY": 0.012, "AUDUSD": 0.00010}
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
V2 = dict(qual=0, sel=0, run=0, att=2, sl_mode=1, body_frac=0.25, att_mode=1)


def intact(path):
    try:
        size = os.path.getsize(path)
        if size <= 1000:
            return False
        with open(path, "rb") as f:
            head = f.readline().decode(errors="ignore").strip()
            f.seek(max(0, size - 4096))
            lines = [x for x in f.read().decode(errors="ignore").splitlines()
                     if x.strip()]
        last = lines[-1].split(",")
        return head.startswith("timestamp") and len(last) == 6 and last[0].isdigit()
    except OSError:
        return False


def fetch_pair(pair):
    os.makedirs(DL, exist_ok=True)
    paths = []
    years = list(range(2015, 2027))
    for k, y in enumerate(years):
        frm = f"{y}-12-01" if y == 2015 else f"{y}-01-01"
        to = TO if y == 2026 else f"{y + 1}-01-01"
        if y == 2015:
            to = "2016-01-01"
        name = f"{pair.lower()}-m1-bid-{frm}-{to}.csv"
        path = os.path.join(DL, "download", name)
        if intact(path):
            paths.append(path)
            continue
        cmd = ["npx", "-y", "dukascopy-node", "-i", pair.lower(), "-from", frm,
               "-to", to, "-t", "m1", "-f", "csv", "-v", "true"]
        for attempt in range(3):
            r = subprocess.run(cmd, cwd=DL, capture_output=True, text=True,
                               timeout=900)
            if r.returncode == 0 and intact(path):
                paths.append(path)
                break
            if os.path.exists(path):
                os.remove(path)
            time.sleep(5 * (attempt + 1))
        else:
            print(f"  !! {pair} {y}: download failed, skipping year")
    return paths


def load_pair(pair):
    parts = []
    for p in fetch_pair(pair):
        df = pd.read_csv(p)
        df = df[df["volume"] > 0]
        parts.append(df)
    df = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp")
    df = df.sort_values("timestamp").reset_index(drop=True)
    ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    out = pd.DataFrame({"timestamp_ny": ts.dt.tz_convert("America/New_York"),
                        "open": df["open"].astype(float),
                        "high": df["high"].astype(float),
                        "low": df["low"].astype(float),
                        "close": df["close"].astype(float)})
    print(f"  {pair}: {len(out):,} M1 bars "
          f"{out['timestamp_ny'].min()} -> {out['timestamp_ny'].max()}")
    return out


def build_lab(m1, tf):
    df = m1 if tf == 1 else lg.resample_ny(m1, tf)
    df = lg.add_session(df.copy())
    lg.MIN_BARS_SESSION = MINBARS[tf]
    st = lg.session_table(df)
    sess = lg.add_force_bars(lg.tradeable_sessions(st), df)
    sess = sess[sess["year"] >= 2016].reset_index(drop=True)
    return lg.Lab(df, sess)


def stats(tb):
    if tb is None or not len(tb):
        return dict(n=0)
    r = tb["r"]
    tr = tb["year"] <= TRAIN_END
    va = ~tr
    return dict(n=len(tb), wr=float((r > 0).mean()), avg=float(r.mean()),
                net=float(r.sum()),
                tr_n=int(tr.sum()), tr_avg=float(r[tr].mean()) if tr.any() else np.nan,
                tr_net=float(r[tr].sum()),
                va_n=int(va.sum()), va_avg=float(r[va].mean()) if va.any() else np.nan,
                va_net=float(r[va].sum()))


def main():
    rows = []
    for pair in ["XAUUSD"] + PAIRS:
        print(f"== {pair} ==", flush=True)
        m1 = (lg.load_m1() if pair == "XAUUSD" else load_pair(pair))
        cost = COSTS[pair]
        for tf in TFS:
            lab = build_lab(m1, tf)
            for t1, t1n in ((1, "swing"), (3, "rr5")):
                for cm in (1.0, 0.0, 2.0):
                    tb = lab.run(V2["qual"], V2["sel"], t1, V2["run"], V2["att"],
                                 cost * cm, sl_mode=V2["sl_mode"],
                                 body_frac=V2["body_frac"],
                                 att_mode=V2["att_mode"])
                    s = stats(tb)
                    rows.append(dict(pair=pair, tf=tf, t1=t1n, cost_mult=cm, **s))
            del lab
            s1 = [x for x in rows if x["pair"] == pair and x["tf"] == tf
                  and x["t1"] == "swing" and x["cost_mult"] == 1.0][0]
            print(f"  M{tf:<3} swing 1x: n={s1.get('n', 0):<5} "
                  f"wr={s1.get('wr', float('nan')):.2f} "
                  f"avg={s1.get('avg', float('nan')):+.3f} "
                  f"tr={s1.get('tr_net', 0):+8.1f} va={s1.get('va_net', 0):+8.1f}",
                  flush=True)
        del m1
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(HERE, "multi_asset_results.csv"), index=False)
    print("\nwrote multi_asset_results.csv")

    piv = res[(res["cost_mult"] == 1.0) & (res["t1"] == "swing")]
    print("\n== spec v2 (swing T1) at house cost: avg R per trade ==")
    print(piv.pivot_table(index="pair", columns="tf", values="avg")
          .round(3).to_string())
    print("\n== validation (2023+) net R ==")
    print(piv.pivot_table(index="pair", columns="tf", values="va_net")
          .round(1).to_string())
    pos = res[(res["cost_mult"] == 1.0) & (res["tr_avg"] > 0) & (res["va_avg"] > 0)
              & (res["n"] >= 100)]
    print(f"\ncells positive in BOTH train and valid at 1x cost (n>=100): {len(pos)}")
    if len(pos):
        print(pos.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
