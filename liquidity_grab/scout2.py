"""scout2.py — four more candidates from the validated battery, cross-feed
replicated on this project's Dukascopy frames (see SCOUT.md for conventions).

  4. XAUUSD-BOS      H1 structure-break continuation long (pivot-high k=3 cross,
                     rr5)          official +267.4R avg +0.170, 3x-immune
  5. XAUUSD-MACROSS  H1 EMA20x50 cross up + H4 bias long, rr3
                     official +49.8R (TZ-fixed +54.5R)
  6. MTF-DONCH N24   H1 Donchian-24 long gated by H4 EMA20>EMA50
                     official watchlist: +48.1 train / +98.0 holdout
  7. XAUUSD-CRASH    H1 crash-continuation SHORT (insurance leg)
                     official +63.1R, holdout negative BY DESIGN in bull runs
  Bonus: P1 ports    EURUSD M30 / USDCHF H1 (official +21R / +16R)

H4 bias mirrors live_signals.h4_gate exactly: H4 EMA20>EMA50, bias timestamped
at the H4 bar CLOSE (+240min), merged backward onto H1 opens.
"""
import sys

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg
from multi_asset import load_pair
from strategy_scout import frame, run_trades, stats
from scout_p1 import p1_trades

XCOST = 0.23


def h4_bias(m1, d):
    h4 = frame(m1, 240)
    c = h4["close"]
    e20 = c.ewm(span=20, adjust=False).mean()
    e50 = c.ewm(span=50, adjust=False).mean()
    g = pd.DataFrame({"timestamp_ny": h4["timestamp_ny"] + pd.Timedelta(minutes=240),
                      "up": (e20 > e50).astype(int)})
    left = d[["timestamp_ny"]].copy()
    left["timestamp_ny"] = left["timestamp_ny"].dt.as_unit("ns")
    g["timestamp_ny"] = g["timestamp_ny"].dt.as_unit("ns")
    m = pd.merge_asof(left, g, on="timestamp_ny",
                      direction="backward")
    return m["up"].fillna(0).to_numpy(int)


def last_pivot_high(h, k):
    """lvl[i] = level of the most recent pivot high (strict k-each-side max)
    CONFIRMED at or before bar i (pivot t needs bars t+1..t+k closed)."""
    n = len(h)
    s = pd.Series(h)
    # strict: h[t] > max(h[t-k..t-1]) and h[t] > max(h[t+1..t+k])
    fwd_max = pd.Series(h[::-1]).shift(1).rolling(k).max().to_numpy()[::-1]
    bwd_max = s.shift(1).rolling(k).max().to_numpy()
    is_piv = (h > np.where(np.isfinite(bwd_max), bwd_max, np.inf)) \
        & (h > np.where(np.isfinite(fwd_max), fwd_max, np.inf))
    lvl = np.full(n, np.nan)
    last = np.nan
    piv_idx = np.flatnonzero(is_piv)
    ptr = 0
    for i in range(n):
        while ptr < len(piv_idx) and piv_idx[ptr] + k <= i:
            last = h[piv_idx[ptr]]
            ptr += 1
        lvl[i] = last
    return lvl


def bos(g, cm, piv_k=3, pad=0.1, rr=5.0):
    cost = XCOST * cm
    h = g["high"].to_numpy(float)
    c = g["close"].to_numpy(float)
    atr = g["atr50"].to_numpy(float)
    lvl = last_pivot_high(h, piv_k)
    thr = lvl + pad * atr
    prev_ok = np.roll(c <= thr, 1)
    prev_ok[0] = False
    sig = np.isfinite(lvl) & (c > thr) & prev_ok
    stop_abs = c - 2.0 * atr
    return run_trades(g, sig, None, cost, stop_abs=stop_abs, rr=rr,
                      max_hold=96, max_tpd=2)


def macross(g, cm, bias):
    cost = XCOST * cm
    c = g["close"]
    ef = c.ewm(span=20, adjust=False).mean().to_numpy()
    es = c.ewm(span=50, adjust=False).mean().to_numpy()
    cross = (ef > es) & (np.roll(ef <= es, 1))
    cross[0] = False
    sig = cross & (bias == 1)
    stop_abs = c.to_numpy() - 2.0 * g["atr50"].to_numpy()
    return run_trades(g, sig, None, cost, stop_abs=stop_abs, rr=3.0,
                      max_hold=96, max_tpd=2)


def mtf_donch(g, cm, bias, N=24):
    cost = XCOST * cm
    hiN = g["high"].shift(1).rolling(N).max().to_numpy(float)
    atr = g["atr50"].to_numpy(float)
    sig = (g["close"].to_numpy(float) > hiN + 0.1 * atr) & (bias == 1)
    stop_abs = g["close"].to_numpy(float) - 2.0 * atr
    return run_trades(g, sig, None, cost, stop_abs=stop_abs, rr=3.0,
                      max_hold=96, max_tpd=2)


def crash(g, cm, bias):
    cost = XCOST * cm
    o = g["open"].to_numpy(float); h = g["high"].to_numpy(float)
    l = g["low"].to_numpy(float); c = g["close"].to_numpy(float)
    atr = g["atr50"].to_numpy(float)
    rng = h - l
    red = c < o
    loc = np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1.0), 1.0)
    sig = (rng >= 2.0 * atr) & red & (loc <= 0.25) & (bias == 0)
    stop_abs = c + 2.0 * atr
    return run_trades(g, None, sig, cost, stop_abs=stop_abs, rr=2.0,
                      max_hold=96, max_tpd=2)


def show(tag, mk, save=None):
    for m, lbl in ((1.0, "1x"), (2.0, "2x"), (3.0, "3x")):
        t = mk(m)
        s = stats(t)
        print(f"  [{lbl}] n={s.get('n', 0):<5} net={s.get('net', 0):+8.1f} "
              f"avg={s.get('avg', float('nan')):+.3f} "
              f"wr={s.get('wr', float('nan')):.2f} tr={s.get('tr', 0):+7.1f} "
              f"ho={s.get('ho', 0):+6.1f} yrs+={s.get('yrs_pos', '-')} "
              f"dd={s.get('maxdd', float('nan')):+.1f}", flush=True)
        if m == 1.0 and save:
            t.to_csv(save, index=False)
            first = t
    return first


def daily_corr(a, b):
    da = a.groupby(pd.to_datetime(a["entry_ts"], utc=True).dt.date)["r"].sum()
    db = b.groupby(pd.to_datetime(b["entry_ts"], utc=True).dt.date)["r"].sum()
    ix = sorted(set(da.index) | set(db.index))
    return float(da.reindex(ix, fill_value=0).corr(db.reindex(ix, fill_value=0)))


def main():
    m1 = lg.load_m1()
    g = frame(m1, 60)
    bias = h4_bias(m1, g)
    print(f"gold H1: {len(g)} bars; H4 bias up {bias.mean():.1%} of bars")

    print("\n== 4. XAUUSD-BOS (pivot-high break, rr5) | official +267.4R "
          "avg +0.170 tr+186/ho+87 ==")
    t_bos = show("BOS", lambda m: bos(g, m), "scout_bos_trades.csv")

    print("\n== 5. XAUUSD-MACROSS (EMA20x50 + H4 bias, rr3) | official +49.8R ==")
    t_mac = show("MACROSS", lambda m: macross(g, m, bias), "scout_macross_trades.csv")

    print("\n== 6. MTF-DONCH N24 H4-gated (rr3) | official tr+48.1/ho+98.0 ==")
    t_mtf = show("MTFDONCH", lambda m: mtf_donch(g, m, bias), "scout_mtfdonch_trades.csv")

    print("\n== 7. XAUUSD-CRASH short insurance | official +63.1R, ho<0 by design ==")
    show("CRASH", lambda m: crash(g, m, bias), "scout_crash_trades.csv")

    print("\n== bonus: P1 ports | EURUSD M30 (official +21R) / USDCHF H1 (+16R) ==")
    eur = frame(load_pair("EURUSD"), 30)
    for m in (1.0, 3.0):
        s = stats(p1_trades(eur, 0.00008 * m))
        print(f"  EURUSD-M30 [{m:.0f}x] n={s.get('n', 0)} net={s.get('net', 0):+.1f} "
              f"avg={s.get('avg', float('nan')):+.3f} tr={s.get('tr', 0):+.1f} "
              f"ho={s.get('ho', 0):+.1f}")
    chf = frame(load_pair("USDCHF"), 60)
    for m in (1.0, 3.0):
        s = stats(p1_trades(chf, 0.00010 * m))
        print(f"  USDCHF-H1  [{m:.0f}x] n={s.get('n', 0)} net={s.get('net', 0):+.1f} "
              f"avg={s.get('avg', float('nan')):+.3f} tr={s.get('tr', 0):+.1f} "
              f"ho={s.get('ho', 0):+.1f}")

    dtr = pd.read_csv("scout_donch_tr_trades.csv")
    print("\n== daily-R correlation vs DONCH-TR (overlap check) ==")
    for nm, t in (("BOS", t_bos), ("MACROSS", t_mac), ("MTF-DONCH", t_mtf)):
        print(f"  {nm}: {daily_corr(dtr, t):+.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
