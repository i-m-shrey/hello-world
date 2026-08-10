"""DISCOVERY ENGINE (July 2026, Mandate 2) — shared machinery for concept discovery.

Everything here is IRON-GATE plumbing, not strategy logic:
  frames(sym, tf)   TZ-verified OHLC frames (event_price_lib rules) resampled to
                    M5/M15/M30/H1/H4, with atr50/atr_pctile/emas/efficiency ratio.
  run_trades(...)   one honest bar-walk executor: enter next open after signal,
                    intrabar stop (conservative: stop before target on the same
                    bar), fixed-RR target or chandelier trail, time exit, max_tpd,
                    ALL-IN round-trip cost per trade (live_signals FX_SPREADS
                    numbers), R = pnl / initial risk.
  gate(...)         the iron gate: train(<=2023)/holdout(>=2024) both positive,
                    avg-R floor, 2x/3x cost stress, minimum sample. Verdict plus
                    every number recorded to discovery_ledger.csv — passes AND
                    rejections. Neighbor plateaus and replication are judged at
                    the study level (the scan scripts print full grids).

The executor is deliberately conservative: same-bar stop&target -> stop first;
entry at next bar open; no slippage beyond the all-in cost (the house convention
used by the deployed validations).
"""
import os

import numpy as np
import pandas as pd

import event_price_lib as epl

ROOT = os.path.dirname(os.path.abspath(__file__))
NY = "America/New_York"
LEDGER = os.path.join(ROOT, "discovery_ledger.csv")

COST = dict(epl.ALL_IN_COST)
COST.update({"US30": 3.4, "JPN225": 13.5, "HK50": 8.3})

_BASE = {}
_FRAMES = {}


def _base(sym):
    if sym not in _BASE:
        if sym in epl.SOURCES:
            _BASE[sym] = epl.load_frame(sym)[["timestamp_ny", "open", "high",
                                              "low", "close"]].copy()
        else:                      # US30 / JPN225 / HK50 index M15 (server time)
            _BASE[sym] = epl._load_tab(os.path.join(ROOT, f"data/IDX_{sym}_M15.csv"),
                                       "ny+7")
    return _BASE[sym]


def frames(sym, tf_min):
    """TZ-correct OHLC at tf_min minutes with standard features."""
    key = (sym, tf_min)
    if key in _FRAMES:
        return _FRAMES[key]
    df = _base(sym)
    native = {"XAUUSD": 5, "USDCAD": 60}.get(sym, 15)
    if tf_min < native:
        raise ValueError(f"{sym}: {tf_min}m below native {native}m")
    if tf_min != native:
        g = df.set_index("timestamp_ny").resample(f"{tf_min}min")
        df = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                           "low": g["low"].min(), "close": g["close"].last()}
                          ).dropna().reset_index()
    df = df.copy()
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr50"] = tr.rolling(50, min_periods=20).mean()
    win = max(60, round(30 * 1440 / tf_min))
    df["atr_pctile"] = df["atr50"].rolling(win, min_periods=max(60, win // 4)).rank(pct=True)
    c = df["close"]
    for span in (20, 50, 200):
        df[f"ema{span}"] = c.ewm(span=span, adjust=False).mean()
    # efficiency ratio (Kaufman): |net move| / path length over 48 bars — the
    # regime measure for the routing studies. Fully causal.
    k = 48
    net = (c - c.shift(k)).abs()
    path = c.diff().abs().rolling(k).sum()
    df["er48"] = (net / path).replace([np.inf, -np.inf], np.nan)
    df["er_pctile"] = df["er48"].rolling(win, min_periods=max(60, win // 4)).rank(pct=True)
    df["year"] = df["timestamp_ny"].dt.year
    df["ny_date"] = df["timestamp_ny"].dt.date.astype(str)
    df["hour"] = df["timestamp_ny"].dt.hour
    _FRAMES[key] = df
    return df


def run_trades(df, sig_long, sig_short, cost, stop_atr=2.0, rr=3.0,
               stop_abs=None, target_abs=None, max_hold=96, max_tpd=2,
               trail_atr=None, be_r=None):
    """Bar-walk executor. sig_* are boolean arrays on the SIGNAL bar; entry is the
    next bar's open. stop_abs/target_abs (arrays) override ATR-relative stops.
    trail_atr: chandelier trail distance in ATRs (replaces the fixed target).
    Returns DataFrame(entry_ts, exit_ts, side, r, year)."""
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
            if target_abs is not None and np.isfinite(target_abs[i]):
                target = target_abs[i]
            else:
                target = entry + side * rr * risk
        trail = stop
        be_done = False
        exit_px = None; exit_j = None
        for j in range(ei, min(ei + max_hold, n)):
            if side == 1:
                if l[j] <= trail:
                    exit_px, exit_j = trail, j; break
                if target is not None and h[j] >= target:
                    exit_px, exit_j = target, j; break
                if trail_atr is not None and np.isfinite(atr[j]):
                    trail = max(trail, c[j] - trail_atr * atr[j])
                if be_r and not be_done and h[j] >= entry + be_r * risk:
                    trail = max(trail, entry); be_done = True
            else:
                if h[j] >= trail:
                    exit_px, exit_j = trail, j; break
                if target is not None and l[j] <= target:
                    exit_px, exit_j = target, j; break
                if trail_atr is not None and np.isfinite(atr[j]):
                    trail = min(trail, c[j] + trail_atr * atr[j])
                if be_r and not be_done and l[j] <= entry - be_r * risk:
                    trail = min(trail, entry); be_done = True
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
        return dict(n=0, net=0.0, avg=np.nan, wr=np.nan, pf=np.nan, tr=0.0, ho=0.0,
                    yrs_pos="0/0", maxdd=np.nan)
    r = t["r"]
    eq = r.cumsum(); dd = float((eq - eq.cummax()).min())
    wins, losses = r[r > 0].sum(), abs(r[r < 0].sum())
    ys = t.groupby("year")["r"].sum()
    return dict(n=len(t), net=float(r.sum()), avg=float(r.mean()),
                wr=float((r > 0).mean()), pf=float(wins / losses) if losses else np.inf,
                tr=float(t.loc[t.year <= 2023, "r"].sum()),
                ho=float(t.loc[t.year >= 2024, "r"].sum()),
                yrs_pos=f"{(ys > 0).sum()}/{len(ys)}", maxdd=dd)


def gate(tag, mk_trades, avg_floor=0.05, min_n=80, ho_required=True, note=""):
    """mk_trades(cost_multiplier) -> trades. Runs 1x/2x/3x cost, applies the iron
    gate, appends everything to the ledger, returns (verdict, stats_1x)."""
    s1 = stats(mk_trades(1.0))
    s2 = stats(mk_trades(2.0))
    s3 = stats(mk_trades(3.0))
    checks = {
        "n>=min": s1["n"] >= min_n,
        "avg>=floor": np.isfinite(s1["avg"]) and s1["avg"] >= avg_floor,
        "train+": s1["tr"] > 0,
        "holdout+": (s1["ho"] > 0) or not ho_required,
        "2x_cost_avg>0": np.isfinite(s2["avg"]) and s2["avg"] > 0,
    }
    verdict = "PASS" if all(checks.values()) else "reject"
    failed = ",".join(k for k, v in checks.items() if not v)
    rec = dict(tag=tag, verdict=verdict, failed=failed, note=note,
               **{k: (round(v, 4) if isinstance(v, float) else v)
                  for k, v in s1.items()},
               avg2x=None if not np.isfinite(s2["avg"]) else round(s2["avg"], 4),
               avg3x=None if not np.isfinite(s3["avg"]) else round(s3["avg"], 4))
    hdr = not os.path.exists(LEDGER)
    pd.DataFrame([rec]).to_csv(LEDGER, mode="a", header=hdr, index=False)
    a = 0.0 if not np.isfinite(s1["avg"]) else s1["avg"]
    print(f"{verdict:>6}  {tag:<60} n={s1['n']:<5} avg={a:+.3f} "
          f"net={s1['net']:+7.1f} tr={s1['tr']:+7.1f} ho={s1['ho']:+6.1f} "
          f"2x={rec['avg2x']} 3x={rec['avg3x']} yrs={s1['yrs_pos']}"
          + (f"  [{failed}]" if failed else ""))
    return verdict, s1
