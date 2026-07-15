"""S3LO CLEAN VALIDATION (owner-approved, July 2026) — is the deployed S3 long-only
edge real on smc_engine labels and TZ-correct time, like S4 was not?

Implements the DEPLOYED rules exactly (live_mt5_bot.eval_s3 + INSTANCES config):
  session 09:00-11:55 NY, 5m swing_bias == +1, bullish displacement within the
  last 25 bars (body >= 60% of range, range >= 1.4x ATR50), bull-FVG touch with a
  bullish confirm close; stop = last_swing_low (- 0.30 stop_pad, bot convention);
  rr 2.0, BE at +1R, risk bounds 1..30 pts, max 2/day, max_hold 96 bars.
Cost: 0.60 pts round trip (house gold M5 convention), stress 2x/3x.
Data: XAU_5m 2008-2026 SERVER-time file parsed with the VERIFIED NY+7 rule, plus
the official research window (2020-08-24..2025-04-25) reported separately.

This is a validation, not a tuning run: no parameter is changed from deployment.
"""
import sys
import types

import numpy as np
import pandas as pd

sys.modules.setdefault("MetaTrader5", types.ModuleType("MetaTrader5"))

import smc_engine

NY = "America/New_York"
SP = 0.60


def load_gold_m5_fixed():
    df = pd.read_csv("data/XAU_5m_data.csv", sep=";")
    df.columns = [c.lower() for c in df.columns]
    ts = (pd.to_datetime(df["date"], format="%Y.%m.%d %H:%M") - pd.Timedelta(hours=7)
          ).dt.tz_localize(NY, ambiguous="NaT", nonexistent="NaT")
    out = pd.DataFrame({"timestamp_ny": ts,
                        "open": pd.to_numeric(df["open"]),
                        "high": pd.to_numeric(df["high"]),
                        "low": pd.to_numeric(df["low"]),
                        "close": pd.to_numeric(df["close"]),
                        "volume": pd.to_numeric(df["volume"], errors="coerce")})
    out = out.dropna(subset=["timestamp_ny"])
    return out[out["timestamp_ny"] >= pd.Timestamp("2008-01-01", tz=NY)].reset_index(drop=True)


def simulate(e5, cost=SP):
    o = e5["open"].to_numpy(float); h = e5["high"].to_numpy(float)
    l = e5["low"].to_numpy(float); c = e5["close"].to_numpy(float)
    atr = e5["atr50"].to_numpy(float)
    bias = e5["swing_bias"].to_numpy(int)
    top = e5["bull_fvg_top"].to_numpy(float)
    bot = e5["bull_fvg_bottom"].to_numpy(float)
    age = e5["bull_fvg_age"].to_numpy(float)
    swl = e5["last_swing_low"].to_numpy(float)
    nt = e5["ny_time"].to_numpy()
    dates = e5["ny_date"].to_numpy()
    yrs = e5["year"].to_numpy(int)

    # displacement in the last 25 bars (vectorized: bullish body>=60%, range>=1.4xATR)
    rng = h - l
    body_ok = (c > o) & (rng > 0) & (np.abs(c - o) / np.where(rng > 0, rng, np.nan) >= 0.60)
    disp = body_ok & np.isfinite(atr) & (rng / np.where(atr > 0, atr, np.nan) >= 1.4)
    disp_recent = (pd.Series(disp).rolling(25, min_periods=1).max()
                   .to_numpy(bool))

    in_sess = (nt >= "09:00") & (nt <= "11:55")
    sig = (in_sess & (bias == 1) & disp_recent
           & np.isfinite(top) & np.isfinite(bot) & (age > 0)
           & (l <= top) & (h >= bot) & (c > o) & np.isfinite(swl))

    n = len(e5); trades = []; tpd = {}; last_exit = -1
    for i in np.flatnonzero(sig):
        ei = i + 1
        if ei >= n or ei <= last_exit:
            continue
        day = dates[ei]
        if tpd.get(day, 0) >= 2:
            continue
        entry = o[ei] + cost / 2
        stop = swl[i] - 0.30 - cost / 2           # bot stop_pad 0.30
        risk = entry - stop
        if not (1.0 <= risk <= 30.0):
            continue
        target = entry + 2.0 * risk
        be = False
        xp = None; xi = None
        for j in range(ei, min(ei + 96, n)):
            if l[j] <= stop:
                xp, xi = stop, j; break
            if h[j] >= target:
                xp, xi = target, j; break
            if not be and h[j] >= entry + risk:
                stop = max(stop, entry); be = True
        if xi is None:
            xi = min(ei + 96, n) - 1; xp = c[xi]
        trades.append((int(yrs[ei]), (xp - entry) / risk, str(dates[ei])))
        tpd[day] = tpd.get(day, 0) + 1
        last_exit = xi
    return pd.DataFrame(trades, columns=["year", "r", "date"])


def rep(tag, t):
    if not len(t):
        print(f"{tag}: no trades"); return
    r = t["r"]
    tr = t.loc[t.year <= 2023, "r"].sum(); ho = t.loc[t.year >= 2024, "r"].sum()
    wins = r[r > 0]; losses = r[r < 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) else float("inf")
    eq = r.cumsum(); dd = (eq - eq.cummax()).min()
    ys = t.groupby("year")["r"].sum()
    print(f"{tag:<44} n={len(t):<5} net={r.sum():+7.1f}R avg={r.mean():+.3f} "
          f"WR={(r > 0).mean() * 100:.0f}% PF={pf:.2f} maxDD={dd:+.1f}R | "
          f"train={tr:+7.1f} holdout={ho:+6.1f} | +yrs {(ys > 0).sum()}/{len(ys)}")


def main():
    raw = load_gold_m5_fixed()
    print(f"gold M5 TZ-correct: {len(raw)} bars "
          f"{raw.timestamp_ny.min():%Y-%m-%d} -> {raw.timestamp_ny.max():%Y-%m-%d}")
    print("building smc_engine frame (one-time, full history)...")
    e5 = smc_engine.build_smc_frame(raw)
    prev = e5["close"].shift(1)
    tr = pd.concat([e5["high"] - e5["low"], (e5["high"] - prev).abs(),
                    (e5["low"] - prev).abs()], axis=1).max(axis=1)
    e5["atr50"] = tr.rolling(50, min_periods=20).mean()
    e5["year"] = e5["timestamp_ny"].dt.year
    if "ny_time" not in e5.columns:
        e5["ny_time"] = e5["timestamp_ny"].dt.strftime("%H:%M")
    print(f"engine frame: {len(e5)} rows\n")

    print("S3LO deployed rules, engine labels, TZ-correct time:")
    t_full = simulate(e5)
    rep("FULL 2008-2026 @0.60pts", t_full)
    for m in (2, 3):
        rep(f"FULL cost {m}x", simulate(e5, SP * m))
    win = e5[(e5["ny_date"] >= "2020-08-24") & (e5["ny_date"] <= "2025-04-25")].reset_index(drop=True)
    t_win = simulate(win)
    rep("OFFICIAL WINDOW 2020-08..2025-04 @0.60", t_win)
    if len(t_full):
        ys = t_full.groupby("year")["r"].sum()
        print("\nyearly:", "  ".join(f"{y}:{ys[y]:+.0f}" for y in sorted(ys.index)))


if __name__ == "__main__":
    main()
