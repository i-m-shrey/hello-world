"""STRATEGY SCOUT — independent cross-feed replication of the three strongest
validated strategies from the prior forex_analyst work (branches capy/analyst-v2
and capy/tz-audit-discovery), re-run from scratch on THIS project's Dukascopy
M1-derived frames (a fully independent feed from the broker/HistData frames the
originals were validated on).

Candidates (chosen for strength + mechanism diversity from STRATEGY_MATRIX.md):
  1. XAUUSD-DONCH-TR  gold H1 Donchian-96 breakout, LONG-only, chandelier trail
     (official: n=609 +205.8R, avg +0.338, train +157.4 / holdout +48.5, 3x PASS)
  2. XAUUSD-STRAD     gold H1 consolidation-box breakout, LONG-only, close-confirmed
     (official: +43.6R / TZ-audit +81.4R, PF 1.78, 13/18 yrs, survives 3x)
  3. GBPUSD-BOLL15    M15 quiet-hours Bollinger fade -> SMA20, both sides
     (official: +409R, PF 1.15, train +362 / holdout +47, cost-immune 3x +294R)

Rules are transcribed EXACTLY from live_signals.py (the deployed bot) and the
executor mirrors discovery_engine.run_trades (entry next open +/- cost/2,
intrabar stop-before-target, chandelier trail on closed bars, time exit,
max/day, R = pnl / initial risk, all-in round-trip cost). One extension: an
entry-relative target offset (STRAD's TP = entry + M*zone_width), which the
original straddle lab used natively.

Split convention matches the originals: train <=2023 / holdout >=2024.
Gold window 2008+ (full Dukascopy depth); GBPUSD 2016+ (Dukascopy M1 depth
downloaded for this project) — a partial-window replication of the 18.5y
original, stated as such.
"""
import os
import sys

import numpy as np
import pandas as pd

import liquidity_grab_lab as lg
from multi_asset import load_pair

HERE = os.path.dirname(os.path.abspath(__file__))
COSTS = {"XAUUSD": 0.23, "GBPUSD": 0.00010}


def frame(m1, tf_min):
    df = lg.resample_ny(m1, tf_min) if tf_min > 1 else m1.copy()
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    win = max(60, round(30 * 1440 / tf_min))
    df["atr_pctile"] = (df["atr50"].rolling(win, min_periods=max(60, win // 4))
                        .rank(pct=True))
    df["year"] = df["timestamp_ny"].dt.year
    df["ny_date"] = df["timestamp_ny"].dt.date.astype(str)
    return df


def run_trades(df, sig_long, sig_short, cost, stop_atr=2.0, rr=3.0,
               stop_abs=None, target_abs=None, target_off=None,
               max_hold=96, max_tpd=2, trail_atr=None):
    """Mirror of discovery_engine.run_trades (+ target_off extension)."""
    if sig_long is None:
        sig_long = np.zeros(len(df), bool)
    if sig_short is None:
        sig_short = np.zeros(len(df), bool)
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    atr = df["atr50"].to_numpy(float)
    ts = df["timestamp_ny"].to_numpy()
    yrs = df["year"].to_numpy(int); dates = df["ny_date"].to_numpy()
    n = len(df)
    sig_idx = np.flatnonzero((sig_long | sig_short) & np.isfinite(atr))
    trades = []; tpd = {}; busy_until = -1
    for i in sig_idx:
        ei = i + 1
        if ei >= n or ei <= busy_until:
            continue
        day = dates[ei]
        if tpd.get(day, 0) >= max_tpd:
            continue
        side = 1 if sig_long[i] else -1
        entry = o[ei] + side * cost / 2
        if stop_abs is not None and np.isfinite(stop_abs[i]):
            stop = stop_abs[i] - side * cost / 2
        else:
            stop = entry - side * (stop_atr * atr[i] + cost / 2)
        risk = side * (entry - stop)
        if risk <= 0 or not np.isfinite(risk):
            continue
        target = None
        if trail_atr is None:
            if target_off is not None and np.isfinite(target_off[i]):
                target = entry + side * target_off[i]
            elif target_abs is not None and np.isfinite(target_abs[i]):
                target = target_abs[i]
            else:
                target = entry + side * rr * risk
        trail = stop
        exit_px = None; exit_j = None
        for j in range(ei, min(ei + max_hold, n)):
            if side == 1:
                if l[j] <= trail:
                    exit_px, exit_j = trail, j; break
                if target is not None and h[j] >= target:
                    exit_px, exit_j = target, j; break
                if trail_atr is not None and np.isfinite(atr[j]):
                    trail = max(trail, c[j] - trail_atr * atr[j])
            else:
                if h[j] >= trail:
                    exit_px, exit_j = trail, j; break
                if target is not None and l[j] <= target:
                    exit_px, exit_j = target, j; break
                if trail_atr is not None and np.isfinite(atr[j]):
                    trail = min(trail, c[j] + trail_atr * atr[j])
        if exit_j is None:
            exit_j = min(ei + max_hold, n) - 1
            exit_px = c[exit_j]
        pnl = side * (exit_px - entry) - cost / 2
        trades.append((ts[ei], ts[exit_j], side, pnl / risk, yrs[ei]))
        tpd[day] = tpd.get(day, 0) + 1
        busy_until = exit_j
    return pd.DataFrame(trades, columns=["entry_ts", "exit_ts", "side", "r", "year"])


def stats(t):
    if t is None or not len(t):
        return dict(n=0)
    r = t["r"]
    eq = r.cumsum()
    wins, losses = r[r > 0].sum(), abs(r[r < 0].sum())
    ys = t.groupby("year")["r"].sum()
    return dict(n=len(t), net=float(r.sum()), avg=float(r.mean()),
                wr=float((r > 0).mean()),
                pf=float(wins / losses) if losses else np.inf,
                tr=float(t.loc[t.year <= 2023, "r"].sum()),
                ho=float(t.loc[t.year >= 2024, "r"].sum()),
                yrs_pos=f"{int((ys > 0).sum())}/{len(ys)}",
                maxdd=float((eq - eq.cummax()).min()))


def show(tag, mk):
    out = {}
    for m, lbl in ((1.0, "1x"), (2.0, "2x"), (3.0, "3x")):
        t = mk(m)
        s = stats(t)
        out[lbl] = (t, s)
        print(f"  [{lbl}] n={s.get('n', 0):<5} net={s.get('net', 0):+8.1f} "
              f"avg={s.get('avg', float('nan')):+.3f} wr={s.get('wr', float('nan')):.2f} "
              f"pf={s.get('pf', float('nan')):.2f} tr={s.get('tr', 0):+7.1f} "
              f"ho={s.get('ho', 0):+6.1f} yrs+={s.get('yrs_pos', '-')} "
              f"dd={s.get('maxdd', float('nan')):+.1f}", flush=True)
    return out


def donch_tr(g, cost_mult, trail=5.0):
    cost = COSTS["XAUUSD"] * cost_mult
    hiN = g["high"].shift(1).rolling(96).max().to_numpy(float)
    atr = g["atr50"].to_numpy(float)
    sig = g["close"].to_numpy(float) > hiN + 0.1 * atr
    stop_abs = g["close"].to_numpy(float) - 2.0 * atr
    return run_trades(g, sig, None, cost, stop_abs=stop_abs, trail_atr=trail,
                      max_hold=192, max_tpd=2)


def strad(g, cost_mult, W=24, K=3.0, M=2.0):
    cost = COSTS["XAUUSD"] * cost_mult
    hi = g["high"].shift(1).rolling(W).max().to_numpy(float)
    lo = g["low"].shift(1).rolling(W).min().to_numpy(float)
    atr = g["atr50"].to_numpy(float)
    c = g["close"].to_numpy(float)
    width = hi - lo
    hrs = g["timestamp_ny"].dt.hour.to_numpy()
    sig = ((width >= 1.0 * atr) & (width <= K * atr)
           & (c > hi + 0.1 * atr) & (hrs != 17))
    return run_trades(g, sig, None, cost, stop_abs=lo, target_off=M * width,
                      max_hold=48, max_tpd=2)


def boll15(d, cost_mult, sides=("long", "short")):
    cost = COSTS["GBPUSD"] * cost_mult
    n = 20
    c = d["close"]
    sma = c.rolling(n).mean()
    sd = c.rolling(n).std(ddof=1)
    atrp = d["atr_pctile"].to_numpy(float)
    hrs = d["timestamp_ny"].dt.hour.to_numpy()
    ok = (np.isin(hrs, list(range(14, 24))) & (hrs != 17) & (atrp <= 0.70))
    lo_sig = ok & (c < sma - 2.0 * sd).to_numpy()
    hi_sig = ok & (c > sma + 2.0 * sd).to_numpy()
    return run_trades(d, lo_sig if "long" in sides else None,
                      hi_sig if "short" in sides else None, cost,
                      stop_atr=1.2, target_abs=sma.to_numpy(float),
                      max_hold=20, max_tpd=3)


def main():
    print("== building frames ==", flush=True)
    gold_h1 = frame(lg.load_m1(), 60)
    print(f"gold H1: {len(gold_h1)} bars {gold_h1['ny_date'].min()} -> "
          f"{gold_h1['ny_date'].max()}", flush=True)

    print("\n== 1. XAUUSD-DONCH-TR (H1 Donchian-96 long, 2xATR stop, "
          "5xATR chandelier) | official n=609 +205.8R tr+157.4 ho+48.5 ==")
    r1 = show("DONCH-TR", lambda m: donch_tr(gold_h1, m))
    print("  trail 4.0 twin (official holdout-stronger cell):")
    show("DONCH-TR4", lambda m: donch_tr(gold_h1, m, trail=4.0))

    print("\n== 2. XAUUSD-STRAD (H1 box-breakout long, W24 K3 M2) "
          "| official +43.6R (TZ-audit +81.4R) ==")
    r2 = show("STRAD", lambda m: strad(gold_h1, m))

    gbp_m15 = frame(load_pair("GBPUSD"), 15)
    print(f"\ngbp M15: {len(gbp_m15)} bars {gbp_m15['ny_date'].min()} -> "
          f"{gbp_m15['ny_date'].max()}")
    print("== 3. GBPUSD-BOLL15 (M15 quiet-hours band fade -> SMA20, both sides) "
          "| official 18.5y +409R tr+362 ho+47; THIS is a 2016+ partial window ==")
    r3 = show("BOLL15", lambda m: boll15(gbp_m15, m))

    for tag, res in (("donch_tr", r1), ("strad", r2), ("gbp_boll15", r3)):
        res["1x"][0].to_csv(os.path.join(HERE, f"scout_{tag}_trades.csv"),
                            index=False)
    print("\ntradebooks written (scout_*_trades.csv)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
